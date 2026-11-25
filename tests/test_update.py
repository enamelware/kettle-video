# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Updating by running the installer again, with rollback (the installer's update step).

The shared update step is installer/update.py; installer/install.sh runs
it for a first install and an update, and the app's "Update and restart"
(the Update and restart work) will call it too. Like tests/test_installer.py, the installer tests
run the real script in a temporary home folder with stand-in tools, on
invented archives whose server is a small stand-in (so a first start can
be checked without the real app). Checked:

- install, then update: settings, data and logs byte-for-byte unchanged;
  the old and new versions printed; the previous version removed only
  after the new one started cleanly; nothing written outside the home;
  sudo never called;
- an older archive warns and asks first; a no changes nothing, and a yes
  leaves the installer's later questions their own answers;
- a checksum mismatch stops the update with nothing changed;
- a failed install step, a failed switch or a failed first start rolls back
  to the previous version and says so;
- a power cut at any step leaves the app folder the old version or the new
  one, complete, never a mix, and the next run tidies up;
- an install made before the versions/ layout (the installer work) is updated too;
- "started cleanly" against the real app: its server starts, the page and
  every file it links answer, and, as it runs as a fresh start, a data
  folder holding what the app tidies at start-up stays byte-for-byte the
  same, after the check and after a rolled-back update.

Run: scripts/test.sh unit tests.test_update
"""

import errno
import fcntl
import importlib.util
import json
import os
import shutil
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend import library_index
from tests.test_installer import (BROKEN_SERVER, NAME, NAMES, PAGE, ROOT, SCRIPT, UPDATER,
                                  InstallerTestCase, make_archive, release, snapshot)

_spec = importlib.util.spec_from_file_location("kettle_video_update", UPDATER)
update = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = update
_spec.loader.exec_module(update)

APP_NAME = NAME["APP_NAME"]


class UpdateTestCase(InstallerTestCase):

    def put_things_in_place(self):
        """Invented settings, data and logs, as a person's would be after
        using the app, so the update can be seen not to touch them."""
        config, data = self.places["CONFIG_DIR"], self.places["DATA_DIR"]
        logs = self.places["LOGS_DIR"]
        (config / "settings.json").write_text(
            '{"movies_path": "/invented/Films", "tv_path": "/invented/Shows"}\n')
        (data / "library.json").write_text('{"movies": ["Quillmoor Abbey (2019).mkv"]}\n')
        (data / "thumbnails").mkdir()
        (data / "thumbnails" / "brindle.png").write_bytes(bytes(range(256)) * 4)
        (logs / "launch-20261101-101010.log").write_text("an invented log\n")

    def theirs(self):
        """Everything of the person's: settings, data and logs."""
        state = self.places["LOGS_DIR"].parent
        return {key: snapshot(folder) for key, folder in
                (("config", self.places["CONFIG_DIR"]), ("data", self.places["DATA_DIR"]),
                 ("state", state))}

    def versions(self):
        return sorted(p.name for p in (self.places["APP_DIR"].parent / "versions").iterdir())

    def version(self):
        return (self.places["APP_DIR"] / "VERSION").read_text().strip()


class Updates(UpdateTestCase):

    def setUp(self):
        super().setUp()
        self.install()
        self.put_things_in_place()
        self.before = self.theirs()
        self.newer = make_archive(self.downloads, "0.3.0")
        self.downloads_before = snapshot(self.downloads)
        self.result = self.run_install(str(self.newer))

    def test_updates_the_app_files(self):
        self.assertEqual(self.result.returncode, 0, self.result.stdout + self.result.stderr)
        self.assertEqual(self.version(), "0.3.0")
        self.assertIn("// invented app 0.3.0", (self.places["APP_DIR"] / "ui/js/app.js").read_text())
        self.assertTrue((self.places["APP_DIR"] / NAME["INSTALL_MARK"]).is_file())

    def test_settings_data_and_logs_are_byte_for_byte_the_same(self):
        self.assertEqual(self.theirs(), self.before)

    def test_prints_the_old_and_new_versions(self):
        out = self.result.stdout
        self.assertIn(f"Installed now: {APP_NAME} 0.2.0", out)
        self.assertIn(f"This archive:  {APP_NAME} 0.3.0", out)
        self.assertIn(f"Updated {APP_NAME} from 0.2.0 to 0.3.0.", out)
        self.assertIn("0.2.0 before, 0.3.0 now", out)
        self.assertIn(f"Done. {APP_NAME} 0.3.0 is installed.", out)

    def test_the_new_version_started_cleanly_before_the_old_one_went(self):
        self.assertIn(f"Checking that {APP_NAME} 0.3.0 starts cleanly", self.result.stdout)
        self.assertIn("It started cleanly.", self.result.stdout)
        self.assertEqual(len(self.versions()), 1)

    def test_the_menu_entry_still_opens_it(self):
        entry = self.home / ".local/share/applications" / NAME["DESKTOP_ENTRY"]
        self.assertIn(f'Exec="{self.places["APP_DIR"]}/launch.sh"', entry.read_text())
        self.assertTrue(os.access(self.places["APP_DIR"] / "launch.sh", os.X_OK))

    def test_nothing_is_written_outside_the_home_folder(self):
        self.assertEqual(snapshot(self.downloads), self.downloads_before)
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()),
                         ["bin", "downloads", "home", "stub-log"])

    def test_never_calls_sudo(self):
        self.assertEqual(self.logged("sudo"), [])


class OlderVersion(UpdateTestCase):

    def setUp(self):
        super().setUp()
        self.archive = make_archive(self.downloads, "0.3.0")
        self.install()
        self.put_things_in_place()
        self.before = self.theirs()
        self.app_before = snapshot(self.places["APP_DIR"])
        self.older = make_archive(self.downloads, "0.2.0")

    def test_warns_and_asks_and_a_no_changes_nothing(self):
        result = self.run_install(str(self.older), answer="n\n")
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.assertIn("Warning: 0.2.0 is older than the 0.3.0 you have.", result.stdout)
        self.assertIn("Install 0.2.0 anyway? [y/N]", result.stdout)
        self.assertIn(f"Nothing was changed: {APP_NAME} 0.3.0 is still installed.", result.stdout)
        self.assertNotIn("Done.", result.stdout)
        self.assertEqual(snapshot(self.places["APP_DIR"]), self.app_before)
        self.assertEqual(len(self.versions()), 1)
        self.assertEqual(self.theirs(), self.before)

    def test_no_answer_counts_as_no(self):
        result = self.run_install(str(self.older), answer="")
        self.assertEqual(result.returncode, 3)
        self.assertEqual(self.version(), "0.3.0")

    def test_a_yes_installs_it_and_the_next_question_gets_its_own_answer(self):
        # "y" for the older version, "n" for mpv: the update step must read
        # only its own line.
        result = self.run_install(str(self.older), answer="y\nn\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.version(), "0.2.0")
        self.assertIn("Install mpv now with that command? [y/N]", result.stdout)
        self.assertIn("mpv not installed.", result.stdout)
        self.assertNotIn("install flathub io.mpv.Mpv", self.logged("flatpak"))
        self.assertEqual(self.theirs(), self.before)

    def test_the_same_version_again_is_put_in_without_asking(self):
        again = make_archive(self.downloads, "0.3.0")
        result = self.run_install(str(again), answer="n\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("anyway?", result.stdout)
        self.assertIn("That is the version you have", result.stdout)
        self.assertEqual(len(self.versions()), 1)


class StopsWithNothingChanged(UpdateTestCase):

    def setUp(self):
        super().setUp()
        self.install()
        self.put_things_in_place()
        self.home_before = snapshot(self.home)
        self.newer = make_archive(self.downloads, "0.3.0")

    def assert_nothing_changed(self, result, *words):
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("Update stopped:", result.stdout)
        self.assertIn(f"Nothing was changed: {APP_NAME} 0.2.0 is still installed.", result.stdout)
        for word in words:
            self.assertIn(word, result.stdout)
        self.assertEqual(snapshot(self.home), self.home_before)

    def test_a_checksum_mismatch(self):
        Path(f"{self.newer}.sha256").write_text("0" * 64 + f"  {self.newer.name}\n")
        self.assert_nothing_changed(self.run_install(str(self.newer)),
                                    "doesn't match its checksum")

    def test_a_changed_archive(self):
        data = bytearray(self.newer.read_bytes())
        data[-1] ^= 1
        self.newer.write_bytes(bytes(data))
        self.assert_nothing_changed(self.run_install(str(self.newer)),
                                    "doesn't match its checksum")

    def test_a_missing_checksum_file(self):
        Path(f"{self.newer}.sha256").unlink()
        self.assert_nothing_changed(self.run_install(str(self.newer)), "checksum file")

    def test_an_archive_that_is_not_the_app(self):
        archive = make_archive(self.downloads, "0.3.0", extra={"VERSION": (b"", 0o644)})
        self.assert_nothing_changed(self.run_install(str(archive)),
                                    f"isn't a {APP_NAME} release")


class RollsBack(UpdateTestCase):

    def setUp(self):
        super().setUp()
        self.install()
        self.put_things_in_place()
        self.before = self.theirs()
        self.app_before = snapshot(self.places["APP_DIR"])
        self.link_before = os.readlink(self.places["APP_DIR"])

    def assert_rolled_back(self, result, *words):
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("The update to 0.3.0 didn't work:", result.stdout)
        self.assertIn(f"Rolled back: {APP_NAME} 0.2.0 is installed again, as it was.",
                      result.stdout)
        for word in words:
            self.assertIn(word, result.stdout)
        self.assertNotIn("Done.", result.stdout)
        self.assertEqual(os.readlink(self.places["APP_DIR"]), self.link_before)
        self.assertEqual(snapshot(self.places["APP_DIR"]), self.app_before)
        self.assertEqual(len(self.versions()), 1)
        self.assertEqual(self.theirs(), self.before)
        self.assertEqual(self.logged("sudo"), [])

    def test_a_first_start_that_fails(self):
        broken = make_archive(self.downloads, "0.3.0", server=BROKEN_SERVER)
        self.assert_rolled_back(self.run_install(str(broken)),
                                f"{APP_NAME} 0.3.0 didn't start cleanly",
                                "it stopped as soon as it started",
                                "invented failure: this version cannot start")

    def test_a_page_that_does_not_load(self):
        page = PAGE.replace(b"js/app.js", b"js/missing.js")
        broken = make_archive(self.downloads, "0.3.0", extra={"ui/index.html": (page, 0o644)})
        self.assert_rolled_back(self.run_install(str(broken)),
                                "its page didn't load: js/missing.js is missing.")

    def test_a_failed_install_step(self):
        # The new version's folder can't be written: a full disk, say.
        result = self.run_update_with(mock.patch.object(
            update, "_unpack", side_effect=OSError(errno.ENOSPC, "No space left on device")))
        self.assertEqual(result.outcome, update.ROLLED_BACK)
        self.assertIn("the disk is full.", result.message)
        self.assert_api_rolled_back()

    def test_a_failed_switch(self):
        result = self.run_update_with(mock.patch.object(
            update, "_point_app_at", side_effect=[OSError(errno.EIO, "I/O error"), None]))
        self.assertEqual(result.outcome, update.ROLLED_BACK)
        self.assertIn("a file couldn't be written", result.message)
        self.assert_api_rolled_back()

    def run_update_with(self, patch):
        newer = make_archive(self.downloads, "0.3.0")
        said = []
        with patch:
            result = update.install(newer, self.places["APP_DIR"], NAME["INSTALL_MARK"],
                                    APP_NAME, say=said.append,
                                    start_check=lambda app, env: (True, ""))
        self.assertIn(result.message, said)
        self.assertIn(f"Rolled back: {APP_NAME} 0.2.0 is installed again", result.message)
        return result

    def assert_api_rolled_back(self):
        self.assertEqual(os.readlink(self.places["APP_DIR"]), self.link_before)
        self.assertEqual(snapshot(self.places["APP_DIR"]), self.app_before)
        self.assertEqual(len(self.versions()), 1)
        self.assertEqual(self.theirs(), self.before)


class PowerCut(BaseException):
    """Stands for the device losing power: nothing after it runs."""


class AlwaysOldOrNew(UpdateTestCase):
    """A power cut at any step leaves the old version or the new one."""

    STEPS = ("unpacking", "unpacked", "switched", "checked")

    def update_cut_at(self, step):
        newer = make_archive(self.downloads, "0.3.0")

        def cut(name):
            if name == step:
                raise PowerCut(name)

        with mock.patch.object(update, "_checkpoint", side_effect=cut):
            with self.assertRaises(PowerCut):
                update.install(newer, self.places["APP_DIR"], NAME["INSTALL_MARK"], APP_NAME,
                               say=lambda text: None, start_check=lambda app, env: (True, ""))
        return newer

    def new_version_snapshot(self, newer):
        """The app folder as a clean update to 0.3.0 leaves it."""
        other = self.tmp / "other"
        app = app_dir_in(other)
        for archive in (self.archive, newer):
            result = update.install(archive, app, NAME["INSTALL_MARK"], APP_NAME,
                                    say=lambda text: None,
                                    start_check=lambda a, env: (True, ""))
            self.assertIn(result.outcome, (update.INSTALLED, update.UPDATED))
        found = snapshot(app)
        shutil.rmtree(other)
        return found

    def test_every_step(self):
        for step in self.STEPS:
            with self.subTest(step=step):
                shutil.rmtree(self.home)
                self.home.mkdir()
                self.install()
                self.put_things_in_place()
                before = self.theirs()
                old = snapshot(self.places["APP_DIR"])
                newer = self.update_cut_at(step)
                new = self.new_version_snapshot(newer)
                now = snapshot(self.places["APP_DIR"])
                self.assertIn(now, (old, new), f"a mix after a power cut at {step}")
                self.assertEqual(self.theirs(), before)
                # The next run works and clears what the cut left behind.
                result = self.run_install(str(newer))
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(self.version(), "0.3.0")
                self.assertEqual(len(self.versions()), 1)
                self.assertEqual(self.theirs(), before)


def app_dir_in(home):
    return home / ".local/share" / NAME["APP_ID"] / "app"


class InstallBeforeVersionsFolder(UpdateTestCase):
    """An install made by the installer work's installer: the app folder a plain folder."""

    def setUp(self):
        super().setUp()
        app = self.places["APP_DIR"]
        app.parent.mkdir(parents=True)
        with tarfile.open(self.archive) as tar:
            tar.extractall(self.tmp / "unpacked", filter="data")
        shutil.move(self.tmp / "unpacked" / f"{NAME['ARCHIVE_NAME']}-0.2.0", app)
        (self.tmp / "unpacked").rmdir()
        (app / NAME["INSTALL_MARK"]).write_text("installed\n")
        for key in ("DATA_DIR", "CONFIG_DIR", "LOGS_DIR"):
            self.places[key].mkdir(parents=True, exist_ok=True)
        self.put_things_in_place()
        self.before = self.theirs()
        self.app_before = snapshot(app)
        self.newer = make_archive(self.downloads, "0.3.0")

    def test_is_updated_into_the_versions_layout(self):
        result = self.run_install(str(self.newer))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"Installed now: {APP_NAME} 0.2.0", result.stdout)
        self.assertTrue(self.places["APP_DIR"].is_symlink())
        self.assertEqual(self.version(), "0.3.0")
        self.assertEqual(len(self.versions()), 1)
        self.assertEqual(self.theirs(), self.before)

    def test_a_failed_first_start_puts_the_old_files_back(self):
        broken = make_archive(self.downloads, "0.3.0", server=BROKEN_SERVER)
        result = self.run_install(str(broken))
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn(f"Rolled back: {APP_NAME} 0.2.0 is installed again", result.stdout)
        self.assertEqual(snapshot(self.places["APP_DIR"]), self.app_before)
        self.assertEqual(self.theirs(), self.before)

    def test_a_failed_switch_moves_the_folder_back(self):
        with mock.patch.object(update, "_point_app_at", side_effect=OSError(errno.EIO, "I/O")):
            result = update.install(self.newer, self.places["APP_DIR"], NAME["INSTALL_MARK"],
                                    APP_NAME, say=lambda text: None,
                                    start_check=lambda app, env: (True, ""))
        self.assertEqual(result.outcome, update.ROLLED_BACK)
        self.assertFalse(self.places["APP_DIR"].is_symlink())
        self.assertEqual(snapshot(self.places["APP_DIR"]), self.app_before)
        self.assertEqual(self.versions(), [])

    def test_a_power_cut_between_the_two_renames_is_mended_by_the_next_run(self):
        # The one moment the app folder is missing (see docs/decisions.md).
        def cut(name):
            if name == "moved the old folder":
                raise PowerCut(name)

        with mock.patch.object(update, "_checkpoint", side_effect=cut):
            with self.assertRaises(PowerCut):
                update.install(self.newer, self.places["APP_DIR"], NAME["INSTALL_MARK"],
                               APP_NAME, say=lambda text: None,
                               start_check=lambda app, env: (True, ""))
        result = self.run_install(str(self.newer))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.version(), "0.3.0")
        self.assertEqual(len(self.versions()), 1)
        self.assertEqual(self.theirs(), self.before)


class StandaloneScriptUpdates(UpdateTestCase):
    """The install.sh the release puts next to the archive carries the
    update step written in, and updates on its own."""

    def test_updates_with_the_written_in_step(self):
        text = release.standalone_installer(SCRIPT.read_text(encoding="utf-8"),
                                            NAMES.read_text(encoding="utf-8"),
                                            UPDATER.read_text(encoding="utf-8"))
        script = self.downloads / "install.sh"
        script.write_text(text, encoding="utf-8")
        self.assertFalse((self.downloads / "update.py").exists())
        self.assertEqual(self.run_install(script=script).returncode, 0)
        self.put_things_in_place()
        before = self.theirs()
        make_archive(self.downloads, "0.3.0")
        result = self.run_install(script=script)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"Updated {APP_NAME} from 0.2.0 to 0.3.0.", result.stdout)
        self.assertIn("It started cleanly.", result.stdout)
        self.assertEqual(self.theirs(), before)


class OneAtATime(UpdateTestCase):

    def test_a_second_update_while_one_runs_stops(self):
        self.install()
        versions = self.places["APP_DIR"].parent / "versions"
        handle = os.open(versions, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, handle)
        fcntl.flock(handle, fcntl.LOCK_EX)
        before = snapshot(self.home)
        result = self.run_install(str(make_archive(self.downloads, "0.3.0")))
        self.assertEqual(result.returncode, 1)
        self.assertIn("another install or update is running", result.stdout)
        self.assertEqual(snapshot(self.home), before)


class Archives(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def members_of(self, *entries):
        path = self.tmp / "a.tar.gz"
        with tarfile.open(path, "w:gz") as tar:
            for info in entries:
                tar.addfile(info)
        return path.read_bytes()

    def entry(self, name, kind=tarfile.REGTYPE, link=""):
        info = tarfile.TarInfo(name)
        info.type, info.linkname = kind, link
        return info

    def test_a_shortcut_inside_the_folder_is_allowed(self):
        data = self.members_of(self.entry("app/a"), self.entry("app/b", tarfile.SYMTYPE, "a"))
        top, _ = update.check_members(data, APP_NAME)
        self.assertEqual(top, "app")

    def test_a_shortcut_out_of_the_folder_stops(self):
        for link in ("../../etc", "/etc/passwd"):
            data = self.members_of(self.entry("app/a"),
                                   self.entry("app/b", tarfile.SYMTYPE, link))
            with self.assertRaisesRegex(update.Stop, "outside its own folder"):
                update.check_members(data, APP_NAME)

    def test_anything_but_files_folders_and_shortcuts_stops(self):
        for kind in (tarfile.LNKTYPE, tarfile.CHRTYPE, tarfile.FIFOTYPE):
            data = self.members_of(self.entry("app/a"), self.entry("app/b", kind, "app/a"))
            with self.assertRaisesRegex(update.Stop, "neither a file nor a folder"):
                update.check_members(data, APP_NAME)


class Versions(unittest.TestCase):

    def test_order(self):
        ordered = ["0.1.0-dev", "0.1.0", "0.1.1", "0.2.0-dev", "0.2.0", "0.9.0", "0.10.0", "1.0.0"]
        self.assertEqual(sorted(reversed(ordered), key=update.version_key), ordered)
        self.assertTrue(update.is_older("0.9.0", "0.10.0"))
        self.assertFalse(update.is_older("0.3.0", "0.3.0"))


class StartedCleanlyWithTheRealApp(unittest.TestCase):
    """The first-start check against this repo's own app, as installed."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.home = self.tmp / "home"
        self.app = app_dir_in(self.home)
        self.app.mkdir(parents=True)
        for folder in ("backend", "ui", "vendor", "installer"):
            shutil.copytree(ROOT / folder, self.app / folder,
                            ignore=shutil.ignore_patterns("__pycache__"))
        for name in ("VERSION", "launch.sh"):
            shutil.copy(ROOT / name, self.app / name)
        (self.app / NAME["INSTALL_MARK"]).write_text("installed\n")
        self.env = {"HOME": str(self.home), "PATH": os.environ.get("PATH", ""),
                    "LANG": "C.UTF-8"}
        share = self.app.parent
        self.config = self.home / ".config" / NAME["APP_ID"]
        self.config.mkdir(parents=True)
        self.data = share / "data"
        self.data.mkdir()
        (self.data / "library.json").write_text("{}\n")

    def things_the_app_tidies_at_start(self):
        """What the app's server tidies as it starts with a real data folder
        (Continue watching, the Continue watching work): pictures that belong to no tile, a
        half-saved one, and a list item whose film is no longer in the
        saved library. All invented."""
        films = self.tmp / "Films"
        films.mkdir()
        (self.config / "settings.json").write_text(
            json.dumps({"movies_path": str(films), "tv_path": ""}))
        gone = "Quillmoor Abbey (2019)/Quillmoor Abbey (2019).mkv"
        key = library_index.item_id("movies", gone)
        (self.data / "library.json").write_text(json.dumps({
            "schema_version": 1, "generated_at": "2026-11-01T10:00:00+00:00",
            "sources": {"movies": {"root": str(films), "items": []}},
            "last_scan": {"new": 0, "changed": 0, "missing": 0, "not_available": []}}))
        (self.data / "continue.json").write_text(json.dumps({"schema_version": 1, "entries": {
            key: {"key": key, "source": "movies", "kind": "movie", "file": gone,
                  "position": 1200.0, "stopped_at": 1_700_000_000.0}}}))
        pictures = self.data / "thumbnails"
        pictures.mkdir()
        (pictures / f"{key}.jpg").write_bytes(b"\xff\xd8 invented picture")
        (pictures / "0123456789abcdef.jpg").write_bytes(b"\xff\xd8 a picture of no tile")
        (pictures / "fedcba9876543210.jpg.part").write_bytes(b"\xff\xd8 half saved")

    def test_the_real_app_starts_cleanly_and_never_opens_the_data_folder(self):
        self.things_the_app_tidies_at_start()
        before = snapshot(self.data), snapshot(self.config)
        ok, why = update.started_cleanly(self.app, self.env)
        self.assertEqual((ok, why), (True, ""))
        self.assertEqual((snapshot(self.data), snapshot(self.config)), before)

    def test_without_its_own_data_folder_the_same_start_would_tidy_the_data(self):
        # The control for the test above: the data really is what the
        # server tidies, so only running as a fresh start keeps it as it is.
        self.things_the_app_tidies_at_start()
        with mock.patch.object(update, "START_ENV_SET", {}):
            ok, why = update.started_cleanly(self.app, self.env)
        self.assertEqual((ok, why), (True, ""))
        left = sorted(p.name for p in (self.data / "thumbnails").iterdir())
        self.assertNotIn("0123456789abcdef.jpg", left)
        self.assertNotIn("fedcba9876543210.jpg.part", left)

    def test_a_rolled_back_update_leaves_the_data_folder_as_it_was(self):
        # The real app as the installed version (the installer work plain folder), and
        # the same app as the update, whose first start is run for real and
        # then counted as failed.
        self.things_the_app_tidies_at_start()
        archive = self.tmp / f"{NAME['ARCHIVE_NAME']}-9.9.9.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(self.app, arcname=f"{NAME['ARCHIVE_NAME']}-9.9.9")
        Path(f"{archive}.sha256").write_text(
            release.sha256_line(archive.read_bytes(), archive.name))
        before = snapshot(self.data), snapshot(self.config)
        app_before = snapshot(self.app)
        started = []

        def first_start_then_fail(app, env):
            started.append(update.started_cleanly(app, self.env))
            return False, "invented failure after a real start."

        result = update.install(archive, self.app, NAME["INSTALL_MARK"], APP_NAME,
                                say=lambda text: None, start_check=first_start_then_fail)
        self.assertEqual(started, [(True, "")])
        self.assertEqual(result.outcome, update.ROLLED_BACK, result.message)
        self.assertEqual((snapshot(self.data), snapshot(self.config)), before)
        self.assertEqual(snapshot(self.app), app_before)

    def test_settings_it_cannot_read_are_not_a_clean_start(self):
        (self.config / "settings.json").write_text('{"movies_path": 3, "tv_path": ""}')
        ok, why = update.started_cleanly(self.app, self.env)
        self.assertFalse(ok)
        self.assertIn("it stopped as soon as it started", why)
        self.assertIn("Settings error", why)


class TheUpdateStepItself(unittest.TestCase):

    def test_never_runs_sudo_or_writes_steam_files(self):
        text = UPDATER.read_text(encoding="utf-8")
        self.assertNotIn("sudo", text.replace("No sudo", ""))
        for steam in (".steam", ".local/share/Steam", "shortcuts.vdf", "steam://"):
            self.assertNotIn(steam, text)

    def test_imports_nothing_from_the_app(self):
        # The release writes it into install.sh, where the app isn't there.
        for line in UPDATER.read_text(encoding="utf-8").splitlines():
            self.assertFalse(line.startswith(("from backend", "import backend")), line)

    def test_install_sh_runs_it(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('UPDATER="$SCRIPT_DIR/update.py"', text)
        self.assertIn('python3 -I "$UPDATER" install "$ARCHIVE"', text)


if __name__ == "__main__":
    unittest.main()
