# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta
"""The Enamelware handbook plugin and the short CLAUDE.md (the handbook work).

The plugin is recorded in the committed project settings, CLAUDE.md starts by
pointing to it, the rules taken out of CLAUDE.md live in the files they moved
to, and nothing points at a CLAUDE.md section that is gone.
Run: scripts/test.sh unit tests.test_handbook_plugin
"""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


class ThePlugin(unittest.TestCase):
    def setUp(self):
        self.settings = json.loads(read(".claude/settings.json"))

    def test_enabled_at_project_scope(self):
        self.assertIs(self.settings["enabledPlugins"].get("enamelware@enamelware"), True)

    def test_its_marketplace_is_the_public_handbook(self):
        source = self.settings["extraKnownMarketplaces"]["enamelware"]["source"]
        self.assertEqual(source, {"source": "github", "repo": "enamelware/handbook"})

    def test_nothing_of_it_is_vendored(self):
        self.assertFalse((ROOT / "vendor" / "handbook").exists())
        self.assertNotIn("handbook", read("THIRD_PARTY_LICENSES.md").lower())


class ClaudeMd(unittest.TestCase):
    def setUp(self):
        self.text = read("CLAUDE.md")

    def test_starts_with_the_handbook_line(self):
        first = self.text.split("\n\n")[1]
        self.assertIn("handbook plugin", first)
        self.assertIn("`enamelware@enamelware`", first)
        self.assertIn("only what is specific to Kettle Video", first)

    def test_stays_short(self):
        # About 2,500 tokens was the aim; it was about 31,500 characters before.
        self.assertLess(len(self.text), 12000)

    def test_shared_rules_are_not_repeated(self):
        for gone in ("### Sizes", "`size:S`: one small change", "Bundles of small issues",
                     "**Hard stops** (the only reasons to stop)", "**Time limit:**",
                     "No framework and no build step", "Must run on both x86 and ARM"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, self.text)


class MovedRules(unittest.TestCase):
    def test_roadmap_moved_to_the_spec(self):
        spec = read("docs/spec.md")
        roadmap = spec.split("\n## Roadmap\n", 1)[1].split("\n## ", 1)[0]
        for words in ("walking skeleton", "Target design", "Milestones", "Decky companion",
                      "emulated controller types", "`._` files"):
            with self.subTest(words=words):
                self.assertIn(words, roadmap)
        self.assertIn('See "Roadmap" below.', spec)

    def test_permission_rules_moved_to_the_dev_environment(self):
        dev = read("docs/dev-environment.md")
        self.assertIn("A new ask or deny rule must never catch a read-only command", dev)
        self.assertIn("`git rm` runs without asking for files git tracks inside this repo", dev)
        self.assertIn("**Release steps:**", dev)

    def test_next_holds_its_own_mechanics(self):
        next_md = read(".claude/commands/next.md")
        for words in ("`.claude/hooks/agent_guard.py` enforces", "never use the interactive question prompt",
                      "`enamelware:operations` skill (\"Sizes\")", "Never force-push",
                      "`main` only ever receives finished work"):
            with self.subTest(words=words):
                self.assertIn(words, next_md)
        self.assertIn("never use the interactive question prompt", read(".claude/commands/tidy.md"))

    def test_decision_is_recorded(self):
        self.assertRegex(read("docs/decisions.md"),
                         r"## \d{4}-\d\d-\d\d — The Enamelware handbook plugin, and a short CLAUDE.md")


class NoPointerToARemovedSection(unittest.TestCase):
    GONE = ("Decide, don't stall", "Sizes", "Testing", "Milestones", "Ways of working",
            "Target devices", "MVP", "Audience and distribution", "Architecture", "Window")
    SKIP = {"docs/decisions.md", "docs/audit-2026-10.md", "tests/test_handbook_plugin.py"}

    def files(self):
        for pattern in (".claude/**/*.md", "docs/**/*.md", "README.md", "scripts/*", "tests/*.py", "tools/*.py"):
            for path in sorted(ROOT.glob(pattern)):
                rel = path.relative_to(ROOT).as_posix()
                if path.is_file() and rel not in self.SKIP:
                    yield rel, path.read_text(encoding="utf-8")

    def test_every_pointer_names_a_section_that_exists(self):
        headings = set(re.findall(r"^## (.+)$", read("CLAUDE.md"), re.M))
        for name in self.GONE:
            self.assertNotIn(name, headings)
        pointer = re.compile(r"CLAUDE\.md[^\n]{0,40}?\"(" + "|".join(map(re.escape, self.GONE)) + r")\"")
        found = [f"{rel}: {m.group(1)}" for rel, text in self.files() for m in pointer.finditer(text)]
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
