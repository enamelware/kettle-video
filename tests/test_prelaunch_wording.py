# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Wording fixed in the pre-launch clean-up: the instructions and docs no
longer promise snippet authors stable hooks, no longer say the test devices
update themselves from main, and CLAUDE.md's screen list names Settings.

Run from the repo root:  python3 -m unittest tests.test_prelaunch_wording
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def instruction_files():
    """CLAUDE.md, README.md, docs/ (without dated decision entries), .claude/."""
    files = [ROOT / "CLAUDE.md", ROOT / "README.md"]
    files += sorted((ROOT / "docs").rglob("*.md"))
    files += sorted((ROOT / ".claude").rglob("*.md"))
    return [f for f in files if f.is_file()]


def text_of(path):
    text = path.read_text(encoding="utf-8")
    if path.name == "decisions.md":
        # Dated entries are history and are never edited.
        return ""
    return text


class SnippetHooksAreInternal(unittest.TestCase):

    def test_no_file_calls_the_hooks_a_public_api_to_keep_stable(self):
        promise = re.compile(r"public API[^.\n]*keep them stable"
                             r"|are a public API for snippets"
                             r"|used by snippets are a public API",
                             re.IGNORECASE)
        for path in instruction_files():
            with self.subTest(path=str(path.relative_to(ROOT))):
                self.assertIsNone(promise.search(text_of(path)))

    def test_spec_says_the_hooks_are_internal(self):
        spec = (ROOT / "docs" / "spec.md").read_text(encoding="utf-8")
        section = spec.split("## Theming hooks", 1)[1]
        self.assertIn("internal and may change", section)
        self.assertIn("not a public API", section)

    def test_no_rule_treats_a_hook_rename_as_breaking(self):
        rules = [ROOT / ".claude" / "agents" / "reviewer.md",
                 ROOT / ".claude" / "agents" / "refactor-scout.md",
                 ROOT / ".claude" / "commands" / "next.md"]
        for path in rules:
            with self.subTest(path=str(path.relative_to(ROOT))):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("No theming hook changes", text)
                self.assertNotIn("public API for snippets", text)
                self.assertNotIn("no class name or `data-` hook renamed, and no existing test", text)

    def test_decision_is_recorded(self):
        decisions = (ROOT / "docs" / "decisions.md").read_text(encoding="utf-8")
        self.assertRegex(decisions, r"## \d{4}-\d\d-\d\d — Snippet hooks are internal for now")


class DevicesUpdateByHand(unittest.TestCase):

    def test_no_instruction_says_devices_update_themselves_from_main(self):
        stale = re.compile(r"auto-update pulls `main`|because the devices update from it")
        for path in (ROOT / "CLAUDE.md", ROOT / ".claude" / "commands" / "next.md"):
            with self.subTest(path=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertIsNone(stale.search(text))
                self.assertIn("updated by hand from", text)

    def test_main_still_holds_only_finished_work(self):
        claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn("`main` only ever holds finished, tested work", claude)
        next_md = (ROOT / ".claude" / "commands" / "next.md").read_text(encoding="utf-8")
        self.assertIn("`main` only ever receives finished work", next_md)


class ScreensListNamesSettings(unittest.TestCase):

    def test_screens_section_mentions_settings(self):
        claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        section = claude.split("## Screens", 1)[1].split("\n## ", 1)[0]
        today = section.split("This is the target design", 1)[0]
        self.assertIn("Settings screen", today)


if __name__ == "__main__":
    unittest.main()
