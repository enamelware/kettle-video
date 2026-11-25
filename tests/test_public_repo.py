# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The app, its docs and the workflow point at the public repo (the public
repo work, and the go-public work for the workflow): the update check and
Update and restart use enamelware/kettle-video, the setup steps clone it, the
board settings and CLAUDE.md's repository line name it, and no file names the
private archive except where it has to: the release check's rules, the rename
checks' test data and decisions dated before the switch.

Run: scripts/test.sh unit tests.test_public_repo
"""

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from backend import app_update, update_check  # noqa: E402

PUBLIC = "enamelware/kettle-video"
# Built from parts, so this file doesn't name it either.
PRIVATE = "kettle-video" + "-private"

# Files allowed to name the private archive, and why.
ALLOWED = {
    "tools/release_check.py": "the release check recognises links into it",
    "tests/test_account_name.py": "test data for the account rename check",
    "tests/test_kettle_video_name.py": "test data for the Kettle Video rename check",
}
# Decisions entries dated before this day may name it, as history.
SWITCH_DAY = "2026-11-24"
_ENTRY = re.compile(r"^## (\d{4}-\d{2}-\d{2})\b")


def tracked_texts():
    names = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True,
                           check=True).stdout.decode("utf-8").split("\0")
    for name in filter(None, names):
        path = ROOT / name
        if name.startswith("vendor/") or not path.is_file():
            continue
        try:
            yield name, path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue


def newer_decision_lines(text):
    """Line numbers naming the archive in entries dated on or after the switch."""
    day, out = "", []
    for number, line in enumerate(text.splitlines(), 1):
        entry = _ENTRY.match(line)
        if entry:
            day = entry.group(1)
        if PRIVATE in line and day >= SWITCH_DAY:
            out.append(number)
    return out


class PointsAtThePublicRepo(unittest.TestCase):

    def test_the_update_check_asks_the_public_repo(self):
        self.assertEqual(update_check.REPO, PUBLIC)
        self.assertEqual(update_check.LATEST_URL,
                         f"https://api.github.com/repos/{PUBLIC}/releases/latest")

    def test_update_and_restart_downloads_from_the_public_repo(self):
        self.assertEqual(app_update.DOWNLOAD_BASE,
                         f"https://github.com/{PUBLIC}/releases/download/")

    def test_the_setup_steps_clone_the_public_repo(self):
        setup = (ROOT / "docs" / "device-setup.md").read_text(encoding="utf-8")
        self.assertIn(f"git clone https://github.com/{PUBLIC}.git kettle-video", setup)

    def test_the_workflow_acts_on_the_public_repo(self):
        board = json.loads((ROOT / ".claude" / "board.json").read_text(encoding="utf-8"))
        self.assertEqual(board["repo"], PUBLIC)
        claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn(f"The repository is `{PUBLIC}`;", claude)

    def test_no_file_names_the_private_archive_outside_the_allowed_places(self):
        found = []
        for name, text in tracked_texts():
            if name in ALLOWED or PRIVATE not in text:
                continue
            if name == "docs/decisions.md":
                found += [f"{name}, line {n}" for n in newer_decision_lines(text)]
                continue
            found.append(name)
        self.assertEqual(found, [])

    def test_a_new_decision_naming_the_archive_is_caught(self):
        text = (f"## 2026-11-01 — Old\n\nIt was {PRIVATE}.\n\n"
                f"## {SWITCH_DAY} — New\n\nStill {PRIVATE}.\n")
        self.assertEqual(newer_decision_lines(text), [7])


if __name__ == "__main__":
    unittest.main()
