# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Design system 3/4 (the third design system step): Continue watching, the Movies and TV Shows
lists, a show's episodes (and the Rescan row, the plain-list fallback, the
developer box and the letter strip) take their look from Enamel.

Checks: in the app's own styles for these parts, every colour, type size,
spacing and radius is a --en- token (layout widths and heights may be the
app's own); rows, lists and tiles carry Enamel's classes next to the
app's hooks; every row is an Enamel row (Scan my folders, the last
to keep the app's own look, became Enamel's button in the design system finish); the focused row and tile show Enamel's
focus look on the app's real focus; no Enamel accent is chosen.

Run from the repo root:  python3 -m unittest tests.test_design_system_lists -v
"""

import re
import unittest
from pathlib import Path

from tests.test_design_system_frame import STYLE_PROPS, leftover, rules

ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "ui"
APP_JS = (UI / "js" / "app.js").read_text(encoding="utf-8")
INDEX = (UI / "index.html").read_text(encoding="utf-8")

# Every rule for the parts in this issue, by selector.
LIST_SELECTORS = {
    "h2",
    "h3.group-heading",
    ".source",
    ".file-row.en-row",
    ".file-row.en-row:focus",
    ".file-row.en-row:focus .row-label",
    ".file-row.en-row:focus .row-year",
    ".file-row.en-row:focus .row-subtitle",
    ".file-row.en-row:focus .row-note",
    ".file-row.en-row:focus .row-path",
    ".parsed-row",
    ".row-line",
    ".row-label",
    ".row-subtitle",
    ".row-note",
    ".row-path",
    ".row-year",
    ".episode-view h2",
    '.episode-view [data-role="show-subtitle"]',
    '.parsed-row[data-status="missing"] .row-title',
    '.file-row.en-row:focus[data-status="missing"] .row-title',
    ".letter-strip",
    '.letter-strip-letter[aria-current="true"]',
    ".continue-watching",
    ".continue-heading",
    ".continue-row",
    ".continue-tile",
    ".continue-tile::after",
    ".continue-tile:focus::after",
    ".continue-frame",
    ".continue-surface-name",
    ".continue-progress",
    ".continue-missing",
    ".continue-caption",
    ".continue-tile:focus .continue-caption",
}

# Not --en- tokens, but allowed: layout sizes, and the letter strip's fitted
# size (capped at --en-text-small; a listed gap). The row's ring room is
# Enamel's own --en-c-shelf-room since the responsive layout work.
ALLOWED_VARS = {
    "--letter-strip-width",
    "--font-size-letter-strip",
    "--font-size-letter-strip-short",
}


def declarations(selector):
    found = {}
    for names, decls in rules():
        if selector in names:
            found.update({prop: value.strip() for prop, value in decls})
    return found


class TokensOnlyTest(unittest.TestCase):
    def test_every_rule_exists(self):
        found = {name for names, _ in rules() for name in names}
        self.assertEqual(LIST_SELECTORS - found, set(), "rules for these parts went missing")

    def test_list_and_tile_styles_use_only_enamel_tokens(self):
        checked = 0
        for names, decls in rules():
            for name in names:
                if name not in LIST_SELECTORS:
                    continue
                for prop, value in decls:
                    if not STYLE_PROPS.match(prop):
                        continue
                    checked += 1
                    with self.subTest(selector=name, prop=prop):
                        self.assertEqual(leftover(value, ALLOWED_VARS), [], f"{name} {{ {prop}: {value} }}")
        self.assertGreater(checked, 40)

    def test_aliases_point_at_enamel_tokens(self):
        tokens = (UI / "css" / "tokens.css").read_text(encoding="utf-8")
        # Since the responsive layout work the row uses Enamel's own shelf room and tile
        # sizes, so the app's copies are gone.
        for gone in ("--continue-ring-room", "--continue-tile-height", "--continue-small-tile-height"):
            self.assertNotIn(gone, tokens)
        self.assertRegex(tokens, r"--font-size-letter-strip:\s*min\(var\(--en-text-small\),")

    def test_no_old_tile_look_left(self):
        # The old Sage ring on the frame and the Mustard bar are gone; the
        # bar's look is Enamel's.
        names = {name for names, _ in rules() for name in names}
        self.assertNotIn(".continue-tile:focus .continue-frame", names)
        self.assertNotIn(".continue-progress-fill", names)
        css = (UI / "css" / "defaults.css").read_text(encoding="utf-8")
        self.assertNotIn("--color-progress", css)
        # The old ring went with the old look in the design system finish.
        self.assertNotIn("--own-look-", css)


class FocusLookTest(unittest.TestCase):
    def test_focused_row_lifts_without_a_ring(self):
        focus = declarations(".file-row.en-row:focus")
        self.assertEqual(focus.get("background-color"), "var(--en-surface-control)")
        self.assertEqual(focus.get("color"), "var(--en-text-strong)")
        self.assertEqual(focus.get("outline"), "none")
        self.assertNotIn("box-shadow", focus)

    def test_muted_lines_step_up_to_soft_on_the_focused_row(self):
        for part in (".row-label", ".row-year", ".row-subtitle", ".row-note", ".row-path"):
            self.assertEqual(declarations(f".file-row.en-row:focus {part}").get("color"), "var(--en-text-soft)", part)
            self.assertEqual(declarations(part).get("color"), "var(--en-text-muted)", part)

    def test_focused_tile_has_the_accent_ring_over_its_frame(self):
        ring = declarations(".continue-tile:focus::after")
        self.assertEqual(ring.get("outline"), "var(--en-focus-ring-width) solid var(--en-focus-ring)")
        self.assertEqual(ring.get("outline-offset"), "var(--en-focus-ring-offset)")
        box = declarations(".continue-tile::after")
        # The frame's box: the first line, 16:9, standing on the bottom edge.
        self.assertEqual((box.get("grid-row"), box.get("align-self"), box.get("aspect-ratio")), ("1", "end", "16 / 9"))
        self.assertEqual(declarations(".continue-caption").get("grid-row"), "2")


class KettleClassesTest(unittest.TestCase):
    def test_rows_and_lists_carry_enamel_classes(self):
        # Since the Home actions work Rescan and Remove are in Home's menu: no list of action rows.
        self.assertNotIn("rescan-list", INDEX)
        self.assertEqual(APP_JS.count('list.className = "file-list en-rows";'), 3)  # sections, episodes, fallback
        self.assertNotIn('list.className = "file-list";', APP_JS)
        self.assertIn('item.className = "file-row en-row";', APP_JS)  # plain-list fallback
        self.assertIn('"file-row parsed-row en-row"', APP_JS)
        for meta in ('"row-note en-row__meta"', '"row-subtitle en-row__meta"'):
            self.assertIn(meta, APP_JS)
        self.assertNotRegex(APP_JS, r'"row-(note|subtitle)"')

    def test_every_parsed_row_is_a_kettle_row(self):
        # Since the design system finish no row keeps the app's own look: every parsed row has
        # Enamel's class, and no rule styles rows without it.
        self.assertIn('item.className = "file-row parsed-row en-row";', APP_JS)
        self.assertNotIn("OWN_LOOK_KINDS", APP_JS)
        names = {name for names, _ in rules() for name in names}
        self.assertFalse([n for n in names if ":not(.en-row)" in n])

    def test_tiles_carry_enamel_classes(self):
        self.assertIn('class="continue-row en-shelf"', INDEX)
        for snippet in (
            '"continue-tile en-tile en-tile--large" : "continue-tile en-tile"',
            '"continue-frame en-tile__frame"',
            '"continue-progress en-progress en-progress--thin"',
            '"continue-progress-fill en-progress__fill"',
            '"continue-caption en-tile__title"',
        ):
            self.assertIn(snippet, APP_JS)
        # Enamel's bar reads --value; the documented --progress hook stays.
        self.assertIn('bar.style.setProperty("--value", `${share * 100}%`)', APP_JS)
        self.assertIn('.style.setProperty("--progress", String(share))', APP_JS)

    def test_default_accent(self):
        self.assertNotIn("data-en-accent", INDEX)
        self.assertNotIn("en-accent", APP_JS)


if __name__ == "__main__":
    unittest.main()
