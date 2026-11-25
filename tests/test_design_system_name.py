# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta
"""No file uses the design system's old names (the Enamel rename).

The design system was renamed Enamel in its 0.7.0 (2026-10-27): every token,
class, data attribute, animation and script name moved from the "kt" prefix
to "en", and its main files took the new name (vendor/enamel/MIGRATION.md).
Every file git tracks is checked for the old names, except:
- vendor/, which holds unmodified copies that are never edited (Enamel's
  MIGRATION.md has to list every old name);
- this file, which has to spell the old names to look for them;
- the update script's one line naming the design system's old folder, which
  it falls back to on a device where the folder hasn't been renamed yet;
- entries in the decisions log dated on or before the rename day, other than
  the rename's own entry: they are history and keep the names they were
  written with.
"""

import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
THIS = "tests/test_design_system_name.py"
RENAMED_ON = "2026-10-27"
HISTORY = "docs/decisions.md"
THE_RENAME = "(the Enamel rename)"
FALLBACK = ("tools/update_enamel.py", 'Path.home() / "Development" / "kettle-ui",')
OLD = re.compile(
    r"kettle-ui|kettle_ui|KettleUI|kettle-components|tokens/kettle\.css|kettle_tokens"
    r"|--kt-|data-kt-|__kt[A-Z]|(?<![\w-])kt-[a-z]",
    re.I,
)
ENTRY = re.compile(r"(?m)^(?=## )")
DATE = re.compile(r"^## (\d{4}-\d{2}-\d{2})")


def tracked_files():
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
    return [name for name in out.decode().split("\0") if name]


def current_text(name, text):
    """The part of a file that describes things as they are now."""
    if name != HISTORY:
        return text
    kept = []
    for entry in ENTRY.split(text):
        date = DATE.match(entry)
        heading = entry.split("\n", 1)[0]
        if not (date and date.group(1) <= RENAMED_ON and THE_RENAME not in heading):
            kept.append(entry)
    return "".join(kept)


def hits(files):
    """files: (name, text) pairs. Returns 'name: line' for each old name."""
    found = []
    for name, text in files:
        for line in current_text(name, text).splitlines():
            if (name, line.strip()) == FALLBACK:
                continue
            if OLD.search(line):
                found.append(f"{name}: {line.strip()[:120]}")
    return found


def repo_files():
    for name in tracked_files():
        if name.startswith("vendor/") or name == THIS:
            continue
        path = ROOT / name
        if path.is_file():
            yield name, path.read_bytes().decode("utf-8", errors="replace")


class NoOldDesignSystemNames(unittest.TestCase):
    def test_no_file_uses_an_old_name(self):
        files = list(repo_files())
        self.assertGreater(len(files), 50, "git ls-files should list the repo")
        self.assertEqual(hits(files), [])

    def test_no_file_lives_under_an_old_name(self):
        old = [name for name in tracked_files() if OLD.search(name) or "kettle_ui" in name]
        self.assertEqual(old, [])

    def test_the_check_catches_what_it_should(self):
        for line in ("Read `vendor/kettle-ui/DESIGN.md`.", "color: var(--kt-accent);",
                     '<html data-kt-motion="reduce">', '<ul class="kt-rows">',
                     "window.KettleUI.picker.open(menu);", 'menu.addEventListener("kt-select", go);',
                     "el.__ktTurn = 1;", '<link href="tokens/kettle.css">',
                     "components/kettle-components.js", "from tools import update_kettle_ui"):
            with self.subTest(line=line):
                self.assertTrue(hits([("ui/index.html", line)]))
        decisions = ("## 2026-10-22 — Old entry\n\nkettle-ui 0.6.0 comes in.\n\n"
                     "## 2026-10-27 — Another entry that day\n\nthe kettle-ui folder.\n\n"
                     "## 2026-10-27 — The rename (the Enamel rename)\n\nStill says kettle-ui.\n\n"
                     "## 2026-10-28 — Later entry\n\nUses --kt-accent.\n")
        self.assertEqual(hits([(HISTORY, decisions)]),
                         [f"{HISTORY}: Still says kettle-ui.", f"{HISTORY}: Uses --kt-accent."])
        self.assertTrue(hits([("docs/spec.md", "## 2026-10-01 — Not history\n\nkettle-ui\n")]),
                        "dated headings only count in the decisions log")
        self.assertTrue(hits([("tools/update_enamel.py", 'DEFAULT = Path.home() / "kettle-ui"')]),
                        "only the update script's one fallback line is allowed")

    def test_new_names_and_app_names_pass(self):
        for line in ("color: var(--en-accent);", '<ul class="en-rows">', "window.EnamelUI.toast.show(t);",
                     '<html data-en-motion="reduce">', 'prefix="kettle-quit-"', ".kettle-logo { }",
                     "Kettle Video", "markt-place", "vendor/enamel/tokens/enamel.css"):
            with self.subTest(line=line):
                self.assertEqual(hits([("ui/index.html", line)]), [])
        self.assertEqual(hits([FALLBACK]), [])


if __name__ == "__main__":
    unittest.main()
