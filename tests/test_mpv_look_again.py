# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Look again on the first launch's "mpv not found" screen (the mpv missing screen), through
the real server: it really checks again, for the system mpv and the Flatpak,
and reads mpv_command from the settings file again, because that screen can ask
for it to be fixed. Only temporary folders and a temporary PATH, with stand-ins
for mpv and flatpak that are never played; the app's own settings.json is never
read or written. What the screen does with the answers: tests/mpv_look_again_check.py.

Run from the repo root:  python3 -m unittest tests.test_mpv_look_again -v
"""

import contextlib
import http.client
import io
import json
import os
import socket
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from backend import mpv, server as backend_server
from backend.launch_options import FRESH_START, PRETEND_NO_MPV, LaunchOptions
from backend.server import make_handler
from backend.settings import SettingsError, read_mpv_command

UI_DIR = Path(__file__).resolve().parent.parent / "ui"
BROKEN = 'mpv "--fs'


def stand_in(path, body):
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(0o755)


class ReadMpvCommandTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.file = Path(tmp.name) / "settings.json"

    def test_says_what_the_file_says_now(self):
        self.file.write_text(json.dumps({"mpv_command": "mpv --fs"}), encoding="utf-8")
        self.assertEqual(read_mpv_command(self.file), "mpv --fs")

    def test_left_out_or_no_file_means_find_mpv(self):
        self.assertEqual(read_mpv_command(self.file), "auto")
        self.file.write_text("{}", encoding="utf-8")
        self.assertEqual(read_mpv_command(self.file), "auto")

    def test_a_broken_file_gives_its_plain_sentence(self):
        self.file.write_text("{ not json", encoding="utf-8")
        with self.assertRaises(SettingsError) as caught:
            read_mpv_command(self.file)
        self.assertNotIn(str(self.file.parent), str(caught.exception))


class Server:
    """Answers HTTP as the app does."""

    def __init__(self, test, port):
        self.test, self.port = test, port

    def ask(self, method, path, content_type="application/json"):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        self.test.addCleanup(conn.close)
        conn.request(method, path, body=b"{}" if method == "POST" else None,
                     headers={"Host": f"127.0.0.1:{self.port}", "Content-Type": content_type})
        response = conn.getresponse()
        return response.status, json.loads(response.read())

    def look_again(self):
        status, answer = self.ask("POST", "/api/mpv-status/look-again")
        self.test.assertEqual(status, 200)
        return answer

    def status(self):
        return self.ask("GET", "/api/mpv-status")[1]


class LookAgainTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        patch = mock.patch.dict(os.environ, {"PATH": str(self.bin)})
        patch.start()
        self.addCleanup(patch.stop)
        self.file = self.tmp / "settings.json"
        self.write({"movies_path": "", "tv_path": "", "mpv_command": "auto"})

    def write(self, data):
        self.file.write_text(json.dumps(data), encoding="utf-8")

    def start(self, mpv_command="auto", options=None, mpv_setting_file="default"):
        settings = {"movies_path": "", "tv_path": "", "mpv_command": mpv_command, "mpv_args": [],
                    "resume": True, "keep_awake": False, "data_dir": str(self.tmp / "data")}
        ref = {}
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        port = httpd.server_address[1]
        base = make_handler(UI_DIR, self.tmp, settings, ref, port, options, None,
                            self.file if mpv_setting_file == "default" else mpv_setting_file)

        class Quiet(base):
            def log_message(self, format, *args):
                pass

        httpd.RequestHandlerClass = Quiet
        ref["server"] = httpd
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        return Server(self, port)

    def test_still_missing_answers_as_missing(self):
        answer = self.start().look_again()
        self.assertEqual(answer, {"available": False, "install_hint": mpv.INSTALL_HINT})

    def test_finds_a_system_mpv_installed_while_the_app_is_open(self):
        app = self.start()
        self.assertFalse(app.status()["available"])
        stand_in(self.bin / "mpv", "exit 0")
        answer = app.look_again()
        self.assertEqual((answer["available"], answer["via"]), (True, "system"))
        self.assertNotIn("command", answer)
        self.assertNotIn(str(self.tmp), json.dumps(answer))

    def test_finds_the_flatpak_installed_while_the_app_is_open(self):
        app = self.start()
        self.assertFalse(app.look_again()["available"])
        # flatpak there, but without mpv: it answers no.
        stand_in(self.bin / "flatpak", "exit 1")
        self.assertFalse(app.look_again()["available"])
        marker = self.tmp / "asked"
        stand_in(self.bin / "flatpak", f'echo "$*" > "{marker}"\nexit 0')
        answer = app.look_again()
        self.assertEqual((answer["available"], answer["via"]), (True, "flatpak"))
        self.assertEqual(marker.read_text().strip(), f"info {mpv.FLATPAK_APP_ID}")

    def test_a_setting_fixed_in_the_file_counts(self):
        self.write({"movies_path": "", "tv_path": "", "mpv_command": BROKEN})
        app = self.start(BROKEN)
        answer = app.look_again()
        self.assertEqual(answer["problem"], "settings.json's 'mpv_command' has a quote that isn't closed.")
        self.assertEqual(answer["hint"], mpv.SETTING_HINT)
        # Set to "auto", as the hint says, with mpv not installed yet.
        self.write({"movies_path": "", "tv_path": "", "mpv_command": "auto"})
        self.assertEqual(app.look_again(), {"available": False, "install_hint": mpv.INSTALL_HINT})
        # Fixed by naming a program that is there.
        stand_in(self.bin / "my-mpv", "exit 0")
        self.write({"movies_path": "", "tv_path": "", "mpv_command": "my-mpv --fs"})
        self.assertEqual(app.look_again()["via"], "configured")
        # The app goes on using it: the plain check, which playing also uses, agrees.
        self.assertEqual(app.status()["via"], "configured")

    def test_a_setting_broken_since_launch_is_reported_too(self):
        app = self.start()
        stand_in(self.bin / "mpv", "exit 0")
        self.write({"movies_path": "", "tv_path": "", "mpv_command": 7})
        answer = app.look_again()
        self.assertFalse(answer["available"])
        self.assertIn("must be text in quotes", answer["problem"])

    def test_a_file_that_cannot_be_read_says_so_then_recovers(self):
        app = self.start()
        stand_in(self.bin / "mpv", "exit 0")
        self.file.write_text("{ half written", encoding="utf-8")
        answer = app.look_again()
        self.assertFalse(answer["available"])
        self.assertIn("settings.json is not valid JSON", answer["problem"])
        self.assertEqual(answer["hint"], mpv.SETTING_HINT)
        self.assertNotIn(str(self.tmp), json.dumps(answer))
        self.write({"movies_path": "", "tv_path": "", "mpv_command": "auto"})
        self.assertTrue(app.look_again()["available"])

    def test_no_settings_file_means_find_mpv(self):
        self.file.unlink()
        app = self.start(BROKEN)
        self.assertEqual(app.look_again(), {"available": False, "install_hint": mpv.INSTALL_HINT})
        self.assertFalse(self.file.exists())

    def test_the_settings_file_is_only_read(self):
        self.file.write_text('{ "movies_path": "",\n  "tv_path": "",   "mpv_command": "auto" }\n', encoding="utf-8")
        before = self.file.read_bytes(), self.file.stat().st_mtime_ns
        app = self.start()
        stand_in(self.bin / "mpv", "exit 0")
        app.look_again()
        self.assertEqual((self.file.read_bytes(), self.file.stat().st_mtime_ns), before)

    def test_pretend_mpv_is_missing_stays_missing(self):
        stand_in(self.bin / "mpv", "exit 0")
        self.file.write_text("{ even a broken file", encoding="utf-8")
        options = LaunchOptions(data_dir=self.tmp / "data", pretend_no_mpv=True)
        answer = self.start(options=options).look_again()
        self.assertEqual(answer, {"available": False, "install_hint": mpv.INSTALL_HINT})

    def test_without_a_file_to_read_the_setting_from_launch_stays(self):
        self.write({"movies_path": "", "tv_path": "", "mpv_command": "auto"})
        answer = self.start(BROKEN, mpv_setting_file=None).look_again()
        self.assertIn("quote", answer["problem"])

    def test_refused_like_every_other_request_from_elsewhere(self):
        app = self.start()
        self.assertEqual(app.ask("POST", "/api/mpv-status/look-again", "text/plain")[0], 403)


class RealStartTest(unittest.TestCase):
    """As launch.sh starts it: Look again reads the real settings file, in
    fresh start too, though fresh start's choices go to a file of its own."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.app = self.tmp / "app"
        self.app.mkdir()
        (self.app / "ui").mkdir()
        self.parent = self.tmp / "fresh-parent"
        self.parent.mkdir()
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        patch = mock.patch.dict(os.environ, {"PATH": str(self.bin)})
        patch.start()
        self.addCleanup(patch.stop)
        self.file = self.app / "settings.json"

    def write(self, command):
        self.file.write_text(json.dumps({"movies_path": "/nowhere/m", "tv_path": "/nowhere/t",
                                         "mpv_command": command, "keep_awake": False}), encoding="utf-8")

    def serve(self, environ):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        ref = {}

        def run():
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                backend_server.serve(self.app, environ, port, ref, self.parent)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        app = Server(self, port)
        for _ in range(100):
            try:
                app.status()
                break
            except OSError:
                threading.Event().wait(0.05)

        def stop():
            app.ask("POST", "/api/shutdown")
            thread.join(10)

        self.addCleanup(stop)
        return app

    def test_normal_start_reads_the_app_folders_file(self):
        self.write(BROKEN)
        app = self.serve({})
        self.assertIn("quote", app.look_again()["problem"])
        stand_in(self.bin / "mpv", "exit 0")
        self.write("auto")
        self.assertEqual(app.look_again()["via"], "system")

    def test_fresh_start_reads_the_real_file_and_leaves_it_alone(self):
        self.write(BROKEN)
        app = self.serve({FRESH_START: "1"})
        self.assertTrue(app.ask("GET", "/api/onboarding")[1]["needed"])
        self.assertIn("quote", app.look_again()["problem"])
        stand_in(self.bin / "mpv", "exit 0")
        self.write("auto")
        before = self.file.read_bytes()
        self.assertEqual(app.look_again()["via"], "system")
        self.assertEqual(self.file.read_bytes(), before)

    def test_fresh_start_pretending_stays_missing(self):
        self.write("auto")
        stand_in(self.bin / "mpv", "exit 0")
        app = self.serve({FRESH_START: "1", PRETEND_NO_MPV: "1"})
        self.assertTrue(app.ask("GET", "/api/onboarding")[1]["needed"])
        self.assertEqual(app.look_again(), {"available": False, "install_hint": mpv.INSTALL_HINT})


if __name__ == "__main__":
    unittest.main()
