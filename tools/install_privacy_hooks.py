# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Put the privacy guard (the privacy guard work) in front of every commit and push.

Run from anywhere:  python3 tools/install_privacy_hooks.py

Writes three small git hooks into this clone's own hooks folder (git keeps
them untracked; this script is the tracked part):

- pre-commit checks what is about to be committed;
- commit-msg checks the commit message;
- pre-push checks every commit the push would send.

Each one runs tools/privacy_guard.py and stops the commit or push if it
finds anything, or if the private word list is missing. A hook that is
already there and wasn't written by this script is left alone and
reported, so nothing of anyone else's is overwritten. Running it again is
safe: it rewrites only its own hooks.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

MARK = "# Written by tools/install_privacy_hooks.py (the privacy guard work)."
HOOKS = {
    "pre-commit": 'python3 tools/privacy_guard.py staged',
    "commit-msg": 'python3 tools/privacy_guard.py message "$1"',
    "pre-push": 'python3 tools/privacy_guard.py push',
}


def hook_text(command):
    # Hooks run from the top of the work tree, where tools/ is.
    return f"#!/bin/sh\n{MARK}\n# Never bypass it with --no-verify.\nexec {command}\n"


def install(repo=None):
    """{hook name: "written" | "unchanged" | "kept (not ours)"}."""
    folder = subprocess.run(["git", "rev-parse", "--git-path", "hooks"], cwd=repo,
                            capture_output=True, text=True, check=True).stdout.strip()
    folder = Path(repo or ".") / folder if not os.path.isabs(folder) else Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    done = {}
    for name, command in HOOKS.items():
        path, text = folder / name, hook_text(command)
        old = path.read_text(encoding="utf-8", errors="replace") if path.exists() else None
        if old is not None and MARK not in old:
            done[name] = "kept (not ours)"
            continue
        if old == text:
            done[name] = "unchanged"
        else:
            path.write_text(text, encoding="utf-8")
            done[name] = "written"
        path.chmod(0o755)
    return done


def main():
    done = install()
    for name, what in done.items():
        print(f"{name}: {what}")
    if "kept (not ours)" in done.values():
        print("Some hooks were already there and were left alone: the privacy guard "
              "doesn't run for those until they call tools/privacy_guard.py.")
        return 1
    print("The privacy guard now checks every commit and push in this clone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
