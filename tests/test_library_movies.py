# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Tests for backend.library_movies, on throwaway folders with invented titles.

Run from the repo root:  python3 -m unittest discover -s tests -t . -v
"""

import os
import tempfile
import time
import unittest
from pathlib import Path

from backend.library_movies import scan_movies
from tests.full_only import full_only


class MovieGroupingTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def make(self, *paths):
        for rel in paths:
            path = self.root / rel
            if rel.endswith("/"):
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"")

    def scan(self):
        return scan_movies(str(self.root))

    def summary(self, scan):
        return [(m.title, m.year, len(m.parts)) for m in scan.movies]

    def test_scene_folder_ignores_extras(self):
        folder = "Example.Movie.1995.1080p.BluRay.x264-GRP/"
        self.make(
            folder + "Example.Movie.1995.1080p.BluRay.x264-GRP.mkv",
            folder + "Example.Movie.1995.1080p.BluRay.x264-GRP.txt",
            folder + "._Example.Movie.1995.1080p.BluRay.x264-GRP.mkv",
            folder + "cover.jpg",
        )
        scan = self.scan()
        self.assertEqual(self.summary(scan), [("Example Movie", 1995, 1)])
        part = scan.movies[0].parts[0]
        self.assertIsNone(part.label)
        self.assertEqual(part.path, folder + "Example.Movie.1995.1080p.BluRay.x264-GRP.mkv")

    def test_folder_name_wins_over_file_case(self):
        self.make("Another Example (2011)/another example (2011).mkv")
        self.assertEqual(self.summary(self.scan()), [("Another Example", 2011, 1)])

    def test_two_parts_become_one_movie(self):
        self.make(
            "Two Part Example (2004)/Two Part Example - 02.mkv",
            "Two Part Example (2004)/Two Part Example - 01.mkv",
        )
        movie, = self.scan().movies
        self.assertEqual((movie.title, movie.year), ("Two Part Example", 2004))
        self.assertEqual(
            [(p.label, p.path) for p in movie.parts],
            [
                ("Part 1", "Two Part Example (2004)/Two Part Example - 01.mkv"),
                ("Part 2", "Two Part Example (2004)/Two Part Example - 02.mkv"),
            ],
        )

    def test_part_markers(self):
        self.make("Example Film/Example Film CD1.avi", "Example Film/Example Film CD2.avi")
        self.assertEqual(self.summary(self.scan()), [("Example Film", None, 2)])

    def test_genre_folder_keeps_movies_apart(self):
        self.make("Comedy/First Example (1990).mkv", "Comedy/Second Example (2001).mp4")
        self.assertEqual(
            self.summary(self.scan()), [("First Example", 1990, 1), ("Second Example", 2001, 1)]
        )

    def test_sequel_is_not_a_part(self):
        self.make("Comedy/Example Movie.mkv", "Comedy/Example Movie 2.mkv")
        self.assertEqual(
            self.summary(self.scan()), [("Example Movie", None, 1), ("Example Movie 2", None, 1)]
        )

    def test_container_folder(self):
        self.make(
            "Collections/Example Saga/First Example (1980)/First Example.mkv",
            "Collections/Example Saga/Second Example (1983)/Second Example.mkv",
        )
        self.assertEqual(
            self.summary(self.scan()), [("First Example", 1980, 1), ("Second Example", 1983, 1)]
        )

    def test_sample_folder_ignored(self):
        self.make(
            "Example Movie (1999)/Example Movie (1999).mkv",
            "Example Movie (1999)/Sample/example-movie-sample.mkv",
            "Example Movie (1999)/SAMPLE/other.mkv",
        )
        scan = self.scan()
        self.assertEqual(self.summary(scan), [("Example Movie", 1999, 1)])
        self.assertEqual(scan.skipped, [])

    def test_loose_file_in_root(self):
        self.make("Loose Example (2015).mkv")
        movie, = self.scan().movies
        self.assertEqual((movie.title, movie.year), ("Loose Example", 2015))
        self.assertEqual(movie.parts[0].path, "Loose Example (2015).mkv")

    def test_movie_without_year(self):
        self.make("Movie Without A Year/Movie Without A Year.mkv")
        self.assertEqual(self.summary(self.scan()), [("Movie Without A Year", None, 1)])

    def test_folder_without_year_uses_file_year(self):
        self.make("Example Movie/Example.Movie.2007.720p.mkv")
        self.assertEqual(self.summary(self.scan()), [("Example Movie", 2007, 1)])

    def test_empty_folder(self):
        self.make("Empty Example/")
        scan = self.scan()
        self.assertEqual((scan.movies, scan.skipped), ([], []))

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root can read anything")
    def test_unreadable_folder_is_skipped(self):
        self.make("Readable Example (2000)/Readable Example.mkv", "Locked Example/Locked.mkv")
        locked = self.root / "Locked Example"
        locked.chmod(0)
        self.addCleanup(locked.chmod, 0o755)
        scan = self.scan()
        self.assertEqual(self.summary(scan), [("Readable Example", 2000, 1)])
        self.assertEqual([(s.path, s.reason) for s in scan.skipped], [("Locked Example", "cannot be read")])

    def test_link_outside_root_is_skipped(self):
        with tempfile.TemporaryDirectory() as outside:
            Path(outside, "Outside Example.mkv").write_bytes(b"")
            os.symlink(outside, self.root / "Link Out")
            scan = self.scan()
        self.assertEqual(scan.movies, [])
        self.assertEqual([(s.path, s.reason) for s in scan.skipped], [("Link Out", "link leads outside the folder")])

    def test_link_inside_root_counted_once(self):
        self.make("Example Movie (1999)/Example Movie.mkv")
        os.symlink(self.root / "Example Movie (1999)", self.root / "Also Example")
        self.assertEqual(len(self.scan().movies), 1)

    def test_sorted_by_title_ignoring_case_then_year(self):
        self.make("b example (2000).mkv", "Alpha Example (2010).mkv", "Alpha Example (1990).mkv")
        self.assertEqual(
            [(m.title, m.year) for m in self.scan().movies],
            [("Alpha Example", 1990), ("Alpha Example", 2010), ("b example", 2000)],
        )

    def test_accented_titles_sort_with_plain_letters(self):
        self.make("Zeta Example (2001).mkv", "Élan Example (2002).mkv", "Delta Example (2003).mkv",
                  "Ever Example (2004).mkv")
        self.assertEqual(
            [m.title for m in self.scan().movies],
            ["Delta Example", "Élan Example", "Ever Example", "Zeta Example"],
        )

    def test_known_limit_genre_folder_with_one_movie(self):
        # Looks exactly like a movie's own folder, so the folder name wins.
        # Recorded as a known limit (docs/decisions.md), not guessed around.
        self.make("Comedy/Example Movie (1999).mkv")
        self.assertEqual(self.summary(self.scan()), [("Comedy", 1999, 1)])


@full_only
class MovieGroupingTimingTest(unittest.TestCase):
    """Informational only: prints the time, asserts nothing."""

    def test_timing_500_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(500):
                year = 1950 + i % 70
                folder = Path(tmp, f"Example.Movie.{i}.{year}.1080p.BluRay.x264-GRP")
                folder.mkdir()
                (folder / f"{folder.name}.mkv").write_bytes(b"")
            scan_movies(tmp)  # warm up: loads guessit once
            start = time.perf_counter()
            scan = scan_movies(tmp)
            elapsed = time.perf_counter() - start
        print(f"\n  scan_movies timing: {len(scan.movies)} movie folders in {elapsed:.2f} s")


if __name__ == "__main__":
    unittest.main()
