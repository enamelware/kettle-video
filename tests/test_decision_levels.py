# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta
"""Decisions follow the handbook's three levels (the decision levels work).

Only "decide and flag" gets the "Decided:" comment and the decided label; a
spec read two ways that would look different to the user is a hard stop, not
a decision; CLAUDE.md, next.md and the reviewer say the same and point to the
handbook's decisions skill.
Run: scripts/test.sh unit tests.test_decision_levels
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POINTER = "`enamelware:decisions`, \"Three levels\""
COMMENT = "Decided: <what>. Why: <one line>. To change it, reply on this issue."
TWO_WAYS = "a spec that can be read two ways when the readings would look different to the user"


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def section(text, heading):
    return text.split(heading, 1)[1].split("\n## ", 1)[0]


class ClaudeMd(unittest.TestCase):
    def setUp(self):
        how = section(read("CLAUDE.md"), "\n## How we work\n")
        self.line = next(line for line in how.splitlines() if line.startswith("- Decisions follow"))

    def test_points_to_the_three_levels(self):
        self.assertIn(POINTER, self.line)

    def test_keeps_the_comment_and_the_label_for_decide_and_flag_only(self):
        self.assertIn("For \"decide and flag\" only", self.line)
        self.assertIn(COMMENT, self.line)
        self.assertIn("the `decided` label", self.line)

    def test_no_longer_flags_every_decision(self):
        text = read("CLAUDE.md")
        for old in ("**Decide yourself**", "If two options seem equal", "review all of these together"):
            with self.subTest(old=old):
                self.assertNotIn(old, text)


class NextMd(unittest.TestCase):
    def setUp(self):
        self.next_md = read(".claude/commands/next.md")
        self.decide = section(self.next_md, "\n## Decide or block\n")

    def test_points_to_the_three_levels(self):
        self.assertIn(POINTER, self.decide)

    def test_a_plain_decision_gets_no_comment_or_label(self):
        self.assertIn("- **Decide:** just decide.", self.decide)
        self.assertIn("No comment, no label.", self.decide)

    def test_only_decide_and_flag_comments_and_labels(self):
        flag = self.decide.split("- **Decide and flag**", 1)[1].split("\n\n", 1)[0]
        self.assertIn(COMMENT, flag)
        self.assertIn("`scripts/board.sh label N add decided`", flag)
        before = self.decide.split("- **Decide and flag**", 1)[0]
        self.assertNotIn("Decided: <what>", before)
        self.assertNotIn("label N add decided", before)

    def test_a_two_way_spec_that_looks_different_is_a_hard_stop(self):
        stops = self.decide.split("**Hard stops**", 1)[1].split("\n\n", 1)[0]
        self.assertIn(TWO_WAYS, stops)
        self.assertIn("decided only when the readings look the same to the user", self.decide)
        self.assertNotIn("An unclear spec", self.decide)

    def test_the_question_has_numbered_options_and_a_recommendation(self):
        self.assertIn("one plain-language question in the issue with numbered options and a recommendation",
                      self.decide)
        blocked = section(self.next_md, "\n## Blocked\n")
        self.assertIn("at most 3 numbered options, your recommendation", blocked)

    def test_builder_prompt_and_reports_say_the_same(self):
        self.assertIn("decide at the handbook's three levels (only a \"decide and flag\" choice gets the "
                      "\"Decided: ...\" comment and the decided label)", self.next_md)
        self.assertNotIn("decide what a git revert can undo and you would recommend (comment", self.next_md)
        self.assertIn("one line per \"decide and flag\" decision made this round", self.next_md)
        self.assertIn("one line per \"decide and flag\" decision made on your behalf", self.next_md)


class Reviewer(unittest.TestCase):
    def test_reviewer_says_the_same(self):
        reviewer = read(".claude/agents/reviewer.md")
        self.assertIn(TWO_WAYS, reviewer)
        self.assertIn("decides at the handbook's three levels", reviewer)
        self.assertIn("Only \"decide and flag\" choices get a \"Decided:\" comment.", reviewer)
        self.assertNotIn("(an ambiguous spec,", reviewer)


class Recorded(unittest.TestCase):
    def test_decision_is_recorded(self):
        self.assertRegex(read("docs/decisions.md"),
                         r"## \d{4}-\d\d-\d\d — Decisions follow the handbook's three levels")


if __name__ == "__main__":
    unittest.main()
