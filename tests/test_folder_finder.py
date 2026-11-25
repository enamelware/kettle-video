# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Onboarding 1a (the folder finder): finding the folders with videos, grouped by
place. Every folder and file here is invented, in a temporary folder;
videos are sparse files, so a "big" one takes no disk space.

Checks: the suggestion rule with the storage report's cases; the places
(only real mounts, display names, numbering, what kind of drive); a card
that can't be read is "not ready"; the counts and example names; the
"what was checked" summary; the time limit; no full path in the answer, the
log line or the server's response; the folders are unchanged after a
search.

Run from the repo root:  python3 -m unittest tests.test_folder_finder -v
"""

import contextlib
import hashlib
import http.client
import io
import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from backend import folder_finder as ff
from backend import server

UI_DIR = Path(__file__).resolve().parent.parent / "ui"
BIG = ff.MIN_VIDEO_BYTES


def make(root, files, size=BIG):
    for rel in files:
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.truncate(size)


def snapshot(root):
    """Every folder's and file's path, size, times and (for files) bytes."""
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            path = os.path.join(dirpath, name)
            st = os.lstat(path)
            digest = None
            if name in filenames:
                with open(path, "rb") as f:
                    digest = hashlib.sha256(f.read()).hexdigest()
            out[os.path.relpath(path, root)] = (st.st_mode, st.st_size, st.st_mtime_ns, digest)
    st = os.lstat(root)
    out["."] = (st.st_mode, st.st_mtime_ns)
    return out


# The storage report's invented layouts (Question 3): files, then the
# folders expected to be suggested ("." is the place itself).
LAYOUTS = {
    "tidy card": (["Films/Alpha (2001)/Alpha.mkv", "Films/Beta/Beta.mp4",
                   "TV/Gamma/Season 1/e01.mkv", "TV/Gamma/Season 2/e01.mkv",
                   "TV/Delta/e01.mkv", "TV/Delta/e02.mkv",
                   "Films/Beta/Sample/beta-sample.mkv", "Films/._Alpha.mkv"],
                  {"Films", "TV"}),
    "nested media folder": (["Media/Films/A/a.mkv", "Media/Films/B/b.mkv",
                             "Media/TV/C/Season 1/e1.mkv", "Media/TV/D/e1.mkv"],
                            {"Media/Films", "Media/TV"}),
    "videos at the top": (["a.mkv", "b.mkv", "Films/C/c.mkv"], {".", "Films"}),
    "a single long chain": (["Stuff/Video/Films/A/a.mkv", "Stuff/Video/Films/B/b.mkv"],
                            {"Stuff/Video/Films"}),
    "one show with seasons": (["Shows/E/Season 1/e1.mkv", "Shows/E/Season 2/e1.mkv",
                               "Shows/E/Specials/s1.mkv", "Shows/E/S03/e1.mkv"], {"Shows"}),
    "one film": (["Films/F/f.mkv"], {"Films"}),
    "Steam and hidden folders": (["steamapps/common/G/intro.webm", "SteamLibrary/x/y.mp4",
                                  "Emulation/tools/downloaded_media/x/videos/v.mp4",
                                  "roms/psx/clip.mp4", ".hidden/a.mkv", "Films/A/a.mkv"],
                                 {"Films"}),
}


class SuggestionRuleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def suggested(self, root):
        result = ff.search([ff.Place("sd", "SD card", root)])
        return {os.path.relpath(s.path, root) for s in result.suggestions}

    def test_the_reports_layouts(self):
        for name, (files, expected) in LAYOUTS.items():
            with self.subTest(name):
                root = os.path.join(self.tmp.name, name)
                make(root, files)
                self.assertEqual(self.suggested(root), expected)

    def test_clips_only_is_not_suggested(self):
        root = os.path.join(self.tmp.name, "clips")
        make(root, ["Previews/p.mp4", "Previews/q.mkv", "Trailers/t/t.mp4"], size=1000)
        self.assertEqual(self.suggested(root), set())

    def test_a_folder_with_one_big_video_among_clips_is_suggested(self):
        root = os.path.join(self.tmp.name, "mixed")
        make(root, ["Films/A/trailer.mp4", "Films/B/trailer.mp4"], size=1000)
        make(root, ["Films/A/a.mkv"])
        self.assertEqual(self.suggested(root), {"Films"})

    def test_deeper_than_six_levels_is_not_read(self):
        root = os.path.join(self.tmp.name, "deep")
        make(root, ["1/2/3/4/5/6/seven.mkv"])
        make(root, ["a/2/3/4/5/6/7/eight.mkv"])
        # Six levels down is read (the chain stops above the film's own
        # folder); seven levels down is not, so "a" holds nothing.
        self.assertEqual(self.suggested(root), {"1/2/3/4/5"})

    def test_skip_names_ignore_capitals(self):
        root = os.path.join(self.tmp.name, "caps")
        make(root, ["STEAMAPPS/a/a.mkv", "RetroArch/b/b.mkv", "Lost+Found/c.mkv", "Films/D/d.mkv"])
        self.assertEqual(self.suggested(root), {"Films"})


class PlacesTest(unittest.TestCase):
    MOUNTINFO = "\n".join([
        "22 1 259:2 / / rw,relatime shared:1 - ext4 /dev/nvme0n1p8 rw",
        "30 22 259:3 / /home rw,relatime shared:2 - ext4 /dev/nvme0n1p9 rw",
        "31 22 0:5 / /proc rw shared:3 - proc proc rw",
        "90 22 179:2 / /run/media/someone/Second\\040Card rw shared:9 - exfat /dev/mmcblk0p2 rw",
        "91 22 179:1 / /run/media/someone/CardOne rw shared:10 - ext4 /dev/mmcblk0p1 rw",
        "92 22 8:1 / /media/someone/Stick rw shared:11 - vfat /dev/sda1 rw",
        "93 22 0:40 / /mnt/inside rw shared:12 - btrfs /dev/sdb3 rw",
        "garbage line",
    ])
    KINDS = {"179:1": "sd", "179:2": "sd", "8:1": "usb", "0:40": "internal"}

    def test_home_then_each_real_mount_with_its_display_name(self):
        places = ff.list_places("/home/someone", self.MOUNTINFO, lambda n, s: self.KINDS[n])
        self.assertEqual([(p.kind, p.name, p.root) for p in places], [
            ("internal", "Internal storage", "/home/someone"),
            ("usb", "USB drive", "/media/someone/Stick"),
            ("internal", "Internal storage 2", "/mnt/inside"),
            ("sd", "SD card", "/run/media/someone/CardOne"),
            ("sd", "SD card 2", "/run/media/someone/Second Card"),
        ])

    def test_a_leftover_folder_is_not_a_place(self):
        # The Nova leaves an empty folder where a pulled card was: it is not
        # in the list of mounts, so it is not offered.
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "run", "media", "someone", "CardOne"))
            places = ff.list_places(tmp, self.MOUNTINFO.splitlines()[0], lambda n, s: "sd")
        self.assertEqual([p.kind for p in places], ["internal"])

    def test_the_system_list_is_read_when_not_given(self):
        places = ff.list_places()
        self.assertEqual(places[0].name, "Internal storage")
        self.assertTrue(all(p.root.startswith(ff.REMOVABLE_ROOTS) for p in places[1:]))

    def test_kind_of_drive_from_the_hardware_tree(self):
        with tempfile.TemporaryDirectory() as sys_root:
            def device(link_dir, name, target, card_type=None):
                real = os.path.join(sys_root, "devices", target)
                os.makedirs(real)
                if card_type:
                    disk = os.path.dirname(real)
                    os.makedirs(os.path.join(disk, "device"))
                    with open(os.path.join(disk, "device", "type"), "w") as f:
                        f.write(card_type + "\n")
                os.makedirs(os.path.join(sys_root, link_dir), exist_ok=True)
                os.symlink(real, os.path.join(sys_root, link_dir, name))

            device("dev/block", "179:1", "pci0/mmc_host/mmc0/mmc0:1/block/mmcblk0/mmcblk0p1", "SD")
            device("dev/block", "179:9", "pci0/mmc_host/mmc1/mmc1:1/block/mmcblk1/mmcblk1p1", "MMC")
            device("dev/block", "8:1", "pci0/usb2/2-1/host0/block/sda/sda1")
            device("dev/block", "259:2", "pci0/nvme/nvme0/nvme0n1/nvme0n1p8")
            device("class/block", "sdc20", "soc@0/1d84000.ufshc/host0/block/sdc/sdc20")
            device("dev/block", "7:0", "virtual/block/loop0")
            self.assertEqual(ff.hardware("179:1", "/dev/mmcblk0p1", sys_root), "sd")
            self.assertEqual(ff.hardware("179:9", "/dev/mmcblk1p1", sys_root), "internal")
            self.assertEqual(ff.hardware("8:1", "/dev/sda1", sys_root), "usb")
            self.assertEqual(ff.hardware("259:2", "/dev/nvme0n1p8", sys_root), "internal")
            # btrfs: a placeholder number, so the named device is looked up.
            self.assertEqual(ff.hardware("0:44", "/dev/sdc20", sys_root), "internal")
            self.assertEqual(ff.hardware("7:0", "/dev/loop0", sys_root), "other")


class GroupingAndStatesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = os.path.join(self.tmp.name, "home")
        self.card = os.path.join(self.tmp.name, "card")
        self.stick = os.path.join(self.tmp.name, "stick")
        make(self.home, ["Videos/Holiday/h.mkv", "Videos/Party/p.mkv"])
        make(self.card, ["Films/A/a.mkv", "Films/B/b.mkv", "Shows/C/Season 1/e1.mkv"])
        make(self.stick, ["loose.mkv"])

    def places(self):
        return [ff.Place("internal", "Internal storage", self.home),
                ff.Place("sd", "SD card", self.card),
                ff.Place("usb", "USB drive", self.stick)]

    def test_folders_are_grouped_by_place_in_place_order(self):
        answer = ff.search(self.places()).answer()
        self.assertEqual([g["name"] for g in answer["places"]], ["Internal storage", "SD card", "USB drive"])
        self.assertEqual([f["name"] for f in answer["places"][0]["folders"]], ["Videos"])
        self.assertEqual([f["name"] for f in answer["places"][1]["folders"]], ["Films", "Shows"])
        stick = answer["places"][2]["folders"]
        self.assertEqual(len(stick), 1)
        self.assertTrue(stick[0]["whole_place"])
        self.assertEqual(stick[0]["name"], "")
        for group in answer["places"]:
            self.assertEqual(group["state"], "ok")
            for folder in group["folders"]:
                self.assertEqual(folder["place"], group["name"])

    def test_a_card_that_cant_be_read_is_not_ready(self):
        os.chmod(self.card, 0)
        self.addCleanup(os.chmod, self.card, 0o755)
        if os.access(self.card, os.R_OK):
            self.skipTest("running with rights that read anything")
        answer = ff.search(self.places()).answer()
        card = answer["places"][1]
        self.assertEqual((card["state"], card["folders"]), ("not_ready", []))
        self.assertIn("SD card (not ready yet)", answer["checked"])

    def test_internal_storage_that_cant_be_read(self):
        os.chmod(self.home, 0)
        self.addCleanup(os.chmod, self.home, 0o755)
        if os.access(self.home, os.R_OK):
            self.skipTest("running with rights that read anything")
        self.assertEqual(ff.search(self.places()).answer()["places"][0]["state"], "unreadable")

    def test_a_card_pulled_before_the_search_is_not_ready_and_nothing_fails(self):
        places = self.places()
        places[1].root = os.path.join(self.tmp.name, "gone")
        answer = ff.search(places).answer()
        self.assertEqual(answer["places"][1]["state"], "not_ready")
        self.assertEqual(len(answer["places"][0]["folders"]), 1)

    def test_the_time_limit_stops_the_search(self):
        answer = ff.search(self.places(), time_limit=-1).answer()
        self.assertEqual({g["state"] for g in answer["places"]}, {"partial"})
        self.assertIn("only partly searched", answer["checked"])

    def test_ids_are_stable_distinct_and_resolve_to_the_folder(self):
        first, again = ff.search(self.places()), ff.search(self.places())
        ids = [s.id for s in first.suggestions]
        self.assertEqual(len(set(ids)), len(ids))
        self.assertEqual(ids, [s.id for s in again.suggestions])
        self.assertEqual(first.suggestions[1].path, os.path.join(self.card, "Films"))

    def gap(self, *places):
        return ff.gaps_text([ff.Place(kind, name, "/invented", state) for kind, name, state in places])

    def test_the_line_above_the_list_says_nothing_when_all_is_well(self):
        # The first onboarding review fixes. No card at all, or a card read in full, is no gap to report.
        self.assertEqual(self.gap(("internal", "Internal storage", ff.OK)), "")
        self.assertEqual(self.gap(("internal", "Internal storage", ff.OK), ("sd", "SD card", ff.OK)), "")

    def test_the_line_for_a_card_that_isnt_ready_never_calls_it_missing(self):
        text = self.gap(("internal", "Internal storage", ff.OK), ("sd", "SD card", ff.NOT_READY))
        self.assertEqual(text, "Kettle found the SD card isn't ready yet, so its folders aren't listed. Press Y to look again.")
        self.assertNotIn("no SD card", text)

    def test_the_line_for_several_cards_that_arent_ready(self):
        text = self.gap(("sd", "SD card", ff.NOT_READY), ("usb", "USB drive", ff.NOT_READY))
        self.assertEqual(text, "Kettle found the SD card and the USB drive aren't ready yet, so their folders "
                               "aren't listed. Press Y to look again.")

    def test_the_line_for_a_search_out_of_time(self):
        self.assertEqual(self.gap(("sd", "SD card", ff.PARTIAL)),
                         "Kettle ran out of time looking through the SD card, so it may have missed some. "
                         "Press Y to look again.")

    def test_the_line_for_storage_that_cant_be_read(self):
        self.assertEqual(self.gap(("internal", "Internal storage", ff.UNREADABLE)),
                         "Kettle couldn't read internal storage. Press Y to look again.")

    def test_the_answer_carries_the_line(self):
        places = self.places()
        places[1].root = os.path.join(self.tmp.name, "gone")
        answer = ff.search(places).answer()
        self.assertIn("isn't ready yet", answer["gaps"])
        self.assertEqual(ff.search(self.places()).answer()["gaps"], "")


class CountsAndExamplesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def folders(self, files):
        make(self.tmp.name, files)
        answer = ff.search([ff.Place("sd", "SD card", self.tmp.name)]).answer()
        return {f["name"] or ".": f for f in answer["places"][0]["folders"]}

    def test_count_text(self):
        self.assertEqual(ff.count_text(62, 1), "62 videos")
        self.assertEqual(ff.count_text(1, 1), "1 video")
        self.assertEqual(ff.count_text(31, 4), "31 videos in 4 folders")

    def test_counts_and_example_names_of_a_collection(self):
        films = self.folders(["Films/Zeta/z.mkv", "Films/Alpha/a1.mkv", "Films/Alpha/a2.mkv",
                              "Films/beta.mkv", "Films/Mu/Extras/x.mkv"])["Films"]
        self.assertEqual((films["videos"], films["folders"]), (5, 4))
        self.assertEqual(films["count_text"], "5 videos in 4 folders")
        self.assertEqual(films["examples"], ["Alpha", "beta"])
        self.assertEqual(films["trail"], ["Films"])

    def test_loose_videos_only(self):
        clips = self.folders(["Movies/one.mkv", "Movies/two.mp4", "Movies/three.avi"])["Movies"]
        self.assertEqual(clips["count_text"], "3 videos")
        self.assertEqual(clips["examples"], ["one", "three"])

    def test_a_shows_own_folder_gives_episode_names(self):
        show = self.folders(["Show/Season 2/later.mkv", "Show/Season 1/pilot.mkv", "Show/Season 1/next.mkv"])["Show"]
        self.assertEqual(show["examples"], ["next", "pilot"])
        self.assertEqual(show["count_text"], "3 videos in 2 folders")

    def test_the_whole_place_shows_its_own_videos_only(self):
        found = self.folders(["top.mkv", "Films/A/a.mkv", "Films/B/b.mkv"])
        self.assertEqual(found["."]["examples"], ["top"])
        self.assertEqual(found["."]["trail"], [])
        self.assertEqual(found["Films"]["examples"], ["A", "B"])

    def test_nested_trail(self):
        found = self.folders(["Media/Films/A/a.mkv", "Media/Films/B/b.mkv",
                              "Media/TV/C/e.mkv", "Media/TV/D/e.mkv"])
        self.assertEqual(found["Films"]["trail"], ["Media", "Films"])


class CheckedTextTest(unittest.TestCase):
    def places(self, *kinds):
        return [ff.Place(kind, name, "/x", state) for kind, name, state in kinds]

    def test_wording(self):
        cases = [
            ([("internal", "Internal storage", "ok")], "Internal storage, and no SD card found"),
            ([("internal", "Internal storage", "ok"), ("sd", "SD card", "ok")], "Internal storage and SD card"),
            ([("internal", "Internal storage", "ok"), ("sd", "SD card", "ok"), ("usb", "USB drive", "ok")],
             "Internal storage, SD card and USB drive"),
            ([("internal", "Internal storage", "ok"), ("sd", "SD card", "not_ready")],
             "Internal storage and SD card (not ready yet)"),
            ([("internal", "Internal storage", "unreadable"), ("usb", "USB drive", "ok")],
             "Internal storage (couldn't be read) and USB drive, and no SD card found"),
        ]
        for kinds, text in cases:
            with self.subTest(text):
                self.assertEqual(ff.checked_text(self.places(*kinds)), text)

    def test_sd_card_found_in_the_answer(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(ff.search([ff.Place("internal", "Internal storage", tmp)]).answer()["sd_card_found"])
            self.assertTrue(ff.search([ff.Place("internal", "Internal storage", tmp),
                                       ff.Place("sd", "SD card", tmp)]).answer()["sd_card_found"])


class LookedTextTest(unittest.TestCase):
    """The "No videos found yet" screen's sentence (the No videos found screen): it names only
    the places really checked, and never says "no SD card" when one was found."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = os.path.join(self.tmp.name, "home")
        self.card = os.path.join(self.tmp.name, "card")
        os.makedirs(self.home)
        os.makedirs(self.card)
        self.internal = ff.Place("internal", "Internal storage", self.home)
        self.sd = ff.Place("sd", "SD card", self.card)

    def looked(self, *places):
        return ff.search(list(places)).answer()["looked"]

    def test_internal_storage_only(self):
        self.assertEqual(self.looked(self.internal), "Kettle looked in internal storage and found no SD card.")

    def test_a_card_found_but_empty(self):
        self.assertEqual(self.looked(self.internal, self.sd), "Kettle looked in internal storage and on the SD card.")

    def test_a_card_holding_only_short_clips_counts_as_looked_at(self):
        make(self.card, ["Clips/one.mp4"], size=1000)
        self.assertEqual(self.looked(self.internal, self.sd), "Kettle looked in internal storage and on the SD card.")

    def test_a_card_not_ready_is_not_called_missing_or_empty(self):
        self.sd.root = os.path.join(self.tmp.name, "not-there-yet")
        text = self.looked(self.internal, self.sd)
        self.assertEqual(text, "Kettle looked in internal storage and found the SD card isn't ready yet.")
        self.assertNotIn("no SD card", text)
        self.assertNotIn("on the SD card", text)

    def test_a_card_that_cant_be_read_is_not_ready(self):
        os.chmod(self.card, 0)
        self.addCleanup(os.chmod, self.card, 0o755)
        if os.access(self.card, os.R_OK):
            self.skipTest("running with rights that read anything")
        self.assertEqual(self.looked(self.internal, self.sd),
                         "Kettle looked in internal storage and found the SD card isn't ready yet.")

    def test_the_other_cases_stay_true(self):
        def places(*kinds):
            return [ff.Place(kind, name, "/x", state) for kind, name, state in kinds]

        internal = ("internal", "Internal storage", "ok")
        cases = [
            ([internal, ("usb", "USB drive", "ok")],
             "Kettle looked in internal storage and on the USB drive, and found no SD card."),
            ([internal, ("sd", "SD card", "ok"), ("sd", "SD card 2", "ok")],
             "Kettle looked in internal storage, on the SD card and on SD card 2."),
            ([internal, ("sd", "SD card", "not_ready"), ("usb", "USB drive", "not_ready")],
             "Kettle looked in internal storage and found the SD card and the USB drive aren't ready yet."),
            ([internal, ("usb", "USB drive", "not_ready")],
             "Kettle looked in internal storage and found no SD card. Kettle found the USB drive isn't ready yet."),
            ([("internal", "Internal storage", "unreadable"), ("sd", "SD card", "not_ready")],
             "Kettle couldn't read internal storage. Kettle found the SD card isn't ready yet."),
            ([("internal", "Internal storage", "unreadable")], "Kettle found no SD card. Kettle couldn't read internal storage."),
            ([("internal", "Internal storage", "unreadable"), ("sd", "SD card", "ok")],
             "Kettle looked on the SD card. Kettle couldn't read internal storage."),
            ([("internal", "Internal storage", "partial"), ("sd", "SD card", "ok")],
             "Kettle looked on the SD card. Kettle ran out of time looking through internal storage, so it may have missed some."),
            ([internal, ("other", "Other drive", "ok"), ("sd", "SD card", "ok")],
             "Kettle looked in internal storage, on the other drive and on the SD card."),
        ]
        for kinds, text in cases:
            with self.subTest(text):
                self.assertEqual(ff.looked_text(places(*kinds)), text)
                # The screen's next sentence starts "It plays...": the one
                # before it must be about Kettle, never about a card.
                self.assertTrue(text.rsplit(". ", 1)[-1].startswith("Kettle"), text)

    def test_no_path_in_the_sentence(self):
        self.sd.root = os.path.join(self.tmp.name, "CardLabel")
        self.assertNotIn(self.tmp.name, self.looked(self.internal, self.sd))
        self.assertNotIn("CardLabel", self.looked(self.internal, self.sd))


class PrivacyAndReadOnlyTest(unittest.TestCase):
    NAMES = ("Holiday", "Alpha", "Films", "secret-episode")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = os.path.join(self.tmp.name, "home-of-someone")
        self.card = os.path.join(self.tmp.name, "CardLabel")
        make(self.home, ["Videos/Holiday/h.mkv", "Videos/Party/p.mkv"])
        make(self.card, ["Films/Alpha/a.mkv", "Films/Beta/b.mkv", "Shows/C/Season 1/secret-episode.mkv",
                         "top.mkv", ".hidden/x.mkv", "steamapps/g/intro.webm"])
        self.places = [ff.Place("internal", "Internal storage", self.home), ff.Place("sd", "SD card", self.card)]

    def test_no_full_path_in_the_answer(self):
        text = json.dumps(ff.search(self.places).answer())
        for private in (self.tmp.name, self.home, self.card, "CardLabel", "home-of-someone", os.sep + "Films"):
            self.assertNotIn(private, text)

    def test_the_log_line_has_no_path_or_name(self):
        line = ff.search(self.places).log_line()
        for private in (self.tmp.name, "CardLabel", "home-of-someone") + self.NAMES:
            self.assertNotIn(private, line)
        self.assertIn("found 4 folders", line)

    def test_the_folders_are_unchanged_after_a_search(self):
        before = snapshot(self.tmp.name)
        ff.search(self.places)
        self.assertEqual(snapshot(self.tmp.name), before)


class EndpointTest(unittest.TestCase):
    """GET /api/onboarding/folders, with the places pointed at invented folders."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.card = root / "CardLabel"
        make(str(self.card), ["Films/Alpha/a.mkv", "Films/Beta/b.mkv"])
        (root / "logs").mkdir()
        places = lambda: [ff.Place("internal", "Internal storage", str(root / "home-of-someone")),
                          ff.Place("sd", "SD card", str(self.card))]
        patch = mock.patch.object(ff, "list_places", places)
        patch.start()
        self.addCleanup(patch.stop)
        self.logged = []
        patch = mock.patch.object(server, "_log", self.logged.append)
        patch.start()
        self.addCleanup(patch.stop)
        settings = {"movies_path": str(root / "m"), "tv_path": str(root / "t"), "mpv_command": "auto",
                    "mpv_args": [], "resume": False, "keep_awake": False, "data_dir": str(root / "data")}
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        self.port = self.httpd.server_address[1]
        with contextlib.redirect_stdout(io.StringIO()):
            base = server.make_handler(UI_DIR, root / "logs", settings, {}, self.port)

        class Quiet(base):
            def log_message(self, format, *args):
                pass

        self.httpd.RequestHandlerClass = Quiet
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def test_the_answer_lists_folders_by_id_without_paths(self):
        before = snapshot(str(self.card))
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("GET", "/api/onboarding/folders")
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8")
        conn.close()
        self.assertEqual(resp.status, 200)
        answer = json.loads(raw)
        self.assertEqual([g["name"] for g in answer["places"]], ["Internal storage", "SD card"])
        films = answer["places"][1]["folders"][0]
        self.assertEqual((films["name"], films["count_text"], films["examples"]), ("Films", "2 videos in 2 folders", ["Alpha", "Beta"]))
        self.assertRegex(films["id"], r"^[0-9a-f]{16}$")
        self.assertEqual(answer["checked"], "Internal storage (couldn't be read) and SD card")
        for private in (self.tmp.name, "CardLabel", "home-of-someone"):
            self.assertNotIn(private, raw)
        log = "\n".join(self.logged)
        self.assertIn("onboarding: looked for folders in 2 places", log)
        for private in (self.tmp.name, "CardLabel", "Films", "Alpha", "Beta"):
            self.assertNotIn(private, log)
        self.assertEqual(snapshot(str(self.card)), before)


if __name__ == "__main__":
    unittest.main()
