# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Loading screen (the loading screen work): the bundled wordmark font is the unmodified
official file with its licence next to it, the UI never loads anything from
the internet, and the app's server hands the font to the browser.

Run from the repo root:  python3 -m unittest discover -s tests -t . -v
"""

import hashlib
import http.client
import re
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from backend.server import make_handler

UI_DIR = Path(__file__).resolve().parent.parent / "ui"
FONT = UI_DIR / "fonts" / "RubikMonoOne-Regular.ttf"
FONT_LICENSE = UI_DIR / "fonts" / "RubikMonoOne-OFL.txt"

# SHA-256 of RubikMonoOne-Regular.ttf in google/fonts, ofl/rubikmonoone
# (commit 0fc79a83d486f399f0fe3c07f4d0a5ab6a39ad1f).
FONT_SHA256 = "b22624b6a36e543e942106edfccd198c50b57b65b924bfe02a6f0a5699429e6b"


class BundledFontTest(unittest.TestCase):
    def test_font_is_the_unmodified_official_file(self):
        self.assertEqual(hashlib.sha256(FONT.read_bytes()).hexdigest(), FONT_SHA256)

    def test_licence_sits_next_to_the_font(self):
        text = FONT_LICENSE.read_text()
        self.assertIn("SIL OPEN FONT LICENSE Version 1.1", text)
        self.assertIn("The Rubik Project Authors", text)

    def test_ui_loads_nothing_from_the_internet(self):
        for path in UI_DIR.rglob("*"):
            if path.suffix not in (".html", ".css", ".js"):
                continue
            with self.subTest(file=str(path.relative_to(UI_DIR))):
                text = path.read_text()
                self.assertNotRegex(text, r"(?i)\b(https?:)?//[\w.-]+\.\w+/")
                self.assertNotRegex(text, r"(?i)@import")

    def test_stylesheet_points_at_the_bundled_font(self):
        css = (UI_DIR / "css" / "defaults.css").read_text()
        urls = re.findall(r"url\(\"?([^\")]+)\"?\)", css)
        self.assertEqual(urls, ["../fonts/RubikMonoOne-Regular.ttf"])
        self.assertTrue((UI_DIR / "css" / urls[0]).resolve() == FONT.resolve())


class FontServedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        settings = {"movies_path": self.tmp.name, "tv_path": self.tmp.name, "mpv_command": "mpv"}
        httpd_ref = {}
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        port = self.httpd.server_address[1]
        self.httpd.RequestHandlerClass = make_handler(
            UI_DIR, Path(self.tmp.name), settings, httpd_ref, port
        )
        httpd_ref["server"] = self.httpd
        self.port = port
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def test_server_delivers_the_font(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", "/fonts/RubikMonoOne-Regular.ttf")
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        self.assertEqual(resp.status, 200)
        self.assertEqual(body, FONT.read_bytes())


if __name__ == "__main__":
    unittest.main()
