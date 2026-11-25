# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The TV Shows tab marked as beta (the TV beta label), without a browser.

Following the designer's comment on the issue ("just use text"), the label
is plain text, "TV Shows (beta)", in the tab's own Enamel style: no badge,
no new class. Checks: the beta text is on the TV Shows tab only, joined to
its label by a non-breaking space; the tab's accessible name is
"TV shows, beta"; the Movies tab is exactly as before; the app sets no
style of its own for it; the README lists TV shows as beta. The tab on
screen, across window widths, is tests/tv_beta_check.py.

Run from the repo root:  python3 -m unittest tests.test_tv_beta -v
"""

import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")


class Tabs(HTMLParser):
    """Each [data-tab] element's attributes and its own text (not the count)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tabs = {}
        self._tab = None
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if self._tab is None and "data-tab" in attrs:
            self._tab = attrs["data-tab"]
            self.tabs[self._tab] = {"attrs": attrs, "text": ""}
            self._depth = 0
        elif self._tab is not None:
            self._depth += 1

    def handle_endtag(self, tag):
        if self._tab is None:
            return
        if self._depth == 0:
            self._tab = None
        else:
            self._depth -= 1

    def handle_data(self, data):
        if self._tab is not None and self._depth == 0:
            self.tabs[self._tab]["text"] += data


def tabs():
    parser = Tabs()
    parser.feed(INDEX)
    return parser.tabs


class TvBetaTest(unittest.TestCase):
    def test_beta_is_on_the_tv_tab_joined_to_its_label(self):
        tv = tabs()["tv"]
        self.assertEqual(tv["text"].strip(), "TV Shows (beta)")

    def test_accessible_name(self):
        self.assertEqual(tabs()["tv"]["attrs"].get("aria-label"), "TV shows, beta")

    def test_movies_tab_unchanged(self):
        movies = tabs()["movies"]
        self.assertEqual(movies["text"].strip(), "Movies")
        self.assertNotIn("aria-label", movies["attrs"])
        self.assertIn(
            '<div class="tab en-tab" role="tab" tabindex="-1" data-tab="movies" aria-selected="true">'
            'Movies <span class="tab-count en-tab__count" data-role="count"></span></div>', INDEX)

    def test_beta_only_on_the_tv_tab(self):
        self.assertEqual(len(re.findall(r"\(beta\)", INDEX, re.I)), 1)

    def test_no_style_of_its_own(self):
        """Plain text: no badge element and no class added for it."""
        line = next(l for l in INDEX.splitlines() if 'data-tab="tv"' in l)
        self.assertIn('class="tab en-tab"', line)
        self.assertNotIn("badge", line)
        self.assertEqual(line.count("<span"), 1)  # the count only

    def test_readme_lists_tv_shows_as_beta(self):
        self.assertIn("**TV shows are in beta**", README)
        self.assertIn('"TV Shows (beta)"', README)


if __name__ == "__main__":
    unittest.main()
