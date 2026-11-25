# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Recursive folder scan + video extension filter. Pure logic, no HTTP awareness."""

import os
import stat as stat_module
from pathlib import Path

VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v",
    ".wmv", ".flv", ".mpg", ".mpeg", ".ts", ".m2ts",
}


def _is_video(filename: str) -> bool:
    return Path(filename).suffix.lower() in VIDEO_EXTENSIONS


def _not_found(label: str, root: str, reason: str) -> dict:
    return {"label": label, "path": root, "status": "not_found", "reason": reason, "groups": []}


def scan_source(label: str, root: str) -> dict:
    root_path = Path(root)

    # Path.exists()/is_dir() swallow PermissionError and just report False,
    # so check explicitly to tell "doesn't exist" apart from "can't read it".
    try:
        st = os.stat(root_path)
    except FileNotFoundError:
        return _not_found(label, root, "does not exist")
    except NotADirectoryError:
        return _not_found(label, root, "is not a folder")
    except PermissionError:
        return _not_found(label, root, "permission denied")

    if not stat_module.S_ISDIR(st.st_mode):
        return _not_found(label, root, "is not a folder")

    try:
        os.listdir(root_path)
    except PermissionError:
        return _not_found(label, root, "permission denied")

    groups = []
    for dirpath, dirnames, filenames in os.walk(root_path):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        videos = sorted(
            (f for f in filenames if not f.startswith(".") and _is_video(f)),
            key=str.casefold,
        )
        if not videos:
            continue

        dir_path = Path(dirpath)
        rel_dir = dir_path.relative_to(root_path)
        group_name = str(rel_dir) if str(rel_dir) != "." else root_path.name

        files = []
        for filename in videos:
            rel_file = (rel_dir / filename) if str(rel_dir) != "." else Path(filename)
            files.append({"name": filename, "path": rel_file.as_posix()})

        groups.append({"name": group_name, "files": files})

    groups.sort(key=lambda g: g["name"].casefold())

    return {"label": label, "path": root, "status": "ok", "groups": groups}
