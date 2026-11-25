# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Onboarding 1b (the folder choice screens): choosing the Movies and TV Shows folders.
Every folder, file and settings file here is invented, in a temporary
folder; the app's own settings.json is never read or written.

Checks: the three refused pairs and their sentences (links included);
skipping one kind; skipping both is refused with its sentence; the folders
are saved under today's keys, every other setting kept in its order, the
file swapped in whole, and a failed save (no temporary file, a folder name
that isn't text, a failed swap) leaves it unchanged with no path in its
text; the flow is needed only when neither folder is set, which includes no
settings file and a copy of the example; an empty folder is never scanned or
played from, and rescans don't report it; and through the server: the whole
flow by ids, the real start saving to the app's own settings file (creating
it if there is none), a launch with no folders set or a kind skipped keeping
the saved library and Continue watching, no full path in any answer or log
line, the invented folders byte-for-byte unchanged. From the series review
(the first onboarding review fixes): a name ending in a space comes back at the next launch; a folder
holding Kettle's own files is refused; the plain list's words for a skipped kind.

Run from the repo root:  python3 -m unittest tests.test_onboarding -v
"""

import contextlib
import http.client
import io
import json
import os
import shutil
import stat
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from backend import folder_finder as ff
from backend import continue_watching, library_index, onboarding, server
from backend.settings import load_settings
from tests.test_folder_finder import make, snapshot
from tests.test_launch_options import free_port

REPO = Path(__file__).resolve().parent.parent
UI_DIR = REPO / "ui"
REAL_SETTINGS = REPO / "settings.json"

OTHER_SETTINGS = {
    "mpv_command": "auto",
    "mpv_args": ["--hwdec=auto"],
    "resume": False,
    "keep_awake": True,
    "dev_auto_update": True,
    "data_dir": "data",
    "a_setting_from_later": {"kept": [1, 2, 3]},
}


def real_settings_stamp():
    """When and how big the app's own settings.json is, without reading it."""
    try:
        st = os.stat(REAL_SETTINGS)
    except FileNotFoundError:
        return None
    return (st.st_size, st.st_mtime_ns, st.st_ino)


class ProblemTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        for rel in ("Card/Films/Old", "Card/Films2", "Card/Shows", "Home/Videos"):
            (root / rel).mkdir(parents=True)
        (root / "Card/LinkToFilms").symlink_to(root / "Card/Films")
        self.p = lambda rel: str(root / rel)

    def test_the_same_folder_twice(self):
        self.assertEqual(onboarding.problem(self.p("Card/Films"), self.p("Card/Films")), onboarding.SAME)
        self.assertEqual(onboarding.SAME, "Already your movies folder. Movies and TV shows need separate "
                                          "folders, so pick a different one.")

    def test_the_same_folder_through_a_link(self):
        self.assertEqual(onboarding.problem(self.p("Card/Films"), self.p("Card/LinkToFilms")), onboarding.SAME)

    def test_a_folder_inside_the_movies_folder(self):
        self.assertEqual(onboarding.problem(self.p("Card/Films"), self.p("Card/Films/Old")),
                         onboarding.INSIDE_MOVIES)
        self.assertEqual(onboarding.INSIDE_MOVIES, "This folder is inside your movies folder, so pick a different one.")

    def test_a_folder_that_holds_the_movies_folder(self):
        self.assertEqual(onboarding.problem(self.p("Card/Films/Old"), self.p("Card")), onboarding.HOLDS_MOVIES)
        self.assertEqual(onboarding.HOLDS_MOVIES, "Your movies folder is inside this one, so pick a different one.")

    def test_separate_folders_are_fine(self):
        for movies, tv in (("Card/Films", "Card/Shows"), ("Card/Films", "Card/Films2"),
                           ("Card/Films", "Home/Videos")):
            with self.subTest(movies=movies, tv=tv):
                self.assertIsNone(onboarding.problem(self.p(movies), self.p(tv)))

    def test_skipping_one_kind(self):
        self.assertIsNone(onboarding.problem(self.p("Card/Films"), None))
        self.assertIsNone(onboarding.problem(None, self.p("Card/Shows")))

    def test_skipping_both_is_refused(self):
        self.assertEqual(onboarding.problem(None, None), onboarding.NEITHER)
        self.assertEqual(onboarding.NEITHER, "Choose a folder for movies or for TV shows to continue.")


class SaveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.file = self.folder / "settings.json"
        data = {"movies_path": "", "tv_path": "", **OTHER_SETTINGS}
        self.file.write_text(json.dumps(data), encoding="utf-8")

    def saved(self):
        return json.loads(self.file.read_text(encoding="utf-8"))

    def test_saved_under_todays_keys_keeping_every_other_setting(self):
        onboarding.save_folders(self.file, "/invented/Films", "/invented/Shows")
        data = self.saved()
        self.assertEqual((data["movies_path"], data["tv_path"]), ("/invented/Films", "/invented/Shows"))
        self.assertEqual({k: v for k, v in data.items() if k not in ("movies_path", "tv_path")}, OTHER_SETTINGS)
        self.assertEqual(list(data), ["movies_path", "tv_path", *OTHER_SETTINGS])
        # Readable for hand editing: indented, one setting per line.
        text = self.file.read_text(encoding="utf-8")
        self.assertTrue(text.endswith("}\n"))
        self.assertIn('\n  "tv_path": "/invented/Shows",\n', text)

    def test_a_skipped_kind_stays_empty(self):
        onboarding.save_folders(self.file, None, "/invented/Shows")
        self.assertEqual((self.saved()["movies_path"], self.saved()["tv_path"]), ("", "/invented/Shows"))

    def test_the_saved_file_loads_as_settings(self):
        onboarding.save_folders(self.file, "/invented/Films", None)
        data = load_settings(self.folder)
        self.assertEqual((data["movies_path"], data["tv_path"]), ("/invented/Films", ""))
        self.assertFalse(data["resume"])

    def test_names_in_any_script_are_kept(self):
        onboarding.save_folders(self.file, "/invented/Фильмы", "/invented/番組")
        self.assertIn("Фильмы", self.file.read_text(encoding="utf-8"))
        self.assertEqual(self.saved()["tv_path"], "/invented/番組")

    def test_swapped_in_whole_with_nothing_left_behind(self):
        self.file.chmod(0o600)
        inode = self.file.stat().st_ino
        onboarding.save_folders(self.file, "/invented/Films", None)
        self.assertEqual(sorted(os.listdir(self.folder)), ["settings.json"])
        self.assertEqual(stat.S_IMODE(self.file.stat().st_mode), 0o600)
        # A new file took its place (the old one was never written into).
        self.assertNotEqual(self.file.stat().st_ino, inode)

    def test_a_failed_write_leaves_it_unchanged(self):
        before = self.file.read_bytes()
        with mock.patch.object(onboarding.os, "replace", side_effect=OSError("disk full")):
            with self.assertRaises(onboarding.SaveError) as exc:
                onboarding.save_folders(self.file, "/invented/Films", None)
        self.assertEqual(self.file.read_bytes(), before)
        self.assertEqual(sorted(os.listdir(self.folder)), ["settings.json"])
        self.assertNotIn(self.tmp.name, str(exc.exception))

    def test_no_temporary_file_can_be_made(self):
        # An app folder that can't be written: the error's text holds its path.
        before = self.file.read_bytes()
        denied = PermissionError(13, "Permission denied", str(self.folder))
        with mock.patch.object(onboarding.tempfile, "mkstemp", side_effect=denied):
            with self.assertRaises(onboarding.SaveError) as exc:
                onboarding.save_folders(self.file, "/invented/Films", None)
        self.assertEqual(self.file.read_bytes(), before)
        self.assertNotIn(self.tmp.name, str(exc.exception))
        self.assertTrue(exc.exception.__suppress_context__)

    def test_a_folder_name_that_isnt_valid_text(self):
        before = self.file.read_bytes()
        with self.assertRaises(onboarding.SaveError) as exc:
            onboarding.save_folders(self.file, "/invented/bad\udcffname", None)
        self.assertEqual(self.file.read_bytes(), before)
        self.assertEqual(sorted(os.listdir(self.folder)), ["settings.json"])
        self.assertNotIn("invented", str(exc.exception))

    def test_no_file_yet_creates_it(self):
        self.file.unlink()
        onboarding.save_folders(self.file, "/invented/Films", None)
        self.assertEqual(self.saved(), {"movies_path": "/invented/Films", "tv_path": ""})
        self.assertEqual(sorted(os.listdir(self.folder)), ["settings.json"])
        self.assertEqual(load_settings(self.folder)["movies_path"], "/invented/Films")

    def test_a_file_that_cant_be_read_is_left_alone(self):
        for raw in (b"{not json", b"[1, 2]", b"\xff\xfe"):
            with self.subTest(raw=raw):
                self.file.write_bytes(raw)
                with self.assertRaises(onboarding.SaveError) as exc:
                    onboarding.save_folders(self.file, "/invented/Films", None)
                self.assertEqual(self.file.read_bytes(), raw)
                self.assertNotIn(self.tmp.name, str(exc.exception))

    def test_a_name_ending_in_a_space_comes_back_at_the_next_launch(self):
        # The first onboarding review fixes: load_settings trims a path, so it must not be saved bare.
        for name in ("Films ", "Films\t", "Films #" "1? 100% ", "Фильмы "):
            with self.subTest(name=name):
                onboarding.save_folders(self.file, f"/invented/{name}", f"/invented/Shows {name}")
                data = load_settings(self.folder)
                self.assertEqual(data["movies_path"], f"/invented/{name}")
                self.assertEqual(data["tv_path"], f"/invented/Shows {name}")

    def test_any_other_name_stays_plain_for_hand_editing(self):
        onboarding.save_folders(self.file, "/invented/My Films", "/invented/Shows #" "1")
        self.assertEqual((self.saved()["movies_path"], self.saved()["tv_path"]),
                         ("/invented/My Films", "/invented/Shows #" "1"))

    def test_a_name_ending_in_a_space_that_isnt_valid_text(self):
        before = self.file.read_bytes()
        with self.assertRaises(onboarding.SaveError):
            onboarding.save_folders(self.file, "/invented/bad\udcffname ", None)
        self.assertEqual(self.file.read_bytes(), before)
        self.assertEqual(sorted(os.listdir(self.folder)), ["settings.json"])

    def test_the_log_line_names_no_folder(self):
        self.assertEqual(onboarding.log_line("/invented/Films", None),
                         "onboarding: movies chosen, tv skipped, settings saved")


class OwnFilesTest(unittest.TestCase):
    """The first onboarding review fixes: a folder that holds Kettle's own files can't be chosen."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        for rel in ("home/kettle/data", "home/Videos", "other"):
            (root / rel).mkdir(parents=True)
        (root / "link-to-home").symlink_to(root / "home")
        self.own = [root / "home" / "kettle", root / "home" / "kettle" / "data"]
        self.p = lambda rel: str(root / rel)

    def test_a_folder_holding_kettles_own_files_is_refused(self):
        for rel in ("home", "home/kettle", "link-to-home"):
            with self.subTest(rel=rel):
                self.assertEqual(onboarding.own_files_problem(self.p(rel), self.own), onboarding.OWN_FILES)

    def test_any_other_folder_is_fine(self):
        for rel in ("home/Videos", "other"):
            with self.subTest(rel=rel):
                self.assertIsNone(onboarding.own_files_problem(self.p(rel), self.own))

    def test_a_data_folder_elsewhere_counts_too(self):
        self.assertEqual(onboarding.own_files_problem(self.p("other"), [self.p("other/data")]), onboarding.OWN_FILES)


class NeededTest(unittest.TestCase):
    def test_needed_only_when_neither_folder_is_set(self):
        self.assertTrue(onboarding.needed({"movies_path": "", "tv_path": ""}))
        self.assertFalse(onboarding.needed({"movies_path": "/invented/Films", "tv_path": ""}))
        self.assertFalse(onboarding.needed({"movies_path": "", "tv_path": "/invented/Shows"}))
        self.assertFalse(onboarding.needed({"movies_path": "/a", "tv_path": "/b"}))

    def test_an_empty_folder_is_never_available(self):
        # Path("") would be the app's own folder: an empty one is not set.
        self.assertEqual(library_index.availability({"movies": "", "tv": ""}), {"movies": False, "tv": False})

    def test_the_example_settings_start_the_flow(self):
        # Copying the example, as the README says, must not count as set.
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copy(REPO / "settings.example.json", Path(tmp) / "settings.json")
            self.assertTrue(onboarding.needed(load_settings(Path(tmp))))

    def test_no_settings_file_starts_the_flow(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(onboarding.needed(load_settings(Path(tmp))))

    def test_a_skipped_kind_is_not_reported_as_not_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            make(tmp, ["Alpha/a.mkv"])
            first = library_index.full_scan({"movies": tmp, "tv": ""}, None, lambda done, total: None)
            self.assertEqual(first["last_scan"]["not_available"], [])
            again = library_index.full_scan({"movies": tmp, "tv": ""}, first, lambda done, total: None)
            self.assertEqual(library_index.scan_message(first, again), "No changes")
            # A folder that is set and isn't there still says so.
            gone = library_index.full_scan({"movies": tmp, "tv": os.path.join(tmp, "gone")}, first,
                                           lambda done, total: None)
            self.assertEqual(library_index.scan_message(first, gone), "TV Shows folder not available")


class ServerTest(unittest.TestCase):
    """The flow through the server, with the places pointed at invented folders."""

    def setUp(self):
        self.real_before = real_settings_stamp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.card = self.root / "CardLabel"
        self.home = self.root / "home-of-someone"
        # The card: a video at its top (so the whole card is offered) and a
        # Films folder inside it; at home, a Shows folder.
        make(str(self.card), ["top-secret-video.mkv", "Films/Alpha/a.mkv", "Films/Beta/b.mkv"])
        make(str(self.home), ["Videos/Shows/Gamma/Season 1/e1.mkv", "Videos/Shows/Delta/e1.mkv"])
        (self.root / "logs").mkdir()
        self.media_before = snapshot(str(self.root / "CardLabel")), snapshot(str(self.home))
        places = lambda: [ff.Place("internal", "Internal storage", str(self.home)),
                          ff.Place("sd", "SD card", str(self.card))]
        for target, name, value in ((ff, "list_places", places), (server, "_log", self.log)):
            patch = mock.patch.object(target, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        self.logged = []
        self.answers = []
        self.settings_file = self.root / "app" / "settings.json"
        self.settings_file.parent.mkdir()
        self.settings_file.write_text(json.dumps({"movies_path": "", "tv_path": "", **OTHER_SETTINGS}, indent=4))

    def log(self, line):
        self.logged.append(line)

    def start(self, settings_file="default", **paths):
        settings = {"movies_path": "", "tv_path": "", "mpv_command": "auto", "mpv_args": [],
                    "resume": False, "keep_awake": False, "data_dir": str(self.root / "data"), **paths}
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        self.port = self.httpd.server_address[1]
        target = self.settings_file if settings_file == "default" else settings_file
        with contextlib.redirect_stdout(io.StringIO()):
            base = server.make_handler(UI_DIR, self.root / "logs", settings, {}, self.port, None, target)

        class Quiet(base):
            def log_message(self, format, *args):
                pass

        self.httpd.RequestHandlerClass = Quiet
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def request(self, method, path, body=None, raw=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
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
        found = {}
        for place in answer["places"]:
            for folder in place["folders"]:
                found["whole card" if folder["whole_place"] else folder["name"]] = folder["id"]
        self.assertEqual(set(found), {"whole card", "Films", "Shows"})
        return found

    def choose(self, movies, tv):
        status, answer = self.request("POST", "/api/onboarding/choose", {"movies": movies, "tv": tv})
        self.assertEqual(status, 200)
        return answer

    def tearDown(self):
        # Nothing private was ever sent or logged, the invented folders are
        # untouched, and the app's own settings.json was never written.
        for text in self.answers + self.logged:
            for private in (self.tmp.name, "CardLabel", "home-of-someone", os.sep + "Films", os.sep + "Shows"):
                self.assertNotIn(private, text)
        for line in self.logged:
            for name in ("Alpha", "Beta", "Gamma", "Delta", "top-secret-video"):
                self.assertNotIn(name, line)
        self.assertEqual((snapshot(str(self.card)), snapshot(str(self.home))), self.media_before)
        self.assertEqual(real_settings_stamp(), self.real_before)

    def test_needed_answers(self):
        self.start()
        self.assertEqual(self.request("GET", "/api/onboarding"), (200, {"needed": True}))

    def test_not_needed_when_either_folder_is_set(self):
        for paths in ({"movies_path": str(self.card / "Films")}, {"tv_path": str(self.home)}):
            with self.subTest(paths=paths):
                self.start(**paths)
                self.assertEqual(self.request("GET", "/api/onboarding"), (200, {"needed": False}))

    def test_the_whole_flow(self):
        self.start()
        before = self.settings_file.read_bytes()
        ids = self.ids()
        # The three refused pairs and both skipped: settings.json unchanged.
        self.assertEqual(self.choose(ids["Films"], ids["Films"]), {"ok": False, "message": onboarding.SAME})
        self.assertEqual(self.choose(ids["whole card"], ids["Films"]),
                         {"ok": False, "message": onboarding.INSIDE_MOVIES})
        self.assertEqual(self.choose(ids["Films"], ids["whole card"]),
                         {"ok": False, "message": onboarding.HOLDS_MOVIES})
        self.assertEqual(self.choose(None, None), {"ok": False, "message": onboarding.NEITHER})
        self.assertEqual(self.choose("0123456789abcdef", None), {"ok": False, "message": onboarding.GONE})
        self.assertEqual(self.settings_file.read_bytes(), before)
        # Look again: the ids from before still count.
        self.assertEqual(self.ids(), ids)
        self.assertEqual(self.choose(ids["Films"], ids["Shows"]), {"ok": True})
        data = json.loads(self.settings_file.read_text(encoding="utf-8"))
        self.assertEqual(data["movies_path"], str(self.card / "Films"))
        self.assertEqual(data["tv_path"], str(self.home / "Videos" / "Shows"))
        self.assertEqual({k: v for k, v in data.items() if k not in ("movies_path", "tv_path")}, OTHER_SETTINGS)
        self.assertIn("onboarding: movies chosen, tv chosen, settings saved", self.logged)
        # The app uses them at once: no longer needed, both folders there.
        self.assertEqual(self.request("GET", "/api/onboarding"), (200, {"needed": False}))
        status, library = self.request("GET", "/api/library/parsed")
        self.assertEqual((library["movies"]["available"], library["tv"]["available"]), (True, True))
        self.assertFalse(library["movies"]["has_library"])

    def test_skipping_one_kind_saves_it_empty(self):
        self.start()
        ids = self.ids()
        self.assertEqual(self.choose(None, ids["Shows"]), {"ok": True})
        data = json.loads(self.settings_file.read_text(encoding="utf-8"))
        self.assertEqual((data["movies_path"], data["tv_path"]), ("", str(self.home / "Videos" / "Shows")))
        self.assertIn("onboarding: movies skipped, tv chosen, settings saved", self.logged)

    def test_a_failed_save_gets_a_plain_line_in_the_log(self):
        self.start()
        ids = self.ids()
        before = self.settings_file.read_bytes()
        denied = PermissionError(13, "Permission denied", str(self.settings_file.parent))
        with mock.patch.object(onboarding.tempfile, "mkstemp", side_effect=denied):
            self.assertEqual(self.choose(ids["Films"], None), {"ok": False, "message": onboarding.SAVE_FAILED})
        self.assertIn("onboarding: settings.json couldn't be written (PermissionError)", self.logged)
        self.assertEqual(self.settings_file.read_bytes(), before)
        self.assertEqual(self.request("GET", "/api/onboarding"), (200, {"needed": True}))

    def test_the_answer_says_which_kind_has_no_folder(self):
        self.start(movies_path=str(self.card / "Films"))
        status, library = self.request("GET", "/api/library/parsed")
        self.assertEqual((library["movies"]["folder_set"], library["tv"]["folder_set"]), (True, False))

    def serve_for_real(self):
        """The app's real start, in the invented app folder: nothing passes
        it the settings file, so this checks it finds its own."""
        self.port = free_port()
        httpd_ref = {}
        out = io.StringIO()

        def run():
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                server.serve(self.settings_file.parent, {}, self.port, httpd_ref)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 10)
        self.addCleanup(lambda: httpd_ref["server"].shutdown())
        end = time.time() + 10
        while "server" not in httpd_ref and time.time() < end:
            time.sleep(0.05)
        self.assertIn("server", httpd_ref)

    def test_the_real_start_saves_to_the_apps_own_settings_file(self):
        self.serve_for_real()
        self.assertEqual(self.request("GET", "/api/onboarding"), (200, {"needed": True}))
        ids = self.ids()
        self.assertEqual(self.choose(ids["Films"], ids["Shows"]), {"ok": True})
        data = json.loads(self.settings_file.read_text(encoding="utf-8"))
        self.assertEqual(data["movies_path"], str(self.card / "Films"))
        self.assertEqual(data["a_setting_from_later"], OTHER_SETTINGS["a_setting_from_later"])

    def test_the_real_start_with_no_settings_file_creates_it(self):
        self.settings_file.unlink()
        self.serve_for_real()
        self.assertEqual(self.request("GET", "/api/onboarding"), (200, {"needed": True}))
        ids = self.ids()
        self.assertEqual(self.choose(None, ids["Shows"]), {"ok": True})
        data = json.loads(self.settings_file.read_text(encoding="utf-8"))
        self.assertEqual((data["movies_path"], data["tv_path"]), ("", str(self.home / "Videos" / "Shows")))
        # The next launch reads what was saved.
        self.assertFalse(onboarding.needed(load_settings(self.settings_file.parent)))

    def saved_row(self):
        """A saved library and a Continue watching list holding one film and
        one episode, as if both folders had been in use. Temporary folders."""
        data = self.root / "data"
        data.mkdir(exist_ok=True)
        roots = {"movies": str(self.card / "Films"), "tv": str(self.home / "Videos" / "Shows")}
        index = library_index.full_scan(roots, None, lambda done, total: None)
        library_index.save(data / library_index.FILE_NAME, index)
        store = continue_watching.ContinueWatching(data, roots.values(), self.log)
        frame = self.root / "frame.jpg"
        frame.write_bytes(b"\xff\xd8 frame")
        for source in roots:
            item = index["sources"][source]["items"][0]
            rel = library_index.children(source, item)[0]["path"]
            target = continue_watching.locate(index, roots, source, rel)
            store.record_stop(target, rel, {"position": 600.0, "duration": 7200.0}, frame, time.time())
        self.assertEqual(len(store.visible()), 2)
        return roots, data

    def saved_files(self, data):
        return {path.relative_to(data): path.read_bytes() for path in data.rglob("*") if path.is_file()}

    def test_a_launch_with_no_folders_set_keeps_library_and_row(self):
        roots, data = self.saved_row()
        before = self.saved_files(data)
        self.assertEqual(len([p for p in before if p.suffix == ".jpg"]), 2)
        self.start()  # the launch, with both folders empty
        self.assertEqual(self.request("GET", "/api/onboarding"), (200, {"needed": True}))
        self.assertEqual(self.saved_files(data), before)
        # With the same folders back, the row is all still there.
        self.start(movies_path=roots["movies"], tv_path=roots["tv"], resume=True)
        self.assertEqual(self.saved_files(data), before)
        self.assertEqual(len(self.request("GET", "/api/continue")[1]["items"]), 2)

    def test_a_skipped_kind_keeps_its_tiles_at_the_next_launch(self):
        roots, data = self.saved_row()
        before = self.saved_files(data)
        self.start(movies_path=roots["movies"], resume=True)  # TV shows skipped
        self.assertEqual(self.saved_files(data), before)
        self.assertEqual(len(self.request("GET", "/api/continue")[1]["items"]), 1)
        self.start(movies_path=roots["movies"], tv_path=roots["tv"], resume=True)
        self.assertEqual(self.saved_files(data), before)
        self.assertEqual(len(self.request("GET", "/api/continue")[1]["items"]), 2)

    def test_a_choice_that_isnt_ids_is_refused(self):
        self.start()
        before = self.settings_file.read_bytes()
        for body in ({"movies": 5, "tv": None}, {"movies": ["x"]}, [1, 2]):
            with self.subTest(body=body):
                status, _ = self.request("POST", "/api/onboarding/choose", body)
                self.assertEqual(status, 400)
        status, _ = self.request("POST", "/api/onboarding/choose", raw=b"{not json")
        self.assertEqual(status, 400)
        self.assertEqual(self.settings_file.read_bytes(), before)

    def test_without_a_settings_file_nothing_is_written(self):
        self.start(settings_file=None)
        ids = self.ids()
        self.assertEqual(self.choose(ids["Films"], None), {"ok": False, "message": onboarding.SAVE_FAILED})
        self.assertEqual(self.request("GET", "/api/onboarding"), (200, {"needed": True}))

    def test_a_listed_folder_holding_kettles_files_is_refused_in_its_row(self):
        # The first onboarding review fixes: videos at the top of the home folder, with Kettle inside it.
        make(str(self.home), ["loose.mkv"])
        self.settings_file = self.home / "kettle" / "settings.json"
        self.settings_file.parent.mkdir()
        self.settings_file.write_text(json.dumps({"movies_path": "", "tv_path": ""}))
        self.media_before = self.media_before[0], snapshot(str(self.home))
        self.start()
        status, answer = self.request("GET", "/api/onboarding/folders")
        folders = {f["id"]: f for p in answer["places"] for f in p["folders"]}
        whole = next(f for f in folders.values() if f["whole_place"] and f["place"] == "Internal storage")
        self.assertEqual(whole["problem"], onboarding.OWN_FILES)
        others = [f["problem"] for f in folders.values() if f is not whole]
        self.assertEqual(others, [None] * len(others))
        before = self.settings_file.read_bytes()
        self.assertEqual(self.choose(whole["id"], None), {"ok": False, "message": onboarding.OWN_FILES})
        self.assertEqual(self.choose(None, whole["id"]), {"ok": False, "message": onboarding.OWN_FILES})
        self.assertEqual(self.settings_file.read_bytes(), before)
        self.assertEqual(self.request("GET", "/api/onboarding"), (200, {"needed": True}))

    def test_videos_moved_into_their_own_folder_can_then_be_chosen(self):
        # The first onboarding review fixes: the refused row's words say this works, so it must.
        make(str(self.home), ["loose.mkv"])
        self.settings_file = self.home / "kettle" / "settings.json"
        self.settings_file.parent.mkdir()
        self.settings_file.write_text(json.dumps({"movies_path": "", "tv_path": ""}))
        self.start()
        self.assertIn("press Y to look again", onboarding.OWN_FILES)
        (self.home / "Mine").mkdir()
        os.rename(self.home / "loose.mkv", self.home / "Mine" / "loose.mkv")
        videos_before = snapshot(str(self.home / "Mine"))
        status, answer = self.request("GET", "/api/onboarding/folders")
        mine = next(f for p in answer["places"] for f in p["folders"] if f["name"] == "Mine")
        self.assertIsNone(mine["problem"])
        self.assertEqual(self.choose(mine["id"], None), {"ok": True})
        self.assertEqual(json.loads(self.settings_file.read_text())["movies_path"], str(self.home / "Mine"))
        self.assertEqual(snapshot(str(self.home / "Mine")), videos_before)
        # The settings file sits in this invented home, so it did change there.
        self.media_before = self.media_before[0], snapshot(str(self.home))

    def test_the_plain_list_says_a_skipped_kind_in_the_normal_words(self):
        # The first onboarding review fixes: "not set: " with nothing after the colon was a broken sentence.
        self.start(movies_path=str(self.card / "Films"))
        status, answer = self.request("GET", "/api/library")
        self.assertEqual((answer["tv"]["reason"], answer["tv"]["path"]), ("No folder chosen", ""))
        self.answers.pop()  # names its configured folder, as before the folder choice screens

    def test_an_empty_folder_is_never_played_from_or_listed(self):
        # The app's own folder holds files; an empty tv_path must never mean it.
        self.start(movies_path=str(self.card / "Films"))
        status, answer = self.request("POST", "/api/play", {"source": "tv", "path": "README.md"})
        self.assertEqual(status, 400)
        status, answer = self.request("GET", "/api/library")
        self.assertEqual((answer["tv"]["status"], answer["tv"]["groups"]), ("not_found", []))
        # The plain-list fallback names its configured folder (as before
        # The folder choice screens), so this one answer isn't part of the privacy check.
        self.answers.pop()


if __name__ == "__main__":
    unittest.main()
