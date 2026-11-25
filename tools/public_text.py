# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The public-text check: what CLAUDE.md's "Public writing" rules out, in
every file that would be published. It joins the release check
(tools/release_check.py, PUBLIC_TEXT_CHECKS) and follows Enamel's own
public-text check (its tools/release_check.py, read with scripts/peek.sh),
adapted to Kettle Video.

It finds:
- an issue number of the private repo (a hash and a number, such as the
  one this work was filed under). The public repo starts its numbering
  again, so a file names the work it means in words instead ("the
  onboarding work"). The workflow's placeholders (#N, #M) are letters, not
  numbers. CSS colours and link fragments are not issue numbers; a number
  after a slash in ordinary text is;
- the person running the project named by role (the role word after "the"
  or "project's", with "'s", or before "feedback", "decision" and the like), in
  every file but the instructions to Claude Code (CLAUDE.md and .claude/),
  which keep their wording: public text says "the designer";
- a claude.ai link (a private chat, document or design canvas);
- a link to the private planning board, except its own address in the
  board settings (.claude/board.json), which scripts/board.sh reads.

Third-party files (vendor/, ui/fonts/) are left out, as in the release
check. Some patterns would match their own text, so they are built from
parts. Standard library only.

    python3 tools/public_text.py        every published file; exit 1 on findings
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
THIRD_PARTY = ("vendor/", "ui/fonts/")
BINARY = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".ttf", ".otf", ".woff", ".woff2")

ISSUE_NUMBER = "an issue number of the private repo"
OWNER_WORDING = "the " + "own" + "er named by role"
CLAUDE_LINK = "a claude.ai link"
BOARD_LINK = "a link to the private planning board"

# A hash, then one to four digits, not part of a word, an HTML entity (&#39;)
# or a formatted value ({x}#3).
ISSUE = re.compile(r"(?<![\w&#}\]])#(\d{1,4})\b(?!\w)")
# A CSS colour: three or four digits after a colon or "solid", ending the
# value, as in a colour or border rule. One or two digits after a colon (a
# "Needs:" line) are always an issue number.
COLOUR_BEFORE = re.compile(r"(?::|\bsolid)\s*$")
COLOUR_AFTER = re.compile(r"\s*[;\"'),}]")
# A link: the run of text before the hash holds "://" (https://example.org/#12).
LINK_BEFORE = re.compile(r"\S*://\S*/$")
OWNER = re.compile(r"\bthe\s+" + "own" + r"er\b|\b" + "own" + r"er['’]s\b|\bproject['’]s\s+" + "own" + r"er\b"
                   r"|\b" + "own" + r"er\s+(?:feedback|decisions?|choices?|answers?|approval|instructions?|wording"
                   r"|testing|options?|yes)\b|\(" + "own" + r"er:\s*[\"“]", re.I)
CLAUDE = re.compile(r"\bclaude\.ai/", re.I)
BOARD = re.compile(r"github\.com/(?:users|orgs)/[\w-]+/projects\b", re.I)

# Files that speak to Claude Code: their wording is the workflow's own and
# changes only in an issue about the workflow.
INSTRUCTIONS = ("CLAUDE.md", ".claude/")
# The board settings hold the board's own address, which the board script reads.
BOARD_SETTINGS = ".claude/board.json"
BOARD_ADDRESS = re.compile(r'\s*"projectUrl":\s*"https://github\.com/users/[\w-]+/projects/\d+",?\s*')


def issue_number(line: str) -> bool:
    """True if the line names an issue by number (colours and links aside)."""
    for m in ISSUE.finditer(line):
        before, after = line[:m.start()], line[m.end():]
        if LINK_BEFORE.search(before):
            continue
        if len(m.group(1)) >= 3 and COLOUR_BEFORE.search(before) and COLOUR_AFTER.match(after):
            continue
        return True
    return False


def findings(path: str, text: str) -> list[tuple[int, str]]:
    """[(line number, kind)] for one file's text."""
    if path.startswith(THIRD_PARTY):
        return []
    instructions = path == INSTRUCTIONS[0] or path.startswith(INSTRUCTIONS[1])
    out = []
    for number, line in enumerate(text.splitlines(), 1):
        if issue_number(line):
            out.append((number, ISSUE_NUMBER))
        if not instructions and OWNER.search(line):
            out.append((number, OWNER_WORDING))
        if CLAUDE.search(line):
            out.append((number, CLAUDE_LINK))
        if BOARD.search(line) and not (path == BOARD_SETTINGS and BOARD_ADDRESS.fullmatch(line)):
            out.append((number, BOARD_LINK))
    return out


def published_files(root: Path = ROOT) -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True).stdout
    return [p for p in out.splitlines() if p and (root / p).is_file()]


def repo_findings(root: Path = ROOT) -> list[str]:
    """Every finding in the tracked files, as 'path, line N: kind'."""
    found = []
    for path in published_files(root):
        if path.lower().endswith(BINARY):
            continue
        try:
            text = (root / path).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        found += [f"{path}, line {n}: {kind}" for n, kind in findings(path, text)]
    return found


def main() -> int:
    found = repo_findings()
    for line in found:
        print(f"PUBLIC TEXT: {line}")
    if found:
        print(f"Public text: {len(found)} findings. Write them as CLAUDE.md \"Public writing\" says.")
        return 1
    print("Public text: nothing private.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
