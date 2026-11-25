# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Idle work is paused (the idle-work pause): /next all stops with its summary
and never runs /tidy; /tidy runs refactor-scout on Sonnet, or on Opus with
"/tidy deep".

Run: python3 -m unittest tests.test_idle_work_paused
"""

import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


class IdleWorkPausedTest(unittest.TestCase):
    def test_next_all_never_runs_idle_work(self):
        text = read(".claude", "commands", "next.md")
        self.assertIn("**Idle work is paused.**", text)
        self.assertIn("it never runs test-writer or refactor-scout", text)
        self.assertNotIn("follow `.claude/commands/tidy.md` from its step 0", text)
        self.assertNotIn("after idle work", text)
        self.assertNotIn("- **Idle work** (`/next all` only)", text)

    def test_tidy_picks_the_scout_model(self):
        text = read(".claude", "commands", "tidy.md")
        self.assertIn('argument-hint: "[deep]"', text)
        self.assertIn("$ARGUMENTS", text)
        self.assertIn("Set the Agent tool's `model` to `sonnet`", text)
        self.assertIn('only when the argument is `deep` ("/tidy deep"), set it to `opus` instead', text)

    def test_both_agents_kept(self):
        for name in ("test-writer", "refactor-scout"):
            self.assertTrue(os.path.isfile(os.path.join(ROOT, ".claude", "agents", name + ".md")), name)

    def test_claude_md_says_so(self):
        self.assertIn("**Idle work is paused: it runs only when I start `/tidy`", read("CLAUDE.md"))


if __name__ == "__main__":
    unittest.main()
