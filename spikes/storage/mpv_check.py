# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Kettle spike (the storage spike), Question 4: can mpv play from each place?

Read-only towards cards and media. For each place drives.py finds, it picks
one video (the smallest real video the Question 3 rule finds there), checks
the app can read it, then asks mpv, found exactly the way the app finds it,
to decode a few frames with no window, no sound and no config, so nothing
is saved (no resume position, no screenshot). Internal storage is checked
with a short test clip that mpv itself makes in /tmp and the script copies
into a temporary folder inside the project (the home folder), then deletes.

    python3 spikes/storage/mpv_check.py [--real]
"""

import os
import shutil
import subprocess
import sys
import tempfile

from common import ROOT, Redactor, is_video
import drives
import find_video_folders as finder
from backend import mpv as app_mpv

MPV_OPTIONS = ["--no-config", "--vo=null", "--ao=null", "--frames=5",
               "--save-position-on-quit=no", "--really-quiet", "--msg-level=all=error"]


def smallest_video(root):
    best = None
    for folder in finder.suggest(finder.walk(root)):
        for dirpath, dirnames, filenames in os.walk(folder.path):
            dirnames[:] = [d for d in dirnames if not finder.skipped(d)]
            for name in filenames:
                if is_video(name):
                    path = os.path.join(dirpath, name)
                    size = os.path.getsize(path)
                    if size >= finder.MIN_VIDEO_BYTES and (best is None or size < best[0]):
                        best = (size, path)
    return best and best[1]


def app_can_read(path):
    try:
        with open(path, "rb") as f:
            return len(f.read(1 << 20)) > 0
    except OSError:
        return False


def mpv_can_play(command, path):
    try:
        result = subprocess.run(command + MPV_OPTIONS + ["--", path],
                                capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, type(e).__name__
    detail = (result.stderr or result.stdout).strip().splitlines()
    return result.returncode == 0, (detail[-1][:120] if detail else "")


def make_test_clip(command):
    """A 2-second test picture made by mpv. The Flatpak mpv can only write
    to /tmp (docs/spikes/mpv-quit.md), so it is made there first."""
    shared = tempfile.mkdtemp(prefix="kettle-42-", dir="/tmp")
    clip = os.path.join(shared, "clip.mkv")
    subprocess.run(command + ["--no-config", "--really-quiet",
                              "av://lavfi:testsrc=duration=2:size=320x240:rate=25",
                              "--of=matroska", "--ovc=ffv1", f"--o={clip}"],
                   capture_output=True, timeout=60)
    return shared, clip if os.path.exists(clip) else None


def main():
    found = app_mpv.detect("auto")
    if not found["available"]:
        sys.exit("mpv not found: " + found["install_hint"])
    command = found["command"]
    print(f"mpv found via: {found['via']}")
    red = Redactor()
    places = drives.places()
    labels = [p["label"] for p in places if p["label"]]
    shared, clip = make_test_clip(command)
    local = tempfile.mkdtemp(prefix="kettle-42-", dir=ROOT)
    try:
        if clip:
            print("/tmp test clip:", "plays" if mpv_can_play(command, clip)[0] else "FAILS")
        for p in places:
            if p["kind"] == "internal":
                if not clip:
                    print(f"{p['name']}: no test clip could be made")
                    continue
                video = shutil.copy(clip, local)
            else:
                video = smallest_video(p["path"])
                if not video:
                    print(f"{p['name']}: no video found to try")
                    continue
            readable = app_can_read(video)
            plays, detail = mpv_can_play(command, video)
            print(f"{p['name']:<18} {red.path(p['path'], labels):<30} app reads: "
                  f"{'yes' if readable else 'NO'}, mpv plays: {'yes' if plays else 'NO'}"
                  + (f" ({detail})" if detail and not plays else ""))
    finally:
        shutil.rmtree(local, ignore_errors=True)
        shutil.rmtree(shared, ignore_errors=True)


if __name__ == "__main__":
    main()
