# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta
"""The commands and agents follow the handbook's size rules (the size-rules work).

The S limits are the handbook's, pointed to rather than repeated (the
handbook 1.1.0 work), Kettle Video's own files behind them are listed in
CLAUDE.md, the full check on an L runs once (by the builder, just before
merging, never by test-checker), a series with an L gets the full check in its
review, and the commands point to the handbook's "Sizes" instead of CLAUDE.md.
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
    """Handbook 1.1.0 holds the S limits; CLAUDE.md lists Kettle Video's files
    behind them (the handbook asks each repo for that list); next.md points to
    both instead of repeating them (the handbook 1.1.0 work)."""

    def setUp(self):
        size_and_path = section(read(".claude/commands/next.md"), "\n## Size and path\n")
        self.upgrades = size_and_path.split("**Upgrades, automatic.**", 1)[1].split("\n\n", 1)[0]
        self.files_line = next(line for line in section(read("CLAUDE.md"), "\n## How we work\n").splitlines()
                               if line.startswith("- Files behind the handbook's size limits"))

    def test_next_points_to_the_handbook_and_the_list(self):
        self.assertIn("the handbook's limits (`enamelware:operations`, \"Sizes\")", self.upgrades)
        self.assertIn("listed in CLAUDE.md (\"How we work\")", self.upgrades)

    def test_the_handbook_limits_are_not_repeated(self):
        for copy in ("An S becomes M if it touches more than about 3 files", "In Kettle Video those are",
                     "`ui/css/tokens.css`", "Sizes only go up"):
            with self.subTest(copy=copy):
                self.assertNotIn(copy, self.upgrades)

    def test_kettle_videos_files_are_listed_once_in_claude_md(self):
        self.assertIn("`enamelware:operations`, \"Sizes\"", self.files_line)
        for trigger in ("the data folder", "how it finds it", "`settings.json`", "`ui/css/tokens.css`",
                        "`launch.sh`", "`backend/server.py`", "privacy", "`LICENSE`",
                        "`THIRD_PARTY_LICENSES.md`", "`vendor/`"):
            with self.subTest(trigger=trigger):
                self.assertIn(trigger, self.files_line)
        for rel in (".claude/commands/next.md", ".claude/commands/draft.md"):
            with self.subTest(rel=rel):
                self.assertNotIn("(anything the app saves there, or how it finds it)", read(rel))

    def test_draft_points_to_the_list(self):
        self.assertIn("files behind its limits listed in CLAUDE.md (\"How we work\")",
                      read(".claude/commands/draft.md"))
        self.assertNotIn("upgrade triggers in `.claude/commands/next.md`", read(".claude/commands/draft.md"))

    def test_m_becomes_l_past_one_feature_or_screen(self):
        self.assertIn("An M becomes L if it grows past one feature or screen", self.upgrades)


class RulesNextActsOn(unittest.TestCase):
    """Three of handbook 1.1.0's new rules stay in next.md, short, because
    /next needs them in front of it to act."""

    def setUp(self):
        self.next_md = read(".claude/commands/next.md")

    def test_the_size_is_checked_again_before_the_checks(self):
        self.assertIn("While building (steps 5 to 7, and again before step 8), compare the change with the size",
                      self.next_md)

    def test_no_bundled_issue_waits_outside_the_bundle(self):
        self.assertIn("not waiting on an unbuilt dependency outside the bundle", self.next_md)

    def test_a_series_gets_a_second_follow_up(self):
        self.assertIn("**Still FAIL after two follow-ups:** handle the last follow-up as **Blocked**",
                      self.next_md)


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

    def test_handbook_1_1_0_decision_is_recorded(self):
        self.assertRegex(read("docs/decisions.md"),
                         r"## \d{4}-\d\d-\d\d — The size rules point to handbook 1\.1\.0")


if __name__ == "__main__":
    unittest.main()
