# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Storage spike (the storage spike): the proposed rules behave as the report says.

Question 1 (SD card, USB drive or internal storage, and the names shown)
is checked against a faked /sys and mount list. Question 2 (folders never
walked into) and Question 3 (which folder to suggest) are checked on
invented folder layouts in a temporary folder, never on a real card. Also
checks that the scripts' output hides user names and card labels, that the
privacy check catches real names, that the before/after fingerprint notices
a change, and that the report answers every question for both devices.

The script tests are skipped when the spike folder has been deleted.

Run from the repo root:  python3 -m unittest tests.test_storage_spike -v
"""

import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SPIKE = ROOT / "spikes" / "storage"


@unittest.skipUnless(SPIKE.is_dir(), "storage spike folder removed")
class StorageSpikeRules(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(SPIKE))
        import common
        import find_video_folders
        import snapshot
        cls.common, cls.finder, cls.snapshot = common, find_video_folders, snapshot

    @classmethod
    def tearDownClass(cls):
        sys.path.remove(str(SPIKE))

    def make(self, root, files, size=None):
        size = self.finder.MIN_VIDEO_BYTES if size is None else size
        for rel in files:
            path = os.path.join(root, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.truncate(size)        # sparse: no real disk used

    def suggested(self, files, size=None):
        with tempfile.TemporaryDirectory() as tmp:
            self.make(tmp, files, size)
            return {os.path.relpath(f.path, tmp)
                    for f in self.finder.suggest(self.finder.walk(tmp))}

    def test_selftest_layouts_all_pass(self):
        result = subprocess.run(
            [sys.executable, "find_video_folders.py", "--selftest"],
            cwd=SPIKE, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("FAIL", result.stdout)

    def test_suggests_collection_not_each_film(self):
        self.assertEqual(self.suggested(["Films/A (2001)/a.mkv", "Films/B/b.mp4"]),
                         {"Films"})

    def test_loose_videos_at_top_suggest_the_place_itself(self):
        self.assertEqual(self.suggested(["a.mkv", "b.mkv"]), {"."})

    def test_steam_hidden_and_junk_are_skipped(self):
        for name in (".hidden", "steamapps", "SteamLibrary", "Emulation",
                     "lost+found", "Sample", "compatdata"):
            with self.subTest(name=name):
                self.assertTrue(self.finder.skipped(name))
        self.assertFalse(self.finder.skipped("Films"))
        self.assertEqual(self.suggested(["steamapps/common/G/intro.webm",
                                         ".var/app/x/v.mkv",
                                         "Films/Sample/s.mkv"]), set())

    def test_mac_dot_underscore_files_are_not_videos(self):
        self.assertFalse(self.common.is_video("._film.mkv"))
        self.assertTrue(self.common.is_video("film.MKV"))

    def test_small_clips_only_are_not_suggested(self):
        self.assertEqual(self.suggested(["Previews/p1.mp4", "Previews/p2.mp4"],
                                        size=1000), set())

    def test_depth_limit_stops_the_walk(self):
        deep = "/".join(f"d{i}" for i in range(self.finder.MAX_DEPTH + 1))
        self.assertEqual(self.suggested([f"{deep}/x/a.mkv"]), set())

    def test_redactor_hides_user_and_card_label(self):
        red = self.common.Redactor()
        user = os.path.basename(os.path.expanduser("~"))
        shown = red.path(f"/run/media/{user}/MYCARD/Films", ["MYCARD"])
        self.assertEqual(shown, "/run/media/<user>/<card-1>/Films")
        self.assertEqual(red.name("folder", "Real Title"), "folder-1")
        self.assertEqual(red.name("folder", "Real Title"), "folder-1")
        self.assertEqual(red.name("folder", "Other"), "folder-2")

    def test_btrfs_placeholder_number_looks_up_named_device(self):
        import drives
        self.assertEqual(drives.sys_device("0:35", "/dev/sda20"),
                         "/sys/class/block/sda20")
        self.assertEqual(drives.sys_device("179:1", "/dev/mmcblk0p1"),
                         "/sys/dev/block/179:1")
        self.assertEqual(drives.sys_device("0:39", "overlay"),
                         "/sys/dev/block/0:39")

    def test_privacy_allow_option_reads_files_and_words(self):
        import privacy_check
        self.assertEqual(privacy_check.split_args(["a.md", "--allow", "Nova", "b.py"]),
                         (["a.md", "b.py"], {"Nova"}))

    def test_fingerprint_notices_a_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.make(tmp, ["Films/A/a.mkv"], size=10)
            before = self.snapshot.fingerprint(tmp)
            self.assertEqual(before, self.snapshot.fingerprint(tmp))
            self.make(tmp, ["Films/A/a.mkv"], size=11)
            self.assertNotEqual(before[0], self.snapshot.fingerprint(tmp)[0])

    def test_fingerprint_notices_rename_and_new_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.make(tmp, ["Films/A/a.mkv"], size=10)
            stamp = os.stat(os.path.join(tmp, "Films/A")).st_mtime_ns
            before = self.snapshot.fingerprint(tmp)
            os.rename(os.path.join(tmp, "Films/A/a.mkv"), os.path.join(tmp, "Films/A/b.mkv"))
            os.utime(os.path.join(tmp, "Films/A"), ns=(stamp, stamp))
            self.assertNotEqual(before[0], self.snapshot.fingerprint(tmp)[0])
            self.make(tmp, ["Films/A/c.mkv"], size=10)
            self.assertEqual(self.snapshot.fingerprint(tmp)[1], 2)

    def test_search_of_a_pulled_card_ends_with_nothing(self):
        # Card out: the folder is gone. The search must end, not raise.
        self.finder.walk.unreadable = 0
        with tempfile.TemporaryDirectory() as tmp:
            gone = os.path.join(tmp, "card")
        node = self.finder.walk(gone)
        self.assertEqual(node.total, 0)
        self.assertEqual(self.finder.suggest(node), [])
        self.assertEqual(self.finder.walk.unreadable, 1)


SYS = "/sys/devices/platform"


@unittest.skipUnless(SPIKE.is_dir(), "storage spike folder removed")
class StorageSpikeDrives(unittest.TestCase):
    """Question 1: telling an SD card, a USB drive and internal storage apart,
    and the names shown for them. /sys and the mount list are faked."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(SPIKE))
        import drives
        cls.drives = drives

    @classmethod
    def tearDownClass(cls):
        sys.path.remove(str(SPIKE))

    def kind(self, sys_path, mmc_type=""):
        def fake_read(path):
            return mmc_type if path.endswith("/device/type") else ""

        def fake_exists(path):
            # Only the whole disk has a "device" link, not a partition.
            return not os.path.basename(os.path.dirname(path)).endswith(("p1", "p2"))

        with mock.patch("os.path.realpath", return_value=sys_path), \
                mock.patch("os.path.exists", side_effect=fake_exists), \
                mock.patch.object(self.drives, "_read", side_effect=fake_read):
            return self.drives.hardware("179:1", "/dev/x")

    def test_sd_card_on_mmc_host(self):
        self.assertEqual(self.kind(f"{SYS}/mmc_host/mmc0/mmc0:1/block/mmcblk0/mmcblk0p1",
                                   "SD"), "sd")

    def test_built_in_emmc_is_internal(self):
        self.assertEqual(self.kind(f"{SYS}/mmc_host/mmc1/mmc1:1/block/mmcblk1/mmcblk1p2",
                                   "MMC"), "internal")

    def test_usb_drive(self):
        self.assertEqual(self.kind("/sys/devices/pci0000:00/usb3/3-1/host0/block/sda/sda1"),
                         "usb")

    def test_nvme_sata_and_ufs_are_internal(self):
        for path in ("/sys/devices/pci0000:00/nvme/nvme0/nvme0n1/nvme0n1p8",
                     "/sys/devices/pci0000:00/ata1/host0/block/sda/sda1",
                     "/sys/devices/platform/soc@0/1d84000.ufshc/host0/block/sda/sda20"):
            with self.subTest(path=path):
                self.assertEqual(self.kind(path), "internal")

    def test_unknown_hardware_is_other(self):
        self.assertEqual(self.kind("/sys/devices/virtual/block/loop0"), "other")

    def test_places_names_and_skips_system_mounts(self):
        fake = [("/", "0:1", "/dev/root", "ext4"),
                ("/boot", "0:2", "/dev/boot", "vfat"),
                ("/run/media/u/CARD", "179:1", "/dev/mmcblk0p1", "ext4"),
                ("/run/media/u/STICK", "8:1", "/dev/sda1", "vfat"),
                ("/media/u/STICK2", "8:17", "/dev/sdb1", "exfat")]
        kinds = {"179:1": "sd", "8:1": "usb", "8:17": "usb"}
        with mock.patch.object(self.drives, "mounts", return_value=fake), \
                mock.patch.object(self.drives, "hardware",
                                  side_effect=lambda n, s="": kinds[n]):
            found = self.drives.places()
        self.assertEqual([(p["kind"], p["name"]) for p in found],
                         [("internal", "Internal storage"), ("sd", "SD card"),
                          ("usb", "USB drive"), ("usb", "USB drive 2")])
        self.assertEqual(found[0]["path"], os.path.expanduser("~"))
        self.assertEqual(found[1]["label"], "CARD")

    def test_mount_list_reads_paths_with_spaces(self):
        line = ("36 25 179:1 / /run/media/u/My\\040Card rw,nosuid shared:1 - "
                "ext4 /dev/mmcblk0p1 rw\n")
        with mock.patch("builtins.open", mock.mock_open(read_data=line)):
            self.assertEqual(self.drives.mounts(),
                             [("/run/media/u/My Card", "179:1", "/dev/mmcblk0p1", "ext4")])


@unittest.skipUnless(SPIKE.is_dir(), "storage spike folder removed")
class StorageSpikePrivacyCheck(unittest.TestCase):
    """The privacy check finds real names, never prints them, and honours
    --allow only outside paths. Uses an invented card in a temporary folder."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(SPIKE))
        import privacy_check
        cls.privacy = privacy_check

    @classmethod
    def tearDownClass(cls):
        sys.path.remove(str(SPIKE))

    def test_private_words_come_from_card_label_and_titles(self):
        with tempfile.TemporaryDirectory() as tmp:
            card = os.path.join(tmp, "ZEPHYRCARD")
            for rel in ("Films/Quillmoor (1999)/Quillmoor.mkv",
                        "Films/Brackenfold/Brackenfold.mp4",
                        "Films/Brackenfold/Sample/s.mkv",
                        "TV/Ostrava Nights/Season 1/e01.mkv"):
                path = os.path.join(card, rel)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as f:
                    f.truncate(20_000_000)
            places = [{"kind": "internal", "path": tmp, "label": None},
                      {"kind": "sd", "path": card, "label": "ZEPHYRCARD"}]
            with mock.patch.object(self.privacy.drives, "places", return_value=places):
                words = self.privacy.private_words()
        for word in ("ZEPHYRCARD", "Quillmoor (1999)", "Quillmoor", "Brackenfold",
                     "Ostrava Nights"):
            self.assertIn(word, words)
        for word in ("Season 1", "Sample", "e01"):
            self.assertNotIn(word, words)

    def run_check(self, text, *extra):
        with tempfile.TemporaryDirectory() as tmp:
            report = os.path.join(tmp, "report.md")
            with open(report, "w", encoding="utf-8") as f:
                f.write(text)
            out = io.StringIO()
            words = {"Quillmoor", "ZEPHYRCARD", "/home/someone"}
            with mock.patch.object(self.privacy, "private_words", return_value=words), \
                    mock.patch.object(sys, "argv", ["privacy_check.py", report, *extra]), \
                    redirect_stdout(out), self.assertRaises(SystemExit) as done:
                self.privacy.main()
        return done.exception.code, out.getvalue()

    def test_clean_report_passes(self):
        code, _ = self.run_check("A film at /run/media/<user>/<card-1>/Films\n")
        self.assertEqual(code, 0)

    def test_real_title_fails_without_printing_it(self):
        code, out = self.run_check("line one\nWe played quillmoor from the card\n")
        self.assertEqual(code, 1)
        self.assertIn("line 2", out)
        self.assertNotIn("uillmoor", out.casefold())

    def test_allowed_word_only_counts_inside_a_path(self):
        self.assertEqual(self.run_check("The ZEPHYRCARD handheld\n",
                                        "--allow", "ZEPHYRCARD")[0], 0)
        self.assertEqual(self.run_check("/run/media/x/ZEPHYRCARD/Films\n",
                                        "--allow", "ZEPHYRCARD")[0], 1)


class StorageSpikeReport(unittest.TestCase):
    """The report answers every question for both devices, with the tables
    and three timed runs, and holds no real user name. The decision log
    links to it."""

    REPORT = ROOT / "docs" / "spikes" / "storage.md"

    @classmethod
    def setUpClass(cls):
        cls.text = cls.REPORT.read_text(encoding="utf-8")

    def section(self, heading):
        start = self.text.index(heading)
        rest = self.text[start + len(heading):]
        level = heading.split(" ")[0]
        ends = [rest.find(f"\n{h} ") for h in ("#" * n for n in range(1, len(level) + 1))]
        ends = [e for e in ends if e >= 0]
        return rest[:min(ends)] if ends else rest

    def test_both_devices_have_a_place_table(self):
        header = "| Place | How it is found | Display name | App can read | mpv can play |"
        for heading in ("## Steam Deck table", "### Nova table"):
            with self.subTest(heading=heading):
                table = self.section(heading)
                self.assertIn(header, table)
                self.assertIn("SD card", table)
                self.assertIn("Internal storage", table)

    def test_three_timed_runs_per_device(self):
        for heading in ("### Timings (Steam Deck", "### Timings (Nova"):
            with self.subTest(heading=heading):
                table = self.section(heading)
                self.assertIn("| Run 1 | Run 2 | Run 3 |", table)
                rows = [line for line in table.splitlines()
                        if line.startswith("| SD card") or line.startswith("| Home folder")]
                self.assertGreaterEqual(len(rows), 2)
                for row in rows:
                    self.assertEqual(row.count(" s |"), 3, row)

    def test_every_question_answered_for_each_device(self):
        for heading in ("## Question 1", "## Question 2", "## Question 3",
                        "## Question 4", "### Question 1 (Nova)",
                        "### Question 2 and 3 (Nova)", "### Question 4 (Nova)",
                        "## Differences between the devices",
                        "## What would stop onboarding",
                        "## Read-only check", "### Read-only check (Nova)"):
            with self.subTest(heading=heading):
                self.assertTrue(self.section(heading).strip())

    def test_card_out_and_in_recorded_for_each_device(self):
        self.assertIn("Card out / back in", self.section("## Question 1"))
        self.assertIn("Card out / back in", self.section("### Question 1 (Nova)"))

    def test_flatpak_permissions_shown(self):
        q4 = self.section("## Question 4")
        self.assertIn("[Context]", q4)
        self.assertIn("filesystems=", q4)
        self.assertIn("permissions", self.section("### Question 4 (Nova)"))

    def test_no_real_user_name_in_report(self):
        user = os.path.basename(os.path.expanduser("~"))
        for prefix in ("/home/", "/var/home/", "/run/media/", "/media/"):
            with self.subTest(prefix=prefix):
                self.assertNotIn(prefix + user, self.text)

    def test_decision_log_links_the_report(self):
        log = (ROOT / "docs" / "decisions.md").read_text(encoding="utf-8")
        self.assertGreaterEqual(log.count("docs/spikes/storage.md"), 2)
        self.assertIn("the storage spike", log)


if __name__ == "__main__":
    unittest.main()
