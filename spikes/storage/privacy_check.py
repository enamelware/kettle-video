# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Kettle spike (the storage spike): check the report and scripts hold no real names.

Read-only. Collects the private words on this device: each card's label,
the user name as it appears in paths, and the name of every film, show,
season and episode inside the folders the Question 3 rule suggests. Then
looks for any of them in the given files (the report, the spike scripts,
a draft issue comment). Prints only how many private words were checked
and, on a hit, which file and line, never the word itself.

    python3 spikes/storage/privacy_check.py FILE [FILE...] [--allow WORD]

--allow WORD: a private word the report must use anyway (on the Nova the
card's label is the device's name). It may appear on its own, but still
counts as private inside a path ("/WORD").
"""

import os
import sys
from pathlib import Path

import drives
import find_video_folders as finder

# The one checker lives in tools/ now (the privacy guard work); this spike keeps its own
# command line and plain matching on top of it.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "tools"))
import privacy_guard  # noqa: E402


def private_words():
    labels, titles = privacy_guard.card_words(
        drives.places(), finder.walk, finder.suggest,
        lambda word: bool(finder.SEASON_LIKE.match(word)))
    user = os.path.basename(os.path.expanduser("~"))
    words = {f"/home/{user}", f"/run/media/{user}"} | labels | titles
    return {w for w in words if w}


def split_args(args):
    """(files, allowed words) from the command line."""
    files, allowed = [], set()
    while args:
        arg = args.pop(0)
        if arg == "--allow" and args:
            allowed.add(args.pop(0))
        else:
            files.append(arg)
    return files, allowed


def main():
    files, allowed = split_args(sys.argv[1:])
    words = private_words()
    allowed = {w for w in words if w.casefold() in {a.casefold() for a in allowed}}
    words = (words - allowed) | {f"/{w}" for w in allowed}
    hits = 0
    for path in files:
        with open(path, encoding="utf-8", errors="replace") as f:
            for number, line in enumerate(f, 1):
                low = line.casefold()
                if any(w.casefold() in low for w in words):
                    hits += 1
                    print(f"PRIVATE NAME in {path}, line {number}")
    print(f"Checked {len(files)} files against {len(words)} private words: "
          f"{'clean' if not hits else f'{hits} lines to fix'}")
    sys.exit(1 if hits else 0)


if __name__ == "__main__":
    main()
