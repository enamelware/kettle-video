# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The README matches the built onboarding (the November 12 tidy-up, improvement 1): the
"Current limitations" paragraph no longer lists onboarding as not built and
says the first launch walks through it (mpv check, choosing the folders, the
first scan), and the Requirements' mpv entry mentions Look again on the first
launch as well as pressing q to quit.

Run from the repo root:  python3 -m unittest tests.test_readme_onboarding -v
"""

import re
import unittest
from pathlib import Path

README = Path(__file__).resolve().parent.parent / "README.md"


def section(title):
    text = README.read_text(encoding="utf-8")
    start = text.index(f"\n## {title}")
    rest = text[start + 1:]
    end = re.search(r"\n## (?!#)", rest)
    return " ".join((rest[: end.start()] if end else rest).split())


class ReadmeOnboardingTest(unittest.TestCase):
    def test_limitations_no_longer_list_onboarding_as_not_built(self):
        limits = section("Current limitations")
        not_built = limits.split("Not built yet:", 1)
        self.assertEqual(len(not_built), 2, "the 'Not built yet:' list is missing")
        missing_list = not_built[1].split(". ", 1)[0]
        self.assertNotIn("onboarding", missing_list.lower())
        self.assertNotIn("rest of onboarding", limits.lower())

    def test_limitations_describe_the_onboarding_steps(self):
        limits = section("Current limitations").lower()
        self.assertIn("onboarding", limits)
        for step in ("mpv", "choose", "scan"):
            self.assertIn(step, limits)

    def test_mpv_missing_mentions_look_again_and_quitting(self):
        requirements = section("Requirements")
        self.assertIn("mpv — not bundled", requirements)
        mpv_line = requirements.split("mpv — not bundled", 1)[1]
        self.assertIn("`q`", mpv_line)
        self.assertIn("Look again", mpv_line)
        self.assertIn("first launch", mpv_line)


if __name__ == "__main__":
    unittest.main()
