# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Three-digit anime numbers on the real library, and the parser timing (the three-digit episode fix).
Not part of the unit tests: it reads the real TV folder from settings.json
(read-only: names only, no file is opened, moved or changed) and takes a
minute or two.

It reads the real TV folder twice: once as the app does now, and once with
the three-digit episode fix step (`_absolute_numbers`) switched off, which is how the app
read names before. Then:

  changes   every show whose seasons or episode numbers differ is listed; a
            difference is only accepted for a file whose name has a bare
            three-digit number after a dash ("Show - 112")
  timing    the same names are read with and without the step, several
            rounds; the step may not make reading names noticeably slower

Run from the repo root:  python3 tests/absolute_numbers_check.py
"""

import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from backend import parser  # noqa: E402
from backend.library_tv import scan_tv  # noqa: E402
from backend.settings import load_settings  # noqa: E402

ROUNDS = 3
MAX_NAMES = 300  # enough for a stable timing, short enough to run quickly
MAX_SLOWDOWN = 1.15  # the step may add at most 15 % to reading a name


def without_step(stem, matches):
    return matches


def layout(scan):
    """{show path: (title, [(season, [(file, numbers), ...]), ...])}"""
    return {
        show.path + "|" + show.title: [
            (s.number, sorted((e.path, tuple(e.numbers)) for e in s.episodes)) for s in show.seasons
        ]
        for show in scan.shows
    }


def where(lay):
    """{file path: (season, numbers)}"""
    return {path: (season, numbers) for seasons in lay.values()
            for season, files in seasons for path, numbers in files}


def scan_both(tv_path):
    real_step = parser._absolute_numbers
    try:
        parser._absolute_numbers = without_step
        before = scan_tv(tv_path)
    finally:
        parser._absolute_numbers = real_step
    after = scan_tv(tv_path)
    return before, after


def timing(names):
    real_step = parser._absolute_numbers
    best = {"before": float("inf"), "after": float("inf")}
    try:
        for _ in range(ROUNDS):
            for label, step in (("before", without_step), ("after", real_step)):
                parser._absolute_numbers = step
                start = time.perf_counter()
                for name in names:
                    parser.parse_name(name, "episode")
                best[label] = min(best[label], (time.perf_counter() - start) / len(names))
    finally:
        parser._absolute_numbers = real_step
    return best


def main():
    results = []

    def check(text, ok, detail=None):
        results.append((text if ok or detail is None else f"{text}: {json.dumps(detail, default=str)}", ok))

    settings = load_settings()
    tv_path = settings["tv_path"]
    fixture_names = [c["name"] for c in json.loads(
        (REPO / "tests/fixtures/names.json").read_text())["cases"] if c["kind"] == "episode"]

    if not os.path.isdir(tv_path):
        check(f"the real TV folder is there ({tv_path})", False)
        real_names = []
    else:
        before, after = scan_both(tv_path)
        lay_before, lay_after = layout(before), layout(after)
        check(f"real library: {len(after.shows)} shows read", bool(after.shows))
        check("real library: the same shows before and after",
              sorted(lay_before) == sorted(lay_after),
              {"only before": sorted(set(lay_before) - set(lay_after)),
               "only after": sorted(set(lay_after) - set(lay_before))})
        files_before, files_after = where(lay_before), where(lay_after)
        moved = sorted(p for p in set(files_before) | set(files_after)
                       if files_before.get(p) != files_after.get(p))
        for p in moved:
            print(f"changed: {p}: {files_before.get(p)} -> {files_after.get(p)}")
        unexplained = [p for p in moved
                       if not parser._DASH_NUMBER.search(parser._strip_extension(os.path.basename(p)))]
        check(f"real library: {len(moved)} file(s) changed season or episode, "
              "all of them \"- NNN\" names", not unexplained, unexplained)
        changed_shows = sorted(k for k in lay_after if lay_before.get(k) != lay_after[k])
        for show in changed_shows:
            print(f"changed show: {show}")
        real_names = sorted(files_after)[:MAX_NAMES]
        real_names = [os.path.basename(p) for p in real_names]

    names = fixture_names + real_names
    best = timing(names)
    ratio = best["after"] / best["before"]
    check(f"timing: {best['before'] * 1000:.2f} ms per name before, {best['after'] * 1000:.2f} ms after "
          f"({len(names)} names, best of {ROUNDS}); at most {MAX_SLOWDOWN:.2f}x",
          ratio <= MAX_SLOWDOWN, {"ratio": round(ratio, 3)})

    for text, ok in results:
        print(f"{'ok  ' if ok else 'FAIL'} {text}")
    failures = sum(not ok for _, ok in results)
    print("all good" if not failures else f"{failures} problem(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
