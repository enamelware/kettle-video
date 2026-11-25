# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Group a Movies folder into movies. Pure logic, read-only.

A folder that directly holds video files is a movie, or holds several
movies; a folder with no videos of its own is only a container. Rules and
reasons: docs/spec.md ("Movie grouping") and docs/decisions.md.

Try it:  python3 -m backend.library_movies "<path>"
"""

import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Optional

from backend.parser import library_order, parse_name
from backend.scanner import VIDEO_EXTENSIONS

# Clear part markers only: "Part 2", "pt2", "CD2", "Disc 2", or " - 01" at
# the end. A bare number ("Example Movie 2") is a sequel, not a part.
_PART_WORD = re.compile(r"(?:^|[\s._-])(?:part|pt|cd|disc|disk)[\s._-]*(\d{1,2})(?!\d)", re.IGNORECASE)
_PART_DASH = re.compile(r"\s-\s(\d{1,2})$")
_TRAILING_TAGS = re.compile(r"(?:\s*[\[(][^\])]*[\])])+\s*$")
_PART_IN_TITLE = re.compile(
    r"(?:[\s._-]+(?:part|pt|cd|disc|disk)[\s._-]*\d{1,2}|\s-\s\d{1,2})$", re.IGNORECASE
)


@dataclass(frozen=True)
class Part:
    label: Optional[str]  # "Part 1", or None for a single-file movie
    path: str  # relative to the root, with "/" separators


@dataclass(frozen=True)
class Movie:
    title: str
    year: Optional[int]
    parts: list
    flags: list = field(default_factory=list)


@dataclass(frozen=True)
class Skipped:
    path: str
    reason: str


@dataclass(frozen=True)
class MovieScan:
    movies: list
    skipped: list


def _is_video(name: str) -> bool:
    return os.path.splitext(name)[1].lower() in VIDEO_EXTENSIONS


def _inside(path: str, root: str) -> bool:
    return os.path.commonpath([path, root]) == root


def _part_number(filename: str) -> Optional[int]:
    stem = os.path.splitext(filename)[0]
    match = _PART_WORD.search(stem) or _PART_DASH.search(_TRAILING_TAGS.sub("", stem))
    return int(match.group(1)) if match else None


def _single(parsed, rel_path: str) -> Movie:
    return Movie(parsed.title, parsed.year, [Part(None, rel_path)], list(parsed.flags))


def _group_folder(folder_name: Optional[str], videos: list, parse) -> list:
    """Turn the videos of one folder into movies.

    `videos` are (filename, relative path) pairs. `folder_name` is None for
    the root, whose loose files always use their own names.
    """
    if len(videos) == 1:
        (filename, rel_path), = videos
        return [_named_after_folder(folder_name, filename, [Part(None, rel_path)], parse)]

    parsed = [(parse(f, "movie"), f, p, _part_number(f)) for f, p in videos]

    groups = {}
    loose = []
    for result, filename, rel_path, part in parsed:
        if part is None:
            loose.append(_single(result, rel_path))
            continue
        key = (_PART_IN_TITLE.sub("", result.title).casefold(), result.year)
        groups.setdefault(key, []).append((part, filename, rel_path, result))

    movies = loose
    for members in groups.values():
        if len(members) == 1:
            _, _, rel_path, result = members[0]
            movies.append(_single(result, rel_path))
            continue
        members.sort(key=lambda m: (m[0], m[1].casefold()))
        first = members[0][3]
        parts = [Part(f"Part {number}", rel_path) for number, _, rel_path, _ in members]
        movies.append(Movie(first.title, first.year, parts, list(first.flags)))

    if len(movies) == 1 and folder_name is not None:
        # One movie in its own folder: the folder name wins.
        only = movies[0]
        first_file = os.path.basename(only.parts[0].path)
        return [_named_after_folder(folder_name, first_file, only.parts, parse)]
    return movies


def _named_after_folder(folder_name: Optional[str], filename: str, parts: list, parse) -> Movie:
    if folder_name is not None:
        folder = parse(folder_name, "movie")
        if folder.title and "fallback" not in folder.flags:
            year = folder.year
            if year is None:
                year = parse(filename, "movie").year
            return Movie(folder.title, year, parts, list(folder.flags))
    file = parse(filename, "movie")
    return Movie(file.title, file.year, parts, list(file.flags))


def _name_is_readable(name: str) -> bool:
    """False for a name saved in another text encoding (common on old
    archives copied onto ext4 cards): Python keeps the raw bytes as
    placeholders that can't be written out as text."""
    try:
        name.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _safe_text(path: str) -> str:
    """The path for the skipped list, with each unreadable character shown
    as a replacement mark, so the saved library can always be written."""
    return os.fsencode(path).decode("utf-8", "replace")


def read_folder(path: str, rel: PurePosixPath, root_real: str, seen: set, skipped: list):
    """List one folder with the ignore rules shared by the Movies and TV scans.

    Returns (videos, subfolders): videos are (filename, relative path)
    pairs, subfolders are (path, relative PurePosixPath) pairs, both sorted
    by name ignoring case. Dot files and folders, "Sample" folders, non-video
    files, links leading outside the root and anything already in `seen`
    are left out; unreadable entries, names that can't be read as text and
    outside links go into `skipped`. Nothing is ever renamed.
    """
    try:
        with os.scandir(path) as it:
            entries = sorted(it, key=lambda e: e.name.casefold())
    except OSError:
        skipped.append(Skipped(rel.as_posix(), "cannot be read"))
        return [], []

    videos = []
    subfolders = []
    for entry in entries:
        if entry.name.startswith("."):
            continue
        entry_rel = rel / entry.name
        shown = _safe_text(entry_rel.as_posix())
        try:
            real = os.path.realpath(entry.path)
            if entry.is_symlink() and not _inside(real, root_real):
                skipped.append(Skipped(shown, "link leads outside the folder"))
                continue
            is_dir = entry.is_dir()
            is_file = entry.is_file()
        except OSError:
            skipped.append(Skipped(shown, "cannot be read"))
            continue

        # Only folders and videos matter: other files are ignored anyway.
        if (is_dir or (is_file and _is_video(entry.name))) and not _name_is_readable(entry.name):
            skipped.append(Skipped(shown, "name can't be read"))
            continue

        # A link to something already seen is followed only once.
        if is_dir and entry.name.casefold() != "sample" and real not in seen:
            seen.add(real)
            subfolders.append((entry.path, entry_rel))
        elif is_file and _is_video(entry.name) and real not in seen:
            seen.add(real)
            videos.append((entry.name, entry_rel.as_posix()))
    return videos, subfolders


def scan_movies(root: str, parse=None) -> MovieScan:
    """Group every video under `root` into movies. Never raises for a bad folder.

    `parse` reads one name; the saved library (the quick rescan and Remove work) passes one that
    reuses saved results for unchanged files. It defaults to parse_name.
    """
    parse = parse or parse_name
    root_real = os.path.realpath(root)
    movies = []
    skipped = []
    seen = {root_real}

    def walk(path: str, rel: PurePosixPath):
        videos, subfolders = read_folder(path, rel, root_real, seen, skipped)
        if videos:
            folder_name = None if rel == PurePosixPath(".") else rel.name
            movies.extend(_group_folder(folder_name, videos, parse))
        for sub_path, sub_rel in subfolders:
            walk(sub_path, sub_rel)

    walk(root_real, PurePosixPath("."))
    movies.sort(key=lambda m: library_order(m.title, m.year))
    return MovieScan(movies, skipped)


def _main(argv: list) -> int:
    if len(argv) != 2:
        print('Usage: python3 -m backend.library_movies "<path>"')
        return 2
    start = time.perf_counter()
    scan = scan_movies(argv[1])
    elapsed = time.perf_counter() - start

    for movie in scan.movies:
        line = movie.title or "(no title)"
        if movie.year is not None:
            line += f" ({movie.year})"
        if len(movie.parts) > 1:
            line += f" - {len(movie.parts)} parts"
        print(line)
    print(f"\n{len(scan.movies)} movies in {elapsed:.1f} s")
    if scan.skipped:
        print(f"Skipped {len(scan.skipped)}:")
        for item in scan.skipped:
            print(f"  {item.path}: {item.reason}")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
