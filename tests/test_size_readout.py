# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The size readout, a developer option (the sizing spike).

With "debug_size_readout": true in settings.json, the page sends its sizes
once at start and the launch log gets exactly one line with the window's
size in CSS pixels, the device pixel ratio, the screen's size and what
Firefox says about its zoom. Off or missing: the app starts as before, the
page isn't asked for anything and nothing is written. Only checked numbers
reach the log.

Run from the repo root:  python3 -m unittest tests.test_size_readout -v
"""

import contextlib
import http.client
import io
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from backend import size_readout
from backend.server import make_handler
from backend.settings import SettingsError, load_settings

UI_DIR = Path(__file__).resolve().parent.parent / "ui"

SIZES_SENT = {"window_width": 1280, "window_height": 800, "device_pixel_ratio": 1,
             "screen_width": 1280, "screen_height": 800}


class Setting(unittest.TestCase):
    def load(self, extra):
        with tempfile.TemporaryDirectory() as tmp:
            body = {"movies_path": "/m", "tv_path": "/t", **extra}
            (Path(tmp) / "settings.json").write_text(json.dumps(body))
            return load_settings(Path(tmp))

    def test_off_when_missing(self):
        self.assertIs(self.load({})["debug_size_readout"], False)

    def test_on_and_off(self):
        self.assertIs(self.load({"debug_size_readout": True})["debug_size_readout"], True)
        self.assertIs(self.load({"debug_size_readout": False})["debug_size_readout"], False)

    def test_not_true_or_false_is_a_plain_message(self):
        for value in ("yes", 1, None):
            with self.subTest(value=value), self.assertRaises(SettingsError) as caught:
                self.load({"debug_size_readout": value})
            self.assertIn("'debug_size_readout' must be true or false", str(caught.exception))


class Line(unittest.TestCase):
    def test_all_four_values(self):
        text = size_readout.line(SIZES_SENT)
        self.assertEqual(text, "size readout: window 1280x800 CSS px; device pixel ratio 1; "
                               "screen 1280x800 CSS px = 1280x800 screen px; "
                               "Firefox zoom: part of the device pixel ratio (Firefox doesn't report it separately)")

    def test_zoomed_or_scaled(self):
        text = size_readout.line({"window_width": 853.3333, "window_height": 533.5, "device_pixel_ratio": 1.5,
                                  "screen_width": 910.6667, "screen_height": 512})
        self.assertIn("window 853.3x533.5 CSS px", text)
        self.assertIn("device pixel ratio 1.5;", text)
        self.assertIn("= 1366x768 screen px", text)

    def test_refuses_anything_but_plausible_numbers(self):
        for key in SIZES_SENT:
            for bad in (None, "1280", True, 0, -1, float("nan"), float("inf"), 10**9):
                with self.subTest(key=key, bad=bad), self.assertRaises(ValueError):
                    size_readout.line({**SIZES_SENT, key: bad})
            with self.subTest(missing=key), self.assertRaises(ValueError):
                size_readout.line({k: v for k, v in SIZES_SENT.items() if k != key})
        with self.assertRaises(ValueError):
            size_readout.line(["not", "an", "object"])


class Endpoint(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.httpd = None

    def tearDown(self):
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()
        self.tmp.cleanup()

    def start(self, **extra):
        settings = {"movies_path": str(self.root), "tv_path": str(self.root), "mpv_command": "mpv",
                    "mpv_args": [], "data_dir": str(self.root / "data"), **extra}
        httpd_ref = {}
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        self.port = self.httpd.server_address[1]
        with contextlib.redirect_stdout(io.StringIO()):
            base = make_handler(UI_DIR, self.root, settings, httpd_ref, self.port)

        class Quiet(base):
            def log_message(self, format, *args):
                pass

        self.httpd.RequestHandlerClass = Quiet
        httpd_ref["server"] = self.httpd
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def request(self, method, path, body=None):
        """(status, answer, what the backend wrote to the launch log)."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
            headers = {"Content-Type": "application/json"} if body is not None else {}
            conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
            resp = conn.getresponse()
            data = json.loads(resp.read())
            conn.close()
        return resp.status, data, out.getvalue()

    def readout_lines(self, log):
        return [line for line in log.splitlines() if line.startswith("size readout:")]

    def test_on_the_page_is_asked_and_one_line_is_written(self):
        self.start(debug_size_readout=True)
        _, dev, _ = self.request("GET", "/api/dev")
        self.assertIs(dev.get("size_readout"), True)
        status, answer, log = self.request("POST", "/api/size-readout", SIZES_SENT)
        self.assertEqual((status, answer), (200, {"ok": True, "logged": True}))
        self.assertEqual(self.readout_lines(log), [size_readout.line(SIZES_SENT)])

    def test_only_once_per_launch(self):
        self.start(debug_size_readout=True)
        self.request("POST", "/api/size-readout", SIZES_SENT)
        status, answer, log = self.request("POST", "/api/size-readout", SIZES_SENT)
        self.assertEqual((status, answer), (200, {"ok": True, "logged": False}))
        self.assertEqual(log, "")

    def test_bad_numbers_write_only_a_plain_refusal(self):
        self.start(debug_size_readout=True)
        for body, reason in (({**SIZES_SENT, "window_width": "a title"}, "window_width must be a number"),
                             ({**SIZES_SENT, "screen_height": 0}, "screen_height is out of range"),
                             ({}, "window_width must be a number"),
                             (["x"], "the readout must be an object")):
            with self.subTest(body=body):
                status, _, log = self.request("POST", "/api/size-readout", body)
                self.assertEqual(status, 400)
                self.assertEqual(log, f"size readout refused: {reason}\n")
                self.assertNotIn("a title", log)
        # A refused readout doesn't use up the launch's one line.
        _, answer, log = self.request("POST", "/api/size-readout", SIZES_SENT)
        self.assertTrue(answer["logged"])
        self.assertEqual(len(self.readout_lines(log)), 1)

    def test_off_or_missing_nothing_is_asked_or_written(self):
        for extra in ({}, {"debug_size_readout": False}):
            with self.subTest(extra=extra):
                self.start(**extra)
                _, dev, _ = self.request("GET", "/api/dev")
                self.assertNotIn("size_readout", dev)
                self.assertEqual(dev, {})
                status, _, log = self.request("POST", "/api/size-readout", SIZES_SENT)
                self.assertEqual(status, 404)
                self.assertEqual(log, "")
                self.httpd.shutdown()
                self.httpd.server_close()
                self.httpd = None


if __name__ == "__main__":
    unittest.main()
