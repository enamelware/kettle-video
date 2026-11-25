# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Kettle spike (the storage spike), Questions 2 and 3: which folders to suggest.

Python standard library only, read-only. Walks a place (a card, a drive or
the home folder) with the proposed rules and prints the folders onboarding
would suggest, with how many videos each holds. Folder names are replaced by
placeholders unless --real is given (on screen only, never in the report).

    python3 spikes/storage/find_video_folders.py PATH [--runs 3] [--real]
    python3 spikes/storage/find_video_folders.py PATH --no-skip   (walk Steam and
        emulator folders too, to measure what the Question 2 rule saves)
    python3 spikes/storage/find_video_folders.py --selftest

Question 2 rule (what not to walk into), see SKIP_* below. Question 3 rule
(which folder to suggest), see suggest() below.
"""

import os
import re
import sys
import tempfile
import time

from common import Redactor, is_video

MAX_DEPTH = 6               # levels below the place's root
MIN_VIDEO_BYTES = 20_000_000  # a folder whose videos are all smaller is clips, not a library

# Never walked into, compared ignoring case. Hidden folders (".anything")
# are skipped too, which already covers Steam's own install, Flatpak app
# data (~/.var) and caches in the home folder.
SKIP_NAMES = {
    "sample", "samples",                      # same junk the scanner ignores
    "lost+found",                             # filesystem repair folder
    "steamapps", "steamlibrary", "steam",     # Steam games and their data
    "compatdata", "shadercache",
    "emulation", "emudeck", "es-de", "retroarch", "roms",  # emulators, their
    "downloaded_media",                       # scraped video previews
    "applications", "homebrew",               # AppImages, Decky plugins
}
SEASON_LIKE = re.compile(r"^(season|series|staffel|saison|s)\s*\d+$|^specials?$|^extras?$"
                         r"|^(disc|disk|cd|dvd|part)\s*\d+$", re.IGNORECASE)


def skipped(name):
    return name.startswith(".") or name.casefold() in SKIP_NAMES


class Folder:
    __slots__ = ("path", "loose", "loose_big", "children", "total", "big")

    def __init__(self, path):
        self.path = path
        self.loose = 0          # videos directly inside
        self.loose_big = 0      # of those, at least MIN_VIDEO_BYTES
        self.children = []      # subfolders holding videos somewhere below
        self.total = 0          # videos in this folder and below
        self.big = 0            # of those, at least MIN_VIDEO_BYTES


def walk(root, depth=0):
    """Tree of folders that hold videos, honouring the skip rule and depth.
    Unreadable folders are counted, not fatal."""
    node = Folder(root)
    try:
        entries = list(os.scandir(root))
    except OSError:
        walk.unreadable += 1
        return node
    walk.folders += 1
    for entry in entries:
        try:
            if entry.is_dir(follow_symlinks=False):
                if depth < MAX_DEPTH and not skipped(entry.name):
                    child = walk(entry.path, depth + 1)
                    if child.total:
                        node.children.append(child)
            elif entry.is_file(follow_symlinks=False) and is_video(entry.name):
                node.loose += 1
                if entry.stat(follow_symlinks=False).st_size >= MIN_VIDEO_BYTES:
                    node.loose_big += 1
        except OSError:
            walk.unreadable += 1
    node.total = node.loose + sum(c.total for c in node.children)
    node.big = node.loose_big + sum(c.big for c in node.children)
    return node


walk.folders = 0
walk.unreadable = 0


def _is_collection(folder):
    """Holds at least two video-bearing subfolders that are titles, not
    seasons or discs of one title."""
    return sum(1 for c in folder.children
               if not SEASON_LIKE.match(os.path.basename(c.path))) >= 2


def _is_title(folder):
    """One film or one show: videos directly inside, or only seasons/discs."""
    return bool(folder.loose) or all(
        SEASON_LIKE.match(os.path.basename(c.path)) for c in folder.children)


def _collapse(folder):
    """Go down while there is only one way down, but never into a single
    film's or show's own folder (suggest "Films", not the one film in it)."""
    while (not folder.loose and len(folder.children) == 1
           and not _is_title(folder.children[0])):
        folder = folder.children[0]
    return folder


def _pick(folder, out):
    folder = _collapse(folder)
    if not folder.loose and sum(1 for c in folder.children if _is_collection(c)) >= 2:
        for child in folder.children:          # e.g. Media/Films + Media/TV
            _pick(child, out)
        return
    out.append(folder)


def suggest(root_node):
    """The Question 3 rule. Start from each top-level folder with videos;
    go down while there is only one way down; split a folder that holds two
    or more collections. Loose videos at the top level suggest the place
    itself. Folders whose videos are all small clips are dropped."""
    out = []
    if root_node.loose:
        out.append(root_node)                  # "the whole card"
    for child in root_node.children:
        _pick(child, out)
    return [f for f in out if f.big]


def run(root, runs, red):
    times = []
    for _ in range(runs):
        walk.folders = walk.unreadable = 0
        start = time.monotonic()
        tree = walk(root)
        picks = suggest(tree)
        times.append(time.monotonic() - start)
    print(f"Folders read: {walk.folders}, unreadable: {walk.unreadable}, "
          f"videos found: {tree.total}")
    for f in picks:
        rel = os.path.relpath(f.path, root)
        shown = "(the place itself)" if rel == "." else "/".join(
            red.name("folder", part) for part in rel.split(os.sep))
        print(f"  suggest {shown:<28} {f.total} videos, depth {0 if rel == '.' else rel.count(os.sep) + 1}")
    print("Runs (s): " + ", ".join(f"{t:.3f}" for t in times))


SELFTEST = {  # invented names: layout -> folders expected to be suggested
    "card-tidy": (["Films/Alpha (2001)/Alpha.mkv", "Films/Beta/Beta.mp4",
                   "TV/Gamma/Season 1/e01.mkv", "TV/Gamma/Season 2/e01.mkv",
                   "TV/Delta/e01.mkv", "TV/Delta/e02.mkv",
                   "Films/Beta/Sample/beta-sample.mkv", "Films/._Alpha.mkv"],
                  {"Films", "TV"}),
    "card-nested": (["Media/Films/A/a.mkv", "Media/Films/B/b.mkv",
                     "Media/TV/C/Season 1/e1.mkv", "Media/TV/D/e1.mkv"],
                    {"Media/Films", "Media/TV"}),
    "loose-top": (["a.mkv", "b.mkv", "Films/C/c.mkv"], {".", "Films"}),
    "one-chain": (["Stuff/Video/Films/A/a.mkv", "Stuff/Video/Films/B/b.mkv"],
                  {"Stuff/Video/Films"}),
    "one-show": (["Shows/E/Season 1/e1.mkv", "Shows/E/Season 2/e1.mkv"], {"Shows"}),
    "one-film": (["Films/F/f.mkv"], {"Films"}),
    "skips": (["steamapps/common/G/intro.webm", "Emulation/tools/downloaded_media/x/videos/v.mp4",
               ".hidden/a.mkv", "Films/A/a.mkv"], {"Films"}),
}


def selftest():
    failures = 0
    with tempfile.TemporaryDirectory() as tmp:
        for name, (files, expected) in SELFTEST.items():
            root = os.path.join(tmp, name)
            for rel in files:
                path = os.path.join(root, rel)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as f:     # sparse: big size, no disk used
                    f.truncate(MIN_VIDEO_BYTES)
            got = {os.path.relpath(f.path, root) for f in suggest(walk(root))}
            ok = got == expected
            failures += not ok
            print(f"{'ok  ' if ok else 'FAIL'} {name}: {sorted(got)}"
                  + ("" if ok else f" (expected {sorted(expected)})"))
        clips = os.path.join(tmp, "clips")
        os.makedirs(os.path.join(clips, "Previews"))
        open(os.path.join(clips, "Previews", "p.mp4"), "wb").close()
        got = suggest(walk(clips))
        failures += bool(got)
        print(f"{'ok  ' if not got else 'FAIL'} clips-only: {len(got)} suggested")
    return failures


def main():
    if "--no-skip" in sys.argv:
        SKIP_NAMES.intersection_update({"sample", "samples"})
    if "--selftest" in sys.argv:
        sys.exit(1 if selftest() else 0)
    args = sys.argv[1:]
    runs = 3
    if "--runs" in args:
        at = args.index("--runs")
        runs = int(args[at + 1])
        del args[at:at + 2]
    paths = [a for a in args if not a.startswith("--")]
    if not paths:
        sys.exit(__doc__)
    red = Redactor()
    for root in paths:
        print(red.path(root, [os.path.basename(root)]))
        run(root, runs, red)


if __name__ == "__main__":
    main()
