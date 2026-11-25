# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The play request, end to end with a fake mpv (the stuck Playing fix): however mpv
fails to start, the playing state goes back to idle and the error and hint
are reported, so the page never stays stuck on "Playing...". Also: a second
play while one runs is refused, mpv missing gives the install message, and
a path outside the media folders is refused.

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

from backend import mpv
from backend.server import make_handler

UI_DIR = Path(__file__).resolve().parent.parent / "ui"


class PlayEndpointTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.movies = self.root / "Movies"
        self.movies.mkdir()
        (self.movies / "Film.mkv").write_bytes(b"")
        self.logs = self.root / "logs"
        self.logs.mkdir()
        self.httpd = None

    def tearDown(self):
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()
        self.tmp.cleanup()

    def start(self, mpv_command, keep_awake=False):
        settings = {
            "movies_path": str(self.movies),
            "tv_path": str(self.movies),
            "mpv_command": mpv_command,
            "mpv_args": [],
            "resume": True,
            "keep_awake": keep_awake,
            "data_dir": str(self.root / "data"),
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

    def fake_mpv(self, script, executable=True):
        path = self.root / "fake-mpv"
        path.write_text(script)
        path.chmod(0o755 if executable else 0o644)
        return str(path)

    def request(self, method, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Content-Type": "application/json"} if body is not None else {}
        conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
        resp = conn.getresponse()
        data = json.loads(resp.read())
        conn.close()
        return resp.status, data

    def play(self, path="Film.mkv"):
        return self.request("POST", "/api/play", {"source": "movies", "path": path})

    def wait_idle(self, timeout=10):
        end = time.time() + timeout
        while time.time() < end:
            _, status = self.request("GET", "/api/status")
            if status["state"] == "idle":
                return status
            time.sleep(0.05)
        self.fail("still playing after the fake mpv should have ended")

    def assert_failed_back_to_idle(self):
        status = self.wait_idle()
        result = status["last_result"]
        self.assertFalse(result["ok"])
        self.assertTrue(result["error"])
        self.assertTrue(result["hint"])
        return result

    def runnable_at_check(self, command):
        """The mpv check passes, as if the program changed after it (since
        The settings mistakes work a bad mpv_command is caught by the check itself)."""
        found = {"available": True, "command": [command], "via": "configured"}
        return mock.patch.object(mpv, "detect", return_value=found)

    def test_mpv_not_allowed_to_run_goes_back_to_idle(self):
        command = self.fake_mpv("#!/bin/sh\nexit 0\n", executable=False)
        self.start(command)
        with self.runnable_at_check(command), contextlib.redirect_stderr(io.StringIO()):
            code, answer = self.play()
            self.assertEqual((code, answer), (200, {"started": True, "keep_awake": False}))
            result = self.assert_failed_back_to_idle()
        self.assertEqual(result["error"], mpv.START_FAILED)
        self.assertNotIn(str(self.root), result["error"])

    def test_mpv_command_is_a_folder_goes_back_to_idle(self):
        self.start(str(self.root))
        with self.runnable_at_check(str(self.root)), contextlib.redirect_stderr(io.StringIO()):
            self.play()
            self.assert_failed_back_to_idle()

    def test_mpv_command_with_a_bad_character_goes_back_to_idle(self):
        self.start("mpv\x00x")
        with self.runnable_at_check("mpv\x00x"), contextlib.redirect_stderr(io.StringIO()):
            self.play()
            self.assert_failed_back_to_idle()

    def test_bad_mpv_command_is_refused_before_playing(self):
        # The settings mistakes work: caught by the check, with the plain sentence and hint.
        for command, words in ((self.fake_mpv("#!/bin/sh\nexit 0\n", executable=False), "can't be found"),
                               (str(self.root), "can't be found"),
                               ('mpv "--fs', "quote that isn't closed")):
            with self.subTest(command=command):
                self.start(command)
                code, answer = self.play()
                self.assertEqual(code, 503)
                self.assertIn("settings.json's 'mpv_command'", answer["error"])
                self.assertIn(words, answer["error"])
                self.assertEqual(answer["hint"], mpv.SETTING_HINT)
                _, status = self.request("GET", "/api/status")
                self.assertEqual(status["state"], "idle")
                self.httpd.shutdown()
                self.httpd.server_close()
                self.httpd = None

    def test_unexpected_failure_while_playing_goes_back_to_idle(self):
        self.start(self.fake_mpv("#!/bin/sh\nexit 0\n"))
        with mock.patch.object(mpv, "play", side_effect=RuntimeError("boom")), \
                contextlib.redirect_stderr(io.StringIO()):
            self.play()
            result = self.assert_failed_back_to_idle()
        self.assertEqual(result["hint"], mpv.START_FAILED_HINT)

    def test_play_works_again_after_a_failed_start(self):
        command = self.fake_mpv("#!/bin/sh\nexit 0\n", executable=False)
        self.start(command)
        with self.runnable_at_check(command), contextlib.redirect_stderr(io.StringIO()):
            self.play()
            self.wait_idle()
            code, answer = self.play()
            self.assertEqual((code, answer), (200, {"started": True, "keep_awake": False}))
            self.wait_idle()

    def test_normal_playback_reports_ok(self):
        self.start(self.fake_mpv("#!/bin/sh\nexit 0\n"))
        self.play()
        self.assertTrue(self.wait_idle()["last_result"]["ok"])

    def test_keep_awake_setting_reaches_the_player(self):
        # The keep-awake work: the server hands the keep_awake setting to mpv.play();
        # play() alone defaults to off, so a dropped setting would mean the
        # lock is never taken.
        for keep_awake in (True, False):
            with self.subTest(keep_awake=keep_awake):
                seen = []

                def fake_play(*args, **kwargs):
                    seen.append(kwargs.get("keep_awake", args[5] if len(args) > 5 else None))
                    return {"ok": True}

                self.start(self.fake_mpv("#!/bin/sh\nexit 0\n"), keep_awake=keep_awake)
                with mock.patch.object(mpv, "play", side_effect=fake_play):
                    self.play()
                    self.wait_idle()
                self.assertEqual(seen, [keep_awake])
                self.httpd.shutdown()
                self.httpd.server_close()
                self.httpd = None

    def test_play_answer_says_whether_to_keep_the_screen_on(self):
        # The screen wake lock fix: the page asks Firefox to keep the screen on only when
        # keep_awake is on, and learns it from the play answer.
        for keep_awake in (True, False):
            with self.subTest(keep_awake=keep_awake):
                self.start(self.fake_mpv("#!/bin/sh\nexit 0\n"), keep_awake=keep_awake)
                with mock.patch.object(mpv, "play", return_value={"ok": True}):
                    self.assertEqual(self.play(), (200, {"started": True, "keep_awake": keep_awake}))
                    self.wait_idle()
                self.httpd.shutdown()
                self.httpd.server_close()
                self.httpd = None

    def test_wake_lock_reports_go_to_the_log_in_fixed_words(self):
        # The screen wake lock fix: one launch-log line per change, so a device test shows
        # whether Firefox granted the lock.
        self.start(self.fake_mpv("#!/bin/sh\nexit 0\n"))
        for state in ("held", "lost", "refused", "unsupported", "released"):
            with self.subTest(state=state):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    answer = self.request("POST", "/api/wake-lock", {"state": state})
                self.assertEqual(answer, (200, {"ok": True}))
                self.assertEqual(out.getvalue(), f"screen wake lock: {state}\n")

    def test_anything_else_about_the_wake_lock_is_refused_and_not_logged(self):
        self.start(self.fake_mpv("#!/bin/sh\nexit 0\n"))
        for body in ({"state": "/home/someone/Films/Secret.mkv"}, {"state": "HELD"}, {"state": ["held"]},
                     {"state": None}, {}, ["held"], "held"):
            with self.subTest(body=body):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    code, _ = self.request("POST", "/api/wake-lock", body)
                self.assertEqual(code, 400)
                self.assertEqual(out.getvalue(), "")

    def test_second_play_while_playing_is_refused(self):
        self.start(self.fake_mpv("#!/bin/sh\nsleep 1\n"))
        self.assertEqual(self.play()[0], 200)
        code, answer = self.play()
        self.assertEqual(code, 409)
        self.assertEqual(answer["error"], "already playing")
        self.wait_idle()

    def test_mpv_missing_gives_the_install_message(self):
        self.start("auto")
        missing = {"available": False, "install_hint": mpv.INSTALL_HINT}
        with mock.patch.object(mpv, "detect", return_value=missing):
            code, answer = self.play()
        self.assertEqual(code, 503)
        self.assertEqual(answer["hint"], mpv.INSTALL_HINT)
        self.assertIn("flatpak install flathub io.mpv.Mpv", answer["hint"])
        _, status = self.request("GET", "/api/status")
        self.assertEqual(status["state"], "idle")

    def test_path_outside_the_media_folders_is_refused(self):
        (self.root / "outside.mkv").write_bytes(b"")
        self.start(self.fake_mpv("#!/bin/sh\nexit 0\n"))
        code, answer = self.play("../outside.mkv")
        self.assertEqual(code, 400)
        self.assertEqual(answer["error"], "path escapes configured folder")
        _, status = self.request("GET", "/api/status")
        self.assertEqual(status["state"], "idle")


if __name__ == "__main__":
    unittest.main()
