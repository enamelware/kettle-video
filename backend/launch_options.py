# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Where the app keeps its data, and the two testing launch options
(the fresh start mode). Pure logic apart from the fresh-start folder itself.

The data folder is chosen here, once, at launch, and nowhere else: the
folder named by settings.json's data_dir (data/ in the app folder unless
it says otherwise), exactly as before; or, with fresh start on, a new
empty folder in a temporary place.

The options come from environment variables, which Steam's launch options
set ("KETTLE_FRESH_START=1 %command%") and launch.sh passes on unchanged:

  KETTLE_FRESH_START=1     open as a brand-new user would: an empty data
                           folder, and mpv's own empty resume folder
                           (watch_later) beside it, both in one temporary
                           folder that is deleted when the app quits. The
                           real data folder and mpv's real resume positions
                           are never read or written. Both media folders
                           count as not set, so onboarding shows, and the
                           ones chosen are saved in that temporary folder
                           (the fresh start onboarding work): the real settings.json is only read,
                           for every other setting.
  KETTLE_PRETEND_NO_MPV=1  behave as if mpv were not installed, to see the
                           "mpv not found" screen. Can be combined with
                           fresh start.

The only thing this module ever deletes is a fresh-start folder: a folder
directly in the temporary place, named kettle-fresh-..., owned by this
user, not a link, holding the mark file the app wrote when it made it,
and not in use by a running copy of the app. Nothing else.
"""

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

FRESH_START = "KETTLE_FRESH_START"
PRETEND_NO_MPV = "KETTLE_PRETEND_NO_MPV"

# Under /tmp, like mpv's other folders: the Flatpak mpv can write its
# resume positions only there (docs/spikes/mpv-quit.md).
FRESH_PARENT = Path("/tmp")
FRESH_PREFIX = "kettle-fresh-"
# Written into every fresh-start folder the app makes; a folder without
# it is never deleted.
MARK_NAME = "kettle-fresh-start"
MARK_FIRST_LINE = "Kettle Video fresh-start folder: deleted when the app quits."
DATA_NAME = "data"
WATCH_LATER_NAME = "watch_later"
# Created there when the folders are chosen, and never read back: the choice
# lasts this session, and a next fresh start makes a new folder (the fresh start onboarding work).
SESSION_SETTINGS_NAME = "settings.json"

_ON = ("1", "true", "yes", "on")


def is_on(environ: Mapping[str, str], name: str) -> bool:
    """An option is on when its variable is 1, true, yes or on."""
    return environ.get(name, "").strip().lower() in _ON


@dataclass(frozen=True)
class LaunchOptions:
    data_dir: Path
    # Fresh start only: the temporary folder holding everything, and mpv's
    # resume folder inside it. None in normal use.
    fresh_root: Optional[Path] = None
    watch_later_dir: Optional[Path] = None
    pretend_no_mpv: bool = False

    @property
    def fresh_start(self) -> bool:
        return self.fresh_root is not None


def choose(settings: dict, environ: Mapping[str, str] = os.environ,
           fresh_parent: Path = FRESH_PARENT) -> LaunchOptions:
    """The data folder and options for this launch. With fresh start on,
    leftovers from an earlier fresh start are cleaned up first, then a new
    folder is made."""
    pretend = is_on(environ, PRETEND_NO_MPV)
    if not is_on(environ, FRESH_START):
        return LaunchOptions(data_dir=Path(settings["data_dir"]), pretend_no_mpv=pretend)
    clean_leftovers(fresh_parent)
    root = make_fresh(fresh_parent)
    return LaunchOptions(
        data_dir=root / DATA_NAME, fresh_root=root, watch_later_dir=root / WATCH_LATER_NAME,
        pretend_no_mpv=pretend,
    )


def for_session(settings: dict, options: LaunchOptions, settings_file: Path):
    """This launch's settings, and the one file onboarding may save the
    folders to. In normal use that is settings_file, with the settings as
    they are, apart from the data folder chosen above. In fresh start both
    folders count as not set and the file is in the temporary folder, so
    nothing in the session can reach the real one (the fresh start onboarding work)."""
    session = {**settings, "data_dir": str(options.data_dir)}
    if not options.fresh_start:
        return session, settings_file
    session.update(movies_path="", tv_path="")
    return session, options.fresh_root / SESSION_SETTINGS_NAME


def make_fresh(parent: Path = FRESH_PARENT) -> Path:
    """A new, empty fresh-start folder, readable only by this user, with
    its mark file and two empty folders: the app's data and mpv's
    resume positions."""
    root = Path(tempfile.mkdtemp(prefix=FRESH_PREFIX, dir=parent))
    (root / MARK_NAME).write_text(f"{MARK_FIRST_LINE}\npid {os.getpid()}\n", encoding="utf-8")
    (root / DATA_NAME).mkdir()
    (root / WATCH_LATER_NAME).mkdir()
    return root


def _mark_pid(folder: Path) -> Optional[int]:
    """The app copy that made this folder, from its mark file, or None if
    the folder isn't one the app made (no mark file, or not the app's)."""
    mark = folder / MARK_NAME
    try:
        if not mark.is_file() or mark.is_symlink():
            return None
        lines = mark.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    if len(lines) < 2 or lines[0] != MARK_FIRST_LINE or not lines[1].startswith("pid "):
        return None
    pid = lines[1].removeprefix("pid ")
    return int(pid) if pid.isdigit() else None


def _running(pid: Optional[int]) -> bool:
    if pid is None:
        return True  # can't tell: treat as in use, so it is kept
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, OverflowError):
        return False
    return True


def is_fresh_folder(folder: Path, parent: Path = FRESH_PARENT) -> bool:
    """True only for a fresh-start folder the app made: directly in
    parent, named kettle-fresh-..., a real folder (not a link) owned by
    this user, with the app's mark file."""
    folder = Path(folder)
    if folder.parent != Path(parent) or not folder.name.startswith(FRESH_PREFIX):
        return False
    try:
        info = folder.lstat()
    except OSError:
        return False
    if folder.is_symlink() or not folder.is_dir() or info.st_uid != os.getuid():
        return False
    return _mark_pid(folder) is not None


def remove_fresh(folder: Path, parent: Path = FRESH_PARENT) -> bool:
    """Delete this fresh-start folder, when the app quits. Refuses
    anything that isn't one (see is_fresh_folder). True if it went."""
    if not is_fresh_folder(folder, parent):
        return False
    shutil.rmtree(folder, ignore_errors=True)
    return not folder.exists()


def clean_leftovers(parent: Path = FRESH_PARENT) -> int:
    """Delete fresh-start folders left behind (after Steam's "Exit game"
    or a crash), skipping any whose maker is still running.
    Returns how many went."""
    removed = 0
    try:
        entries = list(Path(parent).iterdir())
    except OSError:
        return 0
    for entry in entries:
        if not is_fresh_folder(entry, parent):
            continue
        # Still in use (or its number now belongs to another program, which
        # only delays the clean-up until that one ends).
        if _running(_mark_pid(entry)):
            continue
        if remove_fresh(entry, parent):
            removed += 1
    return removed
