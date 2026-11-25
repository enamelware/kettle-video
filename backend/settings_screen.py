# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The Settings screen (the Settings screen work). Pure logic, no HTTP awareness.

- problem(): why a folder can't become this kind's folder, in the words the
  row shows, or None. TV shows' refusals are onboarding's own, word for word;
  for movies the same checks name the TV shows folder instead. Stopping one
  kind while the other isn't set is refused: Kettle needs one folder.
- same_folder(): the choice changes nothing (no save, no rescan).
- folders(): each kind's folder as the page shows it: its place path
  ("SD card › Films") and its id, never a full path.
- version(), credits(), licence_text(): the About section. The credits are
  read from THIRD_PARTY_LICENSES.md, so About always matches it, and each
  bundled one's licence text from the file next to it; the page asks for a
  text by the credit's id, never by a file path.
"""

import os
import re
from pathlib import Path
from typing import Optional

from backend import folder_finder, onboarding

KINDS = tuple(onboarding.KEYS)

# For movies, the refusals onboarding gives on its TV shows screen, seen from
# the other side.
SAME_TV = "Already your TV shows folder. Movies and TV shows need separate folders, so pick a different one."
INSIDE_TV = "This folder is inside your TV shows folder, so pick a different one."
HOLDS_TV = "Your TV shows folder is inside this one, so pick a different one."
MIRRORED = {onboarding.SAME: SAME_TV, onboarding.INSIDE_MOVIES: HOLDS_TV, onboarding.HOLDS_MOVIES: INSIDE_TV}
# "Stop using ..." when the other kind isn't set either.
KEEP_ONE = {
    "movies": "Your TV shows folder isn't set, and Kettle needs at least one folder, so keep this one.",
    "tv": "Your movies folder isn't set, and Kettle needs at least one folder, so keep this one.",
}
# The one-scan-at-a-time rule: a folder can't change under a running scan.
SCANNING = "Kettle is reading your folders. Choose again when it has finished."

APP_LICENCE = "GPL-3.0-or-later"
NOT_AFFILIATED = "Kettle Video is not affiliated with Valve."
LICENCES_FILE = "THIRD_PARTY_LICENSES.md"
NOT_BUNDLED_NOTE = "Not bundled: Kettle Video launches the copy already installed on this device."
# Each bundled credit's licence text, by its name in THIRD_PARTY_LICENSES.md.
LICENCE_FILES = {
    "guessit": "vendor/guessit.LICENSE",
    "rebulk": "vendor/rebulk.LICENSE",
    "babelfish": "vendor/babelfish.LICENSE",
    "python-dateutil": "vendor/python-dateutil.LICENSE",
    "six": "vendor/six.LICENSE",
    "Enamel": "vendor/enamel/LICENSE",
    "Rubik Mono One (Regular)": "ui/fonts/RubikMonoOne-OFL.txt",
}


def problem(kind: str, chosen: Optional[str], other: Optional[str]) -> Optional[str]:
    """None when chosen (None for "Stop using ...") can be saved as kind's
    folder while the other kind's folder is other ("" or None: not set)."""
    if not chosen:
        return None if other else KEEP_ONE[kind]
    if kind == "tv":
        return onboarding.problem(other or None, chosen)
    found = onboarding.problem(chosen, other or None)
    return MIRRORED.get(found, found)


def same_folder(chosen: Optional[str], current: Optional[str]) -> bool:
    if not chosen or not current:
        return not chosen and not current
    return os.path.realpath(chosen) == os.path.realpath(current)


def folders(settings: dict, places=None) -> dict:
    """Each kind as the Settings rows show it: set or not, its place path and
    its id (the folder search's id for the same folder, for its badge)."""
    answer = {}
    for kind, key in onboarding.KEYS.items():
        path = settings.get(key) or ""
        if not path:
            answer[kind] = {"set": False}
            continue
        real = os.path.realpath(path)
        answer[kind] = {"set": True, "path": folder_finder.place_path(real, places),
                        "id": folder_finder.folder_id(real)}
    return answer


def version(root: Path) -> str:
    try:
        return (Path(root) / "VERSION").read_text(encoding="utf-8").strip() or "unknown"
    except (OSError, UnicodeDecodeError):
        return "unknown"


def _plain(cell: str) -> str:
    """A table cell without its markdown: links keep their words, backticks go."""
    cell = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", cell)
    return cell.replace("`", "").replace("**", "").strip()


def _first_link(cell: str) -> Optional[str]:
    match = re.search(r"\]\((https://[^)]+)\)", cell)
    return match.group(1) if match else None


def credit_id(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def short_licence(licence: str) -> str:
    """The licence alone, for a credit's row: without a copyright line or a
    pointer to the licence file, both shown with its licence text. Keeps a
    row short enough to fit above the hint bar in Enamel's smallest box."""
    short = re.split(r",\s*Copyright\b", licence, maxsplit=1)[0]
    return re.sub(r"\s*\(see its licen[cs]e file\)", "", short, flags=re.I).strip()


def credits(root: Path) -> list:
    """Every entry of THIRD_PARTY_LICENSES.md's tables, in order: name,
    version, licence (in full, and short for its row), and either its licence text's id (bundled) or a note
    and a link (used but not bundled). [] if the file can't be read."""
    try:
        text = (Path(root) / LICENCES_FILE).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    found, header = [], None
    for line in text.splitlines():
        if not line.startswith("|"):
            header = None
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if header is None:
            header = [c.lower() for c in cells]
            continue
        if all(set(c) <= set("-: ") for c in cells):
            continue
        row = dict(zip(header, cells))
        name = _plain(cells[0])
        licence = next((_plain(v) for k, v in row.items() if k.startswith("licen")), "")
        credit = {"id": credit_id(name), "name": name, "version": _plain(row.get("version", "")),
                  "licence": licence, "short": short_licence(licence)}
        if name in LICENCE_FILES:
            credit["bundled"] = True
        else:
            credit.update(bundled=False, note=NOT_BUNDLED_NOTE, link=_first_link(row.get("source", "")))
        found.append(credit)
    return found


def licence_text(root: Path, credit: str) -> Optional[dict]:
    """{name, text} for a bundled credit's id, else None."""
    for entry in credits(root):
        if entry["id"] == credit and entry["bundled"]:
            try:
                text = (Path(root) / LICENCE_FILES[entry["name"]]).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                return None
            return {"name": entry["name"], "text": text}
    return None


def about(root: Path) -> dict:
    return {"version": version(root), "licence": APP_LICENCE, "credits": credits(root),
            "not_affiliated": NOT_AFFILIATED}


def log_line(kind: str, chosen: Optional[str]) -> str:
    """For the launch log: what changed, never which folder."""
    return f"settings: {kind} folder {'changed' if chosen else 'stopped'}, settings saved"
