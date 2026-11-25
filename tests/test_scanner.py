# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Tests for backend.scanner, the plain folder scan, on throwaway folders
with invented names: which files count as videos, what is skipped, how
files and groups are sorted, and the plain reasons for an unusable folder.

Run from the repo root:  python3 -m unittest tests.test_scanner -v
"""

import os
import tempfile
import unittest
from pathlib import Path

from backend.scanner import scan_source


class ScanSourceTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "Library"
        self.root.mkdir()
        self.addCleanup(self._tmp.cleanup)

    def make(self, *paths):
        for rel in paths:
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"")

    def scan(self):
        return scan_source("Movies", str(self.root))

    def names(self, scan):
        return {g["name"]: [f["name"] for f in g["files"]] for g in scan["groups"]}

    def test_only_video_extensions_count_whatever_the_case(self):
        self.make("a.MKV", "b.Mp4", "c.txt", "d.jpg", "e.srt", "f.nfo")
        scan = self.scan()
        self.assertEqual(scan["status"], "ok")
        self.assertEqual(self.names(scan), {"Library": ["a.MKV", "b.Mp4"]})

    def test_hidden_files_and_folders_are_skipped(self):
        self.make("._Film.mkv", ".hidden.mkv", ".Trash/Film.mkv", "Real.mkv")
        self.assertEqual(self.names(self.scan()), {"Library": ["Real.mkv"]})

    def test_root_files_are_grouped_under_the_root_folder_name(self):
        self.make("Film.mkv")
        scan = self.scan()
        self.assertEqual(scan["groups"][0]["name"], "Library")
        self.assertEqual(scan["groups"][0]["files"][0]["path"], "Film.mkv")

    def test_subfolder_group_and_file_paths_are_relative(self):
        self.make("Show/Season 1/ep1.mkv")
        scan = self.scan()
        group = scan["groups"][0]
        self.assertEqual(group["name"], str(Path("Show/Season 1")))
        self.assertEqual(group["files"][0]["path"], "Show/Season 1/ep1.mkv")

    def test_folders_without_videos_make_no_group(self):
        self.make("Extras/notes.txt", "Film/Film.mkv")
        self.assertEqual(list(self.names(self.scan())), ["Film"])

    def test_files_and_groups_sort_ignoring_capitals(self):
        # Mixed capitals so a plain (capital-first) sort gives a different
        # order: plain would put "C.mkv" before "b.mkv" and "Library"
        # before "beta".
        self.make("b.mkv", "A.mkv", "C.mkv", "zeta/x.mkv", "Alpha/x.mkv", "beta/x.mkv")
        scan = self.scan()
        self.assertEqual([g["name"] for g in scan["groups"]],
                         ["Alpha", "beta", "Library", "zeta"])
        library = next(g for g in scan["groups"] if g["name"] == "Library")
        self.assertEqual([f["name"] for f in library["files"]],
                         ["A.mkv", "b.mkv", "C.mkv"])

    def test_empty_folder_is_ok_with_no_groups(self):
        scan = self.scan()
        self.assertEqual(scan["status"], "ok")
        self.assertEqual(scan["groups"], [])

    def test_result_carries_label_and_path(self):
        scan = self.scan()
        self.assertEqual(scan["label"], "Movies")
        self.assertEqual(scan["path"], str(self.root))

    def test_missing_folder_is_not_found(self):
        scan = scan_source("Movies", str(self.root / "nope"))
        self.assertEqual(scan["status"], "not_found")
        self.assertEqual(scan["reason"], "does not exist")
        self.assertEqual(scan["groups"], [])

    def test_a_file_instead_of_a_folder_is_not_found(self):
        self.make("file.mkv")
        scan = scan_source("Movies", str(self.root / "file.mkv"))
        self.assertEqual(scan["status"], "not_found")
        self.assertEqual(scan["reason"], "is not a folder")

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0,
                     "root can read any folder")
    def test_unreadable_folder_says_permission_denied(self):
        self.make("Film.mkv")
        self.root.chmod(0o000)
        self.addCleanup(self.root.chmod, 0o700)
        scan = self.scan()
        self.assertEqual(scan["status"], "not_found")
        self.assertEqual(scan["reason"], "permission denied")


if __name__ == "__main__":
    unittest.main()
