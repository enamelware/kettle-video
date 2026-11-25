# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The saved library (the saved library work): saving, loading, IDs, and the scan endpoint.

Invented titles in temporary folders only.
Run from the repo root:  python3 -m unittest discover -s tests -t . -v
"""

import contextlib
import http.client
import io
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from backend import library_index
from backend.server import make_handler
from backend.settings import load_settings
from tests.test_parsed_library import MOVIE_FILES, TV_FILES, _strings

UI_DIR = Path(__file__).resolve().parent.parent / "ui"


def make_folders(root: Path):
    movies, tv = root / "Movies", root / "TV Shows"
    for base, files in ((movies, MOVIE_FILES), (tv, TV_FILES)):
        for rel in files:
            path = base / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x")
    return {"movies": str(movies), "tv": str(tv)}


def invented_index(entries: int) -> dict:
    """An index with `entries` films, for timing."""
    items, files = [], []
    for n in range(entries):
        rel = f"Invented Film {n} (2001)/Invented.Film.{n}.2001.mkv"
        items.append({"id": library_index.item_id("movies", rel), "key": rel, "title": f"Invented Film {n}",
                      "year": 2001, "parts": [{"label": None, "path": rel}], "flags": []})
        files.append({"path": rel, "size": 123456789, "mtime": 1700000000.0})
    entry = {"root": "/invented/Movies", "last_scanned_at": library_index.now_iso(), "scan_seconds": 1.0,
             "counts": {"items": entries, "files": entries, "skipped": 0}, "items": items,
             "skipped": [], "files": files}
    return {"schema_version": library_index.SCHEMA_VERSION, "generated_at": library_index.now_iso(),
            "sources": {"movies": entry}}


class IndexFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.roots = make_folders(self.root)
        self.path = self.root / "data" / "library.json"
        self.lines = []
        with contextlib.redirect_stdout(io.StringIO()):
            self.index = library_index.full_scan(self.roots, None, lambda done, total: None)

    def tearDown(self):
        self.tmp.cleanup()

    def test_save_then_load_gives_back_the_same_library(self):
        library_index.save(self.path, self.index)
        self.assertEqual(library_index.load(self.path, self.lines.append), self.index)
        self.assertEqual(self.lines, [])
        entry = self.index["sources"]["movies"]
        self.assertEqual(entry["root"], self.roots["movies"])
        self.assertEqual(entry["counts"], {"items": 2, "files": 3, "skipped": 0})
        self.assertEqual(sorted(f["path"] for f in entry["files"]), sorted(MOVIE_FILES))
        self.assertTrue(all(f["size"] == 1 and f["mtime"] for f in entry["files"]))

    def test_a_failed_save_leaves_the_old_file_intact(self):
        library_index.save(self.path, self.index)
        before = self.path.read_bytes()
        with mock.patch.object(library_index.os, "replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                library_index.save(self.path, invented_index(3))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual([p.name for p in self.path.parent.iterdir()], ["library.json"])

    def test_a_damaged_file_is_ignored_with_one_line(self):
        self.path.parent.mkdir()
        for text in ('{"schema_version": 1, "sources": ', '{"schema_version": 1, "sources": []}', "\xff"):
            with self.subTest(text=text):
                self.lines.clear()
                self.path.write_text(text, encoding="latin-1")
                self.assertIsNone(library_index.load(self.path, self.lines.append))
                self.assertEqual(len(self.lines), 1)

    def test_a_file_from_another_format_version_is_ignored(self):
        self.index["schema_version"] = library_index.SCHEMA_VERSION + 1
        library_index.save(self.path, self.index)
        self.assertIsNone(library_index.load(self.path, self.lines.append))
        self.assertEqual(self.lines, ["saved library ignored: it was saved in a different format"])

    def test_no_file_yet_is_one_line(self):
        self.assertIsNone(library_index.load(self.path, self.lines.append))
        self.assertEqual(self.lines, ["saved library: none yet"])

    def test_a_changed_folder_path_hides_that_sections_old_items(self):
        moved = dict(self.roots, tv=str(self.root / "Other TV"))
        answer = library_index.render(self.index, moved)
        self.assertFalse(answer["tv"]["has_library"])
        self.assertEqual(answer["tv"]["items"], [])
        self.assertTrue(answer["movies"]["has_library"])
        self.assertEqual(len(answer["movies"]["items"]), 2)

    def test_ids_are_stable_and_differ_between_sources(self):
        self.assertEqual(library_index.item_id("movies", "A/b.mkv"), library_index.item_id("movies", "A/b.mkv"))
        self.assertNotEqual(library_index.item_id("movies", "A/b.mkv"), library_index.item_id("tv", "A/b.mkv"))
        self.assertRegex(library_index.item_id("tv", "x"), r"^[0-9a-f]{16}$")
        with contextlib.redirect_stdout(io.StringIO()):
            again = library_index.full_scan(self.roots, None, lambda done, total: None)
        ids = lambda index: [i["id"] for s in ("movies", "tv") for i in index["sources"][s]["items"]]
        self.assertEqual(ids(again), ids(self.index))
        movie = self.index["sources"]["movies"]["items"][0]
        self.assertEqual(movie["key"], "Example Film (2001)")
        self.assertEqual(movie["id"], library_index.item_id("movies", "Example Film (2001)"))
        episode = self.index["sources"]["tv"]["items"][1]["seasons"][0]["episodes"][0]
        self.assertEqual(episode["id"], library_index.item_id("tv", episode["path"]))
        answer = library_index.render(self.index, self.roots)
        self.assertEqual(answer["movies"]["items"][0]["id"], movie["id"])
        self.assertEqual(answer["tv"]["items"][1]["seasons"][0]["episodes"][0]["id"], episode["id"])

    def test_movies_sharing_a_folder_and_loose_shows_get_their_own_ids(self):
        for rel in ("Collection/Film One (2001).mkv", "Collection/Film Two (2003).mkv", "Loose Film (1999).mkv"):
            (Path(self.roots["movies"]) / rel).parent.mkdir(exist_ok=True)
            (Path(self.roots["movies"]) / rel).write_bytes(b"")
        for rel in ("Loose.Show.S01E01.mkv", "Other.Loose.S01E01.mkv"):
            (Path(self.roots["tv"]) / rel).write_bytes(b"")
        with contextlib.redirect_stdout(io.StringIO()):
            index = library_index.full_scan(self.roots, None, lambda done, total: None)
        keys = {i["title"]: i["key"] for i in index["sources"]["movies"]["items"]}
        self.assertEqual(keys["Film One"], "Collection/Film One (2001).mkv")
        self.assertEqual(keys["Loose Film"], "Loose Film (1999).mkv")
        shows = {i["title"]: i["key"] for i in index["sources"]["tv"]["items"]}
        self.assertEqual((shows["Loose Show"], shows["Other Loose"]), ("Loose Show", "Other Loose"))
        all_ids = [i["id"] for s in ("movies", "tv") for i in index["sources"][s]["items"]]
        self.assertEqual(len(all_ids), len(set(all_ids)))

    def test_a_missing_folder_keeps_its_previous_entry(self):
        shutil.rmtree(self.roots["movies"])
        with contextlib.redirect_stdout(io.StringIO()):
            index = library_index.full_scan(self.roots, self.index, lambda done, total: None)
        self.assertEqual(index["sources"]["movies"], self.index["sources"]["movies"])
        self.assertNotEqual(index["sources"]["tv"]["last_scanned_at"], None)

    def test_progress_reaches_the_total(self):
        seen = []
        with contextlib.redirect_stdout(io.StringIO()):
            library_index.full_scan(self.roots, None, lambda done, total: seen.append((done, total)))
        total = len(MOVIE_FILES) + len(TV_FILES)
        self.assertEqual(seen[0], (0, total))
        self.assertEqual(seen[-1], (total, total))

    def test_timing_save_and_load_5000_items(self):
        index = invented_index(5000)
        start = time.perf_counter()
        library_index.save(self.path, index)
        saved = time.perf_counter() - start
        start = time.perf_counter()
        loaded = library_index.load(self.path, self.lines.append)
        took = time.perf_counter() - start
        start = time.perf_counter()
        library_index.render(loaded, {"movies": "/invented/Movies", "tv": "/invented/TV"})
        rendered = time.perf_counter() - start
        self.assertEqual(loaded, index)
        print(f"\n  saved library timing, 5,000 films ({self.path.stat().st_size // 1024} KB): "
              f"save {saved:.2f} s, load {took:.2f} s, build the page's answer {rendered:.2f} s")


class SettingsTest(unittest.TestCase):
    def test_data_dir_defaults_to_data_in_the_app_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "settings.json").write_text(json.dumps({"movies_path": "/m", "tv_path": "/t"}))
            self.assertEqual(load_settings(root)["data_dir"], str(root / "data"))
            (root / "settings.json").write_text(json.dumps({"movies_path": "/m", "tv_path": "/t",
                                                            "data_dir": "/elsewhere/kettle"}))
            self.assertEqual(load_settings(root)["data_dir"], "/elsewhere/kettle")


class ScanServerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.roots = make_folders(self.root)
        self.data = self.root / "data"
        self.out = io.StringIO()
        self.start_server()

    def start_server(self):
        settings = {"movies_path": self.roots["movies"], "tv_path": self.roots["tv"], "mpv_command": "mpv",
                    "mpv_args": [], "resume": True, "keep_awake": False, "data_dir": str(self.data)}
        logs = self.root / "logs"
        logs.mkdir(exist_ok=True)
        httpd_ref = {}
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        self.port = self.httpd.server_address[1]
        with contextlib.redirect_stdout(self.out):
            self.httpd.RequestHandlerClass = make_handler(UI_DIR, logs, settings, httpd_ref, self.port)
        self.httpd.RequestHandlerClass.log_message = lambda *args: None
        httpd_ref["server"] = self.httpd
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def stop_server(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def tearDown(self):
        self.stop_server()
        self.tmp.cleanup()

    def _request(self, method, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        body = "{}" if method == "POST" else None
        conn.request(method, path, body=body, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        data = json.loads(resp.read().decode("utf-8"))
        conn.close()
        return resp.status, data

    def _wait_idle(self):
        end = time.time() + 30
        while time.time() < end:
            status = self._request("GET", "/api/library/scan/status")[1]
            if status["state"] == "idle":
                return status
            time.sleep(0.05)
        self.fail("scan did not finish")

    def _scan(self):
        with contextlib.redirect_stdout(self.out):
            self._request("POST", "/api/library/scan")
            return self._wait_idle()

    def test_no_scan_at_start_and_the_first_launch_flags(self):
        with mock.patch.object(library_index, "full_scan") as full_scan:
            answer = self._request("GET", "/api/library/parsed")[1]
        full_scan.assert_not_called()
        for source in ("movies", "tv"):
            self.assertEqual((answer[source]["has_library"], answer[source]["available"]), (False, True))
        self.assertFalse((self.data / "library.json").exists())

    def test_a_scan_is_saved_and_loaded_at_the_next_launch(self):
        status = self._scan()
        self.assertTrue(status["last_result"]["ok"])
        self.assertEqual(status["files_done"], status["files_total"])
        first = self._request("GET", "/api/library/parsed")[1]
        self.assertTrue(first["movies"]["has_library"] and first["tv"]["has_library"])
        self.assertTrue(first["movies"]["scanned_at"])
        self.stop_server()
        with mock.patch.object(library_index, "full_scan") as full_scan:
            self.start_server()
            again = self._request("GET", "/api/library/parsed")[1]
        full_scan.assert_not_called()
        self.assertEqual(again, first)

    def test_a_second_scan_request_during_a_scan_does_not_start_another(self):
        release = threading.Event()
        real = library_index.full_scan

        def slow(*args):
            release.wait(10)
            return real(*args)

        with mock.patch.object(library_index, "full_scan", side_effect=slow) as full_scan:
            with contextlib.redirect_stdout(self.out):
                first = self._request("POST", "/api/library/scan")[1]
                second = self._request("POST", "/api/library/scan")[1]
                release.set()
                self._wait_idle()
        self.assertTrue(first["started"])
        self.assertFalse(second["started"])
        self.assertEqual(second["state"], "scanning")
        self.assertEqual(full_scan.call_count, 1)

    def test_a_scan_error_keeps_the_saved_library(self):
        self._scan()
        saved = (self.data / "library.json").read_bytes()
        before = self._request("GET", "/api/library/parsed")[1]
        with mock.patch.object(library_index, "full_scan", side_effect=RuntimeError(f"boom {self.roots['tv']}")):
            status = self._scan()
        self.assertFalse(status["last_result"]["ok"])
        self.assertEqual(status["last_result"]["error"], "Couldn't scan the library. The saved library is unchanged.")
        self.assertEqual((self.data / "library.json").read_bytes(), saved)
        self.assertEqual(self._request("GET", "/api/library/parsed")[1], before)

    def test_a_file_with_an_unreadable_name_does_not_break_the_rescan(self):
        # The unreadable name fix: a name saved in another text encoding is skipped.
        try:
            with open(os.path.join(os.fsencode(self.roots["movies"]), b"Caf\xe9 Invented (1999).mkv"), "wb") as f:
                f.write(b"x")
        except OSError:
            self.skipTest("this file system refuses names that aren't valid UTF-8")
        status = self._scan()
        self.assertTrue(status["last_result"]["ok"])
        answer = self._request("GET", "/api/library/parsed")[1]
        self.assertTrue(answer["movies"]["items"])
        self.assertIn({"path": "Caf� Invented (1999).mkv", "reason": "name can't be read"},
                      answer["skipped"]["movies"])
        self.stop_server()
        self.start_server()
        self.assertEqual(self._request("GET", "/api/library/parsed")[1]["skipped"], answer["skipped"])

    def test_a_missing_folder_keeps_its_items_and_says_not_available(self):
        self._scan()
        shutil.rmtree(self.roots["movies"])
        answer = self._request("GET", "/api/library/parsed")[1]
        self.assertEqual((answer["movies"]["has_library"], answer["movies"]["available"]), (True, False))
        self.assertEqual(len(answer["movies"]["items"]), 2)
        self.assertTrue(answer["tv"]["available"])
        self._scan()  # a rescan with the card out removes nothing
        self.assertEqual(len(self._request("GET", "/api/library/parsed")[1]["movies"]["items"]), 2)
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("POST", "/api/play", body=json.dumps({"source": "movies", "path": MOVIE_FILES[2]}),
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        self.assertEqual(json.loads(resp.read()), {"error": "Folder not available"})
        conn.close()

    def test_no_answer_or_log_line_holds_a_full_path(self):
        (self.data).mkdir()
        (self.data / "library.json").write_text("not json")
        self.stop_server()
        self.start_server()
        self._scan()
        with mock.patch.object(library_index, "full_scan", side_effect=OSError(2, "gone", self.roots["tv"])):
            self._scan()
        answers = [self._request("GET", "/api/library/parsed")[1],
                   self._request("GET", "/api/library/scan/status")[1]]
        text = json.dumps(answers) + self.out.getvalue()
        self.assertIn("saved library ignored", self.out.getvalue())
        self.assertIn("library scan failed (FileNotFoundError)", self.out.getvalue())
        self.assertNotIn(self.tmp.name, text)
        for value in _strings(answers):
            self.assertFalse(value.startswith("/"), value)


if __name__ == "__main__":
    unittest.main()
