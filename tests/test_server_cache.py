# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The server tells the browser to check for newer UI files on every load
(the Brand v0.1 work: the kiosk Firefox kept showing old CSS from its cache), and logs
once when the page has loaded (the start-up fix: launch.sh looks for that line).

Run from the repo root:  python3 -m unittest discover -s tests -t . -v
"""

import contextlib
import http.client
import io
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from backend.server import make_handler

UI_DIR = Path(__file__).resolve().parent.parent / "ui"


class ServerCacheTest(unittest.TestCase):
    def setUp(self):
        os.environ.pop("KETTLE_VIDEO_LAUNCH_START", None)
        self.tmp = tempfile.TemporaryDirectory()
        settings = {"movies_path": self.tmp.name, "tv_path": self.tmp.name, "mpv_command": "mpv"}
        httpd_ref = {}
        # Bind first to learn the free port, then build the handler with it.
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        self.port = self.httpd.server_address[1]
        self.httpd.RequestHandlerClass = make_handler(
            UI_DIR, Path(self.tmp.name), settings, httpd_ref, self.port
        )
        httpd_ref["server"] = self.httpd
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def _get(self, path, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path, headers=headers or {})
        resp = conn.getresponse()
        resp.read()
        conn.close()
        return resp

    def test_ui_files_must_be_revalidated(self):
        for path in ("/", "/css/tokens.css", "/css/defaults.css", "/js/app.js"):
            with self.subTest(path=path):
                resp = self._get(path)
                self.assertEqual(resp.status, 200)
                self.assertEqual(resp.getheader("Cache-Control"), "no-cache")

    def test_unchanged_file_still_answers_not_modified(self):
        first = self._get("/css/tokens.css")
        resp = self._get("/css/tokens.css", {"If-Modified-Since": first.getheader("Last-Modified")})
        self.assertEqual(resp.status, 304)
        self.assertEqual(resp.getheader("Cache-Control"), "no-cache")

    def test_api_answers_also_carry_the_header(self):
        resp = self._get("/api/status")
        self.assertEqual(resp.getheader("Cache-Control"), "no-cache")

    def test_page_loaded_is_logged_once(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self._get("/api/mpv-status")
            self._get("/api/mpv-status")
        lines = [l for l in out.getvalue().splitlines() if l.startswith("page loaded")]
        self.assertEqual(len(lines), 1)
        self.assertRegex(lines[0], r"^page loaded \d+\.\d s after launch$")


if __name__ == "__main__":
    unittest.main()
