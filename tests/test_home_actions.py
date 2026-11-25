# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Home actions (the Home actions work), without a browser: the words the scan toast
shows when a rescan ends (from the backend), a scan can't start twice,
quitting stops the server, no answer from the server holds an absolute
path, and the page has the Menu button (no bar behind it since the Home polish), the menu and the toast in
place of the old top bar, Rescan row and "Rescanning…". The menu's rows,
the keys and the toast on screen are tests/home_actions_check.py.

Run from the repo root:  python3 -m unittest tests.test_home_actions -v
"""

import contextlib
import http.client
import json
import os
import re
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from backend import library_index
from tests import test_library_index
from tests.test_library_index import make_folders


ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "ui"
INDEX = (UI / "index.html").read_text(encoding="utf-8")
APP_JS = (UI / "js" / "app.js").read_text(encoding="utf-8")
KEYBOARD_JS = (UI / "js" / "keyboard.js").read_text(encoding="utf-8")
MENU_JS = (UI / "js" / "home_menu.js").read_text(encoding="utf-8")


def no_progress(done, total):
    pass


class ScanMessageTest(unittest.TestCase):
    """library_index.scan_message: what a rescan changed, in words."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.roots = make_folders(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def scan(self, previous):
        index = library_index.full_scan(self.roots, previous, no_progress)
        return index, library_index.scan_message(previous, index)

    def test_the_first_scan_counts_every_file_added(self):
        index, message = self.scan(None)
        files = sum(entry["counts"]["files"] for entry in index["sources"].values())
        self.assertEqual(message, f"{files} added")

    def test_a_rescan_with_nothing_new_says_no_changes(self):
        first, _ = self.scan(None)
        _, message = self.scan(first)
        self.assertEqual(message, "No changes")

    def test_added_changed_and_missing(self):
        first, _ = self.scan(None)
        movies = Path(self.roots["movies"])
        files = sorted(p for p in movies.rglob("*") if p.is_file())
        files[0].unlink()  # goes missing
        files[1].write_bytes(b"a longer file now")  # changed
        (movies / "New Film (2020)").mkdir()
        (movies / "New Film (2020)" / "New.Film.2020.mkv").write_bytes(b"x")  # added
        _, message = self.scan(first)
        self.assertEqual(message, "1 added, 1 changed, 1 missing")

    def test_missing_counts_only_what_went_missing_in_this_scan(self):
        first, _ = self.scan(None)
        next(p for p in Path(self.roots["movies"]).rglob("*") if p.is_file()).unlink()
        second, message = self.scan(first)
        self.assertEqual(message, "1 missing")
        # Still missing at the next scan: nothing new to say.
        _, message = self.scan(second)
        self.assertEqual(message, "No changes")

    def test_a_folder_that_is_away_is_named(self):
        first, _ = self.scan(None)
        os.rename(self.roots["movies"], self.root / "Movies away")
        _, message = self.scan(first)
        self.assertEqual(message, "Movies folder not available")

    def test_no_path_or_name_in_the_words(self):
        index, message = self.scan(None)
        self.assertNotIn("/", message)
        self.assertNotIn(self.tmp.name, message)


class HomeActionsServerTest(unittest.TestCase):
    """The server side of the menu: the scan's result words, one scan at a
    time, Quit, and answers without absolute paths. Uses the saved-library
    tests' server (not their tests)."""

    setUp = test_library_index.ScanServerTest.setUp
    start_server = test_library_index.ScanServerTest.start_server
    stop_server = test_library_index.ScanServerTest.stop_server
    tearDown = test_library_index.ScanServerTest.tearDown
    _request = test_library_index.ScanServerTest._request
    _wait_idle = test_library_index.ScanServerTest._wait_idle
    _scan = test_library_index.ScanServerTest._scan

    def test_a_scan_result_carries_its_words(self):
        status = self._scan()
        self.assertTrue(status["last_result"]["ok"])
        self.assertRegex(status["last_result"]["message"], r"^\d+ added$")
        self.assertEqual(self._scan()["last_result"], {"ok": True, "message": "No changes"})

    def test_a_scan_cant_start_twice(self):
        release = threading.Event()
        real_scan = library_index.full_scan
        calls = []

        def slow_scan(*args):
            calls.append(1)
            release.wait(10)
            return real_scan(*args)

        with mock.patch.object(library_index, "full_scan", side_effect=slow_scan), \
                contextlib.redirect_stdout(self.out):
            first = self._request("POST", "/api/library/scan")[1]
            second = self._request("POST", "/api/library/scan")[1]
            release.set()
            self._wait_idle()
        self.assertTrue(first["started"])
        self.assertEqual((second["started"], second["state"]), (False, "scanning"))
        self.assertEqual(len(calls), 1)

    def test_quitting_stops_the_server(self):
        with contextlib.redirect_stdout(self.out):
            status, answer = self._request("POST", "/api/shutdown")
        self.assertEqual((status, answer), (200, {"ok": True}))
        # The socket stays open until tearDown, so a stopped server shows as
        # a probe that gets no answer: a short timeout, not _request's 30 s.
        end = time.time() + 10
        while time.time() < end:
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=1)
            try:
                conn.request("GET", "/api/status")
                conn.getresponse().read()
            except OSError:
                return
            finally:
                conn.close()
            time.sleep(0.1)
        self.fail("the server still answers after Quit")

    def strings(self, value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for key, item in value.items():
                yield key
                yield from self.strings(item)
        elif isinstance(value, list):
            for item in value:
                yield from self.strings(item)

    def assertNoAbsolutePath(self, where, answer):
        for text in self.strings(answer):
            self.assertNotIn(self.tmp.name, text, where)
            # Page addresses (/api/…) are fine; a file system path is not.
            if text.startswith("/"):
                self.assertTrue(text.startswith("/api/"), f"{where}: {text!r}")

    def test_no_absolute_paths_in_any_answer(self):
        # The page's own requests, before and after a scan, with something
        # missing so every part of the answers is filled in.
        with mock.patch("backend.mpv.shutil.which", return_value="/usr/bin/mpv"), \
                contextlib.redirect_stdout(self.out):
            answers = {"mpv-status": self._request("GET", "/api/mpv-status")[1]}
            answers["scan"] = self._request("POST", "/api/library/scan")[1]
            self._wait_idle()
            next(p for p in Path(self.roots["movies"]).rglob("*") if p.is_file()).unlink()
            os.rename(self.roots["tv"], self.root / "TV away")
            self._request("POST", "/api/library/scan")
            answers["scan status"] = self._wait_idle()
            for path in ("/api/library/parsed", "/api/status", "/api/continue", "/api/dev"):
                answers[path] = self._request("GET", path)[1]
            answers["remove"] = self._request("POST", "/api/library/remove-missing")[1]
        self.assertEqual(answers["mpv-status"]["available"], True)
        self.assertIn("missing", answers["scan status"]["last_result"]["message"])
        for where, answer in answers.items():
            self.assertNoAbsolutePath(where, answer)


class PageTest(unittest.TestCase):
    """The page: the Menu button, the menu and the toast replace the
    old top bar, the Rescan row and "Rescanning…"."""

    def test_the_action_bar_holds_one_menu_button(self):
        bar = re.search(r'<header id="action-bar" class="action-bar" hidden>(.*?)</header>', INDEX, re.S)
        self.assertIsNotNone(bar)
        buttons = re.findall(r"<button[^>]*>([^<]*)</button>", bar.group(1))
        self.assertEqual(buttons, ["Menu"])
        self.assertIn('class="en-button" tabindex="-1" data-kind="menu"', bar.group(1))

    def test_no_docked_bar_behind_the_menu_button(self):
        # The Home polish, the designer's feedback: no bar at the top, only the Menu
        # button, which scrolls with the page. Enamel's action bar (docked
        # and black) is gone, and nothing keeps room for a docked bar.
        self.assertNotIn("en-actionbar", INDEX)
        defaults = (UI / "css" / "defaults.css").read_text(encoding="utf-8")
        tokens = (UI / "css" / "tokens.css").read_text(encoding="utf-8")
        for text in (defaults, tokens, APP_JS):
            self.assertNotIn("var(--shell-bar-height)", text)
            self.assertNotIn('"--shell-bar-height"', text)
        rule = re.search(r"(?m)^\.action-bar \{([^}]*)\}", defaults)
        self.assertIsNotNone(rule)
        self.assertNotIn("sticky", rule.group(1))
        self.assertNotIn("fixed", rule.group(1))
        self.assertNotIn("background", rule.group(1))

    def test_the_old_top_bar_rescan_row_and_banner_are_gone(self):
        for old in ('id="top-bar"', 'class="clock"', "rescan-list", 'id="rescanning-status"', "Rescanning…"):
            self.assertNotIn(old, INDEX)
        for old in ("clockText", "rescanRow", "removeRow", "lastScannedText", "ACTION_KINDS"):
            self.assertNotIn(old, APP_JS)

    def test_the_menu_is_a_kettle_picker_and_the_toast_kettles_toast(self):
        self.assertRegex(INDEX, r'<dialog id="home-menu" class="home-menu en-dialog"')
        self.assertRegex(INDEX, r'<div id="scan-toast" class="scan-toast en-toast" role="status" aria-live="polite"')
        # The app acts on Enamel's event, and shows Enamel's toast.
        self.assertIn('menuEl.addEventListener("en-select"', APP_JS)
        self.assertIn("window.EnamelUI.toast.show(", APP_JS)
        self.assertIn("window.EnamelUI.toast.update(", APP_JS)

    def test_menu_rows_and_toast_words_are_in_one_module(self):
        for word in ('"Rescan library"', '"Scanning…"', "Remove ${plural(missing, \"missing item\")}", '"Quit"',
                     '"Cancel"', '"No changes"'):
            self.assertIn(word, MENU_JS)

    def test_only_quit_uses_enamels_destructive_row(self):
        # The Home polish, the designer's feedback: Quit uses Enamel's destructive row,
        # which since Enamel 0.13.0 looks like the other rows until it has the
        # focus, then turns red. Quit is the one row marked destructive, and
        # the app gives a marked row Enamel's destructive picker class.
        marked = re.findall(r'\{[^{}]*destructive: true[^{}]*\}', MENU_JS)
        self.assertEqual(marked, ['{ value: "quit", title: "Quit", destructive: true }'])
        self.assertEqual(MENU_JS.count("destructive: true"), 1)
        self.assertIn('if (destructive) row.classList.add("en-picker__row--destructive");', APP_JS)
        # Nothing else in the page or the app's own CSS uses it or restyles
        # a menu row: how it looks comes from Enamel alone.
        self.assertEqual(APP_JS.count("--destructive"), 1)
        self.assertNotIn("destructive", INDEX)
        defaults = (UI / "css" / "defaults.css").read_text(encoding="utf-8")
        self.assertNotIn("destructive", defaults)
        self.assertNotIn("en-picker__row", defaults)

    def test_enamels_destructive_row_is_red_only_with_the_focus(self):
        # The pinned Enamel's rule: a plain row until focused (the Enamel 0.13.1 upgrade).
        design = (ROOT / "vendor" / "enamel" / "DESIGN.md").read_text(encoding="utf-8")
        self.assertIn("unfocused, a plain row of its kind", design)

    def test_the_hint_bar_still_says_quit(self):
        # The Home polish leaves the B Quit hint as it is.
        self.assertRegex(INDEX, r'data-role="back"[^>]*>Quit<')

    def test_start_sends_m_and_opens_the_menu(self):
        self.assertIn('const MENU_KEYS = new Set(["m", "M"]);', KEYBOARD_JS)
        self.assertIn("if (!busy && onMenu) onMenu();", KEYBOARD_JS)
        conf = (ROOT / "backend" / "mpv_input.conf").read_text(encoding="utf-8")
        self.assertRegex(conf, r"(?m)^m\s+ignore\s+# Start$")
        setup = (ROOT / "docs" / "device-setup.md").read_text(encoding="utf-8")
        self.assertIn("| Start | M |", setup)


if __name__ == "__main__":
    unittest.main()
