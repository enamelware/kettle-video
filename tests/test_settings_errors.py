# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Mistakes in settings.json give one plain sentence naming the setting
(the settings mistakes work, audit finding H4), never a raw Python error, and valid settings
keep their meaning. Every settings file here is a temporary copy; the real
settings.json is never read or written.

Run from the repo root:  python3 -m unittest discover -s tests -t . -v
"""

import contextlib
import http.client
import io
import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from backend import mpv
from backend.server import make_handler
from backend.settings import SettingsError, load_settings

UI_DIR = Path(__file__).resolve().parent.parent / "ui"
GOOD = {"movies_path": "/media/Movies", "tv_path": "/media/TV Shows"}


class SettingsFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.path = self.root / "settings.json"

    def tearDown(self):
        self.tmp.cleanup()

    def load_bytes(self, raw: bytes):
        self.path.write_bytes(raw)
        before = self.path.read_bytes()
        try:
            return load_settings(self.root)
        finally:
            # Settings are only ever read: the file is never changed.
            self.assertEqual(self.path.read_bytes(), before)

    def load(self, **changes):
        data = {**GOOD, **changes}
        return self.load_bytes(json.dumps(data).encode("utf-8"))

    def assert_plain(self, exc: SettingsError, *words):
        message = str(exc.exception)
        self.assertIn("settings.json", message)
        for word in words:
            self.assertIn(word, message)
        self.assertNotIn("Traceback", message)
        self.assertNotIn("Error:", message)

    def test_folder_path_null(self):
        for key in ("movies_path", "tv_path"):
            with self.subTest(key=key), self.assertRaises(SettingsError) as exc:
                self.load(**{key: None})
            self.assert_plain(exc, f"'{key}'", "folder path")

    def test_folder_path_wrong_type(self):
        for value in (42, True, ["/media/Movies"], {"path": "/media"}):
            with self.subTest(value=value), self.assertRaises(SettingsError) as exc:
                self.load(movies_path=value)
            self.assert_plain(exc, "'movies_path'", "folder path")

    def test_folder_path_empty_means_not_set(self):
        # Since the folder choice screens an empty folder is not set (onboarding asks for
        # it), never a mistake that stops the app.
        for value in ("", "   ", "file://"):
            with self.subTest(value=value):
                self.assertEqual(self.load(tv_path=value)["tv_path"], "")

    def test_folder_path_missing(self):
        with self.assertRaises(SettingsError) as exc:
            self.load_bytes(json.dumps({"movies_path": "/media/Movies"}).encode())
        self.assert_plain(exc, "'tv_path'")

    def test_file_that_is_not_utf8_text(self):
        for name, raw in (
            ("latin-1", '{"movies_path": "/media/Filmes ç", "tv_path": "/media/TV"}'.encode("latin-1")),
            ("utf-16", json.dumps(GOOD).encode("utf-16")),
            ("binary", bytes(range(256))),
        ):
            with self.subTest(name), self.assertRaises(SettingsError) as exc:
                self.load_bytes(raw)
            self.assert_plain(exc, "UTF-8")

    def test_utf8_with_start_marker_is_read(self):
        data = self.load_bytes(json.dumps(GOOD).encode("utf-8-sig"))
        self.assertEqual(data["movies_path"], "/media/Movies")

    def test_missing_file_means_neither_folder_is_set(self):
        # Since the folder choice screens: a first launch, not a mistake. Loading never creates it.
        data = load_settings(self.root)
        self.assertEqual((data["movies_path"], data["tv_path"]), ("", ""))
        self.assertEqual(data["mpv_command"], "auto")
        self.assertTrue(data["resume"])
        self.assertFalse(self.path.exists())

    def test_file_that_cannot_be_read(self):
        # A folder where the file should be stands in for an unreadable file
        # (permissions don't stop the tests' own user on every system).
        self.path.mkdir()
        with self.assertRaises(SettingsError) as exc:
            load_settings(self.root)
        self.assert_plain(exc, "can't be read")

    def test_not_a_list_of_settings(self):
        for raw in (b"[]", b'"hello"', b"null", b"3"):
            with self.subTest(raw=raw), self.assertRaises(SettingsError) as exc:
                self.load_bytes(raw)
            self.assert_plain(exc, "{")

    def test_valid_settings_keep_their_meaning(self):
        data = self.load(movies_path="  ~/Movies ", tv_path="file:///media/TV%20Shows")
        self.assertEqual(data["movies_path"], os.path.expanduser("~/Movies"))
        self.assertEqual(data["tv_path"], "/media/TV Shows")
        self.assertEqual(data["mpv_command"], "auto")

    def test_mpv_command_mistakes_do_not_stop_the_app(self):
        # They are reported by the mpv check, on screen, instead.
        for value in ('mpv "--title=x', 42, "/nonexistent/mpv"):
            with self.subTest(value=value):
                self.assertEqual(self.load(mpv_command=value)["mpv_command"], value)


class MpvCommandTest(unittest.TestCase):
    def assert_problem(self, status, words):
        self.assertFalse(status["available"])
        self.assertIn("settings.json's 'mpv_command'", status["problem"])
        self.assertIn(words, status["problem"])
        self.assertEqual(status["hint"], mpv.SETTING_HINT)
        self.assertNotIn("command", status)

    def test_unclosed_quote(self):
        for value in ('mpv "--title=x', "mpv '--fs"):
            with self.subTest(value=value):
                self.assert_problem(mpv.detect(value), "quote that isn't closed")

    def test_wrong_type(self):
        for value in (42, 1.5, True, False, ["mpv"], {"cmd": "mpv"}):
            with self.subTest(value=value):
                self.assert_problem(mpv.detect(value), "must be text")

    def test_program_that_does_not_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            not_runnable = Path(tmp) / "mpv"
            not_runnable.write_text("#!/bin/sh\n")
            not_runnable.chmod(0o644)
            for value in ("/nonexistent/mpv", "kettle-no-such-program-xyz --fs",
                          tmp, str(not_runnable), "mpv\x00x", "''"):
                with self.subTest(value=value):
                    status = mpv.detect(value)
                    self.assert_problem(status, "can't be found")
                    self.assertNotIn(tmp, status["problem"])

    def test_program_that_exists_is_used_as_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "my mpv"
            fake.write_text("#!/bin/sh\n")
            fake.chmod(0o755)
            status = mpv.detect(f"'{fake}' --fs")
        self.assertEqual(status, {"available": True, "command": [str(fake), "--fs"], "via": "configured"})

    def test_auto_null_and_empty_still_find_mpv(self):
        found = {"available": True, "command": ["/usr/bin/mpv"], "via": "system"}
        with mock.patch.object(mpv.shutil, "which", return_value="/usr/bin/mpv"):
            for value in ("auto", None, "", "   "):
                with self.subTest(value=value):
                    self.assertEqual(mpv.detect(value), found)


class MpvMissingTest(unittest.TestCase):
    """With "auto" and no mpv anywhere, the install hint still shows, also
    when the flatpak program itself can't be run (any OSError, the settings mistakes work)."""

    def test_flatpak_that_cannot_run_means_mpv_missing(self):
        for error in (FileNotFoundError, PermissionError, OSError):
            with self.subTest(error=error.__name__), \
                    mock.patch.object(mpv.shutil, "which", return_value=None), \
                    mock.patch.object(mpv.subprocess, "run", side_effect=error("no")):
                self.assertEqual(mpv.detect("auto"),
                                 {"available": False, "install_hint": mpv.INSTALL_HINT})


class MpvStatusEndpointTest(unittest.TestCase):
    """What the page gets from /api/mpv-status with a bad mpv_command: a
    plain answer, never a server error."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.httpd = None

    def tearDown(self):
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()
        self.tmp.cleanup()

    def start(self, mpv_command):
        settings = {"movies_path": self.tmp.name, "tv_path": self.tmp.name,
                    "mpv_command": mpv_command, "mpv_args": [], "resume": True, "keep_awake": False,
                    "data_dir": str(Path(self.tmp.name) / "data")}
        httpd_ref = {}
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        self.port = self.httpd.server_address[1]
        with contextlib.redirect_stdout(io.StringIO()):
            base = make_handler(UI_DIR, Path(self.tmp.name), settings, httpd_ref, self.port)

        class Quiet(base):
            def log_message(self, format, *args):
                pass

        self.httpd.RequestHandlerClass = Quiet
        httpd_ref["server"] = self.httpd
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def get_status(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        with contextlib.redirect_stdout(io.StringIO()):
            conn.request("GET", "/api/mpv-status")
            resp = conn.getresponse()
            data = json.loads(resp.read())
        conn.close()
        return resp.status, data

    def test_bad_commands_answer_plainly(self):
        for value, words in (('mpv "--fs', "quote that isn't closed"), (7, "must be text"),
                             ("/nonexistent/mpv", "can't be found")):
            with self.subTest(value=value):
                self.start(value)
                code, data = self.get_status()
                self.assertEqual(code, 200)
                self.assertFalse(data["available"])
                self.assertIn(words, data["problem"])
                self.assertEqual(data["hint"], mpv.SETTING_HINT)
                self.httpd.shutdown()
                self.httpd.server_close()
                self.httpd = None


if __name__ == "__main__":
    unittest.main()
