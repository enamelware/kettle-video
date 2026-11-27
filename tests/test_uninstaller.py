# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The uninstaller, installer/uninstall.sh (the uninstaller work).

Every test installs a small invented release with the real installer
(installer/install.sh) in a temporary home folder, with the same stand-in
tools as tests/test_installer.py, then runs the uninstall script the
installed copy carries. Checked: uninstalling keeps the data (library,
settings, logs) byte for byte and removes the app files, the menu entry and
the kiosk window's Firefox profile; deleting the data happens only after
asking and confirming, and a no to the confirmation keeps it; saying no, or
not answering, removes nothing; anything unexpected (not installed, a folder
the installer didn't make, a place outside the home folder, a media folder
inside what would go, the app still open, root) stops with nothing removed
(a menu entry the installer didn't make is left alone instead, the installer review fixes,
tests/test_menu_entries.py); nothing outside the temporary home is touched, sudo is
never called and the Steam reminder is printed; installing again finds the
kept data; an uninstall that stopped part way finishes on a second run.

Run: scripts/test.sh unit tests.test_uninstaller
"""

import fcntl
import os
import re
import shutil
import unittest
from pathlib import Path

from tests.test_installer import (NAME, ROOT, InstallerTestCase, make_archive, snapshot)

UNINSTALLER = ROOT / "installer" / "uninstall.sh"
# Tools the uninstaller uses beyond the installer's.
MORE_TOOLS = ("realpath", "readlink", "grep", "rmdir", "flock")


class UninstallTestCase(InstallerTestCase):

    def setUp(self):
        super().setUp()
        for tool in MORE_TOOLS:
            found = shutil.which(tool)
            if found and not (self.bin / tool).exists():
                os.symlink(found, self.bin / tool)
        # The archive carries the uninstaller, as a release does (installer/).
        self.archive = make_archive(self.downloads, extra={
            "installer/uninstall.sh": (UNINSTALLER.read_bytes(), 0o755)})
        # Invented media folders, outside the home folder.
        self.media = self.tmp / "media"
        (self.media / "Films").mkdir(parents=True)
        (self.media / "Films" / "Invented Film (2031).mkv").write_bytes(b"not a real film")
        (self.media / "Shows").mkdir()

    def install_with_data(self, **extra):
        """Install, then give it invented settings, data, logs and both
        Firefox profiles, as using the app would."""
        self.install(**extra)
        places = self.places_for(**extra)
        (places["CONFIG_DIR"] / "settings.json").write_text(
            '{"movies_path": "%s", "tv_path": "%s"}\n'
            % (self.media / "Films", self.media / "Shows"), encoding="utf-8")
        (places["DATA_DIR"] / "library.json").write_text('{"invented": true}\n')
        (places["DATA_DIR"] / "thumbnails").mkdir()
        (places["DATA_DIR"] / "thumbnails" / "invented.jpg").write_bytes(b"\xff\xd8 invented")
        (places["LOGS_DIR"] / "launch-1.log").write_text("an invented log\n")
        (places["LOGS_DIR"] / "launch.lock").write_text("")
        for profile in self.profiles:
            profile.mkdir(parents=True)
            (profile / "user.js").write_text('user_pref("invented", true);\n')

    def places_for(self, **extra):
        from backend import app_paths
        return app_paths.install_places(NAME["APP_ID"], {"HOME": str(self.home), **extra})

    @property
    def profiles(self):
        return [self.home / ".mozilla" / NAME["FIREFOX_PROFILE"],
                self.home / ".var/app/org.mozilla.firefox/data" / NAME["FIREFOX_PROFILE"]]

    @property
    def desktop_file(self):
        return self.home / ".local/share/applications" / NAME["DESKTOP_ENTRY"]

    def data_snapshot(self, **extra):
        places = self.places_for(**extra)
        return {key: snapshot(places[key]) for key in ("DATA_DIR", "CONFIG_DIR", "LOGS_DIR")}

    def uninstall(self, answer, script=None, **extra):
        script = script or self.places_for(**extra)["APP_DIR"] / "installer" / "uninstall.sh"
        return self.run_install(answer=answer, script=script, **extra)

    def outside_home(self):
        """Everything in the temporary folder but the home folder."""
        return {name: snapshot(self.tmp / name) for name in ("downloads", "media", "bin")}

    def assert_app_gone(self, **extra):
        places = self.places_for(**extra)
        share = places["APP_DIR"].parent
        self.assertFalse(places["APP_DIR"].exists() or places["APP_DIR"].is_symlink())
        self.assertFalse((share / "versions").exists())
        self.assertFalse(self.desktop_file.exists())
        for profile in self.profiles:
            self.assertFalse(profile.exists(), profile)

    def assert_stopped(self, result, *words):
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("Uninstall stopped", result.stdout)
        self.assertIn("Nothing was removed.", result.stdout)
        for word in words:
            self.assertIn(word, result.stdout)


class KeepsTheData(UninstallTestCase):

    def setUp(self):
        super().setUp()
        self.install_with_data()
        self.data_before = self.data_snapshot()
        self.outside_before = self.outside_home()
        self.result = self.uninstall("y\nn\n")

    def test_finishes(self):
        self.assertEqual(self.result.returncode, 0, self.result.stdout + self.result.stderr)
        self.assertIn(f"Done. {NAME['APP_NAME']} is uninstalled.", self.result.stdout)

    def test_the_data_is_byte_for_byte_unchanged(self):
        self.assertEqual(self.data_snapshot(), self.data_before)
        self.assertIn("are kept", self.result.stdout)

    def test_app_files_menu_entry_and_firefox_profile_are_gone(self):
        self.assert_app_gone()
        share = self.places["APP_DIR"].parent
        self.assertEqual(sorted(p.name for p in share.iterdir()), ["data"])

    def test_nothing_outside_the_home_folder_is_touched(self):
        self.assertEqual(self.outside_home(), self.outside_before)
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()),
                         ["bin", "downloads", "home", "media", "stub-log"])

    def test_never_calls_sudo(self):
        self.assertEqual(self.logged("sudo"), [])

    def test_mpv_is_left_alone(self):
        self.assertFalse([line for line in self.logged("flatpak")
                          if line.startswith(("uninstall", "remove"))])
        self.assertIn("mpv is still installed.", self.result.stdout)

    def test_the_steam_reminder_is_printed(self):
        out = self.result.stdout
        self.assertIn("remove Kettle Video from Steam by hand", out)
        self.assertIn("Remove non-Steam game", out)
        self.assertIn("never changes Steam's", out)

    def test_installing_again_finds_the_kept_data(self):
        self.install()
        self.assertEqual(self.data_snapshot(), self.data_before)
        from backend import app_paths
        paths = app_paths.for_app(self.places["APP_DIR"], {"HOME": str(self.home)})
        self.assertTrue(paths.installed)
        self.assertEqual(paths.data_dir, self.places["DATA_DIR"])
        self.assertTrue((paths.data_dir / "library.json").is_file())
        self.assertTrue(paths.settings_file.is_file())


class RemovesTheDataOnlyWhenConfirmed(UninstallTestCase):

    def setUp(self):
        super().setUp()
        self.install_with_data()
        self.outside_before = self.outside_home()

    def test_yes_then_confirm_removes_the_data(self):
        result = self.uninstall("y\ny\ny\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("can't be undone", result.stdout)
        self.assertIn("were deleted", result.stdout)
        self.assert_app_gone()
        for key in ("DATA_DIR", "CONFIG_DIR", "LOGS_DIR"):
            self.assertFalse(self.places[key].exists(), key)
        self.assertFalse((self.home / ".local/share" / NAME["APP_ID"]).exists())
        self.assertFalse((self.home / ".local/state" / NAME["APP_ID"]).exists())
        # Folders the app shares with others stay.
        self.assertTrue((self.home / ".local/share/applications").is_dir())
        self.assertTrue((self.home / ".mozilla").is_dir())
        self.assertEqual(self.outside_home(), self.outside_before)
        self.assertEqual(self.logged("sudo"), [])
        self.assertIn("Remove non-Steam game", result.stdout)

    def test_no_to_the_confirmation_keeps_the_data(self):
        before = self.data_snapshot()
        result = self.uninstall("y\ny\nn\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.data_snapshot(), before)
        self.assert_app_gone()
        self.assertIn("are kept", result.stdout)

    def test_no_answer_to_the_confirmation_keeps_the_data(self):
        before = self.data_snapshot()
        result = self.uninstall("y\ny\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.data_snapshot(), before)


class SayingNoRemovesNothing(UninstallTestCase):

    def setUp(self):
        super().setUp()
        self.install_with_data()
        self.before = snapshot(self.home)

    def test_no(self):
        result = self.uninstall("n\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Nothing was removed.", result.stdout)
        self.assertEqual(snapshot(self.home), self.before)

    def test_no_answer_at_all(self):
        result = self.uninstall("")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(snapshot(self.home), self.before)

    def test_it_says_what_it_would_remove_and_keep_first(self):
        out = self.uninstall("n\n").stdout
        self.assertIn(str(self.places["APP_DIR"]), out)
        self.assertIn(str(self.desktop_file), out)
        self.assertIn(str(self.profiles[0]), out)
        self.assertIn(str(self.places["DATA_DIR"]), out)
        self.assertIn("never touched", out)
        self.assertLess(out.index("This removes:"), out.index(f"Uninstall {NAME['APP_NAME']}?"))


class StopsWithNothingRemoved(UninstallTestCase):

    def setUp(self):
        super().setUp()
        self.install_with_data()
        self.script = self.tmp / "uninstall-copy"
        self.script.mkdir()
        # A copy of the script with its names, so a test can damage the
        # installed copy freely.
        shutil.copy(UNINSTALLER, self.script / "uninstall.sh")
        shutil.copy(ROOT / "installer" / "names.env", self.script / "names.env")

    def run_copy(self, answer="y\ny\ny\n", **extra):
        before = snapshot(self.home)
        result = self.uninstall(answer, script=self.script / "uninstall.sh", **extra)
        self.assertEqual(snapshot(self.home), before)
        return result

    def test_not_installed(self):
        app = self.places["APP_DIR"]
        shutil.rmtree(app.parent / "versions")
        app.unlink()
        self.assert_stopped(self.run_copy(), "isn't installed here")

    def test_an_app_folder_the_installer_did_not_make(self):
        app = self.places["APP_DIR"]
        shutil.rmtree(app.parent / "versions")
        app.unlink()
        app.mkdir()
        (app / "mine.txt").write_text("someone's own file\n")
        self.assert_stopped(self.run_copy(), "wasn't made by the installer")

    def test_an_app_shortcut_pointing_elsewhere(self):
        app = self.places["APP_DIR"]
        app.unlink()
        app.symlink_to(self.home)
        self.assert_stopped(self.run_copy(), "points somewhere the installer never puts")

    def test_a_profile_that_is_a_shortcut(self):
        profile = self.profiles[0]
        shutil.rmtree(profile)
        elsewhere = self.home / "invented-elsewhere"
        elsewhere.mkdir()
        profile.symlink_to(elsewhere)
        self.assert_stopped(self.run_copy(), "isn't the Firefox profile folder")

    def test_a_place_outside_the_home_folder(self):
        outside = self.tmp / "outside-data"
        outside.mkdir()
        before = snapshot(outside)
        self.assert_stopped(self.run_copy(XDG_CONFIG_HOME=str(outside)),
                            "outside your home folder")
        self.assertEqual(snapshot(outside), before)

    def test_a_media_folder_inside_what_would_be_removed(self):
        films = self.places["DATA_DIR"] / "Films"
        films.mkdir()
        (films / "Invented Film.mkv").write_bytes(b"not a real film")
        (self.places["CONFIG_DIR"] / "settings.json").write_text(
            '{"movies_path": "%s", "tv_path": ""}\n' % films, encoding="utf-8")
        self.assert_stopped(self.run_copy(), "your media folder", str(films))

    def test_the_app_is_open(self):
        with open(self.places["LOGS_DIR"] / "launch.lock") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self.assert_stopped(self.run_copy(), "is open")

    def test_an_install_or_update_is_running(self):
        # installer/update.py holds this lock on versions/ while it works.
        handle = os.open(self.places["APP_DIR"].parent / "versions",
                         os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, handle)
        fcntl.flock(handle, fcntl.LOCK_EX)
        self.assert_stopped(self.run_copy(), "an install or update is running")

    def test_run_as_root(self):
        self.stub("id", "#!/bin/sh\necho 0\n")
        self.assert_stopped(self.run_copy(), "not as root or with sudo")
        self.assertEqual(self.logged("sudo"), [])

    def test_names_missing(self):
        (self.script / "names.env").unlink()
        self.assert_stopped(self.run_copy(), "missing its names")


class OtherLayouts(UninstallTestCase):

    def test_an_install_from_before_updates(self):
        """The installer work's layout: the app folder a plain folder with the mark."""
        self.install_with_data()
        app = self.places["APP_DIR"]
        version = Path(os.path.realpath(app))
        app.unlink()
        version.rename(app)
        (app.parent / "versions").rmdir()
        before = self.data_snapshot()
        result = self.run_install(answer="y\nn\n", script=app / "installer" / "uninstall.sh")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_app_gone()
        self.assertEqual(self.data_snapshot(), before)

    def test_xdg_overrides_inside_the_home_folder(self):
        env = {"XDG_DATA_HOME": str(self.home / "d"), "XDG_CONFIG_HOME": str(self.home / "c"),
               "XDG_STATE_HOME": str(self.home / "s")}
        self.install(**env)
        places = self.places_for(**env)
        (places["DATA_DIR"] / "library.json").write_text("{}\n")
        result = self.uninstall("y\nn\n", **env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(places["APP_DIR"].is_symlink())
        self.assertFalse((self.home / "d/applications" / NAME["DESKTOP_ENTRY"]).exists())
        self.assertEqual((places["DATA_DIR"] / "library.json").read_text(), "{}\n")

    def test_a_second_run_finishes_an_interrupted_uninstall(self):
        self.install_with_data()
        app = self.places["APP_DIR"]
        script_dir = self.tmp / "kept-script"
        shutil.copytree(app / "installer", script_dir)
        # Stopped part way: the versions folder went, the shortcut didn't.
        shutil.rmtree(app.parent / "versions")
        before = self.data_snapshot()
        result = self.run_install(answer="y\nn\n", script=script_dir / "uninstall.sh")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_app_gone()
        self.assertEqual(self.data_snapshot(), before)


class TheScriptItself(unittest.TestCase):

    def setUp(self):
        self.text = UNINSTALLER.read_text(encoding="utf-8")

    def test_licence_header(self):
        self.assertIn("SPDX-License-Identifier: GPL-3.0-or-later", self.text)

    def test_never_runs_sudo(self):
        code = [line for line in self.text.splitlines() if not line.lstrip().startswith("#")]
        self.assertFalse([line for line in code if re.search(r"\bsudo\s", line)
                          and "not as root or with sudo" not in line])

    def test_never_touches_steam_or_mpv(self):
        for word in (".steam", "userdata", "shortcuts.vdf", "flatpak uninstall"):
            self.assertNotIn(word, self.text)
        # mpv's own folder only ever for the installed copy's resume positions
        # inside it (the each-copy-its-own-data work), never mpv's own.
        code = [line for line in self.text.splitlines() if not line.lstrip().startswith("#")]
        self.assertEqual([line.strip() for line in code if "io.mpv" in line],
                         ['mpv_resume_dir="$HOME/.var/app/io.mpv.Mpv/data/$APP_ID"'])
        self.assertNotIn("watch_later", "\n".join(code))

    def test_runnable(self):
        self.assertTrue(os.access(UNINSTALLER, os.X_OK))

    def test_the_profile_name_matches_launch_sh(self):
        # launch.sh asks backend/app_paths.py, and falls back on the same names.
        launch = (ROOT / "launch.sh").read_text(encoding="utf-8")
        self.assertIn('PROFILE_NAME="$(python3 -m backend.app_paths profile 2>/dev/null)"', launch)
        self.assertIn(f'PROFILE_NAME="{NAME["FIREFOX_PROFILE"]}"\n', launch)
        self.assertIn(f'PROFILE_NAME="{NAME["DEV_FIREFOX_PROFILE"]}"\n', launch)
        self.assertIn(f'[ -f "$SCRIPT_DIR/{NAME["INSTALL_MARK"]}" ]', launch)

    def test_the_release_carries_it(self):
        import release
        self.assertTrue(release.included("installer/uninstall.sh"))
        self.assertIn("FIREFOX_PROFILE", release.NAME_KEYS)


if __name__ == "__main__":
    unittest.main()
