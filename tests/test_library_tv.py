# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Tests for backend.library_tv, on throwaway folders with invented titles.

Run from the repo root:  python3 -m unittest discover -s tests -t . -v
"""

import contextlib
import io
import os
import tempfile
import time
import unicodedata
import unittest
from pathlib import Path

from backend.library_tv import _main, scan_tv
from tests.full_only import full_only


class TvGroupingTest(unittest.TestCase):
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
        return scan_tv(str(self.root))

    def layout(self, show):
        """[(season number, [episode numbers or None, ...]), ...]"""
        return [(s.number, [e.number for e in s.episodes]) for s in show.seasons]

    def test_season_folders_in_number_order(self):
        show_dir = "Example Show (2010)/"
        self.make(
            show_dir + "Season 10/Example.Show.S10E01.mkv",
            show_dir + "Season 2/Example.Show.S02E10.mkv",
            show_dir + "Season 2/Example.Show.S02E09.mkv",
            show_dir + "Season 2/Example.Show.S02E01.mkv",
            show_dir + "Season 1/Example.Show.S01E01.mkv",
        )
        show, = self.scan().shows
        self.assertEqual((show.title, show.year, show.path), ("Example Show", 2010, "Example Show (2010)"))
        self.assertEqual(self.layout(show), [(1, [1]), (2, [1, 9, 10]), (10, [1])])

    def test_short_season_folder_name(self):
        self.make("Other Example/S02/Other Example - 2x03.mkv")
        show, = self.scan().shows
        self.assertEqual(self.layout(show), [(2, [3])])

    def test_season_from_folder_when_file_has_none(self):
        self.make("Third Example/Season 3/Third Example - 05.mkv")
        show, = self.scan().shows
        self.assertEqual(self.layout(show), [(3, [5])])
        self.assertNotIn("season-mismatch", show.seasons[0].episodes[0].flags)

    def test_file_season_wins_and_is_flagged(self):
        self.make(
            "Fourth Example/Season 1/Fourth.Example.S01E01.mkv",
            "Fourth Example/Season 1/Fourth.Example.S02E01.mkv",
        )
        show, = self.scan().shows
        self.assertEqual(self.layout(show), [(1, [1]), (2, [1])])
        self.assertNotIn("season-mismatch", show.seasons[0].episodes[0].flags)
        self.assertIn("season-mismatch", show.seasons[1].episodes[0].flags)

    def test_absolute_numbering_anime(self):
        # Shaped like a real folder: numbered episodes, one
        # unnumbered extra, a Sample folder, a number inside an episode title.
        show_dir = "Example Anime (The Complete Series) [DUAL-AUDIO] [480p] [HEVC]/"
        names = [f"[grp] Example Anime - {n:02} - Chapter Title [480p] [h.265].mkv" for n in range(1, 13)]
        names[10] = "[grp] Example Anime - 11 - Room 511 [480p] [h.265].mkv"
        self.make(
            *(show_dir + name for name in names),
            show_dir + "[grp] Example Anime - EC - The Prologue [480p] [h.265].mkv",
            show_dir + "._[grp] Example Anime - 01 - Chapter Title [480p] [h.265].mkv",
            show_dir + "Sample/Sample (Opening).mkv",
            show_dir + "Sample/Still Frame A.png",
        )
        scan = self.scan()
        show, = scan.shows
        self.assertEqual(show.title, "Example Anime")
        self.assertEqual(self.layout(show), [(None, list(range(1, 13)) + [None])])
        episodes = show.seasons[0].episodes
        self.assertEqual(episodes[10].title, "Room 511")
        self.assertEqual(episodes[-1].flags, ["unnumbered"])
        self.assertTrue(episodes[-1].path.endswith("EC - The Prologue [480p] [h.265].mkv"))
        self.assertFalse(any("Sample" in e.path for e in episodes))
        self.assertEqual(scan.skipped, [])

    def test_three_digit_absolute_numbers_stay_one_flat_list(self):
        # The three-digit episode fix: "- 098", "- 100", "- 112" with nothing after the number
        # were read as season 0 (Specials) or season 1.
        self.make(*(f"Example Anime/Example Anime - {n:03}.mkv" for n in range(98, 113)))
        show, = self.scan().shows
        self.assertEqual(self.layout(show), [(None, list(range(98, 113)))])

    def test_multi_episode_file_is_one_entry(self):
        self.make(
            "Fifth Example/Fifth.Example.S01E03.mkv",
            "Fifth Example/Fifth.Example.S01E01E02.mkv",
        )
        show, = self.scan().shows
        episodes = show.seasons[0].episodes
        self.assertEqual([e.numbers for e in episodes], [[1, 2], [3]])

    def test_loose_root_files_grouped_by_title(self):
        self.make(
            "Loose.Example.S01E02.mkv",
            "Loose.Example.S01E01.mkv",
            "Another.Loose.Example.S01E01.mkv",
        )
        shows = self.scan().shows
        self.assertEqual(
            [(s.title, s.path, self.layout(s)) for s in shows],
            [
                ("Another Loose Example", ".", [(1, [1])]),
                ("Loose Example", ".", [(1, [1, 2])]),
            ],
        )

    def test_containers_are_not_shows(self):
        self.make(
            "Anime/Sixth Example/Sixth Example - 01.mkv",
            "Drama/Seventh Example/Season 1/Seventh Example - 1x01.mkv",
            "Drama/notes.txt",
        )
        self.assertEqual(
            [(s.title, s.path) for s in self.scan().shows],
            [("Seventh Example", "Drama/Seventh Example"), ("Sixth Example", "Anime/Sixth Example")],
        )

    def test_title_from_files_when_folder_has_none(self):
        self.make(
            "Season 1/Eighth.Example.S01E01.mkv",
            "Season 1/Eighth.Example.S01E02.mkv",
            "Season 1/Eighth.Exampel.S01E03.mkv",
        )
        show, = self.scan().shows
        self.assertEqual(show.title, "Eighth Example")
        self.assertEqual(self.layout(show), [(1, [1, 2, 3])])

    def test_episodes_without_season_listed_after_seasons(self):
        self.make(
            "Ninth Example/Season 1/Ninth.Example.S01E01.mkv",
            "Ninth Example/Ninth Example - Pilot.mkv",
        )
        show, = self.scan().shows
        self.assertEqual(self.layout(show), [(1, [1]), (None, [None])])

    # Specials, duplicates and unusual names (parser 4b-2, the specials and odd names parser work).

    def test_specials_folder_goes_last(self):
        self.make(
            "Show G/Season 1/Show G S01E01.mkv",
            "Show G/Season 2/Show G S02E01.mkv",
            "Show G/Specials/Show G - Special 01.mkv",
        )
        show, = self.scan().shows
        self.assertEqual(self.layout(show), [(1, [1]), (2, [1]), (0, [1])])
        self.assertEqual([s.label for s in show.seasons], ["Season 1", "Season 2", "Specials"])
        self.assertEqual(show.seasons[-1].episodes[0].flags, [])

    def test_season_0_and_special_folders(self):
        self.make(
            "Show H/Season 0/Show H - Pilot.mkv",
            "Show H/Season 1/Show H S01E01.mkv",
            "Show I/Season 1/Show I S01E01.mkv",
            "Show I/special/Show I - Extra.mkv",
        )
        shows = self.scan().shows
        self.assertEqual(
            [(s.title, self.layout(s)) for s in shows],
            [("Show H", [(1, [1]), (0, [None])]), ("Show I", [(1, [1]), (0, [None])])],
        )

    def test_flat_show_stays_flat_with_specials_after(self):
        self.make(
            "Example Anime/Example Anime - 02.mkv",
            "Example Anime/Example Anime - 01.mkv",
            "Example Anime/Example Anime - EC - Extra.mkv",
            "Example Anime/Specials/Example Anime - OVA.mkv",
        )
        show, = self.scan().shows
        self.assertEqual(self.layout(show), [(None, [1, 2, None]), (0, [None])])
        self.assertIn("unnumbered", show.seasons[0].episodes[-1].flags)

    def test_specials_folder_wins_over_file_season(self):
        self.make(
            "Show J/Season 1/Show J S01E01.mkv",
            "Show J/Specials/Show J S01E05.mkv",
            "Show J/Specials/Show J S00E02.mkv",
        )
        show, = self.scan().shows
        self.assertEqual(self.layout(show), [(1, [1]), (0, [2, 5])])
        specials = show.seasons[-1].episodes
        self.assertEqual([e.flags for e in specials], [[], ["season-mismatch"]])

    def test_duplicates_kept_and_flagged(self):
        self.make(
            "Show K/Season 1/Show K S01E01 720p.mkv",
            "Show K/Season 1/Show K S01E01 1080p.mkv",
            "Show K/Season 1/Show K S01E02.mkv",
        )
        show, = self.scan().shows
        episodes = show.seasons[0].episodes
        self.assertEqual(
            [(os.path.basename(e.path), "duplicate" in e.flags) for e in episodes],
            [
                ("Show K S01E01 1080p.mkv", True),
                ("Show K S01E01 720p.mkv", True),
                ("Show K S01E02.mkv", False),
            ],
        )

    def test_japanese_names(self):
        self.make(
            "例のショー/例のショー - 02 - 二話.mkv",
            "例のショー/例のショー - 01 - 始まり.mkv",
        )
        show, = self.scan().shows
        self.assertEqual(show.title, "例のショー")
        episodes = show.seasons[0].episodes
        self.assertEqual([(e.number, e.title) for e in episodes], [(1, "始まり"), (2, "二話")])
        self.assertEqual(episodes[0].path, "例のショー/例のショー - 01 - 始まり.mkv")

    def test_decomposed_accent_matches_composed(self):
        mac = unicodedata.normalize("NFD", "Café Example")
        self.assertNotEqual(mac, "Café Example")
        self.make(f"{mac} S01E01.mkv", "Café Example S01E02.mkv")
        show, = self.scan().shows
        self.assertEqual(show.title, "Café Example")
        self.assertEqual(self.layout(show), [(1, [1, 2])])
        # The real path is never changed.
        self.assertIn(f"{mac} S01E01.mkv", [e.path for e in show.seasons[0].episodes])

    def test_titles_sort_ignoring_case(self):
        self.make("cherry Example/cherry Example - 01.mkv", "Banana Example/Banana Example - 01.mkv",
                  "apple Example/apple Example - 01.mkv")
        titles = [s.title for s in self.scan().shows]
        self.assertEqual(titles, ["apple Example", "Banana Example", "cherry Example"])

    def test_accented_titles_sort_with_plain_letters(self):
        self.make("Zeta Example/Zeta Example - 01.mkv", "Élan Example/Élan Example - 01.mkv",
                  "Delta Example/Delta Example - 01.mkv", "Ever Example/Ever Example - 01.mkv")
        titles = [s.title for s in self.scan().shows]
        # Accents stay for display; only the order ignores them.
        self.assertEqual(titles, ["Delta Example", "Élan Example", "Ever Example", "Zeta Example"])

    def test_symbols_only_name_keeps_every_character(self):
        self.make("@#$%^&().mkv")
        show, = self.scan().shows
        self.assertEqual(show.title, "@#$%^&()")

    def test_dot_before_marker_joins_the_same_show(self):
        self.make("Plain Example.S01E02.mkv", "Plain Example S01E03.mkv")
        show, = self.scan().shows
        self.assertEqual(show.title, "Plain Example")
        self.assertEqual(self.layout(show), [(1, [2, 3])])

    def test_number_in_title_stays_in_a_flat_show(self):
        self.make(
            "Example Anime/Example Anime - 02 - First Steps.mkv",
            "Example Anime/Example Anime - 03 - The 100 Doors.mkv",
            "Example Anime/Example Anime - 11 - 511 Example Place.mkv",
        )
        show, = self.scan().shows
        season, = show.seasons
        self.assertIsNone(season.number)
        self.assertEqual(
            [(e.number, e.title) for e in season.episodes],
            [(2, "First Steps"), (3, "The 100 Doors"), (11, "511 Example Place")],
        )

    def test_long_name(self):
        ending = " S01E01.mkv"
        name = "Long" + "x" * (255 - len("Long") - len(ending)) + ending
        self.assertEqual(len(name.encode("utf-8")), 255)
        self.make("Long Show/" + name)
        show, = self.scan().shows
        self.assertEqual(self.layout(show), [(1, [1])])
        self.assertEqual(show.seasons[0].episodes[0].path, "Long Show/" + name)

    def test_symbols_only_name(self):
        self.make("@#$%^&().mkv", "!!!.mkv")
        scan = self.scan()
        self.assertEqual(len(scan.shows), 2)
        for show in scan.shows:
            self.assertTrue(show.title)
            self.assertIn("unnumbered", show.seasons[0].episodes[0].flags)

    def test_empty_root(self):
        self.make("Empty Example/", "Another/notes.txt")
        scan = self.scan()
        self.assertEqual((scan.shows, scan.skipped), ([], []))

    def run_main(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = _main(["library_tv", str(self.root), *args])
        return code, out.getvalue()

    def test_command_summary_and_episodes(self):
        self.make(
            "Example Anime/Example Anime - 01.mkv",
            "Example Anime/Example Anime - 02.mkv",
            "Example Anime/Example Anime - EC - Extra.mkv",
        )
        code, out = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("Example Anime - 2 episodes, 1 unnumbered", out)
        self.assertNotIn("[unnumbered]", out)

        code, out = self.run_main("--episodes")
        self.assertEqual(code, 0)
        self.assertIn("[unnumbered]", out)
        self.assertEqual(out.count("Example Anime - 0"), 2)


@full_only
class TvGroupingTimingTest(unittest.TestCase):
    """Informational only: prints a timing, asserts nothing."""

    def test_timing_500_files(self):
        # 20 shows of 25 episodes; 2 of them (50 names) in Japanese.
        with tempfile.TemporaryDirectory() as tmp:
            for show in range(20):
                title = f"例のショー {show:02}" if show < 2 else f"Example Show {show:02}"
                folder = Path(tmp) / title / "Season 1"
                folder.mkdir(parents=True)
                for episode in range(1, 26):
                    (folder / f"{title} S01E{episode:02} 720p.mkv").write_bytes(b"")
            start = time.perf_counter()
            scan = scan_tv(tmp)
            elapsed = time.perf_counter() - start
        print(f"\n  scan_tv timing: 20 shows, 500 episode files (50 non-Latin) in {elapsed:.2f} s")
        self.assertEqual(len(scan.shows), 20)

if __name__ == "__main__":
    unittest.main()
