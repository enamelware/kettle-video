# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Start-up failures are said on screen (the start-up problem screen, audit finding H3).

Scripted runs of the real launch.sh on a temporary copy of the app, with
stand-ins on PATH: a "firefox" that reads the start-up message the way the
page does and closes it (or opens the app and quits it), a "zenity" that
only notes what it was asked to show, and a "flatpak" that finds nothing.
Checks that Firefox missing, a broken settings file and a backend that
never answers each try to show the message and log the reason, and that a
normal launch is unchanged. Also the message itself and its small server.
The real settings.json, Firefox and media are never touched.

Run from the repo root:  python3 -m unittest tests.test_startup_error -v
"""

import contextlib
import http.client
import io
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from backend import startup_error

REPO = Path(__file__).resolve().parent.parent
COPY = ["launch.sh", "backend", "ui", "vendor"]

# Reads the message as the page does, checks the page itself is served,
# then says it was shown and closes it, as A would.
FAKE_FIREFOX_MESSAGE = r'''#!/usr/bin/env python3
import json, os, sys, urllib.request
url = sys.argv[-1].rstrip("/")
def post(path):
    req = urllib.request.Request(url + path, data=b"{}", method="POST",
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=10).read()
page = urllib.request.urlopen(url + "/", timeout=10).read().decode()
message = json.load(urllib.request.urlopen(url + "/api/startup-error", timeout=10))
with open(os.environ["FAKE_OUT"], "w") as out:
    json.dump({"url": url, "page": page, "message": message}, out)
post("/api/shown")
post("/api/close")
'''

# Opens the app the way the page does first, then quits it.
FAKE_FIREFOX_APP = r'''#!/usr/bin/env python3
import json, os, sys, urllib.request
url = sys.argv[-1].rstrip("/")
json.load(urllib.request.urlopen(url + "/api/mpv-status", timeout=10))
with open(os.environ["FAKE_OUT"], "w") as out:
    json.dump({"url": url}, out)
req = urllib.request.Request(url + "/api/shutdown", data=b"{}", method="POST",
                             headers={"Content-Type": "application/json"})
urllib.request.urlopen(req, timeout=10).read()
'''

FAKE_DIALOG = r'''#!/usr/bin/env python3
import json, os, sys
with open(os.environ["FAKE_DIALOG_OUT"], "w") as out:
    json.dump({"tool": os.path.basename(sys.argv[0]), "args": sys.argv[1:]}, out)
'''

FAKE_FLATPAK = "#!/bin/sh\nexit 1\n"

# A backend that starts and never opens its port.
SILENT_SERVER = "import time\ntime.sleep(600)\n"


def system_firefox(path):
    """A real firefox on PATH, outside the stand-ins."""
    return shutil.which("firefox", path=path)


class LauncherRun(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        self.app, self.bin, home = tmp / "app", tmp / "bin", tmp / "home"
        for d in (self.app, self.bin, home, tmp / "Movies", tmp / "TV"):
            d.mkdir()
        for name in COPY:
            src = REPO / name
            if src.is_dir():
                shutil.copytree(src, self.app / name, ignore=shutil.ignore_patterns("__pycache__"))
            else:
                shutil.copy2(src, self.app / name)
        self.good_settings = {"movies_path": str(tmp / "Movies"), "tv_path": str(tmp / "TV"),
                              "mpv_command": "auto", "mpv_args": []}
        self.out, self.dialog_out = tmp / "firefox-out.json", tmp / "dialog-out.json"
        self.stub("flatpak", FAKE_FLATPAK)
        self.stub("zenity", FAKE_DIALOG)
        original = os.environ["PATH"]
        self.env = dict(os.environ, HOME=str(home), PATH=f"{self.bin}:{original}",
                        FAKE_OUT=str(self.out), FAKE_DIALOG_OUT=str(self.dialog_out))
        for name in ("KETTLE_VIDEO_PORT", "KETTLE_VIDEO_LAUNCH_START", "KETTLE_DEV_UPDATE",
                     "KETTLE_LAUNCH_LOG", "MOZ_HEADLESS"):
            self.env.pop(name, None)
        self.real_firefox = system_firefox(original)

    def tearDown(self):
        self.tmp.cleanup()

    def stub(self, name, text):
        path = self.bin / name
        path.write_text(text)
        path.chmod(0o755)

    def settings(self, text):
        (self.app / "settings.json").write_text(text)

    def launch(self, timeout=60):
        proc = subprocess.run(["bash", "launch.sh"], cwd=self.app, env=self.env,
                              capture_output=True, text=True, timeout=timeout)
        logs = sorted((self.app / "logs").glob("launch-*.log"))
        self.assertEqual(len(logs), 1, "one launch log")
        return proc.returncode, logs[0].read_text(), logs[0].name

    def read(self, path):
        return json.loads(path.read_text()) if path.exists() else None

    def test_firefox_missing_shows_a_dialog(self):
        if self.real_firefox:
            self.skipTest("this device has a system firefox on PATH")
        self.settings(json.dumps(self.good_settings))
        code, log, log_name = self.launch()
        self.assertEqual(code, 1)
        self.assertIn("firefox not found", log)
        self.assertIn("showing the start-up problem on screen (no-firefox)", log)
        self.assertIn("showing the start-up problem in a zenity dialog", log)
        # Said at once: the backend is never started without a window.
        self.assertNotIn("starting backend", log)
        dialog = self.read(self.dialog_out)
        self.assertIsNotNone(dialog, "zenity was asked to show the message")
        self.assertIn("--error", dialog["args"])
        self.assertIn("--no-markup", dialog["args"])
        text = next(a for a in dialog["args"] if a.startswith("--text="))
        self.assertIn("Firefox isn't installed", text)
        self.assertIn(log_name, text)
        self.assertNotIn(str(self.app), text)

    def test_broken_settings_show_the_message_in_firefox(self):
        self.stub("firefox", FAKE_FIREFOX_MESSAGE)
        self.settings('{"movies_path": "/films", "tv_path": "/shows",}')
        code, log, log_name = self.launch()
        self.assertEqual(code, 1)
        self.assertIn("Settings error:", log)
        self.assertIn("backend exited early", log)
        self.assertIn("showing the start-up problem on screen (backend-stopped)", log)
        self.assertIn("start-up message shown", log)
        self.assertIn("start-up message closed", log)
        self.assertIn("firefox pid:", log)
        self.assertIsNone(self.read(self.dialog_out), "no dialog when Firefox can show it")
        seen = self.read(self.out)
        self.assertIsNotNone(seen, "firefox was opened on the message")
        self.assertIn('id="startup-error"', seen["page"])
        lines = seen["message"]["lines"]
        self.assertEqual(lines[0], startup_error.TITLE)
        self.assertTrue(lines[1].startswith("Your settings have a mistake: settings.json is not valid JSON"), lines)
        self.assertEqual(lines[2], startup_error.SETTINGS_FIX)
        self.assertIn(log_name, lines[-1])
        self.assertNotIn(str(self.app), json.dumps(lines))

    def test_backend_that_never_answers_shows_the_message(self):
        self.stub("firefox", FAKE_FIREFOX_MESSAGE)
        self.settings(json.dumps(self.good_settings))
        (self.app / "backend" / "server.py").write_text(SILENT_SERVER)
        code, log, _ = self.launch()
        self.assertEqual(code, 1)
        self.assertIn("backend never opened its port", log)
        self.assertIn("showing the start-up problem on screen (backend-silent)", log)
        self.assertIn("start-up message closed", log)
        seen = self.read(self.out)
        self.assertIsNotNone(seen)
        self.assertIn("Kettle took too long to get ready.", seen["message"]["lines"])
        # The silent backend was stopped, not left running.
        pid = int(log.split("backend pid: ")[1].split()[0])
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_normal_launch_is_unchanged(self):
        self.stub("firefox", FAKE_FIREFOX_APP)
        self.settings(json.dumps(self.good_settings))
        code, log, _ = self.launch()
        self.assertEqual(code, 0)
        self.assertIn("found system firefox", log)
        self.assertIn("backend is ready", log)
        self.assertIn("page loaded", log)
        self.assertIn("shutdown complete", log)
        self.assertNotIn("start-up problem", log)
        self.assertIsNone(self.read(self.dialog_out))
        seen = self.read(self.out)
        port = log.split("starting backend on port ")[1].split()[0]
        self.assertEqual(seen["url"], f"http://127.0.0.1:{port}")


class MessageWords(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def lines(self, reason):
        return startup_error.lines(reason, str(self.root / "logs" / "launch-20260101-120000.log"), self.root)

    def check_shape(self, lines):
        self.assertEqual(lines[0], "Kettle couldn't start.")
        self.assertIn("launch-20260101-120000.log", lines[-1])
        self.assertIn("logs folder", lines[-1])
        self.assertNotIn(str(self.root), json.dumps(lines))

    def test_each_reason_says_what_and_what_to_do(self):
        for reason, words in ((startup_error.NO_FIREFOX, "Install Firefox from Discover"),
                              (startup_error.BACKEND_SILENT, "took too long"),
                              (startup_error.BACKEND_STOPPED, "Start Kettle again.")):
            with self.subTest(reason=reason):
                lines = self.lines(reason)
                self.check_shape(lines)
                self.assertIn(words, " ".join(lines))

    def test_settings_mistake_names_it(self):
        (self.root / "settings.json").write_text('{"movies_path": 3, "tv_path": ""}')
        lines = self.lines(startup_error.BACKEND_STOPPED)
        self.check_shape(lines)
        self.assertIn("'movies_path' must be a folder path", lines[1])
        self.assertEqual(lines[2], startup_error.SETTINGS_FIX)

    def test_settings_fine_gives_the_general_message(self):
        (self.root / "settings.json").write_text('{"movies_path": "", "tv_path": ""}')
        lines = self.lines(startup_error.BACKEND_STOPPED)
        self.assertIn("Kettle stopped while it was getting ready.", lines)

    def test_text_mode_prints_the_lines(self):
        out = subprocess.run(["python3", "-m", "backend.startup_error", "text", "no-firefox", "logs/x.log"],
                             cwd=REPO, capture_output=True, text=True, check=True).stdout
        self.assertIn("Firefox isn't installed", out)
        self.assertIn("x.log", out)

    def test_unknown_reason_is_refused(self):
        proc = subprocess.run(["python3", "-m", "backend.startup_error", "text", "other", "x.log"],
                              cwd=REPO, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)


class MessageServer(unittest.TestCase):
    def setUp(self):
        # Its own lines (it says when it starts, each request) stay quiet.
        quiet = contextlib.ExitStack()
        quiet.enter_context(contextlib.redirect_stdout(io.StringIO()))
        quiet.enter_context(contextlib.redirect_stderr(io.StringIO()))
        self.addCleanup(quiet.close)
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.thread = threading.Thread(
            target=startup_error.serve, args=(startup_error.BACKEND_SILENT, "logs/l.log", self.port), daemon=True)
        self.thread.start()
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", self.port), timeout=1).close()
                break
            except OSError:
                threading.Event().wait(0.1)

    def tearDown(self):
        if self.thread.is_alive():
            self.request("POST", "/api/close")
            self.thread.join(5)

    def request(self, method, path, host=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Host": host or f"127.0.0.1:{self.port}", "Content-Type": "application/json"}
        conn.request(method, path, body=b"{}" if method == "POST" else None, headers=headers)
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp.status, body

    def test_serves_the_page_and_its_files(self):
        for path in ("/", "/startup-error.html", "/js/startup_error.js", "/css/defaults.css",
                     "/css/tokens.css", "/vendor/enamel/tokens/enamel.css",
                     "/vendor/enamel/components/enamel-components.css"):
            with self.subTest(path=path):
                self.assertEqual(self.request("GET", path)[0], 200)
        status, body = self.request("GET", "/api/startup-error")
        self.assertEqual(status, 200)
        self.assertIn("Kettle took too long to get ready.", json.loads(body)["lines"])

    def test_nothing_else_is_served(self):
        for path in ("/index.html", "/../settings.json", "/js/app.js", "/vendor/enamel/DESIGN.md"):
            with self.subTest(path=path):
                self.assertEqual(self.request("GET", path)[0], 404)

    def test_other_host_is_refused(self):
        self.assertEqual(self.request("GET", "/api/startup-error", host="example.invalid")[0], 403)
        self.assertEqual(self.request("POST", "/api/close", host="example.invalid")[0], 403)
        self.assertTrue(self.thread.is_alive())

    def test_close_ends_the_server(self):
        self.assertEqual(self.request("POST", "/api/close")[0], 200)
        self.thread.join(5)
        self.assertFalse(self.thread.is_alive())


if __name__ == "__main__":
    unittest.main()
