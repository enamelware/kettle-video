# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Where mpv keeps the resume positions for this copy of the app (the
each-copy-its-own-data work).

Resume itself stays mpv's own (docs/decisions.md, "Resume"): mpv saves a
small file per video in a "watch_later" folder. Which folder:

- A development copy: mpv's own folder, as always (nothing is passed).
- The installed copy: a folder of its own, so it never reads or changes a
  development copy's positions, and the uninstaller can delete it with the
  rest of the installed copy's data:
    - with a normal mpv: watch_later/ in the data folder;
    - with the Flatpak mpv, which can write only to /tmp and its own folder
      (docs/spikes/mpv-quit.md): ~/.var/app/io.mpv.Mpv/data/<APP_ID>/watch_later.
  installer/uninstall.sh finds the second one the same way
  (tests/test_each_copy_own_data.py keeps the two in step).
- Fresh start: its own temporary folder (backend/launch_options.py), which
  wins over everything.
- A --watch-later-dir the viewer set in mpv_args wins over the installed
  copy's own folder: their choice, as for every other option.

Carrying over. Before this work every copy used mpv's own folder. The first
time the installed copy plays something after updating from that layout,
the files in mpv's own folder (only read, never changed) are copied into
its new folder, once. A brand-new install, including one after an
uninstall that deleted the data, never copies anything: it starts with no
positions. Which of the two it is, is noted at the first launch of this
version, in CARRY_FILE in the data folder: an update has a saved library
there already; a brand-new install doesn't.

Nothing here logs a file name or a path in the media folders.
"""

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Callable, Mapping, Optional

FOLDER_NAME = "watch_later"
# In the data folder: whether the positions in mpv's own folder still have
# to be carried over.
CARRY_FILE = "resume_positions.json"
FLATPAK_ID = "io.mpv.Mpv"
# The Flatpak mpv's own data folder, relative to the home folder (Flatpak
# keeps every app's folder here, whatever the XDG variables say).
FLATPAK_DATA = Path(".var") / "app" / FLATPAK_ID / "data"


def _home(environ: Mapping[str, str]) -> Path:
    return Path(environ.get("HOME") or Path.home())


def _xdg(environ: Mapping[str, str], name: str, home: Path, fallback: str) -> Path:
    value = environ.get(name, "")
    return Path(value) if value and os.path.isabs(value) else home / fallback


def is_flatpak(command) -> bool:
    """mpv run through `flatpak run io.mpv.Mpv`."""
    command = list(command or ())
    return bool(command) and Path(command[0]).name == "flatpak" and FLATPAK_ID in command[1:]


def flatpak_folder(app_id: str, environ: Mapping[str, str] = os.environ) -> Path:
    """The folder in the Flatpak mpv's own data folder that belongs to the
    installed copy (the uninstaller deletes it with the data)."""
    return _home(environ) / FLATPAK_DATA / app_id


def own_folder(data_dir: Path, app_id: str, command,
               environ: Mapping[str, str] = os.environ) -> Path:
    """The installed copy's own resume folder for the mpv in command."""
    if is_flatpak(command):
        return flatpak_folder(app_id, environ) / FOLDER_NAME
    return Path(data_dir) / FOLDER_NAME


def mpv_folders(command, environ: Mapping[str, str] = os.environ) -> list:
    """Where mpv keeps its positions by default, newest layout first: its
    state folder (mpv 0.36 and later), then its settings folder (earlier
    versions). Inside the Flatpak's own folder for the Flatpak mpv."""
    home = _home(environ)
    if is_flatpak(command):
        base = home / ".var" / "app" / FLATPAK_ID
        return [base / ".local" / "state" / "mpv" / FOLDER_NAME,
                base / "config" / "mpv" / FOLDER_NAME]
    return [_xdg(environ, "XDG_STATE_HOME", home, ".local/state") / "mpv" / FOLDER_NAME,
            _xdg(environ, "XDG_CONFIG_HOME", home, ".config") / "mpv" / FOLDER_NAME]


def sets_its_own(mpv_args) -> bool:
    """mpv_args already says where mpv keeps its positions."""
    return any(a.lstrip("-").split("=", 1)[0] == "watch-later-dir" for a in mpv_args or ())


# --- Carrying over ---


def note_first_launch(data_dir: Path, had_library: bool) -> None:
    """At every launch of the installed copy (not fresh start), before
    anything is scanned: the first time, note whether this is an update
    from the shared layout (a saved library already there) or a brand-new
    install. Later launches change nothing."""
    path = Path(data_dir) / CARRY_FILE
    if path.exists():
        return
    _write_carry(path, had_library)


def _write_carry(path: Path, carry: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps({"carry_over": bool(carry)}) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _carry_pending(data_dir: Path) -> bool:
    try:
        stored = json.loads((Path(data_dir) / CARRY_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return False
    return isinstance(stored, dict) and stored.get("carry_over") is True


def prepare(folder: Path, data_dir: Path, sources, log: Callable[[str], None]) -> None:
    """Make the installed copy's resume folder before mpv starts, if it
    isn't there yet. When an update from the shared layout is still to be
    carried over, it starts with a copy of the files in sources (mpv's own
    folders, only read); otherwise it starts empty. Made beside its final
    place and renamed into it, so a copy cut short is never half there."""
    folder = Path(folder)
    if folder.is_dir():
        return
    carry = _carry_pending(data_dir)
    try:
        folder.parent.mkdir(parents=True, exist_ok=True)
        temp = Path(tempfile.mkdtemp(prefix=f".{FOLDER_NAME}-", dir=folder.parent))
    except OSError as exc:
        log(f"resume positions: couldn't make this copy's folder ({type(exc).__name__})")
        return
    copied = 0
    if carry:
        for source in sources:
            copied += _copy_files(Path(source), temp)
    try:
        os.rename(temp, folder)
    except OSError:
        shutil.rmtree(temp, ignore_errors=True)
        if not folder.is_dir():
            log("resume positions: couldn't make this copy's folder")
            return
    if carry:
        log(f"resume positions: carried over {copied} from mpv's own folder (only read)")
        try:
            _write_carry(Path(data_dir) / CARRY_FILE, False)
        except OSError as exc:
            log(f"resume positions: couldn't note the carry-over ({type(exc).__name__})")


def _copy_files(source: Path, target: Path) -> int:
    """Copy the plain files in source into target, never over one already
    there. Shortcuts and folders are left out. The number copied."""
    copied = 0
    try:
        if source.is_symlink() or not source.is_dir():
            return 0
        entries = sorted(source.iterdir())
    except OSError:
        return 0
    for entry in entries:
        try:
            if entry.is_symlink() or not entry.is_file() or (target / entry.name).exists():
                continue
            shutil.copyfile(entry, target / entry.name)
            copied += 1
        except OSError:
            continue
    return copied


def folder_for_play(installed: bool, fresh_dir: Optional[Path], data_dir: Path, app_id: str,
                    command, mpv_args, resume: bool, log: Callable[[str], None],
                    environ: Mapping[str, str] = os.environ) -> Optional[Path]:
    """The --watch-later-dir to give mpv for this film, or None for mpv's
    own folder. The installed copy's folder is made (and carried over) here,
    with resume on."""
    if fresh_dir is not None:
        return fresh_dir
    if not installed or sets_its_own(mpv_args):
        return None
    folder = own_folder(data_dir, app_id, command, environ)
    if resume:
        try:
            prepare(folder, data_dir, mpv_folders(command, environ), log)
        except Exception as exc:  # playback never depends on it: mpv makes the folder itself
            log(f"resume positions: couldn't get this copy's folder ready ({type(exc).__name__})")
    return folder
