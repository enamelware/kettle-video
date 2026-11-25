# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Continue watching through the server (the Continue watching work), with a fake mpv that
writes what the real quit script writes. Invented titles in a temporary
folder; nothing real is played.

Checks: a stop shows up in /api/continue with its picture; a tile resumes
by its ID; X removes it; a missing file is flagged, and Remove missing
items takes its tile and picture too; the answer never holds a file
location; /api/library/parsed keeps exactly the same fields; the logs name
no picture; nothing is recorded with resume off or for a file outside the
saved library; the mpv command gets the quit script only then.

Run from the repo root:  python3 -m unittest tests.test_continue_endpoint -v
"""

import contextlib
import http.client
import io
import json
import os
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from unittest import mock

from backend import continue_watching as cw
from backend import mpv, server
from backend.server import make_handler
from tests.test_parsed_library import MOVIE_FILES, TV_FILES

UI_DIR = Path(__file__).resolve().parent.parent / "ui"

# Writes what quit_capture.lua writes, as told by next-stop.json beside it,
# and the small picture when it is run to shrink one. Every call is noted.
FAKE_MPV = """#!/usr/bin/env python3
import json, pathlib, sys
here = pathlib.Path(__file__).parent
args = sys.argv[1:]
with open(here / "calls.jsonl", "a") as f:
    f.write(json.dumps(args) + "\\n")
for a in args:
    if a.startswith("--vo-image-outdir="):
        pathlib.Path(a.split("=", 1)[1], "00000001.jpg").write_bytes(b"\\xff\\xd8 small picture")
        sys.exit(0)
print("[cplayer] Playing")
# What the real mpv prints when the quit script saves the frame.
print("   cplayer: Screenshot: '/tmp/kettle-quit-x/frame.jpg'")
plan = json.loads((here / "next-stop.json").read_text())
for a in args:
    if a.startswith("--script-opts-append=kettle_quit-out_dir="):
        out = pathlib.Path(a.split("kettle_quit-out_dir=", 1)[1])
        if plan.get("frame"):
            (out / "frame.jpg").write_bytes(b"\\xff\\xd8 full frame")
        (out / "record.json").write_text(json.dumps(plan["record"]))
"""

PARSED_FIELDS = {
    "answer": {"last_scan", "missing_count", "movies", "ok", "skipped", "timings", "tv"},
    "source": {"available", "folder_set", "has_library", "items", "scanned_at", "status"},
    "movie": {"display_title", "id", "letter", "missing", "missing_note", "parts", "sort_index", "subtitle"},
    "part": {"label", "missing", "path"},
    "show": {"display_title", "id", "missing", "missing_note", "path", "seasons", "subtitle"},
    "season": {"episodes", "label"},
    "episode": {"flags", "id", "label", "missing", "missing_note", "notes", "path", "title"},
}


class ContinueEndpointTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.movies = self.root / "Movies"
        self.tv = self.root / "TV Shows"
        for base, files in ((self.movies, MOVIE_FILES), (self.tv, TV_FILES)):
            for rel in files:
                (base / rel).parent.mkdir(parents=True, exist_ok=True)
                (base / rel).write_bytes(b"")
        self.logs = self.root / "logs"
        self.logs.mkdir()
        self.data = self.root / "data"
        self.fake = self.root / "fake" / "mpv"
        self.fake.parent.mkdir()
        self.fake.write_text(FAKE_MPV)
        self.fake.chmod(0o755)
        self.tmp_before = set(mpv.SHARED_TMP.glob("kettle-quit-*"))
        # The server's own log lines, kept to check them.
        self.logged = []
        patch = mock.patch.object(server, "_log", self.logged.append)
        patch.start()
        self.addCleanup(patch.stop)
        self.httpd = None

    def tearDown(self):
        self.stop_server()
        self.tmp.cleanup()

    def start(self, resume=True):
        settings = {
            "movies_path": str(self.movies), "tv_path": str(self.tv), "mpv_command": str(self.fake),
            "mpv_args": [], "resume": resume, "keep_awake": False, "data_dir": str(self.data),
        }
        httpd_ref = {}
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        self.port = self.httpd.server_address[1]
        with contextlib.redirect_stdout(io.StringIO()):
            base = make_handler(UI_DIR, self.logs, settings, httpd_ref, self.port)

        class Quiet(base):
            def log_message(self, format, *args):
                pass

        self.httpd.RequestHandlerClass = Quiet
        httpd_ref["server"] = self.httpd
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def stop_server(self):
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None

    def request(self, method, path, body=None, raw=False):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Content-Type": "application/json"} if method == "POST" else {}
        conn.request(method, path, body=json.dumps(body if body is not None else {}) if method == "POST" else None,
                     headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, (data if raw else json.loads(data))

    def scan(self):
        self.request("POST", "/api/library/scan")
        end = time.time() + 60
        while time.time() < end:
            _, status = self.request("GET", "/api/library/scan/status")
            if status["state"] == "idle":
                self.assertTrue(status["last_result"]["ok"], status)
                return
            time.sleep(0.1)
        self.fail("scan didn't finish")

    def parsed(self):
        return self.request("GET", "/api/library/parsed")[1]

    def movie_id(self, title):
        return next(m["id"] for m in self.parsed()["movies"]["items"] if m["display_title"] == title)

    def plan(self, position, duration=7200.0, finished=False, frame=True):
        record = {"position": position, "duration": duration, "finished": finished, "frame_saved": frame}
        (self.fake.parent / "next-stop.json").write_text(json.dumps({"record": record, "frame": frame}))

    def play(self, body):
        code, answer = self.request("POST", "/api/play", body)
        self.assertEqual((code, answer), (200, {"started": True, "keep_awake": False}))
        end = time.time() + 10
        while time.time() < end:
            if self.request("GET", "/api/status")[1]["state"] == "idle":
                return
            time.sleep(0.05)
        self.fail("still playing")

    def calls(self):
        path = self.fake.parent / "calls.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def playback_calls(self):
        return [c for c in self.calls() if not any(a.startswith("--vo-image-outdir=") for a in c)]

    def carousel(self):
        code, answer = self.request("GET", "/api/continue")
        self.assertEqual(code, 200)
        return answer["items"]

    def wait_small_picture(self, link):
        end = time.time() + 10
        while time.time() < end:
            code, body = self.request("GET", link, raw=True)
            if code == 200 and body == b"\xff\xd8 small picture":
                return body
            time.sleep(0.05)
        self.fail("the small picture never replaced the frame")

    def assert_tmp_tidied(self):
        """mpv's folders in /tmp made during this test are gone afterwards."""
        def left():
            return set(mpv.SHARED_TMP.glob("kettle-quit-*")) - self.tmp_before
        end = time.time() + 10
        while left() and time.time() < end:
            time.sleep(0.05)
        self.assertEqual(left(), set(), "mpv's folder in /tmp is tidied up")

    def test_stop_resume_remove(self):
        self.start()
        self.scan()
        film = self.movie_id("Other Movie (1999)")
        self.plan(1800)
        self.play({"source": "movies", "id": film})
        items = self.carousel()
        self.assertEqual([i["name"] for i in items], ["Other Movie"])
        self.assertEqual(items[0]["caption"], "Other Movie · Resume at 30:00 · 90 min left")
        self.assertEqual((items[0]["id"], items[0]["kind"], items[0]["missing"]), (film, "movie", False))
        # The picture: by its ID, made small in the background.
        self.wait_small_picture(items[0]["picture"])
        pictures = list((self.data / cw.PICTURES_DIR).iterdir())
        self.assertEqual([p.name for p in pictures], [f"{film}.jpg"])
        self.assert_tmp_tidied()

        # A on the tile resumes the same file, by the tile's ID.
        self.plan(2400)
        self.play({"continue": film})
        self.assertTrue(self.playback_calls()[-1][-1].endswith(MOVIE_FILES[2]))
        self.assertEqual(self.carousel()[0]["position"], 2400)

        # X removes it at once; the next stop brings it back.
        self.assertEqual(self.request("POST", "/api/continue/remove", {"id": film}), (200, {"ok": True}))
        self.assertEqual(self.carousel(), [])
        self.assertEqual(self.request("GET", items[0]["picture"], raw=True)[0], 404)
        self.assertEqual(list((self.data / cw.PICTURES_DIR).iterdir()), [])
        self.assertEqual(self.request("POST", "/api/continue/remove", {"id": film}), (200, {"ok": False}))
        self.assertEqual(self.request("POST", "/api/play", {"continue": film})[0], 400)
        self.plan(2500)
        self.play({"source": "movies", "id": film})
        self.assertEqual([i["name"] for i in self.carousel()], ["Other Movie"])

    def test_episode_and_part_tiles(self):
        self.start()
        self.scan()
        self.plan(600)
        self.play({"source": "tv", "path": TV_FILES[5]})  # Test Show S02E05
        self.plan(700)
        self.play({"source": "movies", "path": MOVIE_FILES[1]})  # Example Film, part 2
        self.assertEqual([i["name"] for i in self.carousel()], ["Example Film · Part 2", "Test Show · S2 E5"])
        self.assertEqual([i["kind"] for i in self.carousel()], ["movie", "episode"])

    def test_missing_then_removed_from_the_library(self):
        self.start()
        self.scan()
        self.plan(600)
        self.play({"source": "movies", "path": MOVIE_FILES[2]})
        (self.movies / MOVIE_FILES[2]).unlink()
        self.scan()
        items = self.carousel()
        self.assertTrue(items[0]["missing"])
        self.assertEqual(items[0]["caption"], "Other Movie · Missing · stopped at 10:00")
        self.assertEqual(self.request("POST", "/api/library/remove-missing")[1]["ok"], True)
        self.assertEqual(self.carousel(), [])
        self.assertEqual(list((self.data / cw.PICTURES_DIR).iterdir()), [])

    def test_answer_never_holds_a_file_location(self):
        self.start()
        self.scan()
        self.plan(600)
        self.play({"source": "tv", "path": TV_FILES[3]})
        self.plan(600)
        self.play({"source": "movies", "path": MOVIE_FILES[0]})
        text = json.dumps(self.carousel())
        self.assertNotIn(str(self.root), text)
        for rel in MOVIE_FILES + TV_FILES:
            self.assertNotIn(rel, text)
            self.assertNotIn(os.path.basename(rel), text)

    def test_parsed_library_keeps_exactly_the_same_fields(self):
        self.start()
        self.scan()
        self.plan(600)
        self.play({"source": "movies", "path": MOVIE_FILES[2]})
        answer = self.parsed()
        self.assertEqual(set(answer), PARSED_FIELDS["answer"])
        for source, kind in (("movies", "movie"), ("tv", "show")):
            self.assertEqual(set(answer[source]), PARSED_FIELDS["source"])
            for item in answer[source]["items"]:
                self.assertEqual(set(item), PARSED_FIELDS[kind])
        for part in (p for m in answer["movies"]["items"] for p in m["parts"]):
            self.assertEqual(set(part), PARSED_FIELDS["part"])
        for season in (s for show in answer["tv"]["items"] for s in show["seasons"]):
            self.assertEqual(set(season), PARSED_FIELDS["season"])
            for episode in season["episodes"]:
                self.assertEqual(set(episode), PARSED_FIELDS["episode"])

    def test_logs_name_no_picture(self):
        self.start()
        self.scan()
        film = self.movie_id("Other Movie (1999)")
        self.plan(600)
        self.play({"source": "movies", "id": film})
        self.wait_small_picture(self.carousel()[0]["picture"])
        self.request("POST", "/api/continue/remove", {"id": film})
        logs = "\n".join(self.logged) + "".join(p.read_text() for p in self.logs.glob("*.log"))
        self.assertIn("continue watching: stop saved", logs)
        for word in (film, ".jpg", cw.PICTURES_DIR, "Other Movie", "kettle-quit"):
            self.assertNotIn(word, logs)

    def test_nothing_recorded_with_resume_off(self):
        self.start(resume=False)
        self.scan()
        self.plan(600)
        self.play({"source": "movies", "path": MOVIE_FILES[2]})
        self.assertEqual(self.carousel(), [])
        self.assertFalse(any(str(mpv.QUIT_CAPTURE_SCRIPT) in a for a in self.playback_calls()[-1]))
        self.assertFalse((self.data / cw.FILE_NAME).exists())

    def test_nothing_recorded_outside_the_saved_library(self):
        self.start()  # never scanned: no saved library yet
        self.plan(600)
        self.play({"source": "movies", "path": MOVIE_FILES[2]})
        self.assertEqual(self.carousel(), [])
        self.assertFalse(any(str(mpv.QUIT_CAPTURE_SCRIPT) in a for a in self.playback_calls()[-1]))

    def test_the_quit_script_and_its_folder_for_library_files(self):
        self.start()
        self.scan()
        self.plan(600)
        self.play({"source": "movies", "path": MOVIE_FILES[2]})
        args = self.playback_calls()[-1]
        self.assertIn(f"--script={mpv.QUIT_CAPTURE_SCRIPT}", args)
        opts = [a for a in args if a.startswith("--script-opts-append=kettle_quit-out_dir=")]
        self.assertEqual(len(opts), 1)
        self.assertTrue(opts[0].split("=", 2)[2].startswith(str(mpv.SHARED_TMP / "kettle-quit-")))

    def test_saved_list_survives_a_restart_and_launch_cleans_pictures(self):
        self.start()
        self.scan()
        film = self.movie_id("Other Movie (1999)")
        self.plan(600)
        self.play({"source": "movies", "id": film})
        self.wait_small_picture(self.carousel()[0]["picture"])
        stray = self.data / cw.PICTURES_DIR / "0123456789abcdef.jpg"
        stray.write_bytes(b"old")
        self.stop_server()
        self.start()
        self.assertEqual([i["name"] for i in self.carousel()], ["Other Movie"])
        self.assertFalse(stray.exists())
        self.assertTrue((self.data / cw.PICTURES_DIR / f"{film}.jpg").exists())

    def test_picture_address_only_serves_carousel_pictures(self):
        self.start()
        for path in ("/api/continue/picture/0123456789abcdef", "/api/continue/picture/..%2F..%2Fsettings.json",
                     "/api/continue/picture/"):
            self.assertEqual(self.request("GET", path, raw=True)[0], 404, path)


if __name__ == "__main__":
    unittest.main()
