# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Enamel 0.9.0 comes in, with its parts for onboarding (the Enamel 0.9.0 upgrade).

Checks: the vendored copy is at least 0.9.0 (the pin and the copies
agreeing is tests/test_enamel.py); its stylesheet and DESIGN.md hold the
five new parts the folder choice screens and the No videos found screen will use (step label, group band, badge,
message in a row, numbered steps); docs/spec.md names the vendored
version; the "(BETA)" tab label stays the app's own and doesn't move to
Enamel's badge in this issue.

Run from the repo root:  python3 -m unittest tests.test_enamel_onboarding_parts -v
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor" / "enamel"
UI = ROOT / "ui"

# The classes 0.9.0 adds, by the part DESIGN.md describes them under.
NEW_PARTS = {
    "Step label": ["en-steplabel"],
    "Group band": ["en-band", "en-band--outline", "en-band__name", "en-band__count"],
    "Badge": ["en-badge"],
    "Message in a row": ["en-row__message"],
    "Numbered steps": ["en-steps"],
}


def vendored_version():
    return (VENDOR / "VERSION").read_text().strip()


class OnboardingPartsTest(unittest.TestCase):
    def test_vendored_version_is_at_least_090(self):
        version = tuple(int(n) for n in vendored_version().split("."))
        self.assertGreaterEqual(version, (0, 9, 0))

    def test_the_new_classes_are_in_the_stylesheet(self):
        css = (VENDOR / "components" / "enamel-components.css").read_text()
        for part, classes in NEW_PARTS.items():
            for name in classes:
                with self.subTest(part=part, name=name):
                    self.assertRegex(css, r"\." + re.escape(name) + r"(?![\w-])")

    def test_design_md_describes_each_part(self):
        design = (VENDOR / "DESIGN.md").read_text()
        for part in NEW_PARTS:
            with self.subTest(part=part):
                self.assertIn(f"### {part}", design)

    def test_spec_names_the_vendored_version(self):
        spec = (ROOT / "docs" / "spec.md").read_text()
        self.assertIn(f"vendored at {vendored_version()} since", spec)

    def test_the_beta_tab_label_stays_as_it_is(self):
        # Moving "(beta)" (the TV beta label) to the badge is a visible change of its own.
        page = (UI / "index.html").read_text()
        tab = re.search(r'<div class="tab en-tab"[^>]*data-tab="tv".*?</div>', page, flags=re.S)
        self.assertIsNotNone(tab, "the TV Shows tab is missing from index.html")
        self.assertIn("TV Shows&nbsp;(beta)", tab.group(0))
        self.assertNotIn("en-badge", tab.group(0))


if __name__ == "__main__":
    unittest.main()
