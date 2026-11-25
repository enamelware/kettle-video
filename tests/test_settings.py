# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Settings for launch (the Settings screen work): changing the Movies and TV Shows folders,
and the About section. Every folder, file and settings file here is invented,
in a temporary folder; the app's own settings.json is never read or written.

Checks: the menu has a Settings row between Remove N missing items and Quit;
a folder change is saved under today's keys, keeps every other setting and
starts exactly one rescan; the folder already set saves nothing and starts no
rescan; the refused cases and their sentences are onboarding's (for TV shows
word for word, for movies the same checks naming the TV shows folder);
stopping the second kind is refused with its sentence, stopping one with the
other set saves it empty with no rescan; a change while a scan runs, and a
failed save, change nothing; the old folder's items turn missing (Continue
watching too) and what is found again comes back; About lists exactly the
entries of THIRD_PARTY_LICENSES.md, mpv included, each bundled licence text
matching its file, and nothing else can be asked for; the version is the
VERSION file's; fresh start leaves the real settings.json byte-for-byte
unchanged; no full path in any answer or log line.

Run from the repo root:  python3 -m unittest tests.test_settings -v
"""

import contextlib
import http.client
import io
import json
import os
import re
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from backend import folder_finder as ff
from backend import continue_watching, library_index, onboarding, server, settings_screen
from tests.test_folder_finder import make, snapshot
from tests.test_launch_options import free_port
from tests.test_onboarding import OTHER_SETTINGS, REAL_SETTINGS, real_settings_stamp

REPO = Path(__file__).resolve().parent.parent
UI_DIR = REPO / "ui"
MENU_JS = (UI_DIR / "js" / "home_menu.js").read_text(encoding="utf-8")


def table_names():
    """Every entry of THIRD_PARTY_LICENSES.md's tables, read independently
    of the app: the first cell of each row under a header row."""
    names, in_table = [], False
    for line in (REPO / "THIRD_PARTY_LICENSES.md").read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            in_table = False
            continue
        if not in_table:
            in_table = True  # the header row
            continue
        first = line.strip("|").split("|")[0].strip()
        if not re.fullmatch(r"[-: ]+", first):
            names.append(first)
    return names


class MenuTest(unittest.TestCase):
    def test_settings_sits_between_remove_and_quit(self):
        rows = MENU_JS[MENU_JS.index("export function menuRows"):]
        rows = rows[:rows.index("return rows;")]
        order = re.findall(r'value: (?:scanning \? "scanning" : )?"([a-z-]+)"', rows)
        self.assertEqual(order, ["rescan", "remove-missing", "settings", "quit", "cancel"])
        self.assertIn('{ value: "settings", title: "Settings" }', rows)
        # Remove is the only row that depends on anything.
        self.assertIn('if (missing > 0) rows.push({ value: "remove-missing"', rows)


class ProblemTest(unittest.TestCase):
    """The refused cases, against onboarding's own checks and sentences."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        for rel in ("Card/Films/Old", "Card/Shows/Old", "Home/Other"):
            (root / rel).mkdir(parents=True)
        (root / "Card/LinkToShows").symlink_to(root / "Card/Shows")
        self.p = lambda rel: str(root / rel)

    def test_tv_shows_get_onboardings_sentences_word_for_word(self):
        movies = self.p("Card/Films")
        for chosen in ("Card/Films", "Card/Films/Old", "Card", "Home/Other"):
            with self.subTest(chosen=chosen):
                self.assertEqual(settings_screen.problem("tv", self.p(chosen), movies),
                                 onboarding.problem(movies, self.p(chosen)))
        self.assertEqual(settings_screen.problem("tv", movies, movies), onboarding.SAME)
        self.assertEqual(settings_screen.problem("tv", self.p("Card/Films/Old"), movies), onboarding.INSIDE_MOVIES)
        self.assertEqual(settings_screen.problem("tv", self.p("Card"), movies), onboarding.HOLDS_MOVIES)

    def test_movies_get_the_same_checks_naming_the_tv_shows_folder(self):
        tv = self.p("Card/Shows")
        self.assertEqual(settings_screen.problem("movies", tv, tv), settings_screen.SAME_TV)
        self.assertEqual(settings_screen.problem("movies", self.p("Card/LinkToShows"), tv), settings_screen.SAME_TV)
        self.assertEqual(settings_screen.problem("movies", self.p("Card/Shows/Old"), tv), settings_screen.INSIDE_TV)
        self.assertEqual(settings_screen.problem("movies", self.p("Card"), tv), settings_screen.HOLDS_TV)
        self.assertIsNone(settings_screen.problem("movies", self.p("Home/Other"), tv))
        self.assertEqual(settings_screen.SAME_TV, "Already your TV shows folder. Movies and TV shows need "
                                                  "separate folders, so pick a different one.")
        self.assertEqual(settings_screen.INSIDE_TV, "This folder is inside your TV shows folder, so pick a different one.")
        self.assertEqual(settings_screen.HOLDS_TV, "Your TV shows folder is inside this one, so pick a different one.")

    def test_with_the_other_kind_not_set_any_folder_will_do(self):
        for kind in ("movies", "tv"):
            for other in ("", None):
                with self.subTest(kind=kind, other=other):
                    self.assertIsNone(settings_screen.problem(kind, self.p("Card"), other))

    def test_stopping_the_second_kind_is_refused_with_its_sentence(self):
        self.assertEqual(settings_screen.problem("movies", None, ""), settings_screen.KEEP_ONE["movies"])
        self.assertEqual(settings_screen.problem("tv", None, ""), settings_screen.KEEP_ONE["tv"])
        self.assertEqual(settings_screen.KEEP_ONE["movies"],
                         "Your TV shows folder isn't set, and Kettle needs at least one folder, so keep this one.")
        self.assertIsNone(settings_screen.problem("movies", None, self.p("Card/Shows")))

    def test_the_same_folder(self):
        self.assertTrue(settings_screen.same_folder(self.p("Card/Shows"), self.p("Card/LinkToShows")))
        self.assertTrue(settings_screen.same_folder(None, ""))
        self.assertFalse(settings_screen.same_folder(self.p("Card/Shows"), ""))
        self.assertFalse(settings_screen.same_folder(self.p("Card/Shows"), self.p("Card/Films")))


class SaveOneTest(unittest.TestCase):
    def test_one_kind_saved_keeping_the_other_and_every_setting_in_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "settings.json"
            file.write_text(json.dumps({"movies_path": "/invented/Films", "tv_path": "/invented/Shows",
                                        **OTHER_SETTINGS}), encoding="utf-8")
            onboarding.save_folder(file, "movies", "/invented/Cinema")
            data = json.loads(file.read_text(encoding="utf-8"))
            self.assertEqual(list(data), ["movies_path", "tv_path", *OTHER_SETTINGS])
            self.assertEqual((data["movies_path"], data["tv_path"]), ("/invented/Cinema", "/invented/Shows"))
            self.assertEqual({k: v for k, v in data.items() if k not in ("movies_path", "tv_path")}, OTHER_SETTINGS)
            onboarding.save_folder(file, "tv", None)
            self.assertEqual(json.loads(file.read_text(encoding="utf-8"))["tv_path"], "")
            self.assertEqual(sorted(os.listdir(tmp)), ["settings.json"])


class MoveFolderTest(unittest.TestCase):
    def test_every_item_turns_missing_under_the_new_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            make(tmp, ["Films/Alpha/a.mkv", "Films/Beta/b1.mkv", "Films/Beta/b2.mkv", "Shows/Gamma/S01E01.mkv"], size=1)
            roots = {"movies": os.path.join(tmp, "Films"), "tv": os.path.join(tmp, "Shows")}
            index = library_index.full_scan(roots, None, lambda done, total: None)
            moved = library_index.move_folder(index, "movies", "/invented/Elsewhere")
            entry = moved["sources"]["movies"]
            self.assertEqual((entry["root"], entry["files"]), ("/invented/Elsewhere", []))
            self.assertTrue(entry["items"])
            for item in entry["items"]:
                self.assertTrue(library_index.is_missing(item))
                self.assertTrue(all(library_index.is_missing(p) for p in item["parts"]))
            self.assertIs(moved["sources"]["tv"], index["sources"]["tv"])
            # The library it came from is left as it was.
            self.assertFalse(any(library_index.is_missing(i) for i in index["sources"]["movies"]["items"]))
            self.assertIs(library_index.move_folder(index, "movies", roots["movies"]), index)
            self.assertIsNone(library_index.move_folder(None, "movies", "/invented/Elsewhere"))


class AboutTest(unittest.TestCase):
    def test_about_lists_exactly_the_entries_of_the_licences_file(self):
        credits = settings_screen.credits(REPO)
        self.assertEqual([c["name"] for c in credits], table_names())
        self.assertIn("mpv", [c["name"] for c in credits])
        self.assertEqual(len(credits), 8)

    def test_each_bundled_credit_shows_its_own_licence_file(self):
        for credit in settings_screen.credits(REPO):
            with self.subTest(credit=credit["name"]):
                if not credit["bundled"]:
                    self.assertEqual(credit["name"], "mpv")
                    self.assertIsNone(settings_screen.licence_text(REPO, credit["id"]))
                    self.assertEqual(credit["link"], "https://mpv.io/")
                    self.assertIn("Not bundled", credit["note"])
                    continue
                file = REPO / settings_screen.LICENCE_FILES[credit["name"]]
                self.assertEqual(settings_screen.licence_text(REPO, credit["id"]),
                                 {"name": credit["name"], "text": file.read_text(encoding="utf-8")})
                self.assertTrue(credit["licence"])

    def test_a_rows_licence_is_short(self):
        short = {c["name"]: c["short"] for c in settings_screen.credits(REPO)}
        self.assertEqual(short["Enamel"], "MIT")
        self.assertEqual(short["python-dateutil"], "Dual License: Apache-2.0 and BSD-3-Clause")
        self.assertEqual(short["Rubik Mono One (Regular)"], "SIL Open Font License 1.1 (OFL-1.1)")
        for credit in settings_screen.credits(REPO):
            self.assertTrue(credit["licence"].startswith(credit["short"]))
            self.assertNotIn("Copyright", credit["short"])

    def test_the_version_is_the_version_file(self):
        text = (REPO / "VERSION").read_text(encoding="utf-8")
        self.assertRegex(text, r"^\d+\.\d+\.\d+(-[a-z0-9.]+)?\n$")
        self.assertEqual(settings_screen.version(REPO), text.strip())
        self.assertEqual(settings_screen.about(REPO)["version"], text.strip())
        self.assertEqual(settings_screen.about(REPO)["licence"], "GPL-3.0-or-later")
        self.assertEqual(settings_screen.about(REPO)["not_affiliated"], "Kettle Video is not affiliated with Valve.")


class ServerTest(unittest.TestCase):
    """Settings through the server, with the places pointed at invented folders."""

    PRIVATE = ("CardLabel", "home-of-someone", os.sep + "Films", os.sep + "Shows", os.sep + "Cinema")

    def setUp(self):
        self.real_before = real_settings_stamp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.card = self.root / "CardLabel"
        self.home = self.root / "home-of-someone"
        make(str(self.card), ["Loose Clip.mkv", "Films/Alpha (2001)/Alpha (2001).mkv", "Films/Beta (2002)/Beta (2002).mkv",
                              "Cinema/Alpha (2001)/Alpha (2001).mkv", "Cinema/Delta (2004)/Delta (2004).mkv"])
        make(str(self.home), ["Videos/Shows/Gamma/Season 1/Gamma S01E01.mkv", "Videos/Shows/Gamma/Season 1/Gamma S01E02.mkv"])
        (self.root / "logs").mkdir()
        self.media_before = snapshot(str(self.card)), snapshot(str(self.home))
        places = lambda: [ff.Place("internal", "Internal storage", str(self.home)),
                          ff.Place("sd", "SD card", str(self.card))]
        self.logged = []
        self.answers = []
        for target, name, value in ((ff, "list_places", places), (server, "_log", self.logged.append)):
            patch = mock.patch.object(target, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        self.scans = 0
        real_scan = library_index.full_scan

        def counted(*args):
            self.scans += 1
            return real_scan(*args)
        patch = mock.patch.object(library_index, "full_scan", side_effect=counted)
        patch.start()
        self.addCleanup(patch.stop)
        self.films, self.cinema = str(self.card / "Films"), str(self.card / "Cinema")
        self.shows = str(self.home / "Videos" / "Shows")
        self.settings_file = self.root / "app" / "settings.json"
        self.settings_file.parent.mkdir()
        self.write_settings(self.films, self.shows)

    def write_settings(self, movies, tv):
        self.settings_file.write_text(json.dumps({"movies_path": movies, "tv_path": tv, **OTHER_SETTINGS}, indent=4))

    def tearDown(self):
        # Nothing private was ever sent or logged, the invented folders are
        # untouched, and the app's own settings.json was never written.
        for text in self.answers + self.logged:
            for private in (self.tmp.name, *self.PRIVATE):
                self.assertNotIn(private, text)
        for line in self.logged:
            for name in ("Alpha", "Beta", "Gamma", "Delta"):
                self.assertNotIn(name, line)
        self.assertEqual((snapshot(str(self.card)), snapshot(str(self.home))), self.media_before)
        self.assertEqual(real_settings_stamp(), self.real_before)

    def start(self, movies=None, tv=None, resume=False):
        movies = self.films if movies is None else movies
        tv = self.shows if tv is None else tv
        self.data = self.root / "data"
        settings = {"movies_path": movies, "tv_path": tv, "mpv_command": "auto", "mpv_args": [],
                    "resume": resume, "keep_awake": False, "data_dir": str(self.data)}
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        self.port = self.httpd.server_address[1]
        with contextlib.redirect_stdout(io.StringIO()):
            base = server.make_handler(UI_DIR, self.root / "logs", settings, {}, self.port, None, self.settings_file)

        class Quiet(base):
            def log_message(self, format, *args):
                pass

        self.httpd.RequestHandlerClass = Quiet
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def request(self, method, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            data = json.dumps(body).encode() if body is not None else None
            conn.request(method, path, body=data, headers={"Host": f"127.0.0.1:{self.port}",
                                                           "Content-Type": "application/json"})
            resp = conn.getresponse()
            text = resp.read().decode("utf-8")
        finally:
            conn.close()
        self.answers.append(text)
        return resp.status, json.loads(text)

    def ids(self):
        status, answer = self.request("GET", "/api/onboarding/folders")
        self.assertEqual(status, 200)
        return {("whole " + folder["place"]) if folder["whole_place"] else folder["name"]: folder["id"]
                for place in answer["places"] for folder in place["folders"]}

    def choose(self, kind, folder):
        status, answer = self.request("POST", "/api/settings/folder", {"kind": kind, "id": folder})
        self.assertEqual(status, 200)
        return answer

    def wait_for_scan(self):
        end = time.time() + 20
        while time.time() < end:
            if self.request("GET", "/api/library/scan/status")[1]["state"] == "idle":
                return
            time.sleep(0.05)
        self.fail("the scan never finished")

    def scan_first(self):
        """A saved library for the folders set at the start."""
        self.assertTrue(self.request("POST", "/api/library/scan")[1]["started"])
        self.wait_for_scan()
        self.scans = 0

    def saved(self):
        return json.loads(self.settings_file.read_text(encoding="utf-8"))

    def movies(self):
        status, library = self.request("GET", "/api/library/parsed")
        return {item["display_title"]: item["missing"] for item in library["movies"]["items"]}

    def test_the_settings_answer_has_place_paths_ids_and_about(self):
        self.start()
        status, answer = self.request("GET", "/api/settings")
        self.assertEqual(status, 200)
        ids = self.ids()
        self.assertEqual(answer["folders"]["movies"], {"set": True, "path": "SD card › Films", "id": ids["Films"]})
        self.assertEqual(answer["folders"]["tv"], {"set": True, "path": "Internal storage › Shows", "id": ids["Shows"]})
        self.assertEqual([c["name"] for c in answer["credits"]], table_names())
        self.assertEqual(answer["version"], (REPO / "VERSION").read_text(encoding="utf-8").strip())
        self.assertEqual(answer["licence"], "GPL-3.0-or-later")
        self.start(tv="")
        self.assertEqual(self.request("GET", "/api/settings")[1]["folders"]["tv"], {"set": False})

    def test_a_licence_text_is_asked_for_by_its_credits_id_only(self):
        self.start()
        status, answer = self.request("GET", "/api/settings/licence?id=six")
        self.assertEqual((status, answer["name"]), (200, "six"))
        self.assertEqual(answer["text"], (REPO / "vendor" / "six.LICENSE").read_text(encoding="utf-8"))
        for bad in ("mpv", "nothing", "..%2FLICENSE", "vendor%2Fsix.LICENSE", ""):
            with self.subTest(bad=bad):
                self.assertEqual(self.request("GET", f"/api/settings/licence?id={bad}")[0], 404)
        self.answers.clear()  # licence texts name their authors' sites, not this device

    def test_a_folder_change_is_saved_and_starts_exactly_one_rescan(self):
        self.start()
        self.scan_first()
        self.assertEqual(self.movies(), {"Alpha (2001)": False, "Beta (2002)": False})
        ids = self.ids()
        answer = self.choose("movies", ids["Cinema"])
        self.assertEqual((answer["ok"], answer["changed"]), (True, True))
        self.assertTrue(answer["scan"]["started"])
        data = self.saved()
        self.assertEqual((data["movies_path"], data["tv_path"]), (self.cinema, self.shows))
        self.assertEqual(list(data), ["movies_path", "tv_path", *OTHER_SETTINGS])
        self.assertEqual({k: v for k, v in data.items() if k not in ("movies_path", "tv_path")}, OTHER_SETTINGS)
        self.wait_for_scan()
        self.assertEqual(self.scans, 1)
        self.assertIn("settings: movies folder changed, settings saved", self.logged)
        # Beta was only in the old folder: missing until removed. Alpha is in
        # the new one at the same place: back as normal. Delta is new.
        self.assertEqual(self.movies(), {"Alpha (2001)": False, "Beta (2002)": True, "Delta (2004)": False})
        status, settings = self.request("GET", "/api/settings")
        self.assertEqual(settings["folders"]["movies"]["path"], "SD card › Cinema")
        # Remove N missing items clears it.
        self.assertEqual(self.request("POST", "/api/library/remove-missing")[1], {"ok": True, "removed": 1})
        self.assertEqual(self.movies(), {"Alpha (2001)": False, "Delta (2004)": False})

    def test_the_folder_already_set_changes_nothing(self):
        self.start()
        self.scan_first()
        before = self.settings_file.read_bytes()
        ids = self.ids()
        self.assertEqual(self.choose("movies", ids["Films"]), {"ok": True, "changed": False})
        self.assertEqual(self.choose("tv", ids["Shows"]), {"ok": True, "changed": False})
        time.sleep(0.2)
        self.assertEqual(self.scans, 0)
        self.assertEqual(self.settings_file.read_bytes(), before)

    def test_refused_choices_change_nothing(self):
        self.start()
        before = self.settings_file.read_bytes()
        ids = self.ids()
        self.assertEqual(self.choose("tv", ids["Films"]), {"ok": False, "message": onboarding.SAME})
        self.assertEqual(self.choose("tv", ids["whole SD card"]), {"ok": False, "message": onboarding.HOLDS_MOVIES})
        self.assertEqual(self.choose("tv", "0123456789abcdef"), {"ok": False, "message": onboarding.GONE})
        self.assertEqual(self.choose("movies", ids["Shows"]), {"ok": False, "message": settings_screen.SAME_TV})
        for body in ({"kind": "films", "id": None}, {"kind": "movies", "id": 5}, {"id": None}, [1]):
            with self.subTest(body=body):
                self.assertEqual(self.request("POST", "/api/settings/folder", body)[0], 400)
        self.assertEqual(self.settings_file.read_bytes(), before)
        self.assertEqual(self.scans, 0)

    def test_stopping_the_second_kind_is_refused_and_the_first_saves_it_empty(self):
        self.start()
        self.assertEqual(self.choose("tv", None), {"ok": True, "changed": True, "scan": None})
        self.assertEqual(self.saved()["tv_path"], "")
        self.assertIn("settings: tv folder stopped, settings saved", self.logged)
        before = self.settings_file.read_bytes()
        self.assertEqual(self.choose("movies", None), {"ok": False, "message": settings_screen.KEEP_ONE["movies"]})
        self.assertEqual(self.settings_file.read_bytes(), before)
        self.assertEqual(self.scans, 0)
        status, library = self.request("GET", "/api/library/parsed")
        self.assertFalse(library["tv"]["folder_set"])

    def test_not_while_a_scan_runs(self):
        self.start()
        ids = self.ids()
        go = threading.Event()
        real_scan = library_index.full_scan.side_effect

        def held(*args):
            go.wait(10)
            return real_scan(*args)
        library_index.full_scan.side_effect = held
        self.assertTrue(self.request("POST", "/api/library/scan")[1]["started"])
        before = self.settings_file.read_bytes()
        self.assertEqual(self.choose("movies", ids["Cinema"]), {"ok": False, "message": settings_screen.SCANNING})
        go.set()
        self.wait_for_scan()
        self.assertEqual(self.settings_file.read_bytes(), before)

    def test_a_failed_save_changes_nothing(self):
        self.start()
        ids = self.ids()
        before = self.settings_file.read_bytes()
        denied = PermissionError(13, "Permission denied", str(self.settings_file.parent))
        with mock.patch.object(onboarding.tempfile, "mkstemp", side_effect=denied):
            self.assertEqual(self.choose("movies", ids["Cinema"]), {"ok": False, "message": onboarding.SAVE_FAILED})
        self.assertIn("settings: settings.json couldn't be written (PermissionError)", self.logged)
        self.assertEqual(self.settings_file.read_bytes(), before)
        self.assertEqual(self.request("GET", "/api/settings")[1]["folders"]["movies"]["path"], "SD card › Films")
        self.assertEqual(self.scans, 0)

    def test_a_folder_from_the_dialog_is_checked_against_the_other_kind(self):
        self.start()
        self.ids()
        picked = ("picked", self.shows)
        with mock.patch.object(server.folder_dialog, "find", return_value="kdialog"), \
                mock.patch.object(server.folder_dialog, "start", return_value=object()), \
                mock.patch.object(server.folder_dialog, "wait", return_value=picked), \
                mock.patch.object(server.folder_dialog, "PICKED", "picked"):
            status, answer = self.request("POST", "/api/onboarding/browse", {"movies": None, "settings": "movies"})
            self.assertEqual(answer["message"], settings_screen.SAME_TV)
            status, answer = self.request("POST", "/api/onboarding/browse", {"movies": None, "settings": "tv"})
            self.assertIsNone(answer["message"])
            self.assertEqual(self.request("POST", "/api/onboarding/browse", {"settings": "films"})[0], 400)

    def test_continue_watching_from_the_old_folder_shows_missing(self):
        self.data = self.root / "data"
        self.data.mkdir()
        roots = {"movies": self.films, "tv": self.shows}
        index = library_index.full_scan(roots, None, lambda done, total: None)
        library_index.save(self.data / library_index.FILE_NAME, index)
        store = continue_watching.ContinueWatching(self.data, roots.values(), lambda line: None)
        for title in ("Alpha (2001)", "Beta (2002)"):
            rel = f"{title}/{title}.mkv"
            target = continue_watching.locate(index, roots, "movies", rel)
            store.record_stop(target, rel, {"position": 600.0, "duration": 7200.0}, None, time.time())
        self.start(resume=True)
        self.scans = 0
        self.assertEqual([i["missing"] for i in self.request("GET", "/api/continue")[1]["items"]], [False, False])
        self.choose("movies", self.ids()["Cinema"])
        self.wait_for_scan()
        items = {i["title"]: i["missing"] for i in self.request("GET", "/api/continue")[1]["items"]}
        self.assertEqual(items, {"Alpha": False, "Beta": True})


class FreshStartTest(unittest.TestCase):
    """Fresh start: a folder change goes to the session's own settings only."""

    def test_the_real_settings_file_stays_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make(str(root / "media"), ["Films/Alpha/a.mkv", "Cinema/Delta/d.mkv", "Shows/Gamma/S01E01.mkv"])
            app = root / "app"
            app.mkdir()
            real = app / "settings.json"
            real.write_text(json.dumps({"movies_path": str(root / "media" / "Films"),
                                        "tv_path": str(root / "media" / "Shows"), **OTHER_SETTINGS}, indent=4))
            before = real.read_bytes(), os.stat(real).st_mtime_ns
            fresh_parent = root / "fresh"
            fresh_parent.mkdir()
            places = lambda: [ff.Place("internal", "Internal storage", str(root / "media"))]
            port = free_port()
            httpd_ref = {}

            def run():
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    server.serve(app, {"KETTLE_FRESH_START": "1"}, port, httpd_ref, fresh_parent)

            with mock.patch.object(ff, "list_places", places):
                thread = threading.Thread(target=run, daemon=True)
                thread.start()
                end = time.time() + 10
                while "server" not in httpd_ref and time.time() < end:
                    time.sleep(0.05)
                try:
                    conn = lambda: http.client.HTTPConnection("127.0.0.1", port, timeout=10)

                    def call(method, path, body=None):
                        c = conn()
                        c.request(method, path, body=json.dumps(body).encode() if body is not None else None,
                                  headers={"Host": f"127.0.0.1:{port}", "Content-Type": "application/json"})
                        answer = json.loads(c.getresponse().read())
                        c.close()
                        return answer

                    found = call("GET", "/api/onboarding/folders")
                    ids = {f["name"]: f["id"] for p in found["places"] for f in p["folders"]}
                    self.assertEqual(call("POST", "/api/onboarding/choose", {"movies": ids["Films"], "tv": ids["Shows"]}),
                                     {"ok": True})
                    answer = call("POST", "/api/settings/folder", {"kind": "movies", "id": ids["Cinema"]})
                    self.assertEqual((answer["ok"], answer["changed"]), (True, True))
                    session = next(fresh_parent.glob("kettle-fresh-*")) / "settings.json"
                    self.assertEqual(json.loads(session.read_text())["movies_path"], str(root / "media" / "Cinema"))
                    end = time.time() + 10
                    while call("GET", "/api/library/scan/status")["state"] != "idle" and time.time() < end:
                        time.sleep(0.05)
                finally:
                    httpd_ref["server"].shutdown()
                    thread.join(10)
            self.assertEqual((real.read_bytes(), os.stat(real).st_mtime_ns), before)
            self.assertEqual(REAL_SETTINGS.parent, REPO)


if __name__ == "__main__":
    unittest.main()
