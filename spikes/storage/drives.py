# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Kettle spike (the storage spike), Question 1: which cards and drives are present.

Python standard library only. Reads /proc/self/mountinfo (what is mounted
where) and /sys (what kind of hardware each mount sits on). Prints one line
per place, with the name onboarding could show for it.

    python3 spikes/storage/drives.py          private output (placeholders)
    python3 spikes/storage/drives.py --json   the same, as JSON
    python3 spikes/storage/drives.py --real   real labels and paths, on screen only
"""

import json
import os
import sys

from common import SHOW_REAL, Redactor

# Where desktop Linux (udisks) mounts cards and USB drives. SteamOS uses
# /run/media/<user>/<label>; other distributions may use /media/<user>.
REMOVABLE_ROOTS = ("/run/media/", "/media/", "/mnt/")


def _unescape(field):
    # mountinfo writes spaces and tabs in paths as \040 and \011.
    return (field.replace("\\040", " ").replace("\\011", "\t")
            .replace("\\012", "\n").replace("\\134", "\\"))


def mounts():
    """(mount point, 'major:minor', source device, filesystem) per mount."""
    out = []
    with open("/proc/self/mountinfo") as f:
        for line in f:
            left, right = line.rstrip("\n").split(" - ", 1)
            fields = left.split()
            fstype, source = right.split()[:2]
            out.append((_unescape(fields[4]), fields[2], source, fstype))
    return out


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return ""


def sys_device(dev_numbers, source=""):
    """Where a mount's device sits in /sys. btrfs gives every mount a
    placeholder number with major 0 (seen on the Nova's internal storage),
    so then the named source device (/dev/sda20) is looked up instead."""
    if dev_numbers.startswith("0:") and source.startswith("/dev/"):
        return f"/sys/class/block/{os.path.basename(source)}"
    return f"/sys/dev/block/{dev_numbers}"


def hardware(dev_numbers, source=""):
    """What a block device is: 'sd' (SD card), 'usb', 'internal' or 'other'.

    /sys/dev/block/<major:minor> links to the device's place in the hardware
    tree. An SD card hangs off an MMC host and reports type 'SD'; built-in
    eMMC storage also hangs off an MMC host but reports type 'MMC'. A USB
    drive or card reader has 'usb' in its path. NVMe and SATA are internal.
    Note: the Deck's SD slot reports removable=0, so 'removable' is useless.
    """
    sys_path = os.path.realpath(sys_device(dev_numbers, source))
    if "/mmc_host/" in sys_path:
        disk = sys_path if os.path.exists(os.path.join(sys_path, "device")) \
            else os.path.dirname(sys_path)
        kind = _read(os.path.join(disk, "device", "type"))
        return "sd" if kind == "SD" else "internal"
    if "/usb" in sys_path:
        return "usb"
    if "/nvme/" in sys_path or "/ata" in sys_path or "ufshc" in sys_path:  # Nova: soc@0/<addr>.ufshc
        return "internal"
    return "other"


DISPLAY = {"sd": "SD card", "usb": "USB drive", "internal": "Internal storage",
           "other": "Other drive"}


def places():
    """Every place onboarding could offer: internal storage (the home folder)
    plus each card or drive mounted under a removable root."""
    found = []
    home = os.path.expanduser("~")
    home_mount = max((m for m in mounts() if home.startswith(m[0].rstrip("/") + "/")
                      or home == m[0]), key=lambda m: len(m[0]))
    found.append({"kind": "internal", "name": "Internal storage", "path": home,
                  "found_by": f"home folder (on {home_mount[0]})",
                  "fstype": home_mount[3], "label": None})
    counts = {}
    for mount_point, numbers, source, fstype in mounts():
        if not mount_point.startswith(REMOVABLE_ROOTS):
            continue
        kind = hardware(numbers, source)
        counts[kind] = counts.get(kind, 0) + 1
        name = DISPLAY[kind] if counts[kind] == 1 else f"{DISPLAY[kind]} {counts[kind]}"
        found.append({"kind": kind, "name": name, "path": mount_point,
                      "found_by": "mountinfo + /sys", "fstype": fstype,
                      "label": os.path.basename(mount_point)})
    return found


def empty_readers():
    """USB card readers and similar that are present but hold no medium
    (size 0); they must not be listed."""
    out = []
    for disk in sorted(os.listdir("/sys/block")):
        if _read(f"/sys/block/{disk}/size") == "0" and not disk.startswith(("loop", "zram", "ram")):
            out.append(disk)
    return out


def main():
    red = Redactor()
    found = places()
    labels = [p["label"] for p in found if p["label"]]
    for p in found:
        p["path"] = red.path(p["path"], labels)
        if p["label"] and not SHOW_REAL:
            p["label"] = f"<{red.name('card', p['label'])}>"
    if "--json" in sys.argv:
        print(json.dumps({"places": found, "empty_readers": empty_readers()}, indent=2))
        return
    for p in found:
        print(f"{p['name']:<18} {p['path']:<32} {p['fstype']:<6} found by {p['found_by']}")
    readers = empty_readers()
    if readers:
        print(f"Ignored (no medium, size 0): {', '.join(readers)}")


if __name__ == "__main__":
    main()
