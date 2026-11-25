# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta
"""No file names the GitHub account's old name (the account rename).

The account was renamed from steamostools to enamelware on 2026-10-27.
GitHub forwards the old addresses only until someone else takes the name, so
nothing in the repo may rely on it. Every file git tracks is checked, except:
- vendor/, which holds unmodified third-party copies that are never edited;
- this file, which has to spell the old name to look for it;
- entries in the decisions log or a changelog dated on or before the rename
  day: they are history and keep the name they were written with.
"""

import json
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OLD_NAME = "steamostools"
RENAMED_ON = "2026-10-27"
HISTORY = {"docs/decisions.md", "CHANGELOG.md", "docs/changelog.md"}
ENTRY = re.compile(r"(?m)^(?=#{2,3} )")
DATE = re.compile(r"^#{2,3} (?:\[?v?[\w.]*\]?\s*[—-]?\s*)?(\d{4}-\d{2}-\d{2})")


def tracked_files():
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
    return [name for name in out.decode().split("\0") if name]


def current_text(name, text):
    """The part of a file that describes things as they are now."""
    if name not in HISTORY:
        return text
    kept = []
    for entry in ENTRY.split(text):
        date = DATE.match(entry)
        if not (date and date.group(1) <= RENAMED_ON):
            kept.append(entry)
    return "".join(kept)


def hits(files):
    """files: (name, text) pairs. Returns 'name: line' for each mention."""
    found = []
    for name, text in files:
        for line in current_text(name, text).splitlines():
            if OLD_NAME in line.lower():
                found.append(f"{name}: {line.strip()[:120]}")
    return found


def repo_files():
    for name in tracked_files():
        if name.startswith("vendor/") or name == "tests/test_account_name.py":
            continue
        path = ROOT / name
        if path.is_file():
            yield name, path.read_bytes().decode("utf-8", errors="replace")


class NoOldAccountName(unittest.TestCase):
    def test_no_file_names_the_old_account(self):
        files = list(repo_files())
        self.assertGreater(len(files), 50, "git ls-files should list the repo")
        self.assertEqual(hits(files), [])

    def test_the_check_catches_what_it_should(self):
        self.assertTrue(hits([("README.md", "git clone git@github.com:SteamOSTools/kettle-video-private.git")]))
        self.assertTrue(hits([("scripts/board.sh", 'OWNER="steamostools"')]))
        self.assertTrue(hits([("ui/favicon.png", "\x89PNGsteamostools")]))
        decisions = ("## 2026-10-01 — Old entry\n\nPushed to steamostools/kettle-video-private.\n\n"
                     "## 2026-10-27 — The rename\n\nFrom steamostools to enamelware.\n\n"
                     "## 2026-10-28 — Later entry\n\nStill uses steamostools.\n")
        self.assertEqual(hits([("docs/decisions.md", decisions)]),
                         ["docs/decisions.md: Still uses steamostools."])
        self.assertFalse(hits([("CHANGELOG.md", "## [0.1] - 2026-10-20\n\n- Moved from steamostools.\n")]))
        self.assertTrue(hits([("docs/spec.md", "## 2026-10-01 — Not history\n\nsteamostools\n")]),
                        "dated headings only count in the decisions log or a changelog")
        self.assertFalse(hits([("README.md", "Clone git@github.com:enamelware/kettle-video-private.git")]))

    def test_board_settings_name_the_new_account(self):
        board = json.loads((ROOT / ".claude" / "board.json").read_text(encoding="utf-8"))
        self.assertEqual(board["owner"], "enamelware")
        self.assertEqual(board["repo"], "enamelware/kettle-video")
        self.assertEqual(board["projectUrl"], "https://github.com/" + "users/enamelware/projects/1")


if __name__ == "__main__":
    unittest.main()
