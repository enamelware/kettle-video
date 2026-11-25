# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The first scan's result (the first scan screen): what the result screen is told, worked
out from the saved library, with invented folders in a temporary folder.

Run from the repo root:  python3 -m unittest tests.test_first_scan_result -v
"""

import contextlib
import http.client
import io
import json
import shutil
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from backend import continue_watching, folder_finder as ff, library_index, onboarding, server
from tests.test_folder_finder import make, snapshot

UI_DIR = Path(__file__).resolve().parent.parent / "ui"
UI = (UI_DIR / "js" / "onboarding.js").read_text(encoding="utf-8")
APP = (UI_DIR / "js" / "app.js").read_text(encoding="utf-8")
INDEX = (UI_DIR / "index.html").read_text(encoding="utf-8")

FILMS = ["Alpha (2001)/Alpha.2001.mkv", "Beta (2002)/Beta.2002.mkv"]
SHOWS = ["Gamma/Season 1/Gamma.S01E01.mkv", "Gamma/Season 1/Gamma.S01E02.mkv", "Delta/Delta.S01E01.mkv"]


def film(title, path, flags=(), status=None):
    item = {"id": title, "key": path, "title": title, "year": None, "flags": list(flags),
            "parts": [{"label": None, "path": path}]}
    if status:
        item["status"] = status
        item["parts"][0]["status"] = status
    return item


def show(title, episodes, path="", number=1, status=None):
    item = {"id": title, "key": title, "title": title, "year": None, "path": path or title,
            "seasons": [{"number": number, "episodes": episodes}]}
    if status:
        item["status"] = status
    return item


def episode(path, numbers=(1,), flags=(), status=None):
    entry = {"id": path, "numbers": list(numbers), "title": None, "path": path, "flags": list(flags)}
    if status:
        entry["status"] = status
    return entry


class ResultTest(unittest.TestCase):
    ROOTS = {"movies": "/somewhere/CardLabel/Films", "tv": "/somewhere/home/Videos"}
    PLACES = [ff.Place("sd", "SD card", "/somewhere/CardLabel"), ff.Place("internal", "Internal storage", "/somewhere/home")]

    def index(self, movies=None, tv=None, not_available=(), skipped=None):
        sources = {}
        if movies is not None:
            sources["movies"] = {"root": self.ROOTS["movies"], "items": movies, "skipped": skipped or []}
        if tv is not None:
            sources["tv"] = {"root": self.ROOTS["tv"], "items": tv, "skipped": []}
        return {"sources": sources, "last_scan": {"not_available": list(not_available)}}

    def result(self, index, roots=None):
        return onboarding.result(index, roots or self.ROOTS, self.PLACES)

    def test_the_counts_with_each_folders_place_and_name(self):
        r = self.result(self.index([film("A", "a.mkv"), film("B", "b.mkv")],
                                   [show("G", [episode("G/1.mkv"), episode("G/2.mkv", (2,))])]))
        self.assertEqual(r["movies"], {"set": True, "path": "SD card › Films", "count": 2})
        self.assertEqual(r["tv"], {"set": True, "path": "Internal storage › Videos", "shows": 1, "episodes": 2})
        self.assertEqual(r["notes"], [])
        self.assertFalse(r["nothing_found"])
        self.assertFalse(r["failed"])

    def test_a_film_in_many_parts_is_one_film(self):
        item = film("A", "A/1.mkv")
        item["parts"].append({"label": "Part 2", "path": "A/2.mkv"})
        self.assertEqual(self.result(self.index([item], []))["movies"]["count"], 1)

    def test_a_skipped_kind_says_not_set(self):
        roots = {"movies": "", "tv": self.ROOTS["tv"]}
        r = self.result(self.index(None, [show("G", [episode("G/1.mkv")])]), roots)
        self.assertEqual(r["movies"], {"set": False})
        self.assertEqual(r["tv"]["episodes"], 1)
        self.assertFalse(r["nothing_found"])
        roots = {"movies": self.ROOTS["movies"], "tv": ""}
        self.assertEqual(self.result(self.index([film("A", "a.mkv")]), roots)["tv"], {"set": False})

    def test_what_a_rescan_kept_as_missing_is_not_counted(self):
        gone = [film("Gone", "gone.mkv", status="missing")]
        shows = [show("Lost", [episode("L/1.mkv", status="missing")], status="missing"),
                 show("Half", [episode("H/1.mkv"), episode("H/2.mkv", (2,), status="missing")])]
        r = self.result(self.index(gone + [film("A", "a.mkv")], shows))
        self.assertEqual(r["movies"]["count"], 1)
        self.assertEqual((r["tv"]["shows"], r["tv"]["episodes"]), (1, 1))

    def test_only_missing_things_is_nothing_found(self):
        r = self.result(self.index([film("Gone", "gone.mkv", status="missing")], []))
        self.assertTrue(r["nothing_found"])
        self.assertEqual(r["movies"]["count"], 0)

    def test_a_library_saved_for_other_folders_counts_nothing(self):
        roots = {"movies": "/somewhere/CardLabel/Other", "tv": "/somewhere/home/Other"}
        r = self.result(self.index([film("A", "a.mkv")], [show("G", [episode("G/1.mkv")])]), roots)
        self.assertEqual((r["movies"]["count"], r["tv"]["shows"], r["tv"]["episodes"]), (0, 0, 0))
        self.assertTrue(r["nothing_found"])

    def test_the_unreadable_line_shows_only_above_zero(self):
        self.assertEqual(self.result(self.index([film("A", "a.mkv")], []))["notes"], [])
        skipped = [{"path": "bad-name.mkv", "reason": "name can't be read"},
                   {"path": "bad-file.mp4", "reason": "cannot be read"},
                   # Not files that couldn't be read: a folder, and an outside link.
                   {"path": "A folder", "reason": "cannot be read"},
                   {"path": "link.mkv", "reason": "link leads outside the folder"}]
        tv = [show("G", [episode("G/x.mkv", (), ["fallback"]), episode("G/S01E02.mkv", (2,), ["fallback"])])]
        r = self.result(self.index([film("A", "a.mkv"), film("x", "x.mkv", ["fallback"])], tv, skipped=skipped))
        self.assertEqual(r["notes"], ["4 files could not be read as a movie or an episode."])

    def test_one_unreadable_file_is_said_in_the_singular(self):
        r = self.result(self.index([film("x", "x.mkv", ["fallback"])], []))
        self.assertEqual(r["notes"], ["1 file could not be read as a movie or an episode."])
        self.assertFalse(r["nothing_found"])

    def test_files_in_the_movies_folder_that_look_like_episodes(self):
        films = [film(f"E{n}", f"Some.Show.S01E0{n}.mkv") for n in range(1, 4)] + [film("A", "a.mkv")]
        r = self.result(self.index(films, []))
        self.assertEqual(r["notes"], ["3 files in Films look like episodes."])
        self.assertFalse(r["nothing_found"])
        self.assertFalse(r["failed"])
        r = self.result(self.index([film("E", "Show 1x02.mkv")], []))
        self.assertEqual(r["notes"], ["1 file in Films looks like an episode."])

    def test_the_episode_marker_is_never_a_guess(self):
        for name in ("Show.S01E02.mkv", "show s1e2.mkv", "Show S01.E02.mkv", "Show 1x02.mkv", "Show - 10x123.mkv"):
            with self.subTest(name=name):
                self.assertTrue(onboarding.EPISODE_MARKER.search(name))
        for name in ("Quillmoor 13 (1995).mkv", "Alpha.1920x1080.mkv", "Fernhollow 3.mkv", "2001.mkv", "Gl7mmer.mkv", "Se4lwick.mkv",
                     "Brackenfold.of.1999.x264.mkv", "S1lv0rwick.mkv", "Glimmerwick's 8.mkv", "Beta.4K.HDR.mkv"):
            with self.subTest(name=name):
                self.assertIsNone(onboarding.EPISODE_MARKER.search(name))

    def test_loose_files_in_the_tv_folder_that_look_like_films(self):
        loose = show("Film", [episode("Film (1999).mkv", ())], path=".", number=None)
        numbered = show("Loose", [episode("Loose.S01E01.mkv")], path=".")
        foldered = show("Foldered", [episode("Foldered/special.mkv", ())], number=None)
        r = self.result(self.index([], [loose, numbered, foldered]))
        self.assertEqual(r["notes"], ["1 loose file in Videos looks like a film."])
        self.assertFalse(r["nothing_found"])
        more = show("Film", [episode("A (1999).mkv", ()), episode("B (2000).mkv", ())], path=".", number=None)
        self.assertEqual(self.result(self.index([], [more]))["notes"], ["2 loose files in Videos look like films."])

    def test_notes_about_a_whole_place_name_the_place(self):
        roots = {"movies": "/somewhere/CardLabel", "tv": ""}
        index = {"sources": {"movies": {"root": roots["movies"], "items": [film("E", "Show.S01E01.mkv")]}}, "last_scan": {}}
        r = self.result(index, roots)
        self.assertEqual(r["movies"]["path"], "SD card")
        self.assertEqual(r["notes"], ["1 file in SD card looks like an episode."])

    def test_nothing_found_in_either_folder(self):
        r = self.result(self.index([], []))
        self.assertTrue(r["nothing_found"])
        self.assertFalse(r["failed"])
        self.assertEqual((r["movies"]["count"], r["tv"]["shows"], r["tv"]["episodes"]), (0, 0, 0))

    def test_every_folder_out_is_a_failure(self):
        r = self.result(self.index(None, None, not_available=["movies", "tv"]))
        self.assertTrue(r["failed"])
        roots = {"movies": self.ROOTS["movies"], "tv": ""}
        self.assertTrue(self.result(self.index(None, None, not_available=["movies"]), roots)["failed"])

    def test_one_folder_out_is_a_note_and_counts_nothing_saved_for_it(self):
        r = self.result(self.index([film("Saved", "s.mkv")], [show("G", [episode("G/1.mkv")])], not_available=["movies"]))
        self.assertFalse(r["failed"])
        self.assertEqual(r["movies"]["count"], 0)
        self.assertEqual(r["notes"], ["Movies folder not available"])

    def test_no_scan_yet(self):
        r = self.result(None)
        self.assertTrue(r["nothing_found"])
        self.assertFalse(r["failed"])

    def test_no_full_path_in_the_answer(self):
        text = json.dumps(self.result(self.index([film("E", "Show.S01E01.mkv")], [])), ensure_ascii=False)
        self.assertNotIn("/somewhere", text)
        self.assertNotIn("CardLabel", text)


class PlacePathTest(unittest.TestCase):
    PLACES = ResultTest.PLACES

    def test_the_place_and_the_folders_own_name_only(self):
        self.assertEqual(ff.place_path("/somewhere/CardLabel/Media/More/Films", self.PLACES), "SD card › Films")

    def test_a_whole_place_is_the_place(self):
        self.assertEqual(ff.place_path("/somewhere/home", self.PLACES), "Internal storage")

    def test_a_folder_in_no_place(self):
        self.assertEqual(ff.place_path("/elsewhere/deep/Clips", self.PLACES), f"{ff.SOMEWHERE_ELSE} › Clips")


class ScreenCodeTest(unittest.TestCase):
    """What the browser check can't show on its own."""

    def test_the_temporary_screen_is_gone(self):
        for source in (UI, APP, INDEX):
            self.assertNotIn("first-scan", source)
            self.assertNotIn("Scan my folders", source)
            self.assertNotIn("No library yet", source)

    def test_built_from_enamels_parts(self):
        for part in ("en-statpair", "en-statpanel", "en-statpanel__counts", "en-statpanel__count", "en-statpanel__number",
                     "en-statpanel__path", "en-statpanel__notset", "en-note", "en-progress", "en-progress__head"):
            self.assertIn(part, UI)

    def test_an_empty_library_on_home_goes_to_the_scan(self):
        self.assertEqual(APP.count("showFirstScan();"), 2)


class ServerTest(unittest.TestCase):
    """The whole way through the server, with a real scan of invented folders."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.card, self.home = self.root / "CardLabel", self.root / "home-of-someone"
        make(str(self.card), [f"Films/{f}" for f in FILMS] + ["Films/Show.S01E05.mkv"])
        make(str(self.card), ["Other Films/Epsilon (2003)/Epsilon.2003.mkv", "Other Films/Zeta (2004)/Zeta.2004.mkv"])
        make(str(self.home), [f"Videos/{s}" for s in SHOWS] + ["Videos/Loose Film (1999).mkv"])
        (self.home / "Empty Films").mkdir()
        (self.home / "Empty Shows").mkdir()
        (self.root / "logs").mkdir()
        self.media_before = snapshot(str(self.card)), snapshot(str(self.home))
        places = lambda: [ff.Place("internal", "Internal storage", str(self.home)), ff.Place("sd", "SD card", str(self.card))]
        self.logged = []
        for target, name, value in ((ff, "list_places", places), (server, "_log", self.logged.append)):
            patch = mock.patch.object(target, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        self.settings_file = self.root / "app" / "settings.json"
        self.settings_file.parent.mkdir()
        self.settings_file.write_text(json.dumps({"movies_path": "", "tv_path": ""}))
        self.answers = []

    def start(self, **paths):
        settings = {"movies_path": "", "tv_path": "", "mpv_command": "auto", "mpv_args": [], "resume": True,
                    "keep_awake": False, "data_dir": str(self.root / "data"), **paths}
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
            conn.request(method, path, body=json.dumps(body).encode() if body is not None else None,
                         headers={"Host": f"127.0.0.1:{self.port}", "Content-Type": "application/json"})
            resp = conn.getresponse()
            text = resp.read().decode("utf-8")
        finally:
            conn.close()
        self.answers.append(text)
        return json.loads(text)

    def ids(self):
        # Folders with too little in them aren't suggested: the dialog's route
        # would offer them, and these tests only need their ids.
        with mock.patch.object(ff, "MIN_VIDEO_BYTES", 0):
            found = self.request("GET", "/api/onboarding/folders")
        return {folder["name"]: folder["id"] for place in found["places"] for folder in place["folders"]}

    def choose(self, movies, tv):
        self.assertEqual(self.request("POST", "/api/onboarding/choose", {"movies": movies, "tv": tv}), {"ok": True})

    def scan(self):
        self.request("POST", "/api/library/scan", {})
        end = time.time() + 30
        while time.time() < end:
            status = self.request("GET", "/api/library/scan/status")
            if status["state"] == "idle":
                return status["last_result"]
            time.sleep(0.05)
        self.fail("the scan never finished")

    def result(self):
        return self.request("GET", "/api/onboarding/result")

    def tearDown(self):
        for text in self.answers + self.logged:
            for private in (str(self.root), "CardLabel", "home-of-someone"):
                self.assertNotIn(private, text)
        self.assertEqual((snapshot(str(self.card)), snapshot(str(self.home))), self.media_before)

    def test_a_valid_choice_then_the_scan_gives_the_counts_and_notes(self):
        self.start()
        ids = self.ids()
        self.choose(ids["Films"], ids["Videos"])
        self.assertTrue(self.scan()["ok"])
        r = self.result()
        self.assertEqual(r["movies"], {"set": True, "path": "SD card › Films", "count": 3})
        self.assertEqual(r["tv"]["path"], "Internal storage › Videos")
        self.assertEqual((r["tv"]["shows"], r["tv"]["episodes"]), (3, 4))
        self.assertEqual(r["notes"], ["1 file in Films looks like an episode.", "1 loose file in Videos looks like a film."])
        self.assertFalse(r["nothing_found"])
        # The counts match the saved library the app then shows.
        library = self.request("GET", "/api/library/parsed")
        self.assertEqual(len(library["movies"]["items"]), r["movies"]["count"])
        self.assertEqual(len(library["tv"]["items"]), r["tv"]["shows"])

    def test_a_skipped_kind_says_not_set_after_a_real_scan(self):
        self.start()
        ids = self.ids()
        self.choose(ids["Films"], None)
        self.assertTrue(self.scan()["ok"])
        r = self.result()
        self.assertEqual(r["tv"], {"set": False})
        self.assertNotIn("TV Shows folder not available", r["notes"])
        self.assertFalse(r["failed"])

    def test_folders_already_set_scan_with_no_choice(self):
        self.start(movies_path=str(self.card / "Films"), tv_path=str(self.home / "Videos"))
        self.assertFalse(self.request("GET", "/api/onboarding")["needed"])
        self.assertFalse(self.request("GET", "/api/library/parsed")["movies"]["has_library"])
        self.assertTrue(self.scan()["ok"])
        self.assertEqual(self.result()["movies"]["count"], 3)

    def test_nothing_found(self):
        self.start(movies_path=str(self.home / "Empty Films"), tv_path=str(self.home / "Empty Shows"))
        self.assertTrue(self.scan()["ok"])
        r = self.result()
        self.assertTrue(r["nothing_found"])
        self.assertFalse(r["failed"])
        self.assertEqual(r["movies"]["count"], 0)
        self.assertEqual((r["tv"]["shows"], r["tv"]["episodes"]), (0, 0))

    def test_changing_folders_counts_only_whats_there_now(self):
        self.start()
        ids = self.ids()
        self.choose(ids["Films"], ids["Videos"])
        self.scan()
        self.assertEqual(self.result()["movies"]["count"], 3)
        self.choose(ids["Other Films"], None)
        self.assertTrue(self.scan()["ok"])
        r = self.result()
        self.assertEqual(r["movies"], {"set": True, "path": "SD card › Other Films", "count": 2})
        self.assertEqual(r["tv"], {"set": False})
        library = self.request("GET", "/api/library/parsed")
        self.assertEqual(sorted(m["display_title"] for m in library["movies"]["items"]), ["Epsilon (2003)", "Zeta (2004)"])

    def test_choosing_the_same_folder_again_leaves_out_what_has_gone(self):
        work = self.root / "Copy"
        shutil.copytree(self.card / "Films", work)
        self.start(movies_path=str(work))
        self.scan()
        self.assertEqual(self.result()["movies"]["count"], 3)
        shutil.rmtree(work / "Alpha (2001)")
        self.scan()
        self.assertEqual(self.result()["movies"]["count"], 2)

    def test_continue_watching_is_kept_when_folders_change(self):
        data = self.root / "data"
        self.start()
        ids = self.ids()
        self.choose(ids["Films"], ids["Videos"])
        self.scan()
        index = library_index.load(data / library_index.FILE_NAME, lambda line: None)
        item = next(i for i in index["sources"]["movies"]["items"] if i["title"] == "Alpha")
        keeper = continue_watching.ContinueWatching(data, [str(self.card / "Films")], lambda line: None)
        record = {"position": 60.0, "duration": 600.0, "frame_saved": False}
        target = {"key": item["id"], "kind": "movie", "source": "movies"}
        keeper.record_stop(target, item["parts"][0]["path"], record, None, time.time())
        before = (data / continue_watching.FILE_NAME).read_bytes()
        self.choose(ids["Other Films"], None)
        self.assertTrue(self.scan()["ok"])
        self.assertEqual((data / continue_watching.FILE_NAME).read_bytes(), before)

    def test_the_card_coming_out_is_a_failed_result(self):
        work = self.root / "Copy"
        shutil.copytree(self.card / "Films", work)
        self.start(movies_path=str(work))
        shutil.rmtree(work)
        self.assertTrue(self.scan()["ok"])
        r = self.result()
        self.assertTrue(r["failed"])
        self.assertEqual(r["notes"], ["Movies folder not available"])

    def test_a_failed_scan_keeps_its_own_message(self):
        self.start(movies_path=str(self.card / "Films"))
        with mock.patch.object(library_index, "full_scan", side_effect=OSError("invented")):
            result = self.scan()
        self.assertEqual(result, {"ok": False, "error": "Couldn't scan the library. The saved library is unchanged."})

    def test_a_rescan_answers_as_it_always_has(self):
        self.start(movies_path=str(self.card / "Films"))
        self.scan()
        self.assertEqual(self.scan(), {"ok": True, "message": "No changes"})


if __name__ == "__main__":
    unittest.main()
