# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The parsed library answer, GET /api/library/parsed (the parsed library view), as built
from the saved library after a scan (the saved library work).

Invented titles in temporary folders only.
Run from the repo root:  python3 -m unittest discover -s tests -t . -v
"""

import contextlib
import http.client
import io
import json
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from backend import library_index, parsed_library
from backend.server import make_handler

UI_DIR = Path(__file__).resolve().parent.parent / "ui"

MOVIE_FILES = [
    "Example Film (2001)/Example Film (2001) - Part 1.mkv",
    "Example Film (2001)/Example Film (2001) - Part 2.mkv",
    "Other Movie (1999)/Other.Movie.1999.1080p.mkv",
]
TV_FILES = [
    "Kiri Anime/Kiri Anime - 01.mkv",
    "Kiri Anime/Kiri Anime - 02.mkv",
    "Kiri Anime/Kiri Anime - 73.mkv",
    "Test Show/Season 1/Test.Show.S01E01.Pilot.mkv",
    "Test Show/Season 1/Test.Show.S01E02.mkv",
    "Test Show/Season 2/Test.Show.S02E05.mkv",
    "Test Show/Specials/Test.Show.Behind.the.Scenes.mkv",
]


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


class ParsedLibraryServerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.movies = root / "Movies"
        self.tv = root / "TV Shows"
        for base, files in ((self.movies, MOVIE_FILES), (self.tv, TV_FILES)):
            for rel in files:
                path = base / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"")
        logs = root / "logs"
        logs.mkdir()
        settings = {"movies_path": str(self.movies), "tv_path": str(self.tv), "mpv_command": "mpv"}
        httpd_ref = {}
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        self.port = self.httpd.server_address[1]
        self.httpd.RequestHandlerClass = make_handler(UI_DIR, logs, settings, httpd_ref, self.port)
        httpd_ref["server"] = self.httpd
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def _get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read().decode("utf-8")
        conn.close()
        self.assertEqual(resp.status, 200)
        return body

    def _scan(self):
        """Ask for a scan and wait for it to finish; returns its result."""
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        conn.request("POST", "/api/library/scan", body="{}", headers={"Content-Type": "application/json"})
        conn.getresponse().read()
        conn.close()
        end = time.time() + 30
        while time.time() < end:
            status = json.loads(self._get("/api/library/scan/status"))
            if status["state"] == "idle":
                return status["last_result"]
            time.sleep(0.05)
        self.fail("scan did not finish")

    def _parsed(self, path="/api/library/parsed", scan=True):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            if scan:
                self._scan()
            return json.loads(self._get(path))

    def test_movies_have_titles_part_counts_and_paths(self):
        answer = self._parsed()
        self.assertTrue(answer["ok"])
        movies = answer["movies"]["items"]
        self.assertEqual([m["display_title"] for m in movies], ["Example Film (2001)", "Other Movie (1999)"])
        self.assertEqual(movies[0]["subtitle"], "2 parts")
        self.assertEqual([p["path"] for p in movies[0]["parts"]], MOVIE_FILES[:2])
        self.assertEqual(movies[1]["subtitle"], "")
        self.assertEqual(movies[1]["parts"][0]["path"], MOVIE_FILES[2])

    def test_shows_have_subtitles_seasons_and_episode_labels(self):
        shows = {s["display_title"]: s for s in self._parsed()["tv"]["items"]}
        self.assertEqual(set(shows), {"Kiri Anime", "Test Show"})

        flat = shows["Kiri Anime"]
        self.assertEqual(flat["subtitle"], "flat, 3 episodes")
        self.assertEqual(flat["path"], "Kiri Anime")
        self.assertEqual([s["label"] for s in flat["seasons"]], ["Episodes"])
        self.assertEqual([e["label"] for e in flat["seasons"][0]["episodes"]], ["1", "2", "73"])
        self.assertEqual(flat["seasons"][0]["episodes"][2]["path"], TV_FILES[2])

        show = shows["Test Show"]
        self.assertEqual(show["subtitle"], "2 seasons, 3 episodes, 1 special")
        self.assertEqual([s["label"] for s in show["seasons"]], ["Season 1", "Season 2", "Specials"])
        first = show["seasons"][0]["episodes"][0]
        self.assertEqual((first["label"], first["title"], first["path"]), ("S01E01", "Pilot", TV_FILES[3]))
        self.assertEqual(show["seasons"][1]["episodes"][0]["label"], "S02E05")
        special = show["seasons"][2]["episodes"][0]
        self.assertEqual(special["label"], "Special")
        self.assertIn("unnumbered", special["notes"])

    def test_scan_counts_and_times_go_to_the_log(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            self._scan()
        self.assertRegex(
            out.getvalue(),
            r"library scan saved: 2 movies \(3 files\) in \d+\.\d\d s, 0 skipped; "
            r"2 shows \(7 files\) in \d+\.\d\d s, 0 skipped",
        )

    def test_failing_render_gives_the_sentence_and_plain_list_still_works(self):
        with mock.patch.object(library_index, "render", side_effect=RuntimeError(f"boom {self.tv}")):
            answer = self._parsed()
        self.assertEqual(answer, {"ok": False, "error": parsed_library.ERROR_SENTENCE})
        with contextlib.redirect_stderr(io.StringIO()):
            plain = json.loads(self._get("/api/library"))
        self.assertEqual(plain["movies"]["status"], "ok")
        self.assertEqual(plain["tv"]["status"], "ok")
        self.assertEqual(sum(len(g["files"]) for g in plain["tv"]["groups"]), len(TV_FILES))

    def test_answer_never_holds_a_full_path(self):
        for scan in (False, True):
            text = json.dumps(self._parsed(scan=scan))
            self.assertNotIn(self.tmp.name, text)
            for value in _strings(json.loads(text)):
                self.assertFalse(value.startswith("/"), value)


if __name__ == "__main__":
    unittest.main()
