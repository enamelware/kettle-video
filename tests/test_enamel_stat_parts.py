# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Enamel 0.10.0 comes in, with its parts for the result screen (the Enamel 0.10.0 upgrade).

Checks: the vendored copy is at least 0.10.0 (the pin and the copies agreeing
is tests/test_enamel.py); its stylesheet and DESIGN.md hold the parts the first scan screen will
use (stat panel, stat pair, note) and the two component variables for their
sizes; the other documents name the vendored version. Versions are compared
as numbers, since as text 0.10.0 sorts before 0.9.0.

Run from the repo root:  python3 -m unittest tests.test_enamel_stat_parts -v
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor" / "enamel"

NEW_CLASSES = (
    "en-statpanel",
    "en-statpanel__counts",
    "en-statpanel__count",
    "en-statpanel__number",
    "en-statpanel__path",
    "en-statpanel__notset",
    "en-statpair",
    "en-note",
)
NEW_VARIABLES = ("--en-c-statpanel-min", "--en-c-note-gap")


def vendored_version():
    return (VENDOR / "VERSION").read_text(encoding="utf-8").strip()


def stylesheet():
    return (VENDOR / "components" / "enamel-components.css").read_text(encoding="utf-8")


class StatPartsTest(unittest.TestCase):
    def test_vendored_version_is_at_least_0_10_0(self):
        version = tuple(int(n) for n in vendored_version().split("."))
        self.assertGreaterEqual(version, (0, 10, 0))

    def test_the_new_classes_are_in_the_stylesheet(self):
        css = stylesheet()
        for name in NEW_CLASSES:
            with self.subTest(name=name):
                self.assertRegex(css, r"\." + re.escape(name) + r"(?![\w-])")

    def test_the_new_variables_are_declared(self):
        css = stylesheet()
        for name in NEW_VARIABLES:
            with self.subTest(name=name):
                self.assertRegex(css, re.escape(name) + r"\s*:")

    def test_design_md_describes_each_part(self):
        design = (VENDOR / "DESIGN.md").read_text(encoding="utf-8")
        for part in ("Stat panel", "Note"):
            with self.subTest(part=part):
                self.assertIn(f"### {part}", design)

    def test_the_documents_name_the_vendored_version(self):
        version = vendored_version()
        for document, wording in (
            ("CLAUDE.md", f"vendored at {version} since"),
            ("docs/spec.md", f"vendored at {version} since"),
            ("THIRD_PARTY_LICENSES.md", f"| Enamel | {version} |"),
        ):
            with self.subTest(document=document):
                self.assertIn(wording, (ROOT / document).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
