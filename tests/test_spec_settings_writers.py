# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The spec names both things that write settings.json (the November 14 tidy-up,
improvement 1): the "Settings mistakes give one plain sentence" paragraph no
longer says onboarding is the only writer, and names onboarding (both
folders) and the Settings screen (one kind's folder, the Settings screen work), agreeing with the
spec's opening Scope paragraph.

Run from the repo root:  python3 -m unittest tests.test_spec_settings_writers -v
"""

import unittest
from pathlib import Path

SPEC = Path(__file__).resolve().parent.parent / "docs" / "spec.md"


def paragraph(starts_with):
    for block in SPEC.read_text(encoding="utf-8").split("\n\n"):
        if block.strip().startswith(starts_with):
            return " ".join(block.split())
    raise AssertionError(f"no paragraph starting with {starts_with!r} in the spec")


class SpecSettingsWritersTest(unittest.TestCase):
    def test_spec_never_says_onboarding_is_the_only_writer(self):
        text = " ".join(SPEC.read_text(encoding="utf-8").split()).lower()
        self.assertNotIn("only thing that writes", text)

    def test_settings_mistakes_paragraph_names_both_writers(self):
        para = paragraph("**Settings mistakes give one plain sentence**")
        self.assertIn("settings.json", para)
        lower = para.lower()
        self.assertIn("onboarding", lower)
        self.assertIn("both folders", lower)
        self.assertIn("settings screen", lower)
        self.assertIn("one kind's folder", lower)
        self.assertIn("the Settings screen work", para)

    def test_scope_paragraph_names_the_same_two_writers(self):
        scope = paragraph("The walking skeleton").lower()
        self.assertIn("two cases only", scope)
        self.assertIn("onboarding", scope)
        self.assertIn("settings screen saves one kind's folder", scope)


if __name__ == "__main__":
    unittest.main()
