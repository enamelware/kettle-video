# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Kettle spike (the storage spike): prove nothing on a card or media folder changed.

Read-only. Walks a folder and makes one fingerprint from every file's and
folder's relative path, size and modification time. Run it before and
after the spike and compare: equal fingerprints mean nothing was added,
removed, renamed or modified. Only the fingerprint and counts are printed,
never names.

    python3 spikes/storage/snapshot.py PATH [PATH...]
"""

import hashlib
import os
import sys


def fingerprint(root):
    digest = hashlib.sha256()
    files = folders = 0
    errors = []
    for dirpath, dirnames, filenames in os.walk(root, onerror=errors.append):
        dirnames.sort()
        for name in sorted(filenames) + [""]:
            path = os.path.join(dirpath, name) if name else dirpath
            try:
                st = os.lstat(path)
            except OSError as e:
                errors.append(e)
                continue
            rel = os.path.relpath(path, root)
            digest.update(f"{rel}\0{st.st_size}\0{st.st_mtime_ns}\n".encode(
                "utf-8", "surrogateescape"))
            if name:
                files += 1
            else:
                folders += 1
    return digest.hexdigest()[:16], files, folders, len(errors)


def main():
    for i, root in enumerate(sys.argv[1:], 1):
        fp, files, folders, unreadable = fingerprint(root)
        print(f"place {i}: fingerprint {fp}, {files} files, {folders} folders, "
              f"{unreadable} unreadable")


if __name__ == "__main__":
    main()
