# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Load settings.json. Pure logic, no HTTP awareness."""

import json
import os
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlsplit

from backend import app_paths

DEFAULT_MPV_COMMAND = "auto"


class SettingsError(Exception):
    pass


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def clean_path(raw: str) -> str:
    """Make a settings.json folder path forgiving of common ways a user
    might paste one in: surrounding whitespace, a file:// URI (with
    %20-style escapes), or a leading ~ for the home directory."""
    cleaned = raw.strip()
    if cleaned.startswith("file://"):
        cleaned = unquote(urlsplit(cleaned).path)
    cleaned = os.path.expanduser(cleaned)
    return cleaned


def _read_file(settings_path: Path) -> dict:
    try:
        raw = settings_path.read_bytes()
    except OSError as exc:
        raise SettingsError(
            f"settings.json can't be read ({type(exc).__name__}). Check that it "
            "is a normal file the app is allowed to open."
        ) from exc
    try:
        # "utf-8-sig" also accepts the invisible marker some editors put at
        # the start of a UTF-8 file.
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SettingsError(
            "settings.json isn't saved as plain UTF-8 text. Open it in a text "
            "editor and save it again as UTF-8."
        ) from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SettingsError(f"settings.json is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise SettingsError(
            "settings.json must hold its settings between { and }, like "
            "settings.example.json."
        )
    return data


def read_mpv_command(settings_path: Path):
    """What the settings file says about mpv right now, for Look again on the
    "mpv not found" screen (the mpv missing screen): that screen can tell the viewer to fix
    the file while the app is open. Only this setting is read again. A file
    that can't be read raises SettingsError with its plain sentence."""
    if not settings_path.exists():
        return DEFAULT_MPV_COMMAND
    return _read_file(settings_path).get("mpv_command", DEFAULT_MPV_COMMAND)


def load_settings(root: Optional[Path] = None,
                  paths: Optional[app_paths.AppPaths] = None) -> dict:
    root = root or repo_root()
    # A development copy keeps settings.json and data/ in its own folder; an
    # installed copy keeps them in the home folder (the installer work).
    paths = paths or app_paths.for_app(root)
    settings_path = paths.settings_file

    # No file yet is a first launch (the folder choice screens): neither folder is set, so
    # the app asks for them, and choosing them creates the file.
    if settings_path.exists():
        data = _read_file(settings_path)
    else:
        data = {"movies_path": "", "tv_path": ""}

    for key in ("movies_path", "tv_path"):
        if key not in data:
            raise SettingsError(f"settings.json is missing required key '{key}'")
        if not isinstance(data[key], str):
            raise SettingsError(
                f"settings.json's '{key}' must be a folder path in quotes, "
                'like "/media/Movies", or empty quotes for no folder'
            )
        # Empty means not set (the folder choice screens): with both empty the app asks for
        # the folders on first launch, and a kind skipped there stays empty.
        data[key] = clean_path(data[key])

    data.setdefault("mpv_command", DEFAULT_MPV_COMMAND)

    data.setdefault("mpv_args", [])
    mpv_args = data["mpv_args"]
    if not isinstance(mpv_args, list) or not all(isinstance(a, str) for a in mpv_args):
        raise SettingsError(
            "settings.json's 'mpv_args' must be a list of strings, e.g. "
            '["--hwdec=auto"]'
        )

    # Where the saved library lives (the saved library work). Relative paths are inside
    # the folder that holds the data folder: the app folder in a development
    # copy, the app's own folder in the home folder when installed (the installer work).
    data.setdefault("data_dir", paths.data_dir.name)
    if not isinstance(data["data_dir"], str) or not data["data_dir"].strip():
        raise SettingsError("settings.json's 'data_dir' must be a folder path, e.g. \"data\"")
    data_dir = Path(clean_path(data["data_dir"]))
    data["data_dir"] = str(data_dir if data_dir.is_absolute() else paths.data_dir.parent / data_dir)

    data.setdefault("resume", True)
    if not isinstance(data["resume"], bool):
        raise SettingsError("settings.json's 'resume' must be true or false")

    # Hold the system's stay-awake lock while mpv runs (the keep-awake work).
    data.setdefault("keep_awake", True)
    if not isinstance(data["keep_awake"], bool):
        raise SettingsError("settings.json's 'keep_awake' must be true or false")

    # Developer only (the sizing spike): log the window's size and scaling at start.
    data.setdefault("debug_size_readout", False)
    if not isinstance(data["debug_size_readout"], bool):
        raise SettingsError("settings.json's 'debug_size_readout' must be true or false")

    return data
