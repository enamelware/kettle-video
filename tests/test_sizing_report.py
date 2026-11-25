# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The sizing report (the sizing spike and the second sizing spike): docs/sizing-report.md has what the
issues ask for, and nothing that could identify the library.

The second pass (the second sizing spike) has one table per group with the Deck, the Nova, the
baseline rounded up to multiples of 4 (text not rounded) and Enamel's value,
and its sizes are added to the baseline table.

It holds one table per device (Steam's size, Kettle Video's and the ratio),
the split between Enamel's sizes and scaling, the reference measuring point
(said to be a measuring point, not a layout target) and a baseline rounded
up to multiples of 4. It holds no capture (no image), no file path and no
video file name: numbers and plain words only.

Run from the repo root:  python3 -m unittest tests.test_sizing_report -v
"""

import re
import unittest
from pathlib import Path

REPORT = Path(__file__).resolve().parent.parent / "docs" / "sizing-report.md"


def section(text, heading):
    parts = re.split(r"(?m)^## ", text)
    found = [p for p in parts if p.splitlines()[0].strip() == heading]
    if len(found) != 1:
        raise AssertionError(f"one section {heading!r}, found {len(found)}")
    return found[0]


def table_rows(text):
    return [[c.strip() for c in line.strip().strip("|").split("|")]
            for line in text.splitlines() if line.startswith("|") and not line.startswith("|---")][1:]


def subsection_table(text, heading):
    """The header cells and the rows of the table under '### heading'."""
    parts = re.split(r"(?m)^### ", text)
    found = [p for p in parts if p.splitlines()[0].strip() == heading]
    if len(found) != 1:
        raise AssertionError(f"one subsection {heading!r}, found {len(found)}")
    lines = [line for line in found[0].splitlines() if line.startswith("|") and not line.startswith("|---")]
    if not lines:
        raise AssertionError(f"no table under {heading!r}")
    header = [c.strip() for c in lines[0].strip().strip("|").split("|")]
    return header, table_rows(found[0])


def subsection_header(text, heading):
    return subsection_table(text, heading)[0]


class SizingReport(unittest.TestCase):
    TEXT = REPORT.read_text(encoding="utf-8")

    def test_one_table_per_device_with_steam_kettle_and_ratio(self):
        for device in ("Steam Deck", "Nova"):
            with self.subTest(device=device):
                body = section(self.TEXT, device)
                self.assertIn("| What | Steam | Kettle Video | Steam ÷ Kettle |", body)
                names = [row[0] for row in table_rows(body)]
                for what in ("List row height", "Text height, a row's main text", "Button height",
                             "Hint bar height", "Tile width", "Side gutter"):
                    self.assertIn(what, names)

    def test_split_and_reference(self):
        split = section(self.TEXT, "Where the difference comes from")
        self.assertIn("Enamel's sizes, the same on every device", split)
        self.assertIn("Scaling, different per device", split)
        reference = section(self.TEXT, "Recommended reference")
        self.assertIn("only a measuring point", reference)
        self.assertIn("It is not a size the layout is built for", reference)

    def test_baseline_rounded_up_to_multiples_of_4_except_text(self):
        rows = table_rows(section(self.TEXT, "Steam's sizes as Enamel's new baseline"))
        self.assertGreaterEqual(len(rows), 8)
        for what, steam, _ in rows:
            size = int(re.match(r"(?:about )?(\d+)", steam).group(1))
            if what.lower().endswith("text") or "label" in what.lower():
                continue
            with self.subTest(what=what):
                self.assertEqual(size % 4, 0, steam)

    def test_second_pass_has_a_table_per_group(self):
        """The second sizing spike: padding, gaps, side menu, landscape tiles and text."""
        body = section(self.TEXT, "Second pass")
        for group in ("Padding", "Gaps", "Side menu", "Landscape tiles", "Text"):
            with self.subTest(group=group):
                header = subsection_header(body, group)
                for column in ("Deck", "Nova", "Baseline", "Enamel 0.7.0"):
                    self.assertTrue(any(cell.startswith(column) for cell in header), column)
                if group != "Side menu":
                    self.assertIn("Steam ÷ Kettle Video", header)

    def test_second_pass_baseline_rounded_up_to_multiples_of_4_except_text(self):
        body = section(self.TEXT, "Second pass")
        for group in ("Padding", "Gaps", "Side menu", "Landscape tiles"):
            header, rows = subsection_table(body, group)
            column = header.index("Baseline")
            for row in rows:
                with self.subTest(group=group, what=row[0]):
                    for size in re.findall(r"\d+", row[column]):
                        self.assertEqual(int(size) % 4, 0, row[column])

    def test_second_pass_every_nova_value_measured_or_explained(self):
        """Every Nova cell holds a number or says why it can't be measured."""
        body = section(self.TEXT, "Second pass")
        for group in ("Padding", "Gaps", "Side menu", "Landscape tiles", "Text"):
            header, rows = subsection_table(body, group)
            column = header.index("Nova")
            for row in rows:
                with self.subTest(group=group, what=row[0]):
                    self.assertRegex(row[column], r"\d|not measurable")

    def test_second_pass_rows_in_the_baseline_table(self):
        names = [row[0] for row in table_rows(section(self.TEXT, "Steam's sizes as Enamel's new baseline"))]
        for what in ("Text inset, list row", "Text inset, picker row", "Side padding, button",
                     "Side padding, tab", "Gap between list rows", "Gap between an icon and its text",
                     "Gap between hints", "Side menu item, minimum height", "Side menu focus bar, width",
                     "Side menu, width", "Tile width, landscape tile on a shelf", "Gap between tiles",
                     "Page title text", "Section heading text", "Small text", "Row description text"):
            self.assertIn(what, names)

    def test_numbers_and_words_only(self):
        self.assertNotRegex(self.TEXT, r"!\[|<img|\.(?:jpe?g|png|webp)\b", "no capture in the report")
        self.assertNotRegex(self.TEXT, r"/(?:home|run/media|media|mnt)/", "no folder path")
        self.assertNotRegex(self.TEXT, r"\.(?:mkv|mp4|avi|m4v|webm)\b", "no video file name")


if __name__ == "__main__":
    unittest.main()
