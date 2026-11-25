# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Choosing the Movies and TV Shows folders on first launch (the folder choice screens).
Pure logic, no HTTP awareness.

- needed(): the flow shows when settings.json has neither folder.
- problem(): why a pair of folders can't be used, in the words the page
  shows inside the row, or None. Movies and TV shows need separate folders:
  the same folder twice, or one inside the other, is refused.
- save_folders(): writes both folders into settings.json under the keys
  used today (movies_path, tv_path; a skipped one is ""), keeping every
  other setting, in one go: the new file is written next to it and then
  swapped in, so settings.json is never left half written. With no
  settings.json yet, this creates it.
- own_files_problem(): the sentence for a folder that holds Kettle's own
  files (the first onboarding review fixes): media folders are read-only, and settings.json, the
  saved library and the logs would be written inside it.
- result(): what the result screen shows after the first scan (the first scan screen),
  worked out from the saved library.

Only settings.json is ever written. The folders themselves are only
compared by their paths, never opened, created, moved or renamed.
"""

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import quote

from backend import folder_finder, library_index
from backend.scanner import VIDEO_EXTENSIONS

KEYS = {"movies": "movies_path", "tv": "tv_path"}

# Result screen (the first scan screen). Why the scan skipped a file it couldn't read; a
# link leading outside the folder is left out on purpose, not unreadable.
UNREADABLE_REASONS = ("cannot be read", "name can't be read")
# A clear episode marker in a file's name. On purpose stricter than the name
# reader: a note about a film that only seems to hold a number would be wrong
# ("Quillmoor 13"), and one too few costs nothing. 4K or 1920x1080 never match.
EPISODE_MARKER = re.compile(r"(?<![a-z0-9])(?:s\d{1,2}[ ._-]?e\d{1,3}|\d{1,2}x\d{2,3})(?![a-z0-9])", re.IGNORECASE)

SAME = "Already your movies folder. Movies and TV shows need separate folders, so pick a different one."
INSIDE_MOVIES = "This folder is inside your movies folder, so pick a different one."
HOLDS_MOVIES = "Your movies folder is inside this one, so pick a different one."
NEITHER = "Choose a folder for movies or for TV shows to continue."
GONE = "This folder can't be found any more. Press Y to look again."
SAVE_FAILED = "Couldn't save your folders. Your settings are unchanged."
# True even when no other folder is listed: the person can act on it from here.
OWN_FILES = ("Kettle keeps its own files inside this folder, so it can't be used. "
             "Put your videos in a folder of their own, then press Y to look again.")
# A folder from the system's dialog: the search can miss what is moved out of
# it (short clips, hidden folders), and the dialog can always reach it.
OWN_FILES_PICKED = ("Kettle keeps its own files inside this folder, so it can't be used. "
                    "Put your videos in a folder of their own, then press Y to look again, "
                    "or choose that folder with Browse somewhere else.")


class SaveError(Exception):
    pass


def needed(settings: dict) -> bool:
    """Neither folder is set (both empty after load_settings cleaned them)."""
    return not settings.get("movies_path") and not settings.get("tv_path")


def _real(path: str) -> str:
    return os.path.realpath(path)


def problem(movies: Optional[str], tv: Optional[str]) -> Optional[str]:
    """None when the pair can be saved; otherwise the sentence for the TV
    Shows screen's row. None for a folder means "I don't have ..."."""
    if not movies and not tv:
        return NEITHER
    if not movies or not tv:
        return None
    m, t = _real(movies), _real(tv)
    if m == t:
        return SAME
    common = os.path.commonpath([m, t])
    if common == m:
        return INSIDE_MOVIES
    if common == t:
        return HOLDS_MOVIES
    return None


def own_files_problem(path: str, own_folders: Iterable, picked: bool = False) -> Optional[str]:
    """The sentence when path is, or holds, one of Kettle's own folders.
    picked: it came from the system's dialog, not the search."""
    real = _real(path)
    for own in own_folders:
        if os.path.commonpath([real, _real(own)]) == real:
            return OWN_FILES_PICKED if picked else OWN_FILES
    return None


def _saved_form(path: Optional[str]) -> str:
    """How a folder goes in the file. load_settings trims a path, as it may
    have been pasted in, so a name that really ends in a space is written as
    a file:// address, which it reads back exactly. Any other stays plain."""
    if not path:
        return ""
    return path if path == path.strip() else "file://" + quote(path)


def save_folders(settings_file: Path, movies: Optional[str], tv: Optional[str]) -> None:
    """Write both folders into settings_file, keeping every other key and
    value (and their order). Raises SaveError, with no path in its text,
    if the file can't be read or written; it is then left as it was."""
    _save(settings_file, {"movies": movies, "tv": tv})


def save_folder(settings_file: Path, kind: str, path: Optional[str]) -> None:
    """Settings (the Settings screen work): write one kind's folder (None for "Stop using
    ..."), keeping the other and every other setting, as save_folders does."""
    _save(settings_file, {kind: path})


def _save(settings_file: Path, folders: dict) -> None:
    """folders: kind -> path or None, for the kinds to write."""
    settings_file = Path(settings_file)
    try:
        data = json.loads(settings_file.read_bytes().decode("utf-8-sig"))
    except FileNotFoundError:
        # A first launch with no settings file: this creates it, with both
        # keys, as load_settings needs them.
        data = {KEYS["movies"]: "", KEYS["tv"]: ""}
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise SaveError(f"settings.json couldn't be read ({type(exc).__name__})") from None
    if not isinstance(data, dict):
        raise SaveError("settings.json doesn't hold its settings between { and }")
    try:
        for kind, path in folders.items():
            data[KEYS[kind]] = _saved_form(path)
        # Before any temporary file exists: a folder name that isn't valid
        # text can't go in a UTF-8 file.
        body = (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    except UnicodeEncodeError:
        raise SaveError("a folder's name isn't valid text, so settings.json wasn't written") from None
    temp = None
    try:
        fd, temp = tempfile.mkstemp(prefix=".settings-", suffix=".tmp", dir=settings_file.parent)
        with os.fdopen(fd, "wb") as f:
            f.write(body)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.chmod(temp, settings_file.stat().st_mode & 0o7777)
        except OSError:
            pass
        os.replace(temp, settings_file)
    except OSError as exc:
        if temp is not None:
            try:
                os.unlink(temp)
            except OSError:
                pass
        raise SaveError(f"settings.json couldn't be written ({type(exc).__name__})") from None


def _plural(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


def _present(children: list) -> list:
    """Only what is in the folder now: what a rescan keeps as missing isn't."""
    return [c for c in children if not library_index.is_missing(c)]


def _skipped_videos(entry: dict) -> int:
    """Videos the scan had to skip, as the file or its name can't be read."""
    return sum(1 for s in entry.get("skipped", [])
               if s.get("reason") in UNREADABLE_REASONS
               and os.path.splitext(s.get("path", ""))[1].lower() in VIDEO_EXTENSIONS)


def _movies_counts(entry: dict) -> dict:
    """unreadable: skipped videos, and the files of a film whose names gave the
    name reader nothing, so the file name stands in for a title."""
    films = _present(entry["items"])
    parts = [(film, part) for film in films for part in _present(film["parts"])]
    return {
        "count": len(films),
        "unreadable": _skipped_videos(entry) + sum(1 for film, _ in parts if "fallback" in film.get("flags", [])),
        "wrong_kind": sum(1 for _, part in parts if EPISODE_MARKER.search(os.path.basename(part["path"]))),
    }


def _tv_counts(entry: dict) -> dict:
    """unreadable: skipped videos, and files with neither a name nor a number
    to go on. wrong_kind: files loose at the top of the folder, with no season
    or episode number."""
    shows = episodes = unreadable = wrong_kind = 0
    for show in _present(entry["items"]):
        found = [(season, episode) for season in show["seasons"] for episode in _present(season["episodes"])]
        shows += 1 if found else 0
        episodes += len(found)
        for season, episode in found:
            if episode.get("numbers"):
                continue
            unreadable += 1 if "fallback" in episode.get("flags", []) else 0
            wrong_kind += 1 if show.get("path") == "." and season.get("number") is None else 0
    return {"shows": shows, "episodes": episodes, "unreadable": unreadable + _skipped_videos(entry),
            "wrong_kind": wrong_kind}


NO_COUNTS = {"movies": {"count": 0, "unreadable": 0, "wrong_kind": 0},
             "tv": {"shows": 0, "episodes": 0, "unreadable": 0, "wrong_kind": 0}}
COUNTERS = {"movies": _movies_counts, "tv": _tv_counts}


def result(index: Optional[dict], roots: dict, places=None) -> dict:
    """What the result screen shows (the first scan screen), from the saved library just
    written, for the folders chosen now. A panel has no full path: the place
    and the folder's own name only. A folder that couldn't be read counts
    nothing, whatever was saved for it. The notes never block anything. failed:
    none of the folders set could be read (the card came out)."""
    not_available = ((index or {}).get("last_scan") or {}).get("not_available") or []
    panels, counts, folder_names = {}, {}, {}
    for kind in KEYS:
        if not roots[kind]:
            panels[kind] = {"set": False}
            counts[kind] = NO_COUNTS[kind]
            continue
        entry = library_index.entry_for(index, kind, roots[kind])
        counts[kind] = COUNTERS[kind](entry) if entry is not None and kind not in not_available else NO_COUNTS[kind]
        path = folder_finder.place_path(roots[kind], places)
        folder_names[kind] = path.rsplit(" › ", 1)[-1]
        panels[kind] = {"set": True, "path": path,
                        **{key: value for key, value in counts[kind].items() if key not in ("unreadable", "wrong_kind")}}

    notes = []
    unreadable = counts["movies"]["unreadable"] + counts["tv"]["unreadable"]
    if unreadable:
        notes.append(f"{_plural(unreadable, 'file', 'files')} could not be read as a movie or an episode.")
    episodes_here, films_here = counts["movies"]["wrong_kind"], counts["tv"]["wrong_kind"]
    if episodes_here:
        look = "looks like an episode" if episodes_here == 1 else "look like episodes"
        notes.append(f"{_plural(episodes_here, 'file', 'files')} in {folder_names['movies']} {look}.")
    if films_here:
        look = "looks like a film" if films_here == 1 else "look like films"
        notes.append(f"{_plural(films_here, 'loose file', 'loose files')} in {folder_names['tv']} {look}.")
    set_kinds = [kind for kind in KEYS if roots[kind]]
    notes += [f"{library_index.SOURCE_NAMES[kind]} folder not available" for kind in set_kinds if kind in not_available]
    return {
        "movies": panels["movies"], "tv": panels["tv"], "notes": notes,
        "nothing_found": counts["movies"]["count"] + counts["tv"]["episodes"] == 0,
        "failed": bool(set_kinds) and all(kind in not_available for kind in set_kinds),
    }


def log_line(movies: Optional[str], tv: Optional[str]) -> str:
    """For the launch log: what was chosen, never which folder."""
    return (f"onboarding: movies {'chosen' if movies else 'skipped'}, "
            f"tv {'chosen' if tv else 'skipped'}, settings saved")
