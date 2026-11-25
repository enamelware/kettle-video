# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The saved library (the saved library work and the quick rescan and Remove work). Pure logic, no HTTP awareness.

A scan of both folders is saved to one JSON file (data/library.json by
default) and loaded at launch, so the app never scans at start. A rescan
reads again only the names of new or changed files, and keeps files that
have gone as "missing" until the Remove action deletes them. Layout, rules
and reasons: docs/spec.md ("Saved library") and docs/decisions.md.

The file lists file names, so nothing here ever logs a full path.
"""

import hashlib
import json
import os
import tempfile
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable, Optional

from backend import library_order, parsed_library

SCHEMA_VERSION = 1
FILE_NAME = "library.json"
SOURCES = ("movies", "tv")


def item_id(source: str, rel: str) -> str:
    """Stable ID: the same source and relative path always give the same ID."""
    return hashlib.sha1(f"{source}:{rel}".encode("utf-8")).hexdigest()[:16]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# --- Building an entry from a scan ---


def _movie_key(movie, folder_counts: dict) -> str:
    """A movie's folder, unless it shares that folder with other movies (or
    sits loose in the root): then its first file."""
    first = movie.parts[0].path
    folder = os.path.dirname(first)
    return folder if folder and folder_counts[folder] == 1 else first


def _show_key(show) -> str:
    """A show's folder, or its title for loose files in the root."""
    return show.path if show.path != "." else show.title


def _file_info(root: str, rel: str) -> dict:
    try:
        st = os.stat(os.path.join(root, rel))
        return {"path": rel, "size": st.st_size, "mtime": st.st_mtime}
    except OSError:
        return {"path": rel, "size": None, "mtime": None}


def _movies_items(scan) -> list:
    folder_counts = {}
    for movie in scan.movies:
        folder = os.path.dirname(movie.parts[0].path)
        folder_counts[folder] = folder_counts.get(folder, 0) + 1
    items = []
    for movie in scan.movies:
        key = _movie_key(movie, folder_counts)
        items.append({"id": item_id("movies", key), "key": key, **asdict(movie)})
    return items


def _tv_items(scan) -> list:
    items = []
    for show in scan.shows:
        key = _show_key(show)
        data = asdict(show)
        for season in data["seasons"]:
            for episode in season["episodes"]:
                episode["id"] = item_id("tv", episode["path"])
        items.append({"id": item_id("tv", key), "key": key, **data})
    return items


def children(source: str, item: dict) -> list:
    """A film's parts, or a show's episodes (the things that are files)."""
    if source == "movies":
        return item["parts"]
    return [e for season in item["seasons"] for e in season["episodes"]]


def _file_paths(source: str, items: list) -> list:
    return [c["path"] for item in items for c in children(source, item)]


def is_missing(entry: dict) -> bool:
    return entry.get("status") == "missing"


def missing_count(source: str, items: list) -> int:
    """What the Remove row counts: a whole film or show that is missing is
    one item; otherwise each missing part or episode is one."""
    count = 0
    for item in items:
        if is_missing(item):
            count += 1
        else:
            count += sum(1 for c in children(source, item) if is_missing(c))
    return count


# --- Reading the folder before grouping (the quick rescan and Remove work) ---

TOP = "."  # how the folder reader names the Movies or TV Shows folder itself


def _available(root: str) -> bool:
    """The folder is there and can be listed. Any read error (a half-mounted
    card, say) counts as not available, never as an empty folder."""
    try:
        return parsed_library.folder_problem(root) is None
    except OSError:
        return False


def _unreadable(skipped: list) -> list:
    """The folders the folder reader could not list."""
    return [s.path for s in skipped if s.reason == "cannot be read"]



def _walk_files(root: str):
    """Every video the grouping will see, with its size and modified time,
    and the folders that could not be read. Same rules as the grouping
    (it lists folders with the same function)."""
    from backend.library_movies import read_folder

    root_real = os.path.realpath(root)
    seen = {root_real}
    skipped = []
    files = {}
    pending = [(root_real, PurePosixPath("."))]
    while pending:
        path, rel = pending.pop()
        videos, subfolders = read_folder(path, rel, root_real, seen, skipped)
        for _, rel_path in videos:
            info = _file_info(root_real, rel_path)
            files[rel_path] = (info["size"], info["mtime"])
        pending.extend(subfolders)
    return files, _unreadable(skipped)


class _Names:
    """The name reader for one scan. Names it may reuse come from the saved
    library; anything else goes to the parser. Each name is read once."""

    def __init__(self, reusable: dict):
        self.reusable = reusable
        self.used = {}
        self.parsed = 0  # how many names went to the parser

    def __call__(self, name: str, kind: str):
        from backend import parser

        key = f"{kind}:{name}"
        result = self.used.get(key)
        if result is None:
            saved = self.reusable.get(key)
            try:
                result = parser.ParsedName(**saved) if isinstance(saved, dict) else None
            except TypeError:  # saved in another shape: read it again
                result = None
            if result is None:
                result = parser.parse_name(name, kind)
                self.parsed += 1
            self.used[key] = result
        return result

    def saved(self) -> dict:
        return {key: asdict(result) for key, result in self.used.items()}


# --- Keeping what has gone missing (the quick rescan and Remove work) ---


def _mark(entry: dict, now: str) -> dict:
    entry = dict(entry)
    if not is_missing(entry):
        entry["status"] = "missing"
        entry["missing_since"] = now
    return entry


def _part_order(part: dict):
    label = part.get("label") or ""
    number = int(label.split()[-1]) if label.startswith("Part ") else 0
    return (number, part["path"].casefold())


def _episode_order(episode: dict):
    """The grouping's own episode order (library_tv._episode_key)."""
    from backend.library_tv import Episode, _episode_key

    return _episode_key(Episode(episode["numbers"], episode["title"], episode["path"]))


def _with_children(source: str, item: dict, kept: list, old: dict) -> dict:
    """`item` with the old parts or episodes in `kept` added back in place.
    `kept` holds (season number, episode) pairs for a show, (None, part)
    pairs for a film. Parts keep their order in `old`, the saved film: a
    part left alone in its folder loses its "Part 2" label, so labels
    alone can't place it."""
    item = dict(item)
    if source == "movies":
        place = {p["path"]: n for n, p in enumerate(old["parts"])}
        parts = item["parts"] + [part for _, part in kept]
        item["parts"] = sorted(parts, key=lambda p: (p["path"] not in place, place.get(p["path"], 0), _part_order(p)))
        return item
    from backend.library_tv import _season_order

    seasons = {s["number"]: list(s["episodes"]) for s in item["seasons"]}
    for season_number, episode in kept:
        seasons.setdefault(season_number, []).append(episode)
    item["seasons"] = [
        {"number": n, "episodes": sorted(seasons[n], key=_episode_order)}
        for n in sorted(seasons, key=_season_order)
    ]
    return item


def _old_children(source: str, item: dict) -> list:
    """(season number, episode) pairs for a show, (None, part) for a film."""
    if source == "movies":
        return [(None, p) for p in item["parts"]]
    return [(s["number"], e) for s in item["seasons"] for e in s["episodes"]]


def _keep_missing(source: str, items: list, previous: list, present: set, unreadable: list) -> list:
    """Add back what the last library had and this scan no longer finds.

    A file that is gone is marked missing; a file inside a folder that could
    not be read is kept as it was. Nothing is ever dropped here: only the
    Remove action deletes (docs/decisions.md, "A scan never removes anything").
    """
    now = now_iso()

    def unknown(path):
        return any(path == u or path.startswith(u.rstrip("/") + "/") for u in unreadable)

    by_id = {item["id"]: n for n, item in enumerate(items)}
    result = list(items)
    for old in previous:
        kept = []
        for where, child in _old_children(source, old):
            if unknown(child["path"]):
                kept.append((where, child))
            elif child["path"] not in present:
                kept.append((where, _mark(child, now)))
        if not kept:
            continue  # every file is still there, maybe grouped differently

        n = by_id.get(old["id"])
        if n is not None and not (source == "movies" and len(old["parts"]) == 1):
            # Same film or show: its missing parts or episodes go back in.
            current = {c["path"] for c in children(source, result[n])}
            extra = [(w, c) for w, c in kept if c["path"] not in current]
            result[n] = _with_children(source, result[n], extra, old)
            continue
        if n is not None:
            # A single film whose file is gone keeps its ID; the new film in
            # that folder is known by its file until the old one is removed.
            new = dict(result[n])
            new["key"] = new["parts"][0]["path"]
            new["id"] = item_id(source, new["key"])
            result[n] = new
            by_id[new["id"]] = n

        old_item = {k: v for k, v in old.items() if k not in ("status", "missing_since")}
        old_item["parts" if source == "movies" else "seasons"] = []
        old_item = _with_children(source, old_item, kept, old)
        if all(is_missing(c) for _, c in kept):
            old_item = _mark({**old_item, **{k: old[k] for k in ("status", "missing_since") if k in old}}, now)
        by_id[old["id"]] = len(result)
        result.append(old_item)
    return result


def _sorted_items(items: list) -> list:
    from backend.parser import library_order

    # The ID last, so identical titles and years never swap places.
    return sorted(items, key=lambda i: (*library_order(i["title"], i["year"]), i["id"]))


def scan_source(source: str, root: str, previous: Optional[dict], walked: tuple) -> Optional[dict]:
    """Scan one folder into a saved-library entry, reusing what `previous`
    (the saved entry for the same folder, or None) says about unchanged
    files. `walked` is _walk_files(root). The caller checks first that the
    folder is there; None if it could no longer be listed while grouping
    (card pulled out mid-scan): not available, never everything missing."""
    from backend.library_movies import scan_movies
    from backend.library_tv import scan_tv

    start = time.perf_counter()
    found, unreadable = walked
    old_files = {f["path"]: (f["size"], f["mtime"]) for f in (previous or {}).get("files", [])}
    new = [p for p in found if p not in old_files]
    changed = [p for p in found if p in old_files and old_files[p] != found[p]]
    fresh = {os.path.basename(p) for p in new + changed}
    from backend.parser import reader_version

    # Saved names count only if the same name reader read them.
    same_reader = (previous or {}).get("names_version") == reader_version()
    saved_names = ((previous or {}).get("names") or {}) if same_reader else {}
    names = _Names({k: v for k, v in saved_names.items() if k.split(":", 1)[-1] not in fresh})

    if source == "movies":
        scan = scan_movies(root, names)
        items = _movies_items(scan)
    else:
        scan = scan_tv(root, names)
        items = _tv_items(scan)
    # Folders the grouping couldn't list count as unreadable too: the card
    # may have gone between the listing and the grouping.
    unreadable = unreadable + _unreadable(scan.skipped)
    if TOP in unreadable:
        return None
    present = set(_file_paths(source, items))
    items = _sorted_items(_keep_missing(source, items, (previous or {}).get("items", []), present, unreadable))
    files = [
        {"path": rel, "size": found[rel][0], "mtime": found[rel][1]} if rel in found else _file_info(root, rel)
        for rel in _file_paths(source, items)
        if rel in present
    ]
    return {
        "root": root,
        "last_scanned_at": now_iso(),
        "scan_seconds": round(time.perf_counter() - start, 2),
        "counts": {"items": len(items), "files": len(files), "skipped": len(scan.skipped)},
        "items": items,
        "skipped": [{"path": s.path, "reason": s.reason} for s in scan.skipped],
        "files": files,
        "names": names.saved(),
        "names_version": reader_version(),
        "changes": {"new": len(new), "changed": len(changed), "parsed": names.parsed},
    }


def full_scan(roots: dict, previous: Optional[dict], progress: Callable[[int, int], None]) -> dict:
    """Scan both folders into a new index, reusing what hasn't changed. A
    folder that isn't there or can't be listed at any point of the scan
    (card out, or pulled mid-scan) is skipped: its previous entry is kept
    as it was and nothing in it is marked missing."""
    available = {s: _available(roots[s]) for s in SOURCES}
    walks, walk_seconds = {}, {}
    for source in SOURCES:
        if available[source]:
            start = time.perf_counter()
            walks[source] = _walk_files(roots[source])
            walk_seconds[source] = time.perf_counter() - start
            if TOP in walks[source][1]:
                available[source] = False
    totals = {s: len(walks[s][0]) if available[s] else 0 for s in SOURCES}
    total = sum(totals.values())
    done = 0
    progress(done, total)
    sources = {}
    last_scan = {"new": 0, "changed": 0, "missing": 0, "not_available": []}
    for source in SOURCES:
        kept = entry_for(previous, source, roots[source])
        entry = scan_source(source, roots[source], kept, walks[source]) if available[source] else None
        if entry is not None:
            entry["scan_seconds"] = round(entry["scan_seconds"] + walk_seconds[source], 2)
            sources[source] = entry
            done += totals[source]
            progress(done, total)
            for word in ("new", "changed"):
                last_scan[word] += sources[source]["changes"][word]
        else:
            # A folder left empty (the folder choice screens) was a choice, not a fault.
            if roots[source]:
                last_scan["not_available"].append(source)
            if kept is not None:
                sources[source] = kept
        if source in sources:
            last_scan["missing"] += missing_count(source, sources[source]["items"])
    return {"schema_version": SCHEMA_VERSION, "generated_at": now_iso(), "sources": sources,
            "last_scan": last_scan}


def move_folder(index: Optional[dict], source: str, root: str) -> Optional[dict]:
    """Settings changed this kind's folder (the Settings screen work): a copy of `index`
    whose saved list for `source`, from whatever folder it was saved for,
    now belongs to `root`, with every film, show, part and episode in it
    marked missing and no file known, so the rescan that follows reads the
    new folder afresh and brings back what is there. The rest stays missing
    until Remove deletes it, as for any file gone (docs/decisions.md). None
    or the same index when there is nothing to move."""
    entry = ((index or {}).get("sources") or {}).get(source)
    if entry is None or entry.get("root") == root:
        return index
    now = now_iso()
    items = []
    for item in entry["items"]:
        item = _mark(item, now)
        if source == "movies":
            item["parts"] = [_mark(p, now) for p in item["parts"]]
        else:
            item["seasons"] = [{**s, "episodes": [_mark(e, now) for e in s["episodes"]]} for s in item["seasons"]]
        items.append(item)
    moved = {**entry, "root": root, "items": items, "files": []}
    return {**index, "sources": {**index["sources"], source: moved}}


def remove_missing(index: dict) -> tuple:
    """A copy of `index` without anything marked missing, and how many
    items went (counted like the Remove row). The only way anything leaves
    the saved library."""
    removed = 0
    sources = {}
    for source, entry in index["sources"].items():
        removed += missing_count(source, entry["items"])
        items = []
        for item in entry["items"]:
            if is_missing(item):
                continue
            item = dict(item)
            if source == "movies":
                item["parts"] = [p for p in item["parts"] if not is_missing(p)]
            else:
                seasons = [{**s, "episodes": [e for e in s["episodes"] if not is_missing(e)]}
                           for s in item["seasons"]]
                item["seasons"] = [s for s in seasons if s["episodes"]]
            items.append(item)
        counts = {**entry.get("counts", {}), "items": len(items)}
        sources[source] = {**entry, "items": items, "counts": counts}
    last_scan = index.get("last_scan")
    if last_scan:
        last_scan = {**last_scan, "missing": 0}
    return {**index, "sources": sources, "last_scan": last_scan}, removed


# --- Saving and loading ---


def save(path: Path, index: dict) -> None:
    """Write to a temporary file next to it, then swap it in. If anything
    fails, the old file is left exactly as it was."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".library-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, separators=(",", ":"))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _valid(index) -> bool:
    if not isinstance(index, dict) or not isinstance(index.get("sources"), dict):
        return False
    for source, entry in index["sources"].items():
        if source not in SOURCES or not isinstance(entry, dict):
            return False
        if not isinstance(entry.get("root"), str) or not isinstance(entry.get("items"), list):
            return False
    return True


def load(path: Path, log: Callable[[str], None]) -> Optional[dict]:
    """The saved index, or None. Any problem is one plain log line, never a crash."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        log("saved library: none yet")
        return None
    except (OSError, UnicodeDecodeError):
        log("saved library ignored: the file can't be read")
        return None
    try:
        index = json.loads(text)
    except ValueError:
        log("saved library ignored: the file is damaged")
        return None
    if not isinstance(index, dict) or index.get("schema_version") != SCHEMA_VERSION:
        log("saved library ignored: it was saved in a different format")
        return None
    if not _valid(index):
        log("saved library ignored: the file is damaged")
        return None
    return index


def entry_for(index: Optional[dict], source: str, root: str) -> Optional[dict]:
    """A source's saved entry, only while it was saved for this same folder."""
    if not index:
        return None
    entry = index["sources"].get(source)
    if entry is None or entry.get("root") != root:
        return None
    return entry


# --- The answer for the page ---


MISSING = "Missing"


def _render_movie(item: dict) -> dict:
    from backend.library_movies import Movie, Part

    parts = [Part(p["label"], p["path"]) for p in item["parts"]]
    shown = parsed_library.render_movie(Movie(item["title"], item["year"], parts, item.get("flags", [])))
    for part, saved in zip(shown["parts"], item["parts"]):
        part["missing"] = is_missing(saved)
    lost = sum(1 for p in shown["parts"] if p["missing"])
    if is_missing(item):
        note = MISSING
    elif lost:
        note = f"{lost} of {len(shown['parts'])} parts missing"
    else:
        note = ""
    return {"id": item["id"], **shown, "missing": is_missing(item), "missing_note": note}


def _render_show(item: dict) -> dict:
    from backend.library_tv import Episode, Season, Show

    saved = {}
    seasons = []
    for season in item["seasons"]:
        episodes = []
        for e in season["episodes"]:
            saved[e["path"]] = e
            episodes.append(Episode(e["numbers"], e["title"], e["path"], e.get("flags", [])))
        seasons.append(Season(season["number"], episodes))
    shown = parsed_library.render_show(Show(item["title"], item["year"], seasons, item["path"]))
    for season in shown["seasons"]:
        for episode in season["episodes"]:
            episode["id"] = saved[episode["path"]]["id"]
            episode["missing"] = is_missing(saved[episode["path"]])
            episode["missing_note"] = MISSING if episode["missing"] else ""
    missing = is_missing(item)
    return {"id": item["id"], **shown, "missing": missing, "missing_note": MISSING if missing else ""}


def render_movies(items: list) -> list:
    """Saved films in the page's shape and in list order, each with its
    place and letter group (the Movies list work)."""
    return library_order.add_order(items, [_render_movie(item) for item in items])


def render(index: Optional[dict], roots: dict) -> dict:
    """The saved library in the page's shape, without the "available" flags
    (those change while the app runs; see availability())."""
    answer = {"ok": True, "skipped": {}, "timings": {}, "missing_count": 0,
              "last_scan": (index or {}).get("last_scan")}
    for source in SOURCES:
        entry = entry_for(index, source, roots[source])
        if entry is None:
            answer[source] = {"status": "ok", "items": [], "has_library": False, "scanned_at": None}
            answer["skipped"][source] = []
            answer["timings"][source] = 0.0
            continue
        if source == "movies":
            items = render_movies(entry["items"])
        else:
            # Sorted again here, so a change to the order rule (the title sorting work) shows
            # without a rescan.
            items = [_render_show(item) for item in _sorted_items(entry["items"])]
        answer[source] = {
            "status": "ok",
            "items": items,
            "has_library": True,
            "scanned_at": entry.get("last_scanned_at"),
        }
        answer["skipped"][source] = entry.get("skipped", [])
        answer["timings"][source] = entry.get("scan_seconds", 0.0)
        answer["missing_count"] += missing_count(source, entry["items"])
    return answer


def movie_play_path(index: Optional[dict], root: str, movie_id: str) -> Optional[str]:
    """The relative path to play for a saved film's ID (the Movies list work): its
    first part that is still there, else its first part. None for an ID
    that isn't in the saved library."""
    entry = entry_for(index, "movies", root)
    for item in (entry or {}).get("items", []):
        if item["id"] == movie_id and item["parts"]:
            part = next((p for p in item["parts"] if not is_missing(p)), item["parts"][0])
            return part["path"]
    return None


def availability(roots: dict) -> dict:
    return {source: _available(roots[source]) for source in SOURCES}


SOURCE_NAMES = {"movies": "Movies", "tv": "TV Shows"}


def _all_missing(index: Optional[dict]) -> int:
    return sum(missing_count(source, entry["items"])
               for source, entry in ((index or {}).get("sources") or {}).items())


def scan_message(previous: Optional[dict], index: dict) -> str:
    """What a rescan changed, in words for the page's toast (the Home actions work):
    "3 added, 1 changed, 1 missing", "Movies folder not available", or "No
    changes". Added and changed count files; missing counts the items that
    went missing in this scan (as the menu's Remove row counts them). No
    paths or names."""
    last = index.get("last_scan") or {}
    parts = []
    if last.get("new"):
        parts.append(f"{last['new']} added")
    if last.get("changed"):
        parts.append(f"{last['changed']} changed")
    gone = _all_missing(index) - _all_missing(previous)
    if gone > 0:
        parts.append(f"{gone} missing")
    for source in last.get("not_available", []):
        parts.append(f"{SOURCE_NAMES.get(source, source)} folder not available")
    return ", ".join(parts) or "No changes"


def summary(index: dict) -> str:
    """One line for the session log: counts and scan times, no paths."""
    parts = []
    for source, word in (("movies", "movie"), ("tv", "show")):
        entry = index["sources"].get(source)
        if entry is None:
            parts.append(f"no {source} folder")
            continue
        c = entry["counts"]
        parts.append(
            f"{c['items']} {word}{'' if c['items'] == 1 else 's'} ({c['files']} files) "
            f"in {entry['scan_seconds']:.2f} s, {c['skipped']} skipped"
        )
    last = index.get("last_scan")
    if last:
        read = sum(e.get("changes", {}).get("parsed", 0)
                   for s, e in index["sources"].items() if s not in last["not_available"])
        parts.append(f"{last['new']} new, {last['changed']} changed, {last['missing']} missing, {read} names read")
    return "library scan saved: " + "; ".join(parts)
