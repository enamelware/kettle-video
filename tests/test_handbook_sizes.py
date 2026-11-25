# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta
"""The commands and agents follow the handbook's size rules (the size-rules work).

The S limits match the handbook's, Kettle Video's own triggers stay, the full
check on an L runs once (by the builder, just before merging, never by
test-checker), a series with an L gets the full check in its review, and the
commands point to the handbook's "Sizes" instead of CLAUDE.md.
Run: scripts/test.sh unit tests.test_handbook_sizes
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POINTER = "`enamelware:operations` skill (\"Sizes\")"


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def section(text, heading):
    return text.split(heading, 1)[1].split("\n## ", 1)[0]


def step(text, number):
    """One numbered step of next.md's "Steps", up to the next one."""
    steps = section(text, "\n## Steps\n")
    return re.split(r"\n(?=\d+\. \*\*)", steps)[number]


class WhereSizesAreDefined(unittest.TestCase):
    def test_commands_point_to_the_handbook(self):
        for rel in (".claude/commands/next.md", ".claude/commands/draft.md"):
            with self.subTest(rel=rel):
                text = read(rel)
                self.assertIn(POINTER, text)
                self.assertNotIn("Sizes are defined in CLAUDE.md", text)


class TheSLimits(unittest.TestCase):
    def setUp(self):
        size_and_path = section(read(".claude/commands/next.md"), "\n## Size and path\n")
        self.upgrades = size_and_path.split("**Upgrades, automatic.**", 1)[1].split("\n\n", 1)[0]

    def test_what_an_s_does_not_count(self):
        for left_out in ("the tests written for it", "`docs/decisions.md`", "`CHANGELOG.md`",
                         "`VERSION`", "regenerated files"):
            with self.subTest(left_out=left_out):
                self.assertIn(left_out, self.upgrades)

    def test_the_handbook_triggers(self):
        for trigger in ("a new screen, component or page", "a data format", "the settings format",
                        "design tokens", "launch", "the local server", "privacy", "licences"):
            with self.subTest(trigger=trigger):
                self.assertIn(trigger, self.upgrades)

    def test_kettle_videos_own_triggers_stay(self):
        for trigger in ("the data folder", "how it finds it", "`settings.json`", "`ui/css/tokens.css`",
                        "`launch.sh`", "`backend/server.py`", "`THIRD_PARTY_LICENSES.md`", "`vendor/`"):
            with self.subTest(trigger=trigger):
                self.assertIn(trigger, self.upgrades)

    def test_m_becomes_l_past_one_feature_or_screen(self):
        self.assertIn("An M becomes L if it grows past one feature or screen", self.upgrades)


class TheFullCheckRunsOnce(unittest.TestCase):
    def setUp(self):
        self.next_md = read(".claude/commands/next.md")
        self.test_checker = read(".claude/agents/test-checker.md")

    def test_test_checker_never_runs_it(self):
        description = self.test_checker.split("\n---\n", 1)[0]
        self.assertIn("never the full check", description)
        run = section(self.test_checker, "\n## Run\n")
        self.assertIn("Never run the full check (`scripts/test.sh full`), on any size.", run)
        # The only mention of the command is the line that forbids it.
        self.assertEqual(self.test_checker.count("scripts/test.sh full"), 1)

    def test_the_builder_runs_it_in_the_merge_step(self):
        merge = step(self.next_md, 9)
        self.assertIn("**Size L: the full check, once.**", merge)
        self.assertIn("`scripts/test.sh full`", merge)
        self.assertLess(merge.index("the full check, once"), merge.index("git merge --squash"))

    def test_a_failing_full_check_goes_back_to_the_agents(self):
        merge = step(self.next_md, 9)
        self.assertIn("If it fails, nothing is merged", merge)
        self.assertIn("go back to step 8", merge)
        self.assertIn("This counts as one of the 2 fix rounds", merge)
        batch = section(self.next_md, "\n## Batch mode")
        all_pass = batch.split("4. **All PASS**", 1)[1].split("\n5. ", 1)[0]
        self.assertIn("**If the full check fails on an L**", all_pass)
        self.assertIn("replies `READY FOR CHECKS: commit <short commit>, quick check exit code <code>`", all_pass)
        self.assertIn("counts as one of the 2 fix rounds", all_pass)

    def test_not_while_building(self):
        testing = step(self.next_md, 6)
        self.assertIn("don't run the full check here", testing)
        self.assertNotIn("scripts/test.sh full", testing)

    def test_no_checking_agent_runs_it(self):
        for rel in (".claude/agents/reviewer.md", ".claude/agents/test-checker.md"):
            with self.subTest(rel=rel):
                self.assertNotRegex(read(rel), r"(?<!Never )run[^.\n]*`scripts/test\.sh full`")

    def test_the_table_says_once_by_the_builder(self):
        table = section(self.next_md, "\n## Size and path\n")
        self.assertIn("`scripts/test.sh full` once, run by the builder in step 9", table)
        self.assertIn("(never by test-checker)", table)


class Series(unittest.TestCase):
    def setUp(self):
        self.series = read(".claude/commands/next.md").split("\n### Series\n", 1)[1].split("\n## ", 1)[0]

    def test_a_series_with_an_l_gets_the_full_check(self):
        self.assertIn("**A series that contains a `size:L` issue** also gets the full check", self.series)

    def test_fixes_go_straight_to_ready_for_dev(self):
        self.assertIn('`scripts/board.sh status F "Ready for dev"`', self.series)
        self.assertIn("(it goes straight there: it only fixes what", self.series)


class Recorded(unittest.TestCase):
    def test_decision_is_recorded(self):
        self.assertRegex(read("docs/decisions.md"),
                         r"## \d{4}-\d\d-\d\d — The commands and agents follow the handbook's sizes")


if __name__ == "__main__":
    unittest.main()
