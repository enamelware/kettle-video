# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The privacy guard (the privacy guard work): nothing from the development devices, library
or accounts is committed or pushed.

It checks text against a private list of words, kept outside both Kettle
repos and shared with Enamel's guard (~/Development/.privacy-guard/words.txt),
plus patterns that need no list:

- a home folder written out in full (/home/<name>, /var/home/<name>,
  /run/media/<name>, /Users/<name> with a real name); only ~/ or a
  placeholder such as <user> is allowed;
- a Steam user folder (userdata/NUMBER) or a Steam ID;
- an email address other than GitHub's noreply addresses, git@github.com,
  the commits' attribution address (noreply@anthropic.com) and the made-up
  example domains;
- a picture or a log outside the approved folders.

It never prints a private word: a finding names the file, the line and the
kind of thing found. If the list is missing or empty, the guard fails.

    python3 tools/privacy_guard.py staged          what is about to be committed
    python3 tools/privacy_guard.py message FILE    a commit message
    python3 tools/privacy_guard.py push            the commits a push would send
                                                   (git's pre-push lines on stdin)
    python3 tools/privacy_guard.py tracked         every file the repo tracks
    python3 tools/privacy_guard.py files FILE...   the given files
    python3 tools/privacy_guard.py count           how many words, by category
    python3 tools/privacy_guard.py build           (re)write the list from this
                                                   device, read-only everywhere else

--list PATH uses another list (the tests use a temporary one of invented
words). The storage spike's checker (spikes/storage/privacy_check.py) now
uses this file (the privacy guard work).

The list is plain text, one entry per line. A line naming one of the
CATEGORIES in brackets, such as [films and shows], starts that category;
any other line in brackets is an entry. A line starting with # is a note. `build` rewrites every category
it fills and keeps "added by hand" as it is.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LIST = Path.home() / "Development" / ".privacy-guard" / "words.txt"

MIN_LENGTH = 4  # shorter names ("1", "e01") would match ordinary text
# Ordinary words that are folder names in many libraries, not private.
GENERIC = {"sample", "samples", "source", "subs", "subtitles", "extras",
           "featurettes", "specials", "special", "screens", "releases"}

HAND = "added by hand"
CATEGORIES = ("card labels", "user name", "films and shows", "device names",
              "network names", "bluetooth names", "steam ids", HAND)

# Stand-ins for a user name that are fine in a path, besides anything
# written as <name>, {name} or $name.
PLACEHOLDERS = {"user", "someone", "me", "u", "x"}
PLACEHOLDER_START = ("<", "{", "$")
# Only at the start of a path: /somewhere/home/Videos is not a home folder.
_NAME = r"([A-Za-z0-9_.<{$][^/\s\"'`)\],]*)"
HOME_PATH = re.compile(r"(?<![\w.~-])(?:(?:/var)?/home|/run/media|/Users)/" + _NAME)
STEAM_ID64_BASE = 0x0110000100000000  # written in hex so the guard doesn't flag itself
STEAM = re.compile(r"userdata/\d{3,}|\b7656119\d{10}\b")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# noreply@anthropic.com is the commits' public attribution line, not a person.
ALLOWED_EMAIL = re.compile(r"(?i)^(git@github\.com|[^@]+@users\.noreply\.github\.com"
                           r"|noreply@anthropic\.com"
                           r"|[^@]+@example\.(invalid|com|org|net)|[^@]+@[^@]+\.test)$")

PICTURES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".heic", ".avif",
            ".tif", ".tiff"}
LOGS = {".log"}
# Pictures the checks make from invented test data, and the app's own.
APPROVED_PICTURE_FOLDERS = ("docs/screenshots/design-system/", "ui/", "vendor/")
APPROVED_LOG_FOLDERS = ()
# Third-party files, copied unchanged: their authors' addresses and paths stay.
THIRD_PARTY = ("vendor/", "ui/fonts/")


class ListProblem(Exception):
    pass


# ---------------------------------------------------------------- the list

def read_list(path=DEFAULT_LIST):
    """{category: [entries]} from the list file. Fails if it is missing or
    holds no entries, so a lost list never lets everything through."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        raise ListProblem(f"the private word list is missing ({_shown(path)}). "
                          "The guard can't check anything without it. Make one on this device "
                          "with: python3 tools/privacy_guard.py build")
    found, category = {}, "other"
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Only the known names start a category: a film called "[Group] Title
        # [720p]" is a word, and a category name is printed in findings.
        if line.startswith("[") and line.endswith("]") and line[1:-1].strip() in CATEGORIES:
            category = line[1:-1].strip()
            continue
        found.setdefault(category, []).append(line)
    if not any(found.values()):
        raise ListProblem(f"the private word list is empty ({_shown(path)}). "
                          "The guard can't check anything without it.")
    return found


def _shown(path):
    """A path with the home folder written as ~, so messages leak nothing."""
    text, home = str(path), str(Path.home())
    return "~" + text[len(home):] if text.startswith(home + "/") else text


def _bounded(word):
    """A word matched whole: not inside a longer word (Heat is not heater)."""
    out = re.escape(word)
    if word[:1].isalnum():
        out = r"(?<![^\W_])" + out
    if word[-1:].isalnum():
        out += r"(?![^\W_])"
    return out


class Matcher:
    """Finds private words, case-insensitively, and says which category."""

    def __init__(self, categories):
        self.category = {}
        for category, words in categories.items():
            for word in words:
                self.category.setdefault(word.casefold(), category)
        words = sorted(self.category, key=len, reverse=True)
        self.pattern = re.compile("|".join(_bounded(w) for w in words), re.I) if words else None

    def kinds(self, text):
        if not self.pattern:
            return []
        return [self.category.get(m.group(0).casefold(), "private word")
                for m in self.pattern.finditer(text)]


# ---------------------------------------------------------------- checks

def _third_party(path):
    return path.startswith(THIRD_PARTY)


def line_findings(text, matcher, path=""):
    """[(line number, kind)] for one text. Third-party files are only
    checked against the list."""
    out = []
    for number, line in enumerate(text.splitlines(), 1):
        kinds = [f"private word ({k})" for k in matcher.kinds(line)]
        if not _third_party(path):
            for m in HOME_PATH.finditer(line):
                name = m.group(1)
                if not (name.startswith(PLACEHOLDER_START) or name.casefold() in PLACEHOLDERS):
                    kinds.append("home folder written out in full (use ~/ or <user>)")
            if STEAM.search(line):
                kinds.append("Steam user folder or Steam ID")
            for m in EMAIL.finditer(line):
                if not ALLOWED_EMAIL.match(m.group(0)):
                    kinds.append("email address")
        for kind in dict.fromkeys(kinds):
            out.append((number, kind))
    return out


def path_findings(path, matcher, added=True):
    """Problems with a file's own name and place: a private word in it, or a
    picture or log outside the approved folders (checked for new files)."""
    out = [f"private word ({k}) in the file's name" for k in dict.fromkeys(matcher.kinds(path))]
    ext = os.path.splitext(path)[1].lower()
    if added and ext in PICTURES and not path.startswith(APPROVED_PICTURE_FOLDERS):
        out.append("picture outside the approved folders")
    if added and ext in LOGS and not path.startswith(APPROVED_LOG_FOLDERS or ("\0",)):
        out.append("log file")
    return out


def _text(data):
    """Text of a file, or None for a binary one (pictures, fonts)."""
    if b"\0" in data[:8192]:
        return None
    return data.decode("utf-8", errors="replace")


def check_blobs(items, matcher):
    """items: (where, path, bytes, added). Returns finding lines."""
    out = []
    for where, path, data, added in items:
        for kind in path_findings(path, matcher, added):
            out.append(f"{where}: {kind}")
        text = _text(data) if data is not None else None
        if text is not None:
            for number, kind in line_findings(text, matcher, path):
                out.append(f"{where}, line {number}: {kind}")
    return out


# ---------------------------------------------------------------- git

def _git(*args, input=None, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, input=input, capture_output=True,
                          check=True).stdout


def _paths(raw):
    return [p.decode("utf-8", errors="replace") for p in raw.split(b"\0") if p]


def staged_items(cwd=None):
    out = []
    added = set(_paths(_git("diff", "--cached", "--name-only", "-z", "--diff-filter=A", cwd=cwd)))
    for path in _paths(_git("diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR", cwd=cwd)):
        data = _git("show", f":{path}", cwd=cwd)
        out.append((f"{path} (staged)", path, data, path in added))
    return out


def tracked_items(cwd=None):
    base = Path(cwd) if cwd else Path(_git("rev-parse", "--show-toplevel").decode().strip())
    out = []
    for path in _paths(_git("ls-files", "-z", cwd=cwd)):
        try:
            data = (base / path).read_bytes()
        except OSError:
            continue  # deleted and not yet staged
        out.append((path, path, data, True))
    return out


def push_items(lines, cwd=None):
    """The messages, new lines and new files of every commit a push sends
    that no remote has yet. lines: git's pre-push input."""
    out = []
    for line in lines:
        parts = line.split()
        if len(parts) != 4 or set(parts[1]) == {"0"}:
            continue  # a branch being deleted sends nothing
        log = _git("log", "--format=%x00%h%x00%B%x00", parts[1], "--not", "--remotes", cwd=cwd)
        fields = log.split(b"\0")
        for i in range(1, len(fields) - 1, 3):
            commit = fields[i].decode()
            out.append((f"commit {commit} message", "", fields[i + 1], False))
            patch = _git("show", "--format=", "--no-color", "--no-ext-diff", commit, cwd=cwd)
            added_lines = b"\n".join(l[1:] for l in patch.split(b"\n")
                                     if l.startswith(b"+") and not l.startswith(b"+++"))
            out.append((f"commit {commit} changes", "", added_lines, False))
            new = _paths(_git("show", "--format=", "--name-only", "-z", "--diff-filter=AR",
                              commit, cwd=cwd))
            for path in new:
                out.append((f"commit {commit}: {path}", path, None, True))
    return out


# ---------------------------------------------------------------- build

def card_words(places, walk, suggest, season_like):
    """The private words on the cards: each card's label and the name of
    every film, show, season and episode inside the folders the onboarding
    rule suggests. places: [{"kind", "path", "label"}]; walk(path) returns
    the folder tree that suggest() takes (the storage spike's checker, the storage spike)."""
    labels, titles = set(), set()
    for place in places:
        if place["kind"] == "internal":
            continue
        if place["label"]:
            labels.add(place["label"])
        for folder in suggest(walk(place["path"])):
            for dirpath, dirnames, filenames in os.walk(folder.path):
                for name in dirnames + filenames:
                    stem = os.path.splitext(name)[0] if name in filenames else name
                    for word in (name, stem):
                        if (len(word) >= MIN_LENGTH and word.casefold() not in GENERIC
                                and not season_like(word)):
                            titles.add(word)
    return labels, titles


def user_paths(home=None):
    user = os.path.basename(home or os.path.expanduser("~"))
    return {f"/home/{user}", f"/var/home/{user}", f"/run/media/{user}"}


def _run(*command):
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


GENERIC_DEVICE = {"steamdeck", "localhost", "lo"}
GENERIC_NETWORK = re.compile(r"(?i)^(wired connection \d+|lo|docker\d*|virbr\d+)$")


def device_words():
    """Read-only: this device's name, saved network names, paired Bluetooth
    devices and Steam accounts (from the folder names only; no account file
    is opened). Anything that can't be read is left out."""
    found = {"device names": set(), "network names": set(),
             "bluetooth names": set(), "steam ids": set()}
    try:
        host = Path("/etc/hostname").read_text().strip()
    except OSError:
        host = ""
    if host and host.casefold() not in GENERIC_DEVICE:
        found["device names"].add(host)
    for line in _run("nmcli", "-t", "-f", "NAME", "connection", "show").splitlines():
        name = line.replace("\\:", ":").strip()
        if len(name) >= MIN_LENGTH and not GENERIC_NETWORK.match(name):
            found["network names"].add(name)
    for line in _run("bluetoothctl", "devices").splitlines():
        parts = line.split(" ", 2)
        if len(parts) == 3 and parts[0] == "Device":
            found["bluetooth names"].add(parts[2].strip())
            found["bluetooth names"].add(parts[1].strip())
    for steam in (Path.home() / ".local/share/Steam/userdata", Path.home() / ".steam/steam/userdata"):
        try:
            names = [p.name for p in steam.iterdir()]
        except OSError:
            continue
        for name in names:
            if name.isdigit() and name != "0":
                found["steam ids"].update({name, str(int(name) + STEAM_ID64_BASE)})
    return found


def build(path=DEFAULT_LIST):
    """Write the list from this device. Only reads the cards and the system;
    writes only the list. Keeps whatever was added by hand."""
    sys.path.insert(0, str(ROOT))
    from backend import folder_finder as ff

    def walk(top):
        return ff._Walk(deadline=float("inf")).walk(top)

    places = [{"kind": p.kind, "path": p.root, "label": os.path.basename(p.root)}
              for p in ff.list_places()]
    labels, titles = card_words(places, walk, ff.suggest, lambda w: bool(ff.SEASON_LIKE.match(w)))
    words = {"card labels": labels, "user name": user_paths(), "films and shows": titles}
    words.update(device_words())
    try:
        words[HAND] = set(read_list(path).get(HAND, []))
    except ListProblem:
        words[HAND] = set()
    lines = ["# Kettle privacy guard: private words, one per line (the privacy guard work).",
             "# Never commit, print, paste or upload this file.",
             "# `python3 tools/privacy_guard.py build` rewrites every category but the last."]
    for category in CATEGORIES:
        lines += ["", f"[{category}]", *sorted(words.get(category, ()), key=str.casefold)]
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)
    return {c: len(words.get(c, ())) for c in CATEGORIES}


# ---------------------------------------------------------------- command line

def report(findings, what):
    for line in findings:
        print(f"PRIVATE: {line}")
    if findings:
        print(f"Privacy guard: {len(findings)} problems in {what}. Nothing was committed "
              "or pushed. Remove them, or use invented names, then try again.")
        return 1
    print(f"Privacy guard: {what} clean.")
    return 0


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    path = DEFAULT_LIST
    if "--list" in args:
        i = args.index("--list")
        path = Path(args[i + 1])
        del args[i:i + 2]
    command = args.pop(0) if args else ""
    if command == "build":
        counts = build(path)
        print("Privacy guard: list written. Entries by category: "
              + ", ".join(f"{c} {n}" for c, n in counts.items()))
        return 0
    try:
        categories = read_list(path)
    except ListProblem as problem:
        print(f"Privacy guard FAILED: {problem}")
        return 2
    if command == "count":
        print("Privacy guard: entries by category: "
              + ", ".join(f"{c} {len(w)}" for c, w in categories.items()))
        return 0
    matcher = Matcher(categories)
    if command == "staged":
        return report(check_blobs(staged_items(), matcher), "the staged changes")
    if command == "tracked":
        return report(check_blobs(tracked_items(), matcher), "the tracked files")
    if command == "message" and len(args) == 1:
        data = Path(args[0]).read_bytes()
        message = b"\n".join(l for l in data.split(b"\n") if not l.startswith(b"#"))
        return report(check_blobs([("commit message", "", message, False)], matcher),
                      "the commit message")
    if command == "push":
        return report(check_blobs(push_items(sys.stdin.read().splitlines()), matcher),
                      "the commits to push")
    if command == "files" and args:
        items = [(p, p, Path(p).read_bytes(), False) for p in args]
        return report(check_blobs(items, matcher), "the given files")
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
