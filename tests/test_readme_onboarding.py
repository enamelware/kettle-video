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
    # Since the first public release's README (the v1.0.0 release work) the
    # first launch is described under Installing, and nothing is listed as
    # not built: the README describes only what ships.
    def test_nothing_is_listed_as_not_built(self):
        text = README.read_text(encoding="utf-8")
        self.assertNotIn("Not built yet", text)
        self.assertNotIn("rest of onboarding", text.lower())

    def test_installing_describes_the_onboarding_steps(self):
        first = section("Installing").split("On the first launch", 1)
        self.assertEqual(len(first), 2, "Installing doesn't describe the first launch")
        steps = first[1].lower()
        for step in ("checks for mpv", "asks for your movies and tv shows folders", "reads them"):
            self.assertIn(step, steps)

    def test_mpv_missing_mentions_look_again_and_quitting(self):
        requirements = section("Requirements")
        self.assertIn("mpv — not bundled", requirements)
        mpv_line = requirements.split("mpv — not bundled", 1)[1]
        self.assertIn("`q`", mpv_line)
        self.assertIn("Look again", mpv_line)
        self.assertIn("first launch", mpv_line)


if __name__ == "__main__":
    unittest.main()
