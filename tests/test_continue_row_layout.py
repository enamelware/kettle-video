# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The Continue watching row stands its tiles on one shared bottom edge
(the tile alignment work). The browser check (continue_row_layout_check.py) measures it;
these quick tests keep the stylesheet rules that make it so."""

import unittest
from pathlib import Path

from tests.test_design_system_frame import rules


def declarations(selector):
    found = {}
    for names, decls in rules():
        if selector in names:
            found.update({prop: value.strip() for prop, value in decls})
    return found


class BottomAlignedRow(unittest.TestCase):
    def test_row_is_a_two_line_grid_of_tiles_side_by_side(self):
        row = declarations(".continue-row")
        self.assertEqual(row.get("display"), "grid")
        self.assertEqual(row.get("grid-auto-flow"), "column")
        self.assertEqual(row.get("grid-template-rows"), "auto auto")
        # Still scrolls sideways. Enamel's shelf pads it with room for the
        # focus ring all round (the responsive layout work); the app only lines the tiles up.
        self.assertEqual(row.get("overflow-x"), "auto")
        self.assertNotIn("padding", row)
        self.assertEqual(row.get("margin"), "calc(-1 * var(--en-c-shelf-room))")

    def test_each_tile_shares_the_rows_two_lines(self):
        tile = declarations(".continue-tile")
        self.assertEqual(tile.get("grid-row"), "span 2")
        self.assertEqual(tile.get("display"), "grid")
        self.assertEqual(tile.get("grid-template-rows"), "subgrid")

    def test_frames_sit_on_the_bottom_line_and_captions_start_below_it(self):
        self.assertEqual(declarations(".continue-frame").get("align-self"), "end")
        self.assertEqual(declarations(".continue-caption").get("align-self"), "start")

    def test_tiles_take_enamels_widths(self):
        # Since the responsive layout work the app sets no tile width: Enamel's .en-tile and
        # .en-tile--large take theirs from the row, a size container.
        self.assertNotIn("width", declarations(".continue-tile"))
        self.assertEqual(declarations('.continue-tile[data-size="large"]'), {})


class SpecSentence(unittest.TestCase):
    def test_spec_continue_watching_layout_describes_the_shared_bottom_edge(self):
        spec = (Path(__file__).resolve().parent.parent / "docs" / "spec.md").read_text(encoding="utf-8")
        layout = [line for line in spec.splitlines() if line.startswith("**Layout:** the carousel")]
        self.assertEqual(len(layout), 1)
        self.assertIn("one shared bottom edge", layout[0])
        self.assertIn("the tile alignment work", layout[0])


if __name__ == "__main__":
    unittest.main()
