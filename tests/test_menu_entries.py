# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""A development copy and an installed copy each keep their own app menu
entry (the installer review fixes).

install-shortcut.sh (development copies) writes DEV_DESKTOP_ENTRY, named
"Kettle Video (dev)"; installer/install.sh writes DESKTOP_ENTRY. Checked, in
a temporary home folder with the stand-in tools of tests/test_installer.py
and an invented development copy outside that home:
- install-shortcut.sh writes only its own entry, moves the entry older
  versions of it wrote (DESKTOP_ENTRY starting this copy) to its own name,
  never touches a DESKTOP_ENTRY that starts anything else, and refuses to
  run in an installed copy;
- with a development copy's entry present (new or old name), installing a
  release leaves it byte for byte as it was; with the old name it says so,
  doesn't add its own entry and still finishes;
- uninstalling never removes a development copy's entry and still runs to
  the end, removing the app files.

Run: scripts/test.sh unit tests.test_menu_entries
"""

import shutil
import subprocess

from tests.test_installer import NAME, ROOT, make_archive
from tests.test_uninstaller import UninstallTestCase


class MenuEntryTestCase(UninstallTestCase):

    def setUp(self):
        super().setUp()
        # An invented development copy: the launcher, the names and the
        # shortcut script, as in the git folder.
        self.dev = self.tmp / "invented-dev-copy"
        (self.dev / "installer").mkdir(parents=True)
        shutil.copy2(ROOT / "install-shortcut.sh", self.dev / "install-shortcut.sh")
        shutil.copy2(ROOT / "installer" / "names.env", self.dev / "installer" / "names.env")
        (self.dev / "launch.sh").write_text("#!/bin/sh\necho invented dev launch\n")
        self.apps = self.home / ".local/share/applications"

    @property
    def dev_file(self):
        return self.apps / NAME["DEV_DESKTOP_ENTRY"]

    def shortcut(self, folder=None):
        folder = folder or self.dev
        return subprocess.run(["bash", str(folder / "install-shortcut.sh")], cwd=folder,
                              env=self.env(), capture_output=True, text=True, timeout=60)

    def old_dev_entry(self):
        """The entry install-shortcut.sh wrote before the installer review fixes, at DESKTOP_ENTRY."""
        self.apps.mkdir(parents=True, exist_ok=True)
        self.desktop_file.write_text(
            "[Desktop Entry]\nType=Application\nName=Kettle Video\n"
            f"Exec={self.dev}/launch.sh\nPath={self.dev}\n", encoding="utf-8")
        return self.desktop_file.read_bytes()


class TheShortcutScript(MenuEntryTestCase):

    def test_writes_only_its_own_entry(self):
        result = self.shortcut()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(sorted(p.name for p in self.apps.iterdir()),
                         [NAME["DEV_DESKTOP_ENTRY"]])
        text = self.dev_file.read_text(encoding="utf-8")
        self.assertIn(f"\nName={NAME['APP_NAME']} (dev)\n", text)
        self.assertIn(f"\nExec={self.dev}/launch.sh\n", text)
        self.assertNotEqual(NAME["DEV_DESKTOP_ENTRY"], NAME["DESKTOP_ENTRY"])

    def test_moves_its_own_old_entry(self):
        self.old_dev_entry()
        result = self.shortcut()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.desktop_file.exists())
        self.assertTrue(self.dev_file.is_file())
        self.assertIn("Removed", result.stdout)

    def test_never_touches_the_installed_copys_entry(self):
        self.install()
        before = self.desktop_file.read_bytes()
        result = self.shortcut()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.desktop_file.read_bytes(), before)
        self.assertTrue(self.dev_file.is_file())

    def test_never_touches_another_copys_old_entry(self):
        self.apps.mkdir(parents=True)
        self.desktop_file.write_text("[Desktop Entry]\nExec=/invented/other-copy/launch.sh\n")
        before = self.desktop_file.read_bytes()
        self.shortcut()
        self.assertEqual(self.desktop_file.read_bytes(), before)

    def test_refuses_in_an_installed_copy(self):
        # The release archive carries install-shortcut.sh too.
        self.archive = make_archive(self.downloads, extra={
            "install-shortcut.sh": ((ROOT / "install-shortcut.sh").read_bytes(), 0o755)})
        self.install()
        app = self.places["APP_DIR"]
        before = sorted(p.name for p in self.apps.iterdir())
        result = self.shortcut(app)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("installed copy", result.stdout)
        self.assertEqual(sorted(p.name for p in self.apps.iterdir()), before)


class InstallingBesideADevelopmentCopy(MenuEntryTestCase):

    def test_its_own_entry_is_left_alone_and_both_are_listed(self):
        self.shortcut()
        before = self.dev_file.read_bytes()
        self.install()
        self.assertEqual(self.dev_file.read_bytes(), before)
        installed = self.desktop_file.read_text(encoding="utf-8")
        self.assertIn(f'Exec="{self.places["APP_DIR"]}/launch.sh"\n', installed)
        self.assertEqual(sorted(p.name for p in self.apps.glob("*.desktop")),
                         sorted([NAME["DESKTOP_ENTRY"], NAME["DEV_DESKTOP_ENTRY"]]))

    def test_an_old_dev_entry_is_left_alone_and_it_says_so(self):
        before = self.old_dev_entry()
        result = self.install()
        self.assertEqual(self.desktop_file.read_bytes(), before)
        out = result.stdout
        self.assertIn("doesn't start the installed", out)
        self.assertIn("install-shortcut.sh again", out)
        self.assertIn("Not added to the app menu", out)
        self.assertNotIn(f"Added {NAME['APP_NAME']} to the app menu", out)
        self.assertIn(f"Done. {NAME['APP_NAME']} 0.2.0 is installed.", out)
        # The Steam steps never send people to the menu entry, which opens
        # the development copy here (reviewer round 1).
        steam = out[out.index("Next, add"):]
        self.assertNotIn("Right-click it and choose Add to Steam", steam)
        self.assertIn("doesn't open this installed copy", steam)
        self.assertIn("install-shortcut.sh again", steam)
        self.assertIn(f"{self.places['APP_DIR']}/launch.sh", steam)

    def test_the_usual_steam_steps_when_the_entry_is_added(self):
        out = self.install().stdout
        steam = out[out.index("Next, add"):]
        self.assertIn("Right-click it and choose Add to Steam", steam)
        self.assertNotIn("doesn't open this installed copy", steam)

    def test_after_moving_the_old_entry_installing_again_adds_its_own(self):
        self.old_dev_entry()
        self.install()
        self.shortcut()
        result = self.install()
        self.assertIn(f"Added {NAME['APP_NAME']} to the app menu", result.stdout)
        self.assertIn(f'Exec="{self.places["APP_DIR"]}/launch.sh"\n',
                      self.desktop_file.read_text(encoding="utf-8"))
        self.assertIn(f"Exec={self.dev}/launch.sh\n", self.dev_file.read_text(encoding="utf-8"))


class UninstallingBesideADevelopmentCopy(MenuEntryTestCase):

    def test_the_dev_entry_stays(self):
        self.install_with_data()
        self.shortcut()
        before = self.dev_file.read_bytes()
        result = self.uninstall("y\nn\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_app_gone()
        self.assertEqual(self.dev_file.read_bytes(), before)

    def test_an_old_dev_entry_stays_and_it_still_runs(self):
        self.install_with_data()
        before = self.old_dev_entry()
        result = self.uninstall("y\nn\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"Done. {NAME['APP_NAME']} is uninstalled.", result.stdout)
        self.assertIn("leaves", result.stdout)
        self.assertEqual(self.desktop_file.read_bytes(), before)
        places = self.places
        self.assertFalse(places["APP_DIR"].exists() or places["APP_DIR"].is_symlink())
        self.assertFalse((places["APP_DIR"].parent / "versions").exists())
        for profile in self.profiles:
            self.assertFalse(profile.exists(), profile)

    def test_an_entry_starting_something_else_stays(self):
        self.install_with_data()
        self.desktop_file.write_text("[Desktop Entry]\nExec=/invented/other-app\n")
        result = self.uninstall("y\nn\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.desktop_file.read_text(),
                         "[Desktop Entry]\nExec=/invented/other-app\n")
