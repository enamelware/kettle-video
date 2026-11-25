# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Quick rescans, missing items and Remove (the quick rescan and Remove work).

Invented titles in temporary folders only.
Run from the repo root:  python3 -m unittest discover -s tests -t . -v
"""

import contextlib
import http.client
import io
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from backend import library_index, parser
from tests.full_only import full_only
from tests import test_library_index
from tests.test_library_index import make_folders
from tests.test_parsed_library import MOVIE_FILES, TV_FILES

NO_PROGRESS = lambda done, total: None  # noqa: E731


def scan(roots, previous=None):
    with contextlib.redirect_stdout(io.StringIO()):
        return library_index.full_scan(roots, previous, NO_PROGRESS)


def counted_scan(roots, previous):
    """A scan, and the names the name reader was asked to read."""
    with mock.patch.object(parser, "parse_name", wraps=parser.parse_name) as reader:
        index = scan(roots, previous)
    return index, [call.args[0] for call in reader.call_args_list]


def items(index, source):
    return {i["title"]: i for i in index["sources"][source]["items"]}


def episodes(show):
    return {e["path"]: e for season in show["seasons"] for e in season["episodes"]}


class QuickRescanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.roots = make_folders(self.root)
        self.movies = Path(self.roots["movies"])
        self.tv = Path(self.roots["tv"])
        self.first = scan(self.roots)

    def tearDown(self):
        self.tmp.cleanup()

    def test_unchanged_files_are_not_read_again(self):
        again, read = counted_scan(self.roots, self.first)
        self.assertEqual(read, [])
        self.assertEqual(again["last_scan"], {"new": 0, "changed": 0, "missing": 0, "not_available": []})
        for source in ("movies", "tv"):
            self.assertEqual(again["sources"][source]["items"], self.first["sources"][source]["items"])

    def test_a_changed_file_is_read_again(self):
        changed = self.tv / TV_FILES[3]
        changed.write_bytes(b"longer now")
        again, read = counted_scan(self.roots, self.first)
        self.assertEqual(read, [changed.name])
        self.assertEqual((again["last_scan"]["new"], again["last_scan"]["changed"]), (0, 1))
        self.assertEqual(again["sources"]["tv"]["items"], self.first["sources"]["tv"]["items"])
        saved = {f["path"]: f["size"] for f in again["sources"]["tv"]["files"]}
        self.assertEqual(saved[TV_FILES[3]], len(b"longer now"))

    def test_a_file_with_only_a_new_date_is_read_again(self):
        # Same size, different modified time: "changed by size or date".
        changed = self.tv / TV_FILES[4]
        stat = changed.stat()
        os.utime(changed, (stat.st_atime, stat.st_mtime + 60))
        again, read = counted_scan(self.roots, self.first)
        self.assertEqual(read, [changed.name])
        self.assertEqual((again["last_scan"]["new"], again["last_scan"]["changed"]), (0, 1))

    def test_a_new_file_is_added(self):
        new = self.movies / "New.Example.2005.mkv"
        new.write_bytes(b"x")
        again, read = counted_scan(self.roots, self.first)
        self.assertEqual(read, [new.name])
        self.assertEqual(items(again, "movies")["New Example"]["year"], 2005)
        self.assertEqual(again["last_scan"]["new"], 1)
        self.assertIn(new.name, [f["path"] for f in again["sources"]["movies"]["files"]])

    def test_a_saved_library_without_saved_names_still_scans(self):
        for entry in self.first["sources"].values():
            del entry["names"]
        again, read = counted_scan(self.roots, self.first)
        self.assertTrue(read)
        self.assertEqual(again["sources"]["movies"]["items"], self.first["sources"]["movies"]["items"])

    def test_the_name_reader_version_is_saved(self):
        for entry in self.first["sources"].values():
            self.assertEqual(entry["names_version"], parser.reader_version())

    def test_a_new_name_reader_reads_every_name_again_once(self):
        _, all_names = counted_scan(self.roots, None)
        with mock.patch.object(parser, "reader_version", return_value="a newer reader"):
            again, read = counted_scan(self.roots, self.first)
            self.assertEqual(sorted(read), sorted(all_names))
            for entry in again["sources"].values():
                self.assertEqual(entry["names_version"], "a newer reader")
            # The rescan after that reuses the names again.
            _, read = counted_scan(self.roots, again)
            self.assertEqual(read, [])

    def test_a_saved_library_without_a_name_reader_version_reads_every_name(self):
        for entry in self.first["sources"].values():
            del entry["names_version"]
        _, all_names = counted_scan(self.roots, None)
        _, read = counted_scan(self.roots, self.first)
        self.assertEqual(sorted(read), sorted(all_names))


class ReaderVersionTest(unittest.TestCase):
    def test_the_version_changes_only_when_a_file_it_depends_on_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            one, two = Path(tmp, "one.py"), Path(tmp, "two.py")
            one.write_text("a = 1\n")
            two.write_text("b = 2\n")
            before = parser.fingerprint([one, two])
            self.assertEqual(parser.fingerprint([one, two]), before)
            two.write_text("b = 3\n")
            self.assertNotEqual(parser.fingerprint([one, two]), before)

    def test_the_version_covers_the_name_reader_and_its_bundled_parts(self):
        names = [Path(p).as_posix() for p in parser._READER_FILES]
        self.assertTrue(names[0].endswith("backend/parser.py"))
        self.assertTrue(any(n.endswith("vendor/guessit/__version__.py") for n in names))
        self.assertTrue(any(n.endswith("vendor/rebulk/__version__.py") for n in names))
        for path in parser._READER_FILES:
            self.assertTrue(Path(path).is_file(), path)


class MissingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.roots = make_folders(self.root)
        self.movies = Path(self.roots["movies"])
        self.tv = Path(self.roots["tv"])
        self.first = scan(self.roots)

    def tearDown(self):
        self.tmp.cleanup()

    def render(self, index):
        return library_index.render(index, self.roots)

    def test_a_file_that_disappears_is_kept_marked_missing_with_its_id(self):
        gone = self.movies / MOVIE_FILES[2]
        gone.unlink()
        again = scan(self.roots, self.first)
        film = items(again, "movies")["Other Movie"]
        self.assertEqual(film["id"], items(self.first, "movies")["Other Movie"]["id"])
        self.assertEqual(film["status"], "missing")
        self.assertTrue(film["missing_since"])
        self.assertEqual(again["last_scan"]["missing"], 1)
        shown = {i["display_title"]: i for i in self.render(again)["movies"]["items"]}
        self.assertEqual((shown["Other Movie (1999)"]["missing"], shown["Other Movie (1999)"]["missing_note"]),
                         (True, "Missing"))
        self.assertEqual(self.render(again)["missing_count"], 1)

        since = film["missing_since"]
        later = scan(self.roots, again)  # still gone: same item, same time
        self.assertEqual(items(later, "movies")["Other Movie"]["missing_since"], since)

        gone.write_bytes(b"x")
        back = scan(self.roots, later)
        film = items(back, "movies")["Other Movie"]
        self.assertNotIn("status", film)
        self.assertEqual(film["id"], items(self.first, "movies")["Other Movie"]["id"])
        self.assertEqual(self.render(back)["missing_count"], 0)

    def test_a_renamed_single_film_shows_the_old_entry_missing_and_a_new_one(self):
        old = self.movies / MOVIE_FILES[2]
        old.rename(old.with_name("Other.Movie.1999.720p.mkv"))
        again = scan(self.roots, self.first)
        films = [i for i in again["sources"]["movies"]["items"] if i["title"] == "Other Movie"]
        self.assertEqual(len(films), 2)
        missing = [f for f in films if f.get("status") == "missing"]
        present = [f for f in films if f.get("status") != "missing"]
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]["id"], items(self.first, "movies")["Other Movie"]["id"])
        self.assertNotEqual(present[0]["id"], missing[0]["id"])
        all_ids = [i["id"] for i in again["sources"]["movies"]["items"]]
        self.assertEqual(len(all_ids), len(set(all_ids)))

    def test_a_film_with_one_part_gone_says_1_of_2_parts_missing(self):
        (self.movies / MOVIE_FILES[1]).unlink()
        again = scan(self.roots, self.first)
        film = items(again, "movies")["Example Film"]
        self.assertNotIn("status", film)
        self.assertEqual([p.get("status") for p in film["parts"]], [None, "missing"])
        shown = {i["display_title"]: i for i in self.render(again)["movies"]["items"]}["Example Film (2001)"]
        self.assertEqual(shown["missing_note"], "1 of 2 parts missing")
        self.assertFalse(shown["missing"])

    def test_episodes_are_marked_one_by_one_and_a_show_only_when_all_are_gone(self):
        (self.tv / TV_FILES[0]).unlink()
        again = scan(self.roots, self.first)
        show = items(again, "tv")["Kiri Anime"]
        self.assertNotIn("status", show)
        marks = {p: e.get("status") for p, e in episodes(show).items()}
        self.assertEqual(marks, {TV_FILES[0]: "missing", TV_FILES[1]: None, TV_FILES[2]: None})
        self.assertEqual(episodes(show)[TV_FILES[0]]["id"],
                         episodes(items(self.first, "tv")["Kiri Anime"])[TV_FILES[0]]["id"])

        shutil.rmtree(self.tv / "Kiri Anime")
        gone = scan(self.roots, again)
        show = items(gone, "tv")["Kiri Anime"]
        self.assertEqual(show["status"], "missing")
        self.assertEqual(show["id"], items(self.first, "tv")["Kiri Anime"]["id"])
        self.assertTrue(all(e["status"] == "missing" for e in episodes(show).values()))
        self.assertEqual(len(episodes(show)), 3)
        rendered = {i["display_title"]: i for i in self.render(gone)["tv"]["items"]}["Kiri Anime"]
        self.assertEqual(rendered["missing_note"], "Missing")

    def test_a_missing_folder_marks_nothing_missing_and_is_not_available(self):
        shutil.rmtree(self.roots["movies"])
        again = scan(self.roots, self.first)
        self.assertEqual(again["sources"]["movies"], self.first["sources"]["movies"])
        self.assertEqual(again["last_scan"]["not_available"], ["movies"])
        self.assertEqual(again["last_scan"]["missing"], 0)
        answer = self.render(again)
        self.assertEqual(answer["missing_count"], 0)
        self.assertFalse(any(i["missing"] for i in answer["movies"]["items"]))
        self.assertFalse(library_index.availability(self.roots)["movies"])

    def test_an_unreadable_folder_keeps_its_items_as_they_were(self):
        folder = self.tv / "Kiri Anime"
        os.chmod(folder, 0)
        try:
            if os.access(folder, os.R_OK):
                self.skipTest("running with permissions that read anything")
            again = scan(self.roots, self.first)
        finally:
            os.chmod(folder, 0o755)
        show = items(again, "tv")["Kiri Anime"]
        self.assertNotIn("status", show)
        self.assertEqual(len(episodes(show)), 3)
        self.assertEqual(again["last_scan"]["missing"], 0)

    # --- The card going away during a scan: never everything missing ---

    def assert_movies_not_available(self, again):
        self.assertEqual(again["sources"]["movies"], self.first["sources"]["movies"])
        self.assertEqual(again["last_scan"]["not_available"], ["movies"])
        self.assertEqual(again["last_scan"]["missing"], 0)
        self.assertEqual(self.render(again)["missing_count"], 0)

    def failing(self, name, broken):
        """os.<name> raising a read error (not "permission denied") for the
        paths in `broken`, and working as usual for everything else."""
        real = getattr(os, name)

        def fake(path=".", *args, **kwargs):
            if os.path.realpath(path) in broken:
                raise OSError(5, "Input/output error")
            return real(path, *args, **kwargs)

        return mock.patch.object(os, name, fake)

    def test_a_top_folder_that_cant_be_listed_while_scanning_is_not_available(self):
        top = os.path.realpath(self.roots["movies"])
        with self.failing("scandir", {top}):
            again = scan(self.roots, self.first)
        self.assert_movies_not_available(again)

    def test_a_read_error_on_the_top_folder_says_folder_not_available(self):
        top = os.path.realpath(self.roots["movies"])
        with self.failing("listdir", {top}), self.failing("scandir", {top}):
            again = scan(self.roots, self.first)
            self.assertFalse(library_index.availability(self.roots)["movies"])
        self.assert_movies_not_available(again)

    def gone_after_listing(self, folder):
        """A scan where `folder` disappears between the listing and the grouping."""
        real_walk = library_index._walk_files
        aside = Path(self.tmp.name, "aside")

        def walk_then_remove(root):
            walked = real_walk(root)
            if root == self.roots["movies"]:
                os.rename(folder, aside)
            return walked

        try:
            with mock.patch.object(library_index, "_walk_files", walk_then_remove):
                return scan(self.roots, self.first)
        finally:
            if aside.exists():
                os.rename(aside, folder)

    def test_the_card_going_between_listing_and_grouping_marks_nothing_missing(self):
        again = self.gone_after_listing(self.movies)
        self.assert_movies_not_available(again)

    # --- The pulled card fix: the card pulled out during a rescan ---

    def test_the_folder_vanishing_mid_scan_keeps_it_and_still_scans_the_other_one(self):
        added = self.tv / "Test Show/Season 2/Test.Show.S02E06.mkv"
        added.write_bytes(b"x")
        (self.tv / TV_FILES[4]).unlink()
        again = self.gone_after_listing(self.movies)
        # Movies: the saved list as it was, "not available", nothing missing.
        self.assertEqual(again["sources"]["movies"], self.first["sources"]["movies"])
        self.assertEqual(again["last_scan"]["not_available"], ["movies"])
        self.assertFalse(any(i["missing"] for i in self.render(again)["movies"]["items"]))
        # TV Shows: scanned as usual, the new episode in, the gone one marked.
        self.assertEqual(again["last_scan"]["new"], 1)
        self.assertEqual(again["last_scan"]["missing"], 1)
        show = episodes(items(again, "tv")["Test Show"])
        self.assertIn(added.relative_to(self.tv).as_posix(), show)
        self.assertEqual(show[TV_FILES[4]]["status"], "missing")
        self.assertIn(added.relative_to(self.tv).as_posix(),
                      [f["path"] for f in again["sources"]["tv"]["files"]])

    def test_the_folder_vanishing_partway_through_reading_it_is_not_available(self):
        # The top folder is listed, then the card goes before its subfolders.
        from backend import library_movies

        real_read = library_movies.read_folder
        aside = Path(self.tmp.name, "aside")

        def read_then_pull(path, rel, *args):
            answer = real_read(path, rel, *args)
            if rel.as_posix() == "." and path == os.path.realpath(self.movies) and not aside.exists():
                os.rename(self.movies, aside)
            return answer

        try:
            with mock.patch.object(library_movies, "read_folder", read_then_pull):
                again = scan(self.roots, self.first)
        finally:
            if aside.exists():
                os.rename(aside, self.movies)
        self.assert_movies_not_available(again)
        self.assertEqual(again["sources"]["tv"]["items"], self.first["sources"]["tv"]["items"])

    def test_an_unreadable_subfolder_is_listed_as_skipped_and_the_rest_is_saved(self):
        added = self.movies / "New.Example.2005.mkv"
        added.write_bytes(b"x")
        broken = os.path.realpath(self.tv / "Test Show/Season 2")
        with self.failing("scandir", {broken}):
            again = scan(self.roots, self.first)
        self.assertEqual(again["last_scan"]["not_available"], [])
        tv = again["sources"]["tv"]
        self.assertIn({"path": "Test Show/Season 2", "reason": "cannot be read"}, tv["skipped"])
        self.assertEqual(self.render(again)["skipped"]["tv"], tv["skipped"])
        # Everything else is read and saved as usual.
        saved = {f["path"] for f in tv["files"]}
        for rel in TV_FILES:
            if not rel.startswith("Test Show/Season 2/"):
                self.assertIn(rel, saved)
        self.assertIn(added.name, [f["path"] for f in again["sources"]["movies"]["files"]])
        # What was in the unreadable folder stays as it was, not missing.
        show = episodes(items(again, "tv")["Test Show"])
        self.assertNotIn("status", show[TV_FILES[5]])
        self.assertEqual(again["last_scan"]["missing"], 0)

    def test_a_folder_that_fails_to_list_while_grouping_keeps_its_items(self):
        folder = os.path.realpath(self.movies / "Other Movie (1999)")
        real_walk = library_index._walk_files
        patches = []

        def walk_then_break(root):
            walked = real_walk(root)
            if root == self.roots["movies"]:
                patches.append(self.failing("scandir", {folder}))
                patches[-1].start()
            return walked

        try:
            with mock.patch.object(library_index, "_walk_files", walk_then_break):
                again = scan(self.roots, self.first)
        finally:
            for patch in patches:
                patch.stop()
        film = items(again, "movies")["Other Movie"]
        self.assertNotIn("status", film)
        self.assertEqual(film["id"], items(self.first, "movies")["Other Movie"]["id"])
        self.assertEqual(again["last_scan"]["missing"], 0)

    def test_remove_deletes_only_missing_items(self):
        (self.movies / MOVIE_FILES[1]).unlink()
        (self.movies / MOVIE_FILES[2]).unlink()
        (self.tv / TV_FILES[3]).unlink()
        again = scan(self.roots, self.first)
        self.assertEqual(self.render(again)["missing_count"], 3)
        cleaned, removed = library_index.remove_missing(again)
        self.assertEqual(removed, 3)
        films = items(cleaned, "movies")
        self.assertEqual(set(films), {"Example Film"})
        self.assertEqual([p["path"] for p in films["Example Film"]["parts"]], [MOVIE_FILES[0]])
        test_show = episodes(items(cleaned, "tv")["Test Show"])
        self.assertNotIn(TV_FILES[3], test_show)
        self.assertEqual(set(test_show), set(TV_FILES[4:]))
        self.assertEqual(len(episodes(items(cleaned, "tv")["Kiri Anime"])), 3)
        self.assertEqual(self.render(cleaned)["missing_count"], 0)
        self.assertEqual(cleaned["last_scan"]["missing"], 0)
        # The library it came from is untouched.
        self.assertEqual(self.render(again)["missing_count"], 3)
        # A rescan afterwards brings nothing back.
        self.assertEqual(self.render(scan(self.roots, cleaned))["missing_count"], 0)

    def test_remove_drops_a_whole_missing_show_and_seasons_left_empty(self):
        shutil.rmtree(self.tv / "Kiri Anime")
        (self.tv / TV_FILES[5]).unlink()  # the only episode of season 2
        again = scan(self.roots, self.first)
        # A whole missing show is one item; a lone missing episode is one.
        self.assertEqual(self.render(again)["missing_count"], 2)
        self.assertEqual(again["last_scan"]["missing"], 2)
        cleaned, removed = library_index.remove_missing(again)
        self.assertEqual(removed, 2)
        shows = items(cleaned, "tv")
        self.assertEqual(set(shows), {"Test Show"})
        self.assertNotIn(2, [s["number"] for s in shows["Test Show"]["seasons"]])
        self.assertTrue(all(s["episodes"] for s in shows["Test Show"]["seasons"]))
        self.assertEqual(cleaned["sources"]["tv"]["counts"]["items"], 1)

    def test_missing_episodes_and_parts_are_flagged_for_the_page(self):
        (self.tv / TV_FILES[4]).unlink()
        (self.movies / MOVIE_FILES[0]).unlink()
        answer = self.render(scan(self.roots, self.first))
        show = {i["display_title"]: i for i in answer["tv"]["items"]}["Test Show"]
        self.assertEqual((show["missing"], show["missing_note"]), (False, ""))
        marks = {e["path"]: (e["missing"], e["missing_note"]) for s in show["seasons"] for e in s["episodes"]}
        self.assertEqual(marks[TV_FILES[4]], (True, "Missing"))
        self.assertEqual(marks[TV_FILES[3]], (False, ""))
        film = {i["display_title"]: i for i in answer["movies"]["items"]}["Example Film (2001)"]
        self.assertEqual({p["path"]: p["missing"] for p in film["parts"]},
                         {MOVIE_FILES[0]: True, MOVIE_FILES[1]: False})
        self.assertEqual(film["missing_note"], "1 of 2 parts missing")

    def test_a_missing_first_part_keeps_its_place_before_the_second(self):
        (self.movies / MOVIE_FILES[0]).unlink()
        film = items(scan(self.roots, self.first), "movies")["Example Film"]
        self.assertEqual([(p["path"], p.get("status")) for p in film["parts"]],
                         [(MOVIE_FILES[0], "missing"), (MOVIE_FILES[1], None)])

    def test_the_log_line_counts_new_changed_missing_and_names_read(self):
        (self.movies / MOVIE_FILES[2]).unlink()
        (self.tv / TV_FILES[3]).write_bytes(b"longer now")
        (self.movies / "New.Example.2005.mkv").write_bytes(b"x")
        line = library_index.summary(scan(self.roots, self.first))
        self.assertTrue(line.endswith("1 new, 1 changed, 1 missing, 2 names read"), line)


@full_only
class TimingTest(unittest.TestCase):
    def test_timing_quick_rescan_of_2000_unchanged_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            movies = Path(tmp) / "Movies"
            tv = Path(tmp) / "TV Shows"
            tv.mkdir()
            for n in range(2000):
                folder = movies / f"Invented Film {n} ({1950 + n % 70})"
                folder.mkdir(parents=True)
                (folder / f"Invented.Film.{n}.{1950 + n % 70}.1080p.mkv").write_bytes(b"x")
            roots = {"movies": str(movies), "tv": str(tv)}
            scan(roots)  # warm up: loads the name reader once
            start = time.perf_counter()
            full = scan(roots)
            full_time = time.perf_counter() - start
            start = time.perf_counter()
            quick, read = counted_scan(roots, full)
            quick_time = time.perf_counter() - start
        self.assertEqual(read, [])
        self.assertEqual(len(quick["sources"]["movies"]["items"]), 2000)
        print(f"\n  rescan timing, 2,000 unchanged invented films: full scan {full_time:.2f} s, "
              f"quick rescan {quick_time:.2f} s")


class RescanServerTest(test_library_index.ScanServerTest):
    """The endpoints. Reuses the saved library work server set-up; its own tests are
    switched off here so they don't run twice."""

    for _name in [n for n in dir(test_library_index.ScanServerTest) if n.startswith("test_")]:
        locals()[_name] = None
    del _name

    def _post(self, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        conn.request("POST", path, body=json.dumps(body or {}), headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        data = json.loads(resp.read().decode("utf-8"))
        conn.close()
        return resp.status, data

    def test_a_scan_request_while_playing_answers_busy(self):
        finish = threading.Event()

        def play(*args, **kwargs):
            finish.wait(10)
            return {"ok": True}

        detect = {"available": True, "command": ["mpv"], "via": "configured"}
        with mock.patch("backend.server.mpv.detect", return_value=detect), \
                mock.patch("backend.server.mpv.play", side_effect=play), \
                mock.patch.object(library_index, "full_scan") as full_scan:
            status, started = self._post("/api/play", {"source": "movies", "path": MOVIE_FILES[2]})
            self.assertEqual((status, started), (200, {"started": True, "keep_awake": False}))
            status, answer = self._post("/api/library/scan")
            finish.set()
            end = time.time() + 10
            while self._request("GET", "/api/status")[1]["state"] == "playing" and time.time() < end:
                time.sleep(0.05)
        self.assertEqual(status, 409)
        self.assertEqual(answer, {"started": False, "busy": True, "error": "Rescan unavailable while playing"})
        full_scan.assert_not_called()
        self.assertTrue(self._scan()["last_result"]["ok"])  # after playing, it scans again

    def test_remove_deletes_only_missing_items_and_saves_them(self):
        self._scan()
        (Path(self.roots["movies"]) / MOVIE_FILES[2]).unlink()
        self._scan()
        answer = self._request("GET", "/api/library/parsed")[1]
        self.assertEqual(answer["missing_count"], 1)
        self.assertEqual(answer["last_scan"]["missing"], 1)
        with contextlib.redirect_stdout(self.out):
            status, result = self._post("/api/library/remove-missing")
        self.assertEqual((status, result), (200, {"ok": True, "removed": 1}))
        after = self._request("GET", "/api/library/parsed")[1]
        self.assertEqual(after["missing_count"], 0)
        self.assertEqual([i["display_title"] for i in after["movies"]["items"]], ["Example Film (2001)"])
        self.assertEqual(len(after["tv"]["items"]), 2)
        saved = json.loads((self.data / "library.json").read_text())
        self.assertEqual(len(saved["sources"]["movies"]["items"]), 1)

    def test_a_failed_remove_leaves_the_saved_library_unchanged(self):
        self._scan()
        (Path(self.roots["movies"]) / MOVIE_FILES[2]).unlink()
        self._scan()
        before = (self.data / "library.json").read_bytes()
        with mock.patch.object(library_index.os, "replace", side_effect=OSError("disk full")), \
                contextlib.redirect_stdout(self.out):
            status, result = self._post("/api/library/remove-missing")
        self.assertFalse(result["ok"])
        self.assertEqual((self.data / "library.json").read_bytes(), before)
        self.assertEqual(self._request("GET", "/api/library/parsed")[1]["missing_count"], 1)

    def test_remove_during_a_scan_answers_busy_and_removes_nothing(self):
        self._scan()
        (Path(self.roots["movies"]) / MOVIE_FILES[2]).unlink()
        self._scan()
        saved = (self.data / "library.json").read_bytes()
        release = threading.Event()
        real = library_index.full_scan

        def slow(*args):
            release.wait(10)
            return real(*args)

        with mock.patch.object(library_index, "full_scan", side_effect=slow), \
                contextlib.redirect_stdout(self.out):
            self._request("POST", "/api/library/scan")
            status, result = self._post("/api/library/remove-missing")
            during = (self.data / "library.json").read_bytes()
            release.set()
            self._wait_idle()
        self.assertEqual(status, 409)
        self.assertFalse(result["ok"])
        self.assertTrue(result["busy"])
        self.assertEqual(during, saved)
        # The scan that was running still sees the film as missing.
        self.assertEqual(self._request("GET", "/api/library/parsed")[1]["missing_count"], 1)

    def test_a_scan_error_leaves_the_saved_library_and_its_missing_marks(self):
        self._scan()
        (Path(self.roots["movies"]) / MOVIE_FILES[2]).unlink()
        self._scan()
        saved = (self.data / "library.json").read_bytes()
        with mock.patch.object(library_index, "_keep_missing", side_effect=RuntimeError("boom")):
            status = self._scan()
        self.assertFalse(status["last_result"]["ok"])
        self.assertEqual((self.data / "library.json").read_bytes(), saved)


if __name__ == "__main__":
    unittest.main()
