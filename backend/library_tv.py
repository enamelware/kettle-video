# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Group a TV Shows folder into shows, seasons and episodes. Pure logic, read-only.

A folder that directly holds videos, or holds season folders ("Season 2",
"S02", "Specials"), is a show; any other folder is only a container. Videos
loose in the root are grouped into shows by the title in their names.
Specials go last as season 0; files sharing an episode are kept and flagged
"duplicate". Rules and reasons: docs/spec.md ("TV grouping") and docs/decisions.md.

Try it:  python3 -m backend.library_tv "<path>" [--episodes]
"""

import os
import sys
import time
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Optional

from backend.library_movies import read_folder
from backend.parser import library_order, parse_name


@dataclass(frozen=True)
class Episode:
    numbers: list  # [3], [1, 2] for a multi-episode file, [] when unnumbered
    title: Optional[str]  # the episode title from the name, if any
    path: str  # relative to the root, with "/" separators
    flags: list = field(default_factory=list)

    @property
    def number(self) -> Optional[int]:
        return self.numbers[0] if self.numbers else None


@dataclass(frozen=True)
class Season:
    number: Optional[int]  # None: no season info (absolute numbering); 0: Specials
    episodes: list

    @property
    def label(self) -> str:
        if self.number is None:
            return "No season"
        return "Specials" if self.number == 0 else f"Season {self.number}"


@dataclass(frozen=True)
class Show:
    title: str
    year: Optional[int]
    seasons: list  # by number, then no season, then Specials (see docs/spec.md)
    path: str  # the show folder relative to the root, or "." for loose root files


@dataclass(frozen=True)
class TvScan:
    shows: list
    skipped: list


SPECIALS = 0
_SPECIALS_NAMES = {"specials", "special"}


def display(text: Optional[str]) -> Optional[str]:
    """Join decomposed accents (as macOS writes them) for display and sorting.
    Paths are never changed."""
    return unicodedata.normalize("NFC", text) if text else text


def _sort_key(text: str) -> str:
    return display(text).casefold()


def _season_folder(name: str, parse) -> Optional[int]:
    if name.strip().casefold() in _SPECIALS_NAMES:
        return SPECIALS
    parsed = parse(name, "episode")
    return parsed.season if "season-only" in parsed.flags else None


def _episode_key(episode: Episode):
    # Numbered first, in number order; unnumbered last; then by file name.
    name = os.path.basename(episode.path)
    return (episode.number is None, episode.number or 0, _sort_key(name), episode.path)


def _season_order(number: Optional[int]):
    # Normal seasons by number, then "no season", then Specials.
    if number == SPECIALS:
        return (2, 0)
    return (1, 0) if number is None else (0, number)


def _mark_duplicates(episodes: list) -> list:
    """Flag every file that shares an episode number with another one."""
    counts = Counter(n for e in episodes for n in set(e.numbers))
    marked = []
    for e in episodes:
        if any(counts[n] > 1 for n in e.numbers) and "duplicate" not in e.flags:
            e = Episode(e.numbers, e.title, e.path, e.flags + ["duplicate"])
        marked.append(e)
    return marked


def _build_show(folder_name: Optional[str], show_path: str, files: list, parse) -> Show:
    """`files` are (filename, relative path, season from its folder or None)."""
    parsed = [(parse(f, "episode"), p, folder_season) for f, p, folder_season in files]

    title, year = "", None
    if folder_name is not None:
        folder = parse(folder_name, "episode")
        if folder.title and not ({"fallback", "season-only"} & set(folder.flags)):
            title, year = display(folder.title), folder.year
    if not title:
        # Most common file title; ties go to the first in name order.
        titles = [display(r.title) for r, _, _ in parsed]
        common = Counter(t for t in titles if t).most_common(1)
        title = common[0][0] if common else ""
        years = Counter(r.year for (r, _, _), t in zip(parsed, titles) if t == title and r.year)
        year = years.most_common(1)[0][0] if years else None

    by_season = {}
    for result, rel_path, folder_season in parsed:
        flags = list(result.flags)
        season = result.season
        if folder_season == SPECIALS:
            # A Specials folder is an explicit choice, so it wins over the name.
            if season not in (None, SPECIALS):
                flags.append("season-mismatch")
            season = SPECIALS
        elif season is None:
            season = folder_season
        elif folder_season is not None and folder_season != season:
            flags.append("season-mismatch")
        if not result.episodes:
            flags.append("unnumbered")
        episode = Episode(list(result.episodes), display(result.episode_title), rel_path, flags)
        by_season.setdefault(season, []).append(episode)

    seasons = [
        Season(n, sorted(_mark_duplicates(by_season[n]), key=_episode_key))
        for n in sorted(by_season, key=_season_order)
    ]
    return Show(title, year, seasons, show_path)


def scan_tv(root: str, parse=None) -> TvScan:
    """Group every video under `root` into shows. Never raises for a bad folder.

    `parse` reads one name; the saved library (the quick rescan and Remove work) passes one that
    reuses saved results for unchanged files. It defaults to parse_name.
    """
    parse = parse or parse_name
    root_real = os.path.realpath(root)
    shows = []
    skipped = []
    seen = {root_real}

    def walk(path: str, rel: PurePosixPath):
        videos, subfolders = read_folder(path, rel, root_real, seen, skipped)
        is_root = rel == PurePosixPath(".")

        if is_root:
            # Loose files in the root: one show per parsed title.
            groups = {}
            for filename, rel_path in videos:
                key = _sort_key(parse(filename, "episode").title)
                groups.setdefault(key, []).append((filename, rel_path, None))
            shows.extend(_build_show(None, ".", files, parse) for files in groups.values())
            for sub_path, sub_rel in subfolders:
                walk(sub_path, sub_rel)
            return

        season_dirs = []
        other_dirs = []
        for sub_path, sub_rel in subfolders:
            number = _season_folder(sub_rel.name, parse)
            if number is None:
                other_dirs.append((sub_path, sub_rel))
            else:
                season_dirs.append((sub_path, sub_rel, number))

        if not videos and not season_dirs:
            for sub_path, sub_rel in other_dirs:
                walk(sub_path, sub_rel)
            return

        files = [(f, p, None) for f, p in videos]
        for season_path, season_rel, number in season_dirs:
            season_videos, inner = read_folder(season_path, season_rel, root_real, seen, skipped)
            files.extend((f, p, number) for f, p in season_videos)
            other_dirs.extend(inner)
        if files:
            shows.append(_build_show(rel.name, rel.as_posix(), files, parse))
        for sub_path, sub_rel in other_dirs:
            walk(sub_path, sub_rel)

    walk(root_real, PurePosixPath("."))
    shows.sort(key=lambda s: library_order(s.title, s.year))
    return TvScan(shows, skipped)


def _label(episode: Episode) -> str:
    if not episode.numbers:
        return "?"
    if len(episode.numbers) > 1:
        return f"{episode.numbers[0]}-{episode.numbers[-1]}"
    return str(episode.number)


def _summary(show: Show) -> str:
    specials = sum(len(s.episodes) for s in show.seasons if s.number == SPECIALS)
    episodes = [e for s in show.seasons if s.number != SPECIALS for e in s.episodes]
    unnumbered = sum(1 for e in episodes if not e.numbers)
    numbered = len(episodes) - unnumbered
    line = show.title or "(no title)"
    if show.year is not None:
        line += f" ({show.year})"
    parts = []
    season_count = sum(1 for s in show.seasons if s.number not in (None, SPECIALS))
    if season_count:
        parts.append(f"{season_count} season{'s' if season_count != 1 else ''}")
    parts.append(f"{numbered} episode{'s' if numbered != 1 else ''}")
    if unnumbered:
        parts.append(f"{unnumbered} unnumbered")
    if specials:
        parts.append(f"{specials} special{'s' if specials != 1 else ''}")
    every = [e for s in show.seasons for e in s.episodes]
    for flag in ("duplicate", "season-mismatch"):
        flagged = sum(1 for e in every if flag in e.flags)
        if flagged:
            parts.append(f"{flagged} {flag}")
    return f"{line} - {', '.join(parts)}"


def _main(argv: list) -> int:
    args = argv[1:]
    show_episodes = "--episodes" in args
    paths = [a for a in args if a != "--episodes"]
    if len(paths) != 1:
        print('Usage: python3 -m backend.library_tv "<path>" [--episodes]')
        return 2
    start = time.perf_counter()
    scan = scan_tv(paths[0])
    elapsed = time.perf_counter() - start

    for show in scan.shows:
        print(_summary(show))
        if not show_episodes:
            continue
        flat = all(s.number in (None, SPECIALS) for s in show.seasons)
        for season in show.seasons:
            if len(show.seasons) > 1 or season.number is not None:
                print("  Episodes" if flat and season.number is None else f"  {season.label}")
            for episode in season.episodes:
                name = episode.title or os.path.basename(episode.path)
                flags = [f for f in episode.flags if f in ("unnumbered", "season-mismatch", "duplicate")]
                note = f"  [{', '.join(flags)}]" if flags else ""
                print(f"    {_label(episode):>5}  {name}{note}")

    files = sum(len(s.episodes) for show in scan.shows for s in show.seasons)
    shows = len(scan.shows)
    print(f"\n{shows} show{'s' if shows != 1 else ''}, {files} files in {elapsed:.1f} s")
    if scan.skipped:
        print(f"Skipped {len(scan.skipped)}:")
        for item in scan.skipped:
            print(f"  {item.path}: {item.reason}")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
