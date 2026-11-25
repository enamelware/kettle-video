# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta
"""The app's own sizes follow Enamel's units and grid rule (the Enamel 0.8.0 upgrade, the Enamel 0.11.0 upgrade).

Since Enamel 0.11.0 (the Enamel 0.11.0 upgrade) each size answers one question: should it grow
when the user makes text bigger? Yes is rem, no is px (lines, corners,
shadows, room for a focus ring or a lift, side padding that would squeeze
text). Each is a multiple of 4 in its own unit: 0.25rem or 4px. Since 0.11.0
--en-root-size scales pixels too, through zoom, so px no longer escapes it.

This test fails if the app's own stylesheets (ui/css/) set a size in px that
isn't a multiple of 4 (hairlines of 1 or 2px aside), a size in rem that isn't
a multiple of 0.25, a size in another absolute unit (pt, pc, cm, mm, in, Q),
the root font size, or a fixed height outside the listed exceptions
(anything that holds text takes a minimum height, so wrapped text makes it
taller). Comments are ignored, so they may still name sizes. It also fails
if the app's styles, scripts or page set --en-root-size themselves. The
other exceptions (em and ratios, text sizes as formulas) are listed in
docs/spec.md, "Units and grid audit".

Run from the repo root:  python3 -m unittest tests.test_no_fixed_pixels -v
"""

import re
import unittest
from pathlib import Path

CSS_DIR = Path(__file__).resolve().parent.parent / "ui" / "css"

COMMENT = re.compile(r"/\*.*?\*/", re.S)
# A number with an absolute unit, not part of a longer word (so "1.5rem" or
# "max-height" never match). Q is the quarter-millimetre.
# CSS units ignore case, so "12PX" is as fixed as "12px".
ABSOLUTE = re.compile(r"(?<![\w.-])(-?\d*\.?\d+)(px|pt|pc|cm|mm|in|Q)\b", re.I)
HAIRLINE = {"1", "-1", "1.0", "2", "-2"}
REM = re.compile(r"(?<![\w.-])(-?\d*\.?\d+)rem\b", re.I)
# Nothing sets the root font size: the user's own text size is 1rem.
ROOT_FONT_SIZE = re.compile(r"(?:^|[},])\s*(?:html|:root)\s*\{[^}]*\bfont(?:-size)?\s*:", re.S)
# A fixed height (not min-height, max-height or line-height).
HEIGHT = re.compile(r"(?<![\w-])height\s*:\s*([^;}]+)")
# The only fixed heights the app sets, none on anything that holds text:
# the hidden heading's clip box and a picture filling its frame.
ALLOWED_HEIGHTS = {"1px", "100%"}
UI_DIR = CSS_DIR.parent
# Setting Enamel's root size: "--en-root-size:" in a stylesheet, or
# setProperty('--en-root-size', ...) in a script.
SETS_ROOT_SIZE = re.compile(r"--en-root-size\s*:|setProperty\(\s*['\"]--en-root-size")


def without_comments(css):
    return COMMENT.sub(lambda m: "\n" * m.group(0).count("\n"), css)


def off_grid_rems(css):
    """Every size in rem outside comments that isn't a multiple of 0.25rem,
    as (line, text)."""
    found = []
    for number, line in enumerate(without_comments(css).splitlines(), start=1):
        for match in REM.finditer(line):
            if (float(match.group(1)) * 4) % 1:
                found.append((number, match.group(0)))
    return found


def fixed_heights(css):
    """Every fixed height outside the allowed ones, as written."""
    return [value.strip() for value in HEIGHT.findall(without_comments(css))
            if value.strip() not in ALLOWED_HEIGHTS]


def fixed_sizes(css):
    """Every size in css outside comments that breaks the grid in px, or uses
    another absolute unit, as (line, text). Hairlines of 1 or 2px pass."""
    found = []
    for number, line in enumerate(without_comments(css).splitlines(), start=1):
        for match in ABSOLUTE.finditer(line):
            value, unit = match.groups()
            if unit.lower() == "px" and (value in HAIRLINE or not float(value) % 4):
                continue
            found.append((number, match.group(0)))
    return found


class FinderTest(unittest.TestCase):
    """The finder itself: what counts as a fixed size."""

    def test_finds_off_grid_pixels_and_other_absolute_units(self):
        css = ".a { width: 10px; margin: 0.5pt -3px; height: 2cm; padding: 6px; }"
        self.assertEqual([size for _, size in fixed_sizes(css)], ["10px", "0.5pt", "-3px", "2cm", "6px"])

    def test_pixels_on_the_grid_pass(self):
        css = ".a { box-shadow: inset 4px 0 0 red; gap: 12px; margin: -8px; padding: 0 24px; }"
        self.assertEqual(fixed_sizes(css), [])

    def test_hairlines_rem_tokens_and_comments_pass(self):
        css = (".a { width: 1px; height: 2px; padding: 1.5rem; gap: var(--en-space-gap);\n"
               "  min-width: 4.5em; max-height: 100vh; inset: 0; }\n"
               "/* 60px at the normal font size */\n"
               "@media (max-height: 24.25rem) { .b { top: 0; } }")
        self.assertEqual(fixed_sizes(css), [])

    def test_units_in_capitals_are_found(self):
        css = ".a { width: 13PX; height: 2Pt; border-top: 1PX solid; }"
        self.assertEqual([size for _, size in fixed_sizes(css)], ["13PX", "2Pt"])

    def test_rems_off_the_grid_are_found(self):
        css = ".a { width: 2.25rem; margin: 0.3rem -0.5rem; max-width: 40.1rem; }\n@media (max-height: 24.25rem) {}"
        self.assertEqual([size for _, size in off_grid_rems(css)], ["0.3rem", "40.1rem"])

    def test_root_font_size_is_found(self):
        for css in ("html { font-size: 62.5%; }", ":root {\n  color: red;\n  font-size: 20px;\n}",
                    "a {} html { font: 16px sans-serif; }"):
            with self.subTest(css=css):
                self.assertRegex(css, ROOT_FONT_SIZE)
        for css in ("html { scroll-padding-top: 0; }", "body { font-size: 1rem; }", ".x html-ish { font-size: 1rem; }"):
            with self.subTest(css=css):
                self.assertNotRegex(css, ROOT_FONT_SIZE)

    def test_fixed_heights_are_found(self):
        css = ".a { height: 3rem; min-height: 4rem; max-height: 2rem; line-height: 1; }\n.b { height: 1px; height: 100%; }"
        self.assertEqual(fixed_heights(css), ["3rem"])

    def test_reports_the_line(self):
        css = "/* one\n two */\n.a {\n  width: 21px;\n}"
        self.assertEqual(fixed_sizes(css), [(4, "21px")])


class AppStylesTest(unittest.TestCase):
    """The app's own stylesheets follow the units and grid rule."""

    def test_the_app_has_stylesheets(self):
        self.assertTrue(sorted(CSS_DIR.glob("*.css")), "no stylesheets found in ui/css/")

    def test_no_fixed_size_in_ui_css(self):
        for path in sorted(CSS_DIR.glob("*.css")):
            with self.subTest(file=path.name):
                found = fixed_sizes(path.read_text(encoding="utf-8"))
                self.assertEqual(found, [], f"{path.name} sets sizes off the 4px grid or in absolute units "
                                 f"(line, size): {found}; use rem, a multiple of 4px, or Enamel's tokens (the Enamel 0.11.0 upgrade)")

    def test_rems_are_on_the_grid(self):
        for path in sorted(CSS_DIR.glob("*.css")):
            with self.subTest(file=path.name):
                found = off_grid_rems(path.read_text(encoding="utf-8"))
                self.assertEqual(found, [], f"{path.name} sets sizes off the 0.25rem grid (line, size): {found} (the Enamel 0.11.0 upgrade)")

    def test_nothing_sets_the_root_font_size(self):
        for path in sorted(CSS_DIR.glob("*.css")):
            with self.subTest(file=path.name):
                self.assertNotRegex(without_comments(path.read_text(encoding="utf-8")), ROOT_FONT_SIZE,
                                    f"{path.name} sets the root font size; 1rem is the user's own text size (the Enamel 0.11.0 upgrade)")

    def test_no_fixed_height_on_text(self):
        for path in sorted(CSS_DIR.glob("*.css")):
            with self.subTest(file=path.name):
                found = fixed_heights(path.read_text(encoding="utf-8"))
                self.assertEqual(found, [], f"{path.name} sets fixed heights {found}; use min-height (the Enamel 0.11.0 upgrade)")


class RootSizeTest(unittest.TestCase):
    """The app leaves Enamel's one root size at its default (the Enamel 0.8.0 upgrade):
    setting it from the screen or the device would tie the layout to a
    screen size (CLAUDE.md). Reading it is fine; setting it is not."""

    def test_the_finder_spots_a_setting(self):
        for text in (":root { --en-root-size: 112.5%; }",
                     "document.documentElement.style.setProperty('--en-root-size', '90%');",
                     'el.style.setProperty( "--en-root-size", x);'):
            with self.subTest(text=text):
                self.assertRegex(text, SETS_ROOT_SIZE)
        self.assertNotRegex("font-size: var(--en-root-size);", SETS_ROOT_SIZE)

    def test_the_app_never_sets_the_root_size(self):
        files = [*sorted((UI_DIR / "css").glob("*.css")), *sorted((UI_DIR / "js").glob("*.js")),
                 UI_DIR / "index.html"]
        self.assertTrue(len(files) > 2)
        for path in files:
            with self.subTest(file=path.name):
                self.assertNotRegex(path.read_text(encoding="utf-8"), SETS_ROOT_SIZE,
                                    f"{path.name} sets --en-root-size; leave it at Enamel's default (the Enamel 0.8.0 upgrade)")


if __name__ == "__main__":
    unittest.main()
