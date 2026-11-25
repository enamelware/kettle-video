# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Kettle spike (the storage spike): helpers shared by the storage spike's scripts.

Everything here only reads. Nothing is written to any card, drive or media
folder. Output is private by default: card labels, user names and folder
names are replaced by placeholders, so it can be pasted into an issue or
the report. Pass --real to a script to see the real names on screen.
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from backend.scanner import VIDEO_EXTENSIONS  # noqa: E402  same list the app uses

SHOW_REAL = "--real" in sys.argv
_USER = os.path.basename(os.path.expanduser("~"))


class Redactor:
    """Swaps real names for stable placeholders: <user>, <card-1>, folder-1..."""

    def __init__(self):
        self._names = {}

    def name(self, kind, real):
        if SHOW_REAL:
            return real
        key = (kind, real)
        if key not in self._names:
            count = sum(1 for k in self._names if k[0] == kind) + 1
            self._names[key] = f"{kind}-{count}"
        return self._names[key]

    def path(self, path, labels=()):
        """A mount path with the user name and card labels hidden."""
        if SHOW_REAL:
            return path
        out = re.sub(rf"(?<=/){re.escape(_USER)}(?=/|$)", "<user>", path)
        for label in labels:
            out = re.sub(rf"(?<=/){re.escape(label)}(?=/|$)",
                         f"<{self.name('card', label)}>", out)
        return out


def is_video(filename):
    return (not filename.startswith(".")
            and os.path.splitext(filename)[1].lower() in VIDEO_EXTENSIONS)
