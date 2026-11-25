# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Kettle spike (the storage spike), Question 1: what happens when the card is taken
out and put back.

Read-only. Watches the SD card found by drives.py, four times a second, and
keeps searching it for videos (no skip rule, so each search reads every
folder) the whole time. Prints a line only when something changes: the
mount, the folder, the /run/media/<label> shortcut, or how a search ends
(fine, error, or still running after HANG_SECONDS). Stops by itself once the
card has been back for SETTLE_SECONDS, or after --seconds (default 600).

    python3 spikes/storage/card_watch.py [--seconds 600]
"""

import os
import sys
import threading
import time

import drives
import find_video_folders as fvf
from common import Redactor

TICK = 0.25
HANG_SECONDS = 5
SETTLE_SECONDS = 15


def sd_mounts():
    return {m[0]: m for m in drives.mounts()
            if m[0].startswith(drives.REMOVABLE_ROOTS) and drives.hardware(m[1], m[2]) == "sd"}


def search(path):
    """One full search of the card, in a thread so a hang can be seen.
    Returns a short outcome: 'ok, N videos', 'error: <type>' or 'hung'."""
    result = {}

    def work():
        fvf.walk.folders = fvf.walk.unreadable = 0
        try:
            node = fvf.walk(path)
            result["out"] = (f"ok, {node.total} videos, {fvf.walk.folders} folders"
                             + (f", {fvf.walk.unreadable} unreadable"
                                if fvf.walk.unreadable else ""))
        except Exception as e:  # noqa: BLE001  any failure is the finding
            result["out"] = f"error: {type(e).__name__}"

    t = threading.Thread(target=work, daemon=True)
    started = time.monotonic()
    t.start()
    t.join(HANG_SECONDS)
    if t.is_alive():
        return "hung", None
    return result["out"], time.monotonic() - started


def main():
    limit = float(sys.argv[sys.argv.index("--seconds") + 1]) if "--seconds" in sys.argv else 600
    fvf.skipped = lambda name: False   # read every folder: the slowest search
    red = Redactor()
    start = sd_mounts()
    if not start:
        print("No SD card mounted at the start; put one in and run again.")
        return
    card = next(iter(start))
    label = os.path.basename(card)
    shortcut = os.path.join("/run/media", label)
    labels = [label]

    def show(path):
        return red.path(path, labels)

    def state():
        now = sd_mounts()
        mounted = sorted(show(p) for p in now)
        exists = os.path.isdir(card)
        try:
            listable = bool(os.listdir(card)) if exists else False
        except OSError as e:
            listable = f"error: {type(e).__name__}"
        link = ("missing" if not os.path.lexists(shortcut) else
                "points to the card" if os.path.isdir(shortcut) else "dangling")
        return (f"SD mounts: {mounted or 'none'}; {show(card)}: "
                f"{'exists' if exists else 'gone'}, listable={listable}; "
                f"shortcut {show(shortcut)}: {link}"), bool(now)

    t0 = time.monotonic()
    last_state = last_search = None
    went_out = back_at = None
    slowest = 0.0
    print(f"Watching {show(card)}. Searches use no skip rule.")
    while time.monotonic() - t0 < limit:
        stamp = f"{time.monotonic() - t0:7.2f} s"
        text, present = state()
        if text != last_state:
            print(f"{stamp}  {text}")
            last_state = text
        if not present and went_out is None:
            went_out = time.monotonic()
        if present and went_out is not None and back_at is None:
            back_at = time.monotonic()
        outcome, took = search(card)
        if took:
            slowest = max(slowest, took)
        if outcome != last_search:
            print(f"{stamp}  search: {outcome}"
                  + (f" ({took:.3f} s)" if took is not None else f" (> {HANG_SECONDS} s)"))
            last_search = outcome
        if outcome == "hung":
            print(f"{stamp}  a search is still running after {HANG_SECONDS} s; stopping.")
            break
        if back_at and time.monotonic() - back_at > SETTLE_SECONDS:
            print(f"{stamp}  card back for {SETTLE_SECONDS} s; stopping.")
            break
        time.sleep(TICK)
    print(f"Slowest finished search: {slowest:.3f} s")


if __name__ == "__main__":
    main()
