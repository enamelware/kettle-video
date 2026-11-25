# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Find the folders with videos, for onboarding (the folder finder). Pure logic, no
HTTP awareness; only reads, never creates, moves, renames or deletes.

The rules are the storage spike's (docs/spikes/storage.md, Questions 1 to 3,
and "What would stop onboarding"):

- Places: internal storage (the home folder only) and every card or USB
  drive that is really mounted, that is, in the system's list of mounts
  under /run/media/, /media/ or /mnt/. A leftover empty folder where a card
  was (seen on the Nova) is not a mount, so it is not a place. A mounted
  card whose folder exists but can't be read is "not ready", not empty.
- In each place, up to 6 levels down, never into hidden, Steam, emulator or
  junk folders.
- Suggest the folder that holds the films or shows, never one film's own
  folder; season-like folders belong to their show; a folder whose videos
  are all short clips is not suggested.

Full paths stay here. answer() gives the page, for each folder, an id, its
place's name, its own name, the counts and up to two example names; the
page picks a folder by its id, and the server keeps every folder's path by
its id for the session.
"""

import hashlib
import os
import re
import time
from dataclasses import dataclass, field
from typing import List, Optional

from backend.scanner import VIDEO_EXTENSIONS

MAX_DEPTH = 6                 # levels below the place's top
MIN_VIDEO_BYTES = 20_000_000  # a folder whose videos are all smaller holds clips, not a library
# A search never takes longer than this, whatever the card does; what was
# read by then is kept and the place is marked "partial".
TIME_LIMIT = 10.0

# Where desktop Linux mounts cards and USB drives. SteamOS and Armada use
# /run/media/<user>/<label>.
REMOVABLE_ROOTS = ("/run/media/", "/media/", "/mnt/")
MOUNTINFO = "/proc/self/mountinfo"

# Never walked into, compared ignoring capitals. Hidden folders (".anything")
# are skipped too, which covers Steam's own install, Flatpak data and caches.
SKIP_NAMES = {
    "sample", "samples",                      # junk the scanner ignores
    "lost+found",                             # file system repair folder
    "steamapps", "steamlibrary", "steam",     # Steam games and their data
    "compatdata", "shadercache",
    "emulation", "emudeck", "es-de", "retroarch", "roms",  # emulators
    "downloaded_media",                       # scraped video previews
    "applications", "homebrew",               # AppImages, Decky plugins
}
SEASON_LIKE = re.compile(r"^(season|series|staffel|saison|s)\s*\d+$|^specials?$|^extras?$"
                         r"|^(disc|disk|cd|dvd|part)\s*\d+$", re.IGNORECASE)

KIND_NAMES = {"internal": "Internal storage", "sd": "SD card", "usb": "USB drive",
              "other": "Other drive"}
# Where a folder chosen in the system's dialog shows when it is in no place.
SOMEWHERE_ELSE = "Somewhere else"
# A place's state: read in full, not ready (a card's folder that exists but
# can't be read yet), unreadable (internal storage that can't be read), or
# partial (the time limit ran out).
OK, NOT_READY, UNREADABLE, PARTIAL = "ok", "not_ready", "unreadable", "partial"

MAX_EXAMPLES = 2

# A folder chosen in the system's dialog that can't be read (the first onboarding review fixes).
CANT_BE_READ = "Kettle couldn't read this folder, so pick a different one."


@dataclass
class Place:
    kind: str           # "internal", "sd", "usb" or "other"
    name: str           # "Internal storage", "SD card", "USB drive 2"...
    root: str           # full path: never sent to the page
    state: str = OK


@dataclass
class Folder:
    """One folder in the tree of folders that hold videos."""
    path: str
    files: List[str] = field(default_factory=list)  # videos directly inside
    loose_big: int = 0                               # of those, at least MIN_VIDEO_BYTES
    children: list = field(default_factory=list)     # subfolders with videos below
    total: int = 0                                   # videos here and below
    big: int = 0                                     # of those, at least MIN_VIDEO_BYTES
    holding: int = 0                                 # folders here and below with videos directly inside
    unreadable: bool = False                         # this folder itself couldn't be read


# ---------------------------------------------------------------- places

def _unescape(text):
    # mountinfo writes spaces, tabs, newlines and backslashes in paths as octal.
    return (text.replace("\\040", " ").replace("\\011", "\t")
            .replace("\\012", "\n").replace("\\134", "\\"))


def parse_mountinfo(text):
    """(mount point, 'major:minor', source device) for each mount."""
    out = []
    for line in text.splitlines():
        if " - " not in line:
            continue
        left, right = line.split(" - ", 1)
        fields, rest = left.split(), right.split()
        if len(fields) < 5 or len(rest) < 2:
            continue
        out.append((_unescape(fields[4]), fields[2], rest[1]))
    return out


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return ""


def hardware(dev_numbers, source="", sys_root="/sys"):
    """What a drive is: "sd", "usb", "internal" or "other", from where it
    sits in the hardware tree. An SD card hangs off an MMC controller and
    reports type SD (built-in eMMC reports MMC); a USB drive has "usb" in
    its path; NVMe, SATA and UFS are internal. btrfs gives its mounts a
    placeholder number (major 0), so then the named device is looked up.
    The "removable" flag is not used: the Deck's SD slot says it isn't."""
    if dev_numbers.startswith("0:") and source.startswith("/dev/"):
        link = os.path.join(sys_root, "class", "block", os.path.basename(source))
    else:
        link = os.path.join(sys_root, "dev", "block", dev_numbers)
    sys_path = os.path.realpath(link)
    if "/mmc_host/" in sys_path:
        disk = sys_path if os.path.exists(os.path.join(sys_path, "device")) else os.path.dirname(sys_path)
        return "sd" if _read(os.path.join(disk, "device", "type")) == "SD" else "internal"
    if "/usb" in sys_path:
        return "usb"
    if "/nvme/" in sys_path or "/ata" in sys_path or "ufshc" in sys_path:
        return "internal"
    return "other"


def list_places(home=None, mountinfo=None, kind_of=hardware):
    """Internal storage (the home folder), then each mounted card or drive,
    in mount-point order, with its display name. mountinfo is the text of
    the system's list of mounts (read from the system when not given)."""
    home = home if home is not None else os.path.expanduser("~")
    if mountinfo is None:
        mountinfo = _read(MOUNTINFO)
    places = [Place("internal", KIND_NAMES["internal"], home)]
    seen = {}
    for mount_point, numbers, source in parse_mountinfo(mountinfo):
        if mount_point.startswith(REMOVABLE_ROOTS):
            seen[mount_point] = (numbers, source)  # a later mount on the same point wins
    counts = {"internal": 1}  # an internal drive mounted there is "Internal storage 2"
    for mount_point in sorted(seen):
        numbers, source = seen[mount_point]
        kind = kind_of(numbers, source)
        counts[kind] = counts.get(kind, 0) + 1
        name = KIND_NAMES[kind] if counts[kind] == 1 else f"{KIND_NAMES[kind]} {counts[kind]}"
        places.append(Place(kind, name, mount_point))
    return places


# ---------------------------------------------------------------- walking

def skipped(name):
    return name.startswith(".") or name.casefold() in SKIP_NAMES


def is_video(name):
    return not name.startswith(".") and os.path.splitext(name)[1].lower() in VIDEO_EXTENSIONS


class _Walk:
    def __init__(self, deadline):
        self.deadline = deadline
        self.out_of_time = False
        self.unreadable_part = False  # some folder on the way couldn't be read

    def walk(self, path, depth=0):
        node = Folder(path)
        if time.monotonic() > self.deadline:
            self.out_of_time = True
            return node
        try:
            with os.scandir(path) as it:
                entries = sorted(it, key=lambda e: e.name.casefold())  # folders in name order
        except OSError:
            node.unreadable = self.unreadable_part = True
            return node  # pulled out, or can't be read: nothing found here
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    if depth < MAX_DEPTH and not skipped(entry.name):
                        child = self.walk(entry.path, depth + 1)
                        if child.total:
                            node.children.append(child)
                elif entry.is_file(follow_symlinks=False) and is_video(entry.name):
                    node.files.append(entry.name)
                    if entry.stat(follow_symlinks=False).st_size >= MIN_VIDEO_BYTES:
                        node.loose_big += 1
            except OSError:
                continue
        node.total = len(node.files) + sum(c.total for c in node.children)
        node.big = node.loose_big + sum(c.big for c in node.children)
        node.holding = (1 if node.files else 0) + sum(c.holding for c in node.children)
        return node


def _season_like(folder):
    return bool(SEASON_LIKE.match(os.path.basename(folder.path)))


def _is_collection(folder):
    """Holds two or more titles (not seasons or discs of one title)."""
    return sum(1 for c in folder.children if not _season_like(c)) >= 2


def _is_title(folder):
    """One film or one show: videos directly inside, or only seasons or discs."""
    return bool(folder.files) or all(_season_like(c) for c in folder.children)


def _collapse(folder):
    """Go down while there is only one way down, but never into a single
    film's or show's own folder ("Films", not the one film in it)."""
    while not folder.files and len(folder.children) == 1 and not _is_title(folder.children[0]):
        folder = folder.children[0]
    return folder


def _pick(folder, out):
    folder = _collapse(folder)
    if not folder.files and sum(1 for c in folder.children if _is_collection(c)) >= 2:
        for child in folder.children:  # e.g. Media/Films and Media/TV
            _pick(child, out)
        return
    out.append(folder)


def suggest(top):
    """The suggestion rule (spike, Question 3). Loose videos at the top of a
    place suggest the place itself; then each top-level folder with videos,
    gone down while there is one way down, split when it holds two or more
    collections. Folders whose videos are all short clips are dropped."""
    out = [top] if top.files else []
    for child in top.children:
        _pick(child, out)
    return [f for f in out if f.big]


# ---------------------------------------------------------------- results

def _stem(name):
    return os.path.splitext(name)[0]


def examples(folder, whole_place=False):
    """Up to two names from inside the folder, in name order: the titles'
    folders and loose videos; for a show's own folder, its episodes. For a
    whole place, only the videos at its top (its folders are suggested on
    their own)."""
    if whole_place:
        names = [_stem(n) for n in folder.files]
    else:
        names = [os.path.basename(c.path) for c in folder.children if not _season_like(c)]
        names += [_stem(n) for n in folder.files]
        if not names:
            for child in sorted(folder.children, key=lambda c: os.path.basename(c.path).casefold()):
                names += [_stem(n) for n in child.files]
                if names:
                    break
    return sorted(names, key=str.casefold)[:MAX_EXAMPLES]


def count_text(videos, folders):
    """ "62 videos", "1 video", "31 videos in 4 folders"."""
    text = f"{videos} video" + ("" if videos == 1 else "s")
    return text if folders <= 1 else f"{text} in {folders} folders"


def folder_id(path):
    """A short id that names the folder without giving its path away; the
    same folder gets the same id each time it is found."""
    return hashlib.sha256(os.fsencode(path)).hexdigest()[:16]


def _join(parts):
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


STATE_NOTES = {NOT_READY: " (not ready yet)", UNREADABLE: " (couldn't be read)",
               PARTIAL: " (only partly searched)"}


def checked_text(places):
    """What was really checked, in plain words: "Internal storage, and no SD
    card found", "Internal storage and SD card (not ready yet)"."""
    text = _join([p.name + STATE_NOTES.get(p.state, "") for p in places])
    if not any(p.kind == "sd" for p in places):
        text += ", and no SD card found"
    return text


def _where(place):
    """A place's name inside a sentence: "internal storage", "the SD card",
    "SD card 2"."""
    name = place.name if place.kind in ("sd", "usb") else place.name[0].lower() + place.name[1:]
    return name if place.kind == "internal" or name[-1].isdigit() else "the " + name


def _named(places, state):
    names = [_where(p) for p in places if p.state == state]
    return _join(names) if names else ""


def _not_ready_words(places):
    """ "found the SD card isn't ready yet", or "" when every card is ready."""
    if not _named(places, NOT_READY):
        return ""
    several = sum(p.state == NOT_READY for p in places) > 1
    return f"found {_named(places, NOT_READY)} {'aren' if several else 'isn'}'t ready yet"


def _out_of_time_sentence(places):
    return f"Kettle ran out of time looking through {_named(places, PARTIAL)}, so it may have missed some."


def _unreadable_sentence(places):
    return f"Kettle couldn't read {_named(places, UNREADABLE)}."


def gaps_text(places):
    """What screens 1 and 2 say above their list when the search didn't see
    everything (the first onboarding review fixes): a card that isn't ready, a search that ran out of
    time, storage that can't be read. Empty when it did; finding no card at
    all is not a gap, and a card that isn't ready is never called missing."""
    sentences = []
    if _not_ready_words(places):
        several = sum(p.state == NOT_READY for p in places) > 1
        sentences.append(f"Kettle {_not_ready_words(places)}, so {'their' if several else 'its'} folders aren't listed.")
    if _named(places, PARTIAL):
        sentences.append(_out_of_time_sentence(places))
    if _named(places, UNREADABLE):
        sentences.append(_unreadable_sentence(places))
    return " ".join(sentences + ["Press Y to look again."]) if sentences else ""


def looked_text(places):
    """Where the search looked, as the "No videos found yet" screen says it
    (the No videos found screen). Built only from what was really checked: "no SD card" only
    when no card was found, and a card that can't be read yet is "not ready",
    never missing or empty. Every sentence is about Kettle, so the screen's
    next one, "It plays videos...", can only mean Kettle."""
    looked = [("in " if p.kind == "internal" else "on ") + _where(p) for p in places if p.state == OK]
    no_card = not any(p.kind == "sd" for p in places)
    not_ready = _not_ready_words(places)
    sentences = []
    if looked:
        joining = ", and " if len(looked) > 1 else " and "
        if no_card:
            sentences.append(f"Kettle looked {_join(looked)}{joining}found no SD card.")
        elif not_ready:
            sentences.append(f"Kettle looked {_join(looked)}{joining}{not_ready}.")
            not_ready = ""
        else:
            sentences.append(f"Kettle looked {_join(looked)}.")
    elif no_card:
        sentences.append("Kettle found no SD card.")
    if _named(places, PARTIAL):
        sentences.append(_out_of_time_sentence(places))
    if _named(places, UNREADABLE):
        sentences.append(_unreadable_sentence(places))
    if not_ready:
        sentences.append(f"Kettle {not_ready}.")
    return " ".join(sentences)


@dataclass
class Suggestion:
    id: str
    path: str           # full path: never sent to the page
    place: Place
    trail: List[str]    # folder names from the place's top down to it; [] for the whole place
    videos: int
    folders: int
    examples: List[str]
    count: Optional[str] = None  # the count's words, when they aren't count_text's
    problem: Optional[str] = None  # why it can't be chosen, in the words its row shows


def folder_answer(s):
    """One folder as the page gets it: no full path."""
    return {
        "id": s.id,
        "place": s.place.name,
        "name": s.trail[-1] if s.trail else "",
        "whole_place": not s.trail,
        "trail": list(s.trail),
        "videos": s.videos,
        "folders": s.folders,
        "count_text": s.count or count_text(s.videos, s.folders),
        "examples": list(s.examples),
        "problem": s.problem,
    }


def _inside(path, root):
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def _place_and_trail(path, places):
    """The deepest place holding this folder, and the names down to it. Outside
    every place only its own name is known to the page, never what is above it."""
    holders = [(os.path.realpath(p.root), p) for p in places]
    holders = [(root, p) for root, p in holders if _inside(path, root)]
    if not holders:
        name = os.path.basename(path)
        return Place("other", SOMEWHERE_ELSE, os.path.dirname(path)), [name] if name else []
    root, place = max(holders, key=lambda holder: len(holder[0]))
    rel = os.path.relpath(path, root)
    return place, [] if rel == "." else rel.split(os.sep)


def place_path(path, places=None):
    """Where a folder is, as the result screen says it (the first scan screen): the place
    and the folder's own name, "SD card › Films", or the place alone for a
    whole place. Never anything above or between them."""
    place, trail = _place_and_trail(os.path.realpath(path), list_places() if places is None else places)
    return f"{place.name} › {trail[-1]}" if trail else place.name


def picked(path, search_result=None, time_limit=TIME_LIMIT):
    """A folder someone chose in the system's dialog (the Browse somewhere else work), as a
    Suggestion like any found folder. A folder the search already found comes
    back as that one, with its id; the walk only reads. Unlike a suggestion it
    may hold no videos, or be too big to count in time, and its words say so.
    A folder that can't be read is never called empty (the first onboarding review fixes): it can't be
    chosen, and one with only unreadable parts says what it did read."""
    path = os.path.realpath(path)
    for s in search_result.suggestions if search_result else []:
        if os.path.realpath(s.path) == path:
            return s
    places = search_result.places if search_result else list_places()
    place, trail = _place_and_trail(path, places)
    walker = _Walk(time.monotonic() + time_limit)
    folder = walker.walk(path)
    problem = None
    if folder.unreadable:
        count, problem = "Couldn't be read", CANT_BE_READ
    elif walker.out_of_time:
        count = f"At least {count_text(folder.total, 1)}" if folder.total else "Too big to search in time"
    elif folder.total:
        count = None
    else:
        count = "No videos found in the parts Kettle could read" if walker.unreadable_part else "No videos found"
    return Suggestion(folder_id(path), path, place, trail, folder.total, folder.holding,
                      examples(folder, not trail), count, problem)


class FolderSearch:
    """The result of one search: the places checked and the folders found."""

    def __init__(self, places, suggestions, seconds):
        self.places = places
        self.suggestions = suggestions
        self.seconds = seconds

    def answer(self):
        """What the page gets: no full path, only ids, names and counts."""
        groups = []
        for place in self.places:
            folders = [folder_answer(s) for s in self.suggestions if s.place is place]
            groups.append({"name": place.name, "kind": place.kind, "state": place.state,
                           "folders": folders})
        return {
            "places": groups,
            "checked": checked_text(self.places),
            "looked": looked_text(self.places),
            "gaps": gaps_text(self.places),
            "sd_card_found": any(p.kind == "sd" for p in self.places),
        }

    def log_line(self):
        """One line for the launch log: counts and kinds only, never a name."""
        states = ", ".join(f"{p.kind} {p.state}" for p in self.places)
        return (f"onboarding: looked for folders in {len(self.places)} places ({states}), "
                f"found {len(self.suggestions)} folders in {self.seconds:.3f} s")


def _readable(root):
    try:
        with os.scandir(root) as it:
            next(it, None)
        return True
    except OSError:
        return False


def search(places=None, time_limit=TIME_LIMIT):
    """Look in every place at once and return a FolderSearch. Only reads."""
    start = time.monotonic()
    places = list_places() if places is None else places
    walker = _Walk(start + time_limit)
    found = []
    for place in places:
        if not _readable(place.root):
            # A card's folder that exists but can't be read is a card that
            # isn't ready yet (the Deck, just after it goes in), not an
            # empty one.
            place.state = UNREADABLE if place.kind == "internal" else NOT_READY
            continue
        walker.out_of_time = False
        top = walker.walk(place.root)
        if walker.out_of_time:
            place.state = PARTIAL
        for folder in suggest(top):
            rel = os.path.relpath(folder.path, place.root)
            trail = [] if rel == "." else rel.split(os.sep)
            found.append(Suggestion(folder_id(folder.path), folder.path, place, trail,
                                    folder.total, folder.holding, examples(folder, not trail)))
    return FolderSearch(places, found, time.monotonic() - start)
