# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Continue watching (the Continue watching work): which items show, in what order, what the
tiles say, and when their pictures are deleted. Invented titles and a
saved library built by hand; no real video files.

Run from the repo root:  python3 -m unittest tests.test_continue_watching -v
"""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from backend import continue_watching as cw
from backend import mpv
from backend.library_index import item_id

ROOTS = {"movies": "/media/Movies", "tv": "/media/TV Shows"}
AVAILABLE = {"movies": True, "tv": True}
HOUR = 3600.0


def movie(key, title, parts, year=None, status=None, part_status=None):
    item = {
        "id": item_id("movies", key), "key": key, "title": title, "year": year, "flags": [],
        "parts": [{"label": label, "path": path} for label, path in parts],
    }
    if status:
        item["status"] = status
    if part_status:
        item["parts"][part_status[0]]["status"] = part_status[1]
    return item


def show(key, title, seasons):
    return {
        "id": item_id("tv", key), "key": key, "title": title, "year": None, "path": key,
        "seasons": [
            {"number": number, "episodes": [
                {"numbers": numbers, "title": "", "path": path, "flags": [], "id": item_id("tv", path)}
                for numbers, path in episodes
            ]}
            for number, episodes in seasons
        ],
    }


def library(movies=(), shows=()):
    return {"schema_version": 1, "sources": {
        "movies": {"root": ROOTS["movies"], "items": list(movies)},
        "tv": {"root": ROOTS["tv"], "items": list(shows)},
    }}


# Eight films, one in two parts, and a show with seasons, specials and an
# absolutely numbered one.
FILMS = [movie(f"Film {n}", f"Film {n}", [("", f"Film {n}/Film {n}.mkv")], year=2000 + n) for n in range(1, 9)]
SPLIT = movie("Split", "Split Film", [("Part 1", "Split/Split.cd1.mkv"), ("Part 2", "Split/Split.cd2.mkv")])
SHOW = show("Show", "Example Show", [
    (1, [([1], "Show/S01/e1.mkv"), ([2], "Show/S01/e2.mkv")]),
    (2, [([5], "Show/S02/e5.mkv")]),
    (0, [([3], "Show/Specials/sp3.mkv")]),
])
FLAT = show("Flat", "Flat Show", [(None, [([37], "Flat/37.mkv")])])
INDEX = library(FILMS + [SPLIT], [SHOW, FLAT])


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.data = self.dir / "data"
        self.logged = []
        self.store = self.new_store()
        self.clock = 1_000_000.0
        self.frame = self.dir / "frame.jpg"
        self.frame.write_bytes(b"\xff\xd8 full frame")

    def tearDown(self):
        self.tmp.cleanup()

    def new_store(self, roots=ROOTS):
        return cw.ContinueWatching(self.data, roots.values(), self.logged.append)

    def stop(self, rel, position, duration=2 * HOUR, finished=False, frame=True, source=None):
        """Plays the file `rel` and stops it, like mpv's quit script."""
        source = source or ("tv" if rel.startswith(("Show/", "Flat/")) else "movies")
        target = cw.locate(INDEX, ROOTS, source, rel)
        self.assertIsNotNone(target, rel)
        self.clock += 10
        record = {"position": position, "duration": duration, "finished": finished, "frame_saved": frame}
        return self.store.record_stop(target, rel, record, self.frame if frame else None, self.clock)

    def shown(self, index=INDEX, available=AVAILABLE):
        return self.store.items(index, ROOTS, available)

    def names(self):
        return [item["name"] for item in self.shown()]

    def picture(self, rel):
        return self.data / cw.PICTURES_DIR / f"{FILMS_BY_PATH[rel]}.jpg"


FILMS_BY_PATH = {p["path"]: m["id"] for m in FILMS + [SPLIT] for p in m["parts"]}
FILMS_BY_PATH.update({e["path"]: s["id"] for s in (SHOW, FLAT) for season in s["seasons"] for e in season["episodes"]})


class RulesTest(Base):
    def test_sixty_seconds_rule(self):
        self.stop(FILMS[0]["parts"][0]["path"], 59)
        self.assertEqual(self.shown(), [])
        self.assertFalse(self.picture(FILMS[0]["parts"][0]["path"]).exists())
        self.stop(FILMS[0]["parts"][0]["path"], 60)
        self.assertEqual(self.names(), ["Film 1"])
        self.assertTrue(self.picture(FILMS[0]["parts"][0]["path"]).exists())

    def test_finished_at_95_percent(self):
        rel = FILMS[0]["parts"][0]["path"]
        self.stop(rel, 0.94 * 2 * HOUR)
        self.assertEqual(self.names(), ["Film 1"])
        self.stop(rel, 0.95 * 2 * HOUR)
        self.assertEqual(self.shown(), [])
        self.assertFalse(self.picture(rel).exists())

    def test_played_to_the_end_is_finished(self):
        rel = FILMS[0]["parts"][0]["path"]
        self.stop(rel, 600)
        self.stop(rel, None, finished=True, frame=False)
        self.assertEqual(self.shown(), [])
        self.assertFalse(self.picture(rel).exists())

    def test_is_finished(self):
        self.assertTrue(cw.is_finished(95, 100, False))
        self.assertFalse(cw.is_finished(94.9, 100, False))
        self.assertTrue(cw.is_finished(10, 100, True))
        self.assertFalse(cw.is_finished(500, None, False))  # length unknown: never by share

    def test_cap_of_six_newest_first(self):
        for film in FILMS[:6]:
            self.stop(film["parts"][0]["path"], 600)
        self.assertEqual(self.names(), [f"Film {n}" for n in range(6, 0, -1)])

    def test_seventh_drops_the_oldest_and_keeps_its_position(self):
        for film in FILMS[:7]:
            self.stop(film["parts"][0]["path"], 600 + int(film["year"]))
        self.assertEqual(self.names(), [f"Film {n}" for n in range(7, 1, -1)])
        oldest = self.store.entries[FILMS[0]["id"]]
        self.assertEqual(oldest["hidden"], cw.DROPPED)
        self.assertEqual(oldest["position"], 600 + 2001)  # still known
        self.assertFalse(self.picture(FILMS[0]["parts"][0]["path"]).exists())
        # It doesn't come back when another leaves...
        self.store.remove(FILMS[6]["id"])
        self.assertNotIn("Film 1", self.names())
        # ...only the next time it is stopped.
        self.stop(FILMS[0]["parts"][0]["path"], 900)
        self.assertEqual(self.names()[0], "Film 1")

    def test_remove_keeps_the_position_and_it_comes_back(self):
        rel = FILMS[0]["parts"][0]["path"]
        self.stop(rel, 1234)
        self.assertTrue(self.store.remove(FILMS[0]["id"]))
        self.assertEqual(self.shown(), [])
        self.assertEqual(self.store.entries[FILMS[0]["id"]]["position"], 1234)
        self.assertEqual(self.store.entries[FILMS[0]["id"]]["hidden"], cw.REMOVED)
        self.assertFalse(self.picture(rel).exists())
        self.assertFalse(self.store.remove(FILMS[0]["id"]))  # already gone
        self.stop(rel, 1300)
        self.assertEqual(self.names(), ["Film 1"])

    def test_saved_and_read_back(self):
        self.stop(FILMS[0]["parts"][0]["path"], 1234)
        self.store.remove(FILMS[0]["id"])
        self.stop(FILMS[1]["parts"][0]["path"], 600)
        again = self.new_store()
        self.assertEqual(again.entries, self.store.entries)
        self.assertEqual([i["name"] for i in again.items(INDEX, ROOTS, AVAILABLE)], ["Film 2"])

    def test_a_damaged_saved_list_starts_empty(self):
        self.data.mkdir(parents=True, exist_ok=True)
        for text in ("{not json", json.dumps({"schema_version": 99, "entries": {}}), json.dumps([1])):
            (self.data / cw.FILE_NAME).write_text(text)
            self.assertEqual(self.new_store().entries, {})
        self.assertTrue(self.logged)


class TilesTest(Base):
    def test_one_tile_per_multi_part_movie_with_part_n(self):
        self.stop("Split/Split.cd1.mkv", 600)
        self.stop("Split/Split.cd2.mkv", 700)
        items = self.shown()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["label"], "Part 2")
        self.assertEqual(items[0]["name"], "Split Film · Part 2")
        self.assertEqual(items[0]["position"], 700)
        self.assertTrue(items[0]["caption"].startswith("Split Film · Part 2 · Resume at 11:40"))

    def test_single_part_film_has_no_part_label(self):
        self.stop(FILMS[0]["parts"][0]["path"], 600)
        self.assertEqual(self.shown()[0]["label"], "")
        self.assertEqual(self.shown()[0]["kind"], "movie")

    def test_one_tile_per_show_for_the_latest_episode(self):
        self.stop("Show/S01/e1.mkv", 600)
        self.stop("Show/S02/e5.mkv", 300)
        items = self.shown()
        self.assertEqual([i["name"] for i in items], ["Example Show · S2 E5"])
        self.assertEqual(items[0]["kind"], "episode")
        self.assertEqual(items[0]["position"], 300)

    def test_episode_names(self):
        self.stop("Flat/37.mkv", 600)
        self.stop("Show/Specials/sp3.mkv", 600)
        self.assertEqual(self.names(), ["Example Show · Special 3", "Flat Show · Episode 37"])

    def test_episode_label_formats(self):
        self.assertEqual(cw.episode_label(2, [5]), "S2 E5")
        self.assertEqual(cw.episode_label(None, [37]), "Episode 37")
        self.assertEqual(cw.episode_label(0, [3]), "Special 3")
        self.assertEqual(cw.episode_label(2, [5, 6]), "S2 E5-6")
        self.assertEqual(cw.episode_label(0, []), "Special")

    def test_caption_resume_and_time_left(self):
        self.stop(FILMS[0]["parts"][0]["path"], HOUR + 12 * 60 + 40, duration=HOUR + 12 * 60 + 40 + 44 * 60)
        self.assertEqual(self.shown()[0]["caption"], "Film 1 · Resume at 1:12:40 · 44 min left")

    def test_missing_item_stays_in_place_and_is_flagged(self):
        for film in FILMS[:3]:
            self.stop(film["parts"][0]["path"], 600 + film["year"])
        gone = library([movie("Film 2", "Film 2", [("", "Film 2/Film 2.mkv")], year=2002, status="missing")]
                       + FILMS[:1] + FILMS[2:], [SHOW, FLAT])
        items = self.shown(index=gone)
        self.assertEqual([i["name"] for i in items], ["Film 3", "Film 2", "Film 1"])
        self.assertEqual([i["missing"] for i in items], [False, True, False])
        self.assertEqual(items[1]["caption"], f"Film 2 · Missing · stopped at {cw.clock(600 + 2002)}")
        self.assertIsNotNone(items[1]["picture"])  # the picture stays, shown dark and grey

    def test_missing_part_or_folder_not_available_is_flagged(self):
        self.stop("Split/Split.cd2.mkv", 600)
        lost = library(FILMS + [movie("Split", "Split Film", [("Part 1", "Split/Split.cd1.mkv"),
                                                               ("Part 2", "Split/Split.cd2.mkv")],
                                      part_status=(1, "missing"))], [SHOW, FLAT])
        self.assertTrue(self.shown(index=lost)[0]["missing"])
        self.assertFalse(self.shown()[0]["missing"])
        self.assertTrue(self.shown(available={"movies": False, "tv": True})[0]["missing"])

    def test_time_formats(self):
        self.assertEqual(cw.clock(HOUR + 12 * 60 + 40), "1:12:40")
        self.assertEqual(cw.clock(38 * 60 + 10), "38:10")
        self.assertEqual(cw.clock(5), "0:05")
        self.assertEqual(cw.clock(10 * HOUR + 1), "10:00:01")
        self.assertEqual(cw.time_left(44 * 60), "44 min left")
        self.assertEqual(cw.time_left(43 * 60 + 1), "44 min left")  # rounded up
        self.assertEqual(cw.time_left(61), "2 min left")
        self.assertEqual(cw.time_left(60), "1 min left")
        self.assertEqual(cw.time_left(59), "less than 1 min left")
        self.assertEqual(cw.time_left(0), "less than 1 min left")

    def test_no_file_location_in_the_answer(self):
        for film in FILMS[:3]:
            self.stop(film["parts"][0]["path"], 600)
        self.stop("Show/S02/e5.mkv", 600)
        text = json.dumps(self.shown())
        for root in ROOTS.values():
            self.assertNotIn(root, text)
        for rel in FILMS_BY_PATH:
            self.assertNotIn(rel, text)
        self.assertEqual(set(self.shown()[0]), {"id", "kind", "title", "label", "name", "caption", "position",
                                                "duration", "missing", "picture"})

    def test_picture_link_and_file(self):
        rel = FILMS[0]["parts"][0]["path"]
        self.stop(rel, 600)
        link = self.shown()[0]["picture"]
        self.assertTrue(link.startswith(f"/api/continue/picture/{FILMS[0]['id']}?v="))
        self.assertEqual(self.store.picture_file(FILMS[0]["id"]).read_bytes(), self.frame.read_bytes())
        self.assertIsNone(self.store.picture_file("../../etc/passwd"))
        self.assertIsNone(self.store.picture_file(FILMS[1]["id"]))  # not in the carousel

    def test_no_frame_no_picture(self):
        rel = FILMS[0]["parts"][0]["path"]
        self.stop(rel, 600)
        self.stop(rel, 700, frame=False)  # e.g. the window was closed
        self.assertIsNone(self.shown()[0]["picture"])
        self.assertFalse(self.picture(rel).exists())

    def test_play_target(self):
        self.stop("Split/Split.cd2.mkv", 600)
        self.assertEqual(self.store.play_target(SPLIT["id"]), ("movies", "Split/Split.cd2.mkv"))
        self.assertIsNone(self.store.play_target(FILMS[0]["id"]))

    def test_a_file_outside_the_saved_library_is_not_recorded(self):
        self.assertIsNone(cw.locate(INDEX, ROOTS, "movies", "Elsewhere/Other.mkv"))
        self.assertIsNone(cw.locate(None, ROOTS, "movies", FILMS[0]["parts"][0]["path"]))


class PlayTitleTest(unittest.TestCase):
    """What D-pad Up shows in mpv (the playback controls work, the designer's choice A): Kettle's
    title in the tiles' wording, never the file name."""

    def title(self, source, rel):
        return cw.play_title(INDEX, ROOTS, source, rel)

    def test_film_with_its_year(self):
        self.assertEqual(self.title("movies", "Film 3/Film 3.mkv"), "Film 3 (2003)")

    def test_film_without_a_year(self):
        no_year = movie("Plain", "Plain Film", [("", "Plain/Plain.mkv")])
        self.assertEqual(cw.play_title(library([no_year]), ROOTS, "movies", "Plain/Plain.mkv"), "Plain Film")

    def test_part_of_a_split_film(self):
        self.assertEqual(self.title("movies", "Split/Split.cd2.mkv"), "Split Film · Part 2")

    def test_episodes(self):
        self.assertEqual(self.title("tv", "Show/S02/e5.mkv"), "Example Show · S2 E5")
        self.assertEqual(self.title("tv", "Show/Specials/sp3.mkv"), "Example Show · Special 3")
        self.assertEqual(self.title("tv", "Flat/37.mkv"), "Flat Show · Episode 37")

    def test_outside_the_saved_library_gives_none(self):
        self.assertIsNone(self.title("movies", "Elsewhere/Other.mkv"))
        self.assertIsNone(cw.play_title(None, ROOTS, "movies", "Film 1/Film 1.mkv"))
        self.assertIsNone(cw.play_title(INDEX, ROOTS, "nowhere", "Film 1/Film 1.mkv"))


class PicturesTest(Base):
    def files(self):
        folder = self.data / cw.PICTURES_DIR
        return sorted(p.name for p in folder.iterdir()) if folder.exists() else []

    def test_deleted_when_finished(self):
        rel = FILMS[0]["parts"][0]["path"]
        self.stop(rel, 600)
        self.assertEqual(len(self.files()), 1)
        self.stop(rel, 2 * HOUR, finished=True, frame=False)
        self.assertEqual(self.files(), [])

    def test_deleted_when_removed(self):
        self.stop(FILMS[0]["parts"][0]["path"], 600)
        self.store.remove(FILMS[0]["id"])
        self.assertEqual(self.files(), [])

    def test_deleted_when_it_drops_off(self):
        for film in FILMS[:7]:
            self.stop(film["parts"][0]["path"], 600)
        self.assertEqual(len(self.files()), 6)
        self.assertNotIn(f"{FILMS[0]['id']}.jpg", self.files())

    def test_deleted_when_removed_from_the_library(self):
        for film in FILMS[:2]:
            self.stop(film["parts"][0]["path"], 600)
        smaller = library(FILMS[1:] + [SPLIT], [SHOW, FLAT])  # Film 1 removed as missing
        self.assertEqual(self.store.prune(smaller, ROOTS), 1)
        self.assertEqual(self.files(), [f"{FILMS[1]['id']}.jpg"])
        self.assertNotIn(FILMS[0]["id"], self.store.entries)
        self.assertEqual(self.new_store().entries.keys(), {FILMS[1]["id"]})

    def test_episode_removed_from_the_library_goes_too(self):
        self.stop("Show/S02/e5.mkv", 600)
        without = library(FILMS + [SPLIT], [show("Show", "Example Show", [(1, [([1], "Show/S01/e1.mkv")])]), FLAT])
        self.assertEqual(self.store.prune(without, ROOTS), 1)
        self.assertEqual(self.files(), [])

    def test_prune_needs_a_library(self):
        self.stop(FILMS[0]["parts"][0]["path"], 600)
        self.assertEqual(self.store.prune(None, ROOTS), 0)
        self.assertEqual(len(self.files()), 1)

    def test_prune_keeps_an_item_when_nothing_is_saved_for_its_folder(self):
        # The folder choice screens: no folder chosen yet, a kind skipped, or a folder chosen
        # and not scanned yet say nothing about whether the file has left.
        self.stop(FILMS[0]["parts"][0]["path"], 600)
        self.stop("Show/S02/e5.mkv", 600)
        for roots in ({"movies": "", "tv": ""}, {**ROOTS, "tv": ""}, {**ROOTS, "movies": ""},
                      {**ROOTS, "tv": "/invented/other"}):
            with self.subTest(roots=roots):
                self.assertEqual(self.store.prune(INDEX, roots), 0)
                self.assertEqual(len(self.files()), 2)
                self.assertEqual(len(self.store.entries), 2)

    def test_launch_clean_up(self):
        self.stop(FILMS[0]["parts"][0]["path"], 600)
        self.stop(FILMS[1]["parts"][0]["path"], 600)
        self.store.remove(FILMS[1]["id"])
        folder = self.data / cw.PICTURES_DIR
        stray = item_id("movies", "Gone")
        (folder / f"{stray}.jpg").write_bytes(b"old")
        (folder / f"{FILMS[1]['id']}.jpg").write_bytes(b"left behind")
        (folder / f"{stray}.jpg.part").write_bytes(b"half")
        (folder / "notes.txt").write_text("not ours")
        self.assertEqual(self.new_store().clean_pictures(), 3)
        self.assertEqual(self.files(), [f"{FILMS[0]['id']}.jpg", "notes.txt"])

    def test_replaced_by_the_small_picture_unless_stopped_again(self):
        rel = FILMS[0]["parts"][0]["path"]
        stamp = self.stop(rel, 600)
        small = self.dir / "small.jpg"
        small.write_bytes(b"\xff\xd8 small")
        self.assertTrue(self.store.replace_picture(FILMS[0]["id"], stamp, small))
        self.assertEqual(self.picture(rel).read_bytes(), small.read_bytes())
        newer = self.stop(rel, 700)
        self.assertFalse(self.store.replace_picture(FILMS[0]["id"], stamp, small))  # an older frame
        self.assertEqual(self.picture(rel).read_bytes(), self.frame.read_bytes())
        self.store.remove(FILMS[0]["id"])
        self.assertFalse(self.store.replace_picture(FILMS[0]["id"], newer, small))
        self.assertFalse(self.picture(rel).exists())

    def test_never_inside_a_media_folder(self):
        roots = {"movies": str(self.dir), "tv": "/media/TV Shows"}  # data_dir sits inside Movies
        self.store = self.new_store(roots)
        self.assertFalse(self.store.pictures_allowed)
        self.assertIsNone(self.stop(FILMS[0]["parts"][0]["path"], 600))
        self.assertEqual(self.files(), [])
        self.assertEqual(self.names(), ["Film 1"])  # the tile is still there, as a plain surface
        self.assertIsNone(self.shown()[0]["picture"])

    def test_new_folders_follow_the_same_rule_with_the_same_log_line(self):
        # The first onboarding review fixes: onboarding changes the folders while the app is running.
        logged = []
        store = cw.ContinueWatching(self.data, [], logged.append)
        self.assertTrue(store.pictures_allowed)
        self.assertEqual(logged, [])
        store.set_media_roots([str(self.dir)])  # data_dir sits inside it
        self.assertFalse(store.pictures_allowed)
        self.assertEqual(logged, ["continue watching: data_dir is inside a media folder, so no pictures are saved"])
        store.set_media_roots(["/media/Movies"])
        self.assertTrue(store.pictures_allowed)
        self.assertEqual(len(logged), 1)

    def test_nothing_deleted_inside_a_media_folder(self):
        # Files that look like ours, in a "thumbnails" folder inside the media.
        folder = self.data / cw.PICTURES_DIR
        folder.mkdir(parents=True)
        lookalikes = [folder / f"{FILMS[0]['id']}.jpg", folder / f"{item_id('movies', 'Gone')}.jpg",
                      folder / f"{FILMS[1]['id']}.jpg.part"]
        for path in lookalikes:
            path.write_bytes(b"someone's file")
        self.store = self.new_store({"movies": str(self.dir), "tv": "/media/TV Shows"})
        self.assertEqual(self.store.clean_pictures(), 0)
        rel = FILMS[0]["parts"][0]["path"]
        self.stop(rel, 600)
        self.stop(rel, 2 * HOUR, finished=True)  # finished
        self.stop(FILMS[1]["parts"][0]["path"], 600)
        self.store.remove(FILMS[1]["id"])  # X
        for film in FILMS[2:]:
            self.stop(film["parts"][0]["path"], 600)  # one drops off
        self.store.prune(library(FILMS[3:]), ROOTS)  # removed from the library
        self.assertTrue(all(path.read_bytes() == b"someone's file" for path in lookalikes))

    def test_picture_folder_is_not_tracked_by_git(self):
        repo = Path(__file__).resolve().parent.parent
        if shutil.which("git") is None or not (repo / ".git").exists():
            self.skipTest("no git checkout")
        folder = f"data/{cw.PICTURES_DIR}/{FILMS[0]['id']}.jpg"
        ignored = subprocess.run(["git", "check-ignore", "-q", folder], cwd=repo)
        self.assertEqual(ignored.returncode, 0, "the default picture folder must be ignored by git")

    def test_logs_name_no_picture_or_title(self):
        self.data.mkdir(parents=True, exist_ok=True)
        (self.data / cw.FILE_NAME).write_text("{damaged")
        self.store = self.new_store({"movies": str(self.dir), "tv": "/media/TV Shows"})
        self.stop(FILMS[0]["parts"][0]["path"], 600)
        self.store.remove(FILMS[0]["id"])
        text = "\n".join(self.logged)
        self.assertTrue(text)
        for word in (FILMS[0]["id"], "Film 1", ".jpg", cw.PICTURES_DIR, str(self.dir)):
            self.assertNotIn(word, text)


class MpvCommandTest(unittest.TestCase):
    """How the quit script is handed to mpv, and the small picture."""

    FILE = Path("/media/Movies/Film/Film.mkv")
    CAPTURE = Path("/tmp/kettle-quit-abc")

    def build(self, extra=(), resume=True, capture=CAPTURE):
        return mpv.build_command(["mpv"], self.FILE, list(extra), resume, capture)

    def test_script_and_folder_only_with_a_capture_folder_and_resume(self):
        args = self.build()
        self.assertIn(f"--script={mpv.QUIT_CAPTURE_SCRIPT}", args)
        self.assertIn(f"--script-opts-append=kettle_quit-out_dir={self.CAPTURE}", args)
        self.assertIn(f"--script={mpv.RESUME_REWIND_SCRIPT}", args)
        self.assertEqual(args[-1], str(self.FILE))
        for args in (self.build(capture=None), self.build(resume=False)):
            self.assertFalse(any("quit_capture" in a or "kettle_quit" in a for a in args), args)

    def test_folder_comes_after_the_users_script_opts(self):
        # A --script-opts in mpv_args replaces the whole list; ours is added after it.
        user = ["--script-opts=osc-hidetimeout=4000"]
        args = self.build(extra=user)
        self.assertLess(args.index(user[0]), args.index(f"--script-opts-append=kettle_quit-out_dir={self.CAPTURE}"))
        self.assertTrue(mpv.QUIT_CAPTURE_SCRIPT.is_file())

    def test_shrink_frame(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            fake = out / "fake-mpv"
            fake.write_text("#!/bin/sh\nfor a in \"$@\"; do case \"$a\" in --vo-image-outdir=*) "
                            "printf small > \"${a#--vo-image-outdir=}/00000001.jpg\";; esac; done\n")
            fake.chmod(0o755)
            self.assertEqual(mpv.shrink_frame([str(fake)], out / "frame.jpg", out), out / "00000001.jpg")
            self.assertEqual((out / "00000001.jpg").read_text(), "small")
            (out / "00000001.jpg").unlink()
            silent = out / "silent-mpv"
            silent.write_text("#!/bin/sh\nexit 1\n")
            silent.chmod(0o755)
            self.assertIsNone(mpv.shrink_frame([str(silent)], out / "frame.jpg", out))
            self.assertIsNone(mpv.shrink_frame([str(out / "no-such-mpv")], out / "frame.jpg", out))


if __name__ == "__main__":
    unittest.main()
