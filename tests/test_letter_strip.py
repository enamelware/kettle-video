# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The rules that keep the letter strip whole, without a browser (the letter strip fix).
tests/letter_strip_check.py drives them in a real Firefox."""

import re
import unittest
from pathlib import Path

UI = Path(__file__).resolve().parent.parent / "ui"
CSS = (UI / "css" / "defaults.css").read_text(encoding="utf-8")
TOKENS = (UI / "css" / "tokens.css").read_text(encoding="utf-8")
PAGE = (UI / "index.html").read_text(encoding="utf-8")


def rule(selector):
    match = re.search(r"(?m)^" + re.escape(selector) + r" \{(.*?)^\}", CSS, re.S)
    if not match:
        raise AssertionError(f"no rule for {selector}")
    return match.group(1)


class DrawnInFrontOfTheTabsTest(unittest.TestCase):
    """With Continue watching showing, the tab strip crosses the letters'
    column until it docks; that is what hid letters on first load."""

    def test_the_strip_is_not_stacked_below_the_tabs(self):
        level = lambda selector: int(re.search(r"z-index: (\d+);", rule(selector)).group(1))
        self.assertGreaterEqual(level(".letter-strip"), level(".tab-strip"))

    def test_the_strip_comes_after_the_tabs_in_the_page(self):
        self.assertLess(PAGE.index('id="tab-strip"'), PAGE.index('class="letter-strip"'))


class ReachableInAShortWindowTest(unittest.TestCase):
    def test_the_strip_scrolls_rather_than_cutting_letters_off(self):
        css = rule(".letter-strip")
        self.assertIn("overflow: hidden auto;", css)
        # Plain centring would push the first letters out of reach.
        self.assertIn("justify-content: safe center;", css)

    def test_a_strip_that_scrolls_still_never_takes_the_focus(self):
        self.assertRegex(PAGE, r'<nav class="letter-strip"[^>]*tabindex="-1"')

    def test_the_letters_never_shrink_below_a_readable_size(self):
        for name in ("--font-size-letter-strip", "--font-size-letter-strip-short"):
            with self.subTest(name=name):
                self.assertRegex(TOKENS, name + r":\s*min\(var\(--en-text-small\), max\(calc\(0\.7 \* var\(--en-text-small\)\),")


if __name__ == "__main__":
    unittest.main()
