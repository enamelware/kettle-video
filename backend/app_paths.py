# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Where this copy of the app keeps its settings, data and logs (the installer work).

Two kinds of copy:

- A development copy (this git folder on the Deck and the Nova, or any
  unpacked folder): everything stays where it always was, inside the app
  folder: settings.json, data/ and logs/.
- An installed copy, made by installer/install.sh: the installer leaves a
  mark file in the app folder (INSTALL_MARK in installer/names.env). Its
  settings, data and logs then live outside the app files, in Linux's
  standard places in the home folder (the designer's decision on the installer work), so an
  update can replace the app files without touching them:

    settings  $XDG_CONFIG_HOME/<APP_ID>/settings.json  (~/.config/...)
    data      $XDG_DATA_HOME/<APP_ID>/data             (~/.local/share/...)
    logs      $XDG_STATE_HOME/<APP_ID>/logs            (~/.local/state/...)

  The app files themselves are in $XDG_DATA_HOME/<APP_ID>/app, a shortcut
  to the current version's folder in versions/ beside it (installer/
  update.py, the installer's update step); the mark is found through it. Each XDG
  variable counts only when it is set to an absolute path, as the XDG rules
  say; otherwise the usual place in the home folder is used.

Names come from installer/names.env, the one place the installer series
keeps them. Pure logic apart from reading that file and checking the mark.

    python3 -m backend.app_paths logs     prints this copy's logs folder

installer/install.sh works out the same installed places in shell;
tests/test_installer.py keeps the two in step. installer/uninstall.sh
repeats the same folder rule in shell too; tests/test_uninstaller.py keeps
it in step. tools/release.py reads names.env with read_names() below.
"""

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

NAMES_FILE = Path("installer") / "names.env"
# Used only if names.env can't be read.
DEFAULT_APP_ID = "kettle-video"
DEFAULT_INSTALL_MARK = "kettle-video-installed"


def read_names(text: str) -> dict:
    """{KEY: value} from names.env's KEY="value" lines."""
    names = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        names[key.strip()] = value
    return names


def names(app_dir: Path) -> dict:
    try:
        found = read_names((Path(app_dir) / NAMES_FILE).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        found = {}
    found.setdefault("APP_ID", DEFAULT_APP_ID)
    found.setdefault("INSTALL_MARK", DEFAULT_INSTALL_MARK)
    return found


def _xdg(environ: Mapping[str, str], name: str, home: Path, fallback: str) -> Path:
    value = environ.get(name, "")
    if value and os.path.isabs(value):
        return Path(value)
    return home / fallback


@dataclass(frozen=True)
class AppPaths:
    app_dir: Path
    settings_file: Path
    data_dir: Path
    logs_dir: Path
    installed: bool


def install_places(app_id: str, environ: Mapping[str, str] = os.environ) -> dict:
    """The installed copy's folders, whether or not it is installed yet."""
    home = Path(environ.get("HOME") or Path.home())
    share = _xdg(environ, "XDG_DATA_HOME", home, ".local/share") / app_id
    return {
        "APP_DIR": share / "app",
        "DATA_DIR": share / "data",
        "CONFIG_DIR": _xdg(environ, "XDG_CONFIG_HOME", home, ".config") / app_id,
        "LOGS_DIR": _xdg(environ, "XDG_STATE_HOME", home, ".local/state") / app_id / "logs",
    }


def is_installed(app_dir: Path) -> bool:
    return (Path(app_dir) / names(app_dir)["INSTALL_MARK"]).is_file()


def for_app(app_dir: Path, environ: Optional[Mapping[str, str]] = None) -> AppPaths:
    """Where the copy in app_dir keeps its settings, data and logs."""
    app_dir = Path(app_dir)
    environ = os.environ if environ is None else environ
    if not is_installed(app_dir):
        return AppPaths(app_dir, app_dir / "settings.json", app_dir / "data",
                        app_dir / "logs", False)
    places = install_places(names(app_dir)["APP_ID"], environ)
    return AppPaths(app_dir, places["CONFIG_DIR"] / "settings.json", places["DATA_DIR"],
                    places["LOGS_DIR"], True)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    app_dir = Path(__file__).resolve().parent.parent
    if argv == ["logs"]:
        print(for_app(app_dir).logs_dir)
        return 0
    print("usage: python3 -m backend.app_paths logs", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
