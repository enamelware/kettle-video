# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Continue watching (the Continue watching work). Pure logic and its own small files, no HTTP.

When mpv closes, the quit script (backend/mpv_scripts/quit_capture.lua) has
saved the position, the length and the frame on screen. This module keeps
them against the library item (a film, or a show for its episodes), decides
what the carousel shows, and keeps one small picture per shown item in
<data_dir>/thumbnails/. Rules and reasons: docs/spec.md ("Continue
watching") and docs/decisions.md.

Resume itself stays mpv's own (docs/decisions.md, "Resume"): nothing here
reads or changes mpv's saved positions, so an item that finishes, is
removed or drops off never loses its resume position. This module keeps
its own last position for each item too, for the tiles.

Nothing here logs a file name, a title or a picture name.
"""

import json
import math
import os
import re
import shutil
from pathlib import Path
from typing import Callable, Optional

from backend import library_index, parsed_library

SCHEMA_VERSION = 1
FILE_NAME = "continue.json"
PICTURES_DIR = "thumbnails"
MAX_ITEMS = 6
MIN_WATCHED_SECONDS = 60
# Resume has no "finished" rule of its own (mpv only knows the very end),
# so finished means 95% watched, or played to the end (docs/decisions.md).
FINISHED_SHARE = 0.95

# Why an item is out of the carousel. Any other item is in it once it
# reaches MIN_WATCHED_SECONDS.
FINISHED, REMOVED, DROPPED = "finished", "removed", "dropped"

_ID = re.compile(r"^[0-9a-f]{16}$")  # library_index.item_id


# --- Words on the tiles ---


def clock(seconds) -> str:
    """h:mm:ss, or m:ss under an hour."""
    total = max(int(seconds or 0), 0)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def time_left(seconds) -> str:
    """Minutes left, rounded up; under a minute says so."""
    if seconds < 60:
        return "less than 1 min left"
    return f"{math.ceil(seconds / 60)} min left"


def episode_label(season: Optional[int], numbers: list) -> str:
    """"S2 E5", "Episode 37" for a show numbered straight through, or
    "Special 3" for season 0. A file holding several episodes: "S2 E5-6"."""
    span = f"{numbers[0]}-{numbers[-1]}" if len(numbers) > 1 else "".join(str(n) for n in numbers)
    if season == 0:
        word = "Special"
    elif season is None:
        word = "Episode"
    else:
        return f"S{season} E{span}" if span else f"S{season}"
    return f"{word} {span}" if span else word


# --- Which items are in the carousel ---


def is_finished(position: float, duration: Optional[float], played_to_end: bool) -> bool:
    return played_to_end or (bool(duration) and position >= FINISHED_SHARE * duration)


def in_carousel(entry: dict) -> bool:
    return entry.get("hidden") is None and entry["position"] >= MIN_WATCHED_SECONDS


def locate(index: Optional[dict], roots: dict, source: str, rel: str) -> Optional[dict]:
    """What a played file belongs to: its film, or its show for an episode.
    None if it isn't in the saved library (nothing is recorded then)."""
    saved = library_index.entry_for(index, source, roots[source]) if source in roots else None
    for item in (saved or {}).get("items", []):
        if any(child["path"] == rel for child in library_index.children(source, item)):
            return {"key": item["id"], "kind": "movie" if source == "movies" else "episode", "source": source}
    return None


def play_title(index: Optional[dict], roots: dict, source: str, rel: str) -> Optional[str]:
    """The name mpv shows on D-pad Up (the playback controls work): Kettle's title, the same
    wording as the tiles. "Title (Year)" for a film, "Show · S2 E5" for an
    episode, "Title (Year) · Part 2" for a part. None if the file isn't in
    the saved library."""
    saved = library_index.entry_for(index, source, roots[source]) if source in roots else None
    for item in (saved or {}).get("items", []):
        child = next((c for c in library_index.children(source, item) if c["path"] == rel), None)
        if child is None:
            continue
        # The same "Title (Year)" as the list; a show's name stays plain.
        title = parsed_library._title(item.get("title"), item.get("year") if source == "movies" else None)
        label = _label(source, item, child)
        return f"{title} · {label}" if label else title
    return None


def _find(index: Optional[dict], roots: dict, entry: dict):
    """(library item, its part or episode) for an entry, or None once the
    library no longer holds that file."""
    source = entry["source"]
    saved = library_index.entry_for(index, source, roots[source])
    for item in (saved or {}).get("items", []):
        if item["id"] == entry["key"]:
            child = next((c for c in library_index.children(source, item) if c["path"] == entry["file"]), None)
            return (item, child) if child is not None else None
    return None


def _label(source: str, item: dict, child: dict) -> str:
    """"Part 2" for a film in several parts, the episode label for a show."""
    if source == "movies":
        parts = item["parts"]
        if len(parts) < 2:
            return ""
        return child.get("label") or f"Part {parts.index(child) + 1}"
    season = next(s["number"] for s in item["seasons"] if child in s["episodes"])
    return episode_label(season, child.get("numbers") or [])


def _number(value) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def _valid(key, entry) -> bool:
    return (
        isinstance(key, str) and _ID.match(key) is not None and isinstance(entry, dict)
        and entry.get("key") == key and entry.get("source") in library_index.SOURCES
        and entry.get("kind") in ("movie", "episode") and isinstance(entry.get("file"), str)
        and _number(entry.get("position")) is not None and _number(entry.get("stopped_at")) is not None
        and entry.get("hidden") in (None, FINISHED, REMOVED, DROPPED)
    )


def _inside(path: Path, root: str) -> bool:
    return Path(os.path.realpath(path)).is_relative_to(os.path.realpath(root))


class ContinueWatching:
    """The saved list (<data_dir>/continue.json) and its pictures. Not
    thread-safe: the server calls it under one lock."""

    def __init__(self, data_dir, media_roots, log: Callable[[str], None]):
        self.path = Path(data_dir) / FILE_NAME
        self.pictures = Path(data_dir) / PICTURES_DIR
        self.log = log
        self.set_media_roots(media_roots)
        self.entries = self._load()

    def set_media_roots(self, media_roots) -> None:
        """At the start, and when onboarding chooses new folders. data_dir
        could be set inside a media folder: pictures never go there."""
        self.pictures_allowed = not any(_inside(self.pictures, root) for root in media_roots)
        if not self.pictures_allowed:
            self.log("continue watching: data_dir is inside a media folder, so no pictures are saved")

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            self.log("continue watching: the saved list can't be read; starting empty")
            return {}
        if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION \
                or not isinstance(data.get("entries"), dict):
            self.log("continue watching: the saved list was saved in a different format; starting empty")
            return {}
        return {key: entry for key, entry in data["entries"].items() if _valid(key, entry)}

    def _save(self) -> None:
        library_index.save(self.path, {"schema_version": SCHEMA_VERSION, "entries": self.entries})

    def _picture(self, key: str) -> Path:
        return self.pictures / f"{key}.jpg"

    def _delete_picture(self, key: str) -> None:
        if not self.pictures_allowed:
            return  # inside a media folder: never touch anything there
        try:
            self._picture(key).unlink()
        except FileNotFoundError:
            pass
        except OSError:
            self.log("continue watching: a picture couldn't be deleted")

    def _put_picture(self, key: str, source: Path) -> bool:
        """Copy a picture in under the item's name, swapped in whole."""
        if not self.pictures_allowed:
            return False
        part = self.pictures / f"{key}.jpg.part"
        try:
            self.pictures.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, part)
            os.replace(part, self._picture(key))
        except OSError:
            self.log("continue watching: a picture couldn't be saved")
            return False
        return True

    def _newest_first(self) -> list:
        shown = [e for e in self.entries.values() if in_carousel(e)]
        return sorted(shown, key=lambda e: e["stopped_at"], reverse=True)

    def visible(self) -> list:
        """The carousel's entries, most recently stopped first."""
        return self._newest_first()[:MAX_ITEMS]

    def _shown(self, key: str) -> Optional[dict]:
        entry = self.entries.get(key) if isinstance(key, str) else None
        return entry if entry is not None and in_carousel(entry) else None

    def _settle(self) -> None:
        """Past the cap, the oldest drop off: picture deleted, entry kept."""
        for entry in self._newest_first()[MAX_ITEMS:]:
            entry["hidden"] = DROPPED
            self._delete_picture(entry["key"])

    def record_stop(self, target: dict, rel: str, record: dict, frame: Optional[Path], now: float):
        """Keep what mpv reported for the file `rel` of `target` (see
        locate). Returns `now` when the frame became the item's picture
        (the caller may then shrink it with replace_picture), else None."""
        position = _number(record.get("position"))
        duration = _number(record.get("duration"))
        played_to_end = record.get("finished") is True
        if position is None:
            if not (played_to_end and duration):
                return None
            position = duration
        key = target["key"]
        entry = {
            "key": key, "kind": target["kind"], "source": target["source"], "file": rel,
            "position": position, "duration": duration, "stopped_at": now,
            "hidden": FINISHED if is_finished(position, duration, played_to_end) else None,
        }
        self.entries[key] = entry
        placed = in_carousel(entry) and frame is not None and self._put_picture(key, frame)
        if not placed:
            # Finished, too short, or no new frame: no picture of an older moment.
            self._delete_picture(key)
        self._settle()
        self._save()
        return now if placed else None

    def replace_picture(self, key: str, stamp: float, small: Optional[Path]) -> bool:
        """Swap in the small picture made from the frame saved at `stamp`,
        unless the item has been stopped again, removed or has left since."""
        entry = self._shown(key)
        if small is None or entry is None or entry["stopped_at"] != stamp or not self._picture(key).is_file():
            return False
        return self._put_picture(key, small)

    def remove(self, key: str) -> bool:
        """X on a tile: out of the carousel at once, picture deleted. The
        entry and its position stay; the next stop brings it back."""
        entry = self._shown(key)
        if entry is None:
            return False
        entry["hidden"] = REMOVED
        self._delete_picture(key)
        self._save()
        return True

    def prune(self, index: Optional[dict], roots: dict) -> int:
        """Forget items whose file has left the saved library (Remove missing
        items), with their pictures. Nothing happens without a library, and
        an item stays while the library holds nothing for its kind's folder
        (the folder choice screens: none chosen yet, skipped, or not scanned since it was
        chosen), because then nothing says its file has left."""
        if index is None:
            return 0
        gone = [key for key, entry in self.entries.items()
                if library_index.entry_for(index, entry["source"], roots[entry["source"]]) is not None
                and _find(index, roots, entry) is None]
        for key in gone:
            del self.entries[key]
            self._delete_picture(key)
        if gone:
            self._save()
        return len(gone)

    def clean_pictures(self) -> int:
        """At launch: delete every picture that no longer belongs to a
        carousel item (and half-copied ones). Other files are left alone."""
        if not self.pictures_allowed:
            return 0  # inside a media folder: never touch anything there
        keep = {f"{entry['key']}.jpg" for entry in self.visible()}
        removed = 0
        try:
            names = os.listdir(self.pictures)
        except OSError:
            return 0
        for name in names:
            stem = name.removesuffix(".part").removesuffix(".jpg")
            if _ID.match(stem) and name.endswith((".jpg", ".jpg.part")) and name not in keep:
                try:
                    os.unlink(self.pictures / name)
                    removed += 1
                except OSError:
                    self.log("continue watching: a picture couldn't be deleted")
        return removed

    def picture_file(self, key: str) -> Optional[Path]:
        """The picture of an item in the carousel, if it has one."""
        if not isinstance(key, str) or not _ID.match(key) or self._shown(key) is None:
            return None
        picture = self._picture(key)
        return picture if picture.is_file() else None

    def play_target(self, key: str) -> Optional[tuple]:
        """(source, relative path) to resume an item in the carousel."""
        entry = self._shown(key)
        return (entry["source"], entry["file"]) if entry is not None else None

    def items(self, index: Optional[dict], roots: dict, available: dict) -> list:
        """The carousel for the page: at most MAX_ITEMS, newest first. Ids,
        words and numbers only: never a file location."""
        result = []
        for entry in self.visible():
            found = _find(index, roots, entry)
            if found is None:
                continue
            item, child = found
            source, key = entry["source"], entry["key"]
            title = item.get("title") or "(no title)"
            label = _label(source, item, child)
            name = f"{title} · {label}" if label else title
            position, duration = entry["position"], entry["duration"]
            missing = (library_index.is_missing(item) or library_index.is_missing(child)
                       or not available.get(source, True))
            if missing:
                caption = f"{name} · Missing · stopped at {clock(position)}"
            else:
                caption = f"{name} · Resume at {clock(position)}"
                if duration:
                    caption += f" · {time_left(max(duration - position, 0))}"
            picture = self.picture_file(key)
            result.append({
                "id": key,
                "kind": entry["kind"],
                "title": title,
                "label": label,
                "name": name,
                "caption": caption,
                "position": position,
                "duration": duration,
                "missing": missing,
                "picture": f"/api/continue/picture/{key}?v={int(entry['stopped_at'] * 1000)}" if picture else None,
            })
        return result
