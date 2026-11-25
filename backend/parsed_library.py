# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The parsed library as the page shows it (the parsed library view).

Turns grouped movies and shows into ready-to-show strings. Every path in
the answer is relative to its folder; no full path from the device ever
goes in. The saved library (backend/library_index.py, the saved library work) uses it
to build its answer; see docs/spec.md ("Parsed library view").
"""

import os
import stat as stat_module
from typing import Optional

ERROR_SENTENCE = "Couldn't read the library with the new name reader, so here is the plain file list."

# Episode flags worth a muted note on screen, with their wording.
_NOTES = {"unnumbered": "unnumbered", "season-mismatch": "season differs from folder", "duplicate": "duplicate"}


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def folder_problem(root: str) -> Optional[str]:
    """Same three reasons as the plain list (backend/scanner.py), or None."""
    try:
        st = os.stat(root)
    except FileNotFoundError:
        return "does not exist"
    except NotADirectoryError:
        return "is not a folder"
    except PermissionError:
        return "permission denied"
    if not stat_module.S_ISDIR(st.st_mode):
        return "is not a folder"
    try:
        os.listdir(root)
    except PermissionError:
        return "permission denied"
    return None


def _title(title: str, year: Optional[int]) -> str:
    line = title or "(no title)"
    return f"{line} ({year})" if year is not None else line


def render_movie(movie) -> dict:
    count = len(movie.parts)
    return {
        "display_title": _title(movie.title, movie.year),
        "subtitle": _plural(count, "part") if count > 1 else "",
        "parts": [{"label": p.label, "path": p.path} for p in movie.parts],
    }


def _episode_label(season: Optional[int], numbers: list) -> str:
    if season == 0:
        return "Special"
    if not numbers:
        return "?"
    number = str(numbers[0]) if len(numbers) == 1 else f"{numbers[0]}-{numbers[-1]}"
    if season is None:
        return number
    if len(numbers) == 1:
        return f"S{season:02d}E{numbers[0]:02d}"
    return f"S{season:02d}E{numbers[0]:02d}-E{numbers[-1]:02d}"


def render_show(show) -> dict:
    specials = sum(len(s.episodes) for s in show.seasons if s.number == 0)
    episodes = sum(len(s.episodes) for s in show.seasons if s.number != 0)
    seasons = sum(1 for s in show.seasons if s.number not in (None, 0))
    parts = [_plural(seasons, "season") if seasons else "flat", _plural(episodes, "episode")]
    if specials:
        parts.append(_plural(specials, "special"))
    flat = seasons == 0
    return {
        "display_title": _title(show.title, show.year),
        "subtitle": ", ".join(parts),
        "path": show.path,
        "seasons": [
            {
                "label": "Episodes" if flat and s.number is None else s.label,
                "episodes": [
                    {
                        "label": _episode_label(s.number, e.numbers),
                        "title": e.title or os.path.basename(e.path),
                        "path": e.path,
                        "flags": list(e.flags),
                        "notes": [_NOTES[f] for f in e.flags if f in _NOTES],
                    }
                    for e in s.episodes
                ],
            }
            for s in show.seasons
        ],
    }
