# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Names that can't be read as text (the unreadable name fix, audit finding H8).

Old archives copied onto ext4 cards can hold names saved in another text
encoding. One such file must not break the rescan: it is skipped with
"name can't be read", the other files are listed, and the saved library
loads again. Invented names in temporary folders only.
Run from the repo root:  python3 -m unittest discover -s tests -t . -v
"""

import os
import tempfile
import unittest
from pathlib import Path

from backend import library_index
from backend.library_movies import scan_movies
from backend.library_tv import scan_tv

# "Café" saved in Latin-1: the é is one byte that isn't valid UTF-8.
BAD_MOVIE = b"Caf\xe9 Invented (1999).mkv"
BAD_EPISODE = b"Invented Show S01E01 Caf\xe9.mkv"
BAD_FOLDER = b"Invented Caf\xe9 Film (2003)"
REASON = "name can't be read"


def _touch(folder: Path, name: bytes) -> None:
    with open(os.path.join(os.fsencode(folder), name), "wb") as f:
        f.write(b"x")


class UnreadableNameTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.movies, self.tv = root / "Movies", root / "TV Shows"
        show = self.tv / "Invented Show"
        show.mkdir(parents=True)
        self.movies.mkdir()
        (self.movies / "Good Invented (2001).mkv").write_bytes(b"x")
        (show / "Invented Show S01E02.mkv").write_bytes(b"x")
        try:
            _touch(self.movies, BAD_MOVIE)
            _touch(show, BAD_EPISODE)
            os.mkdir(os.path.join(os.fsencode(self.movies), BAD_FOLDER))
            _touch(Path(os.fsdecode(os.path.join(os.fsencode(self.movies), BAD_FOLDER))), b"film.mkv")
            # A non-video with a bad name is ignored like any other non-video.
            _touch(self.movies, b"notes caf\xe9.txt")
        except (OSError, UnicodeError):
            self.tmp.cleanup()
            self.skipTest("this file system refuses names that aren't valid UTF-8")
        self.roots = {"movies": str(self.movies), "tv": str(self.tv)}
        self.saved = root / "data" / "library.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _rescan(self) -> dict:
        index = library_index.full_scan(self.roots, None, lambda done, total: None)
        library_index.save(self.saved, index)
        return index

    def test_the_rescan_succeeds_and_skips_the_badly_named_entries(self):
        index = self._rescan()
        movies, tv = index["sources"]["movies"], index["sources"]["tv"]
        self.assertEqual([m["title"] for m in movies["items"]], ["Good Invented"])
        self.assertEqual([s["title"] for s in tv["items"]], ["Invented Show"])
        self.assertEqual([e["path"] for s in tv["items"][0]["seasons"] for e in s["episodes"]],
                         ["Invented Show/Invented Show S01E02.mkv"])
        self.assertEqual(movies["skipped"], [
            {"path": "Caf� Invented (1999).mkv", "reason": REASON},
            {"path": "Invented Caf� Film (2003)", "reason": REASON},
        ])
        self.assertEqual(tv["skipped"], [{"path": "Invented Show/Invented Show S01E01 Caf�.mkv", "reason": REASON}])
        self.assertEqual((movies["counts"]["skipped"], tv["counts"]["skipped"]), (2, 1))

    def test_the_saved_library_with_the_skipped_entries_loads_again(self):
        index = self._rescan()
        logs = []
        loaded = library_index.load(self.saved, logs.append)
        self.assertEqual(logs, [])
        self.assertEqual(loaded, index)
        answer = library_index.render(loaded, self.roots)
        self.assertEqual(answer["skipped"]["movies"][0]["reason"], REASON)
        self.assertEqual(answer["skipped"]["tv"][0]["reason"], REASON)
        self.assertIn("1 skipped", library_index.summary(loaded))

    def test_both_folder_scans_skip_rather_than_raise(self):
        for scan, folder in ((scan_movies, self.movies), (scan_tv, self.tv)):
            result = scan(str(folder))
            self.assertTrue(result.skipped)
            for item in result.skipped:
                self.assertEqual(item.reason, REASON)
                item.path.encode("utf-8")  # always plain text

    def test_the_badly_named_files_are_never_renamed_or_changed(self):
        before = sorted(os.listdir(os.fsencode(self.movies)))
        self._rescan()
        self.assertEqual(sorted(os.listdir(os.fsencode(self.movies))), before)
        self.assertIn(BAD_MOVIE, before)
        with open(os.path.join(os.fsencode(self.movies), BAD_MOVIE), "rb") as f:
            self.assertEqual(f.read(), b"x")


if __name__ == "__main__":
    unittest.main()
