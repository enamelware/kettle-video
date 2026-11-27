# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Running the installer again with the same archive keeps everything
(the reinstall fix, found by the launch rehearsal).

The real installer/install.sh runs twice in a made-up home folder, on one
archive of this repo's own app files (backend/, ui/, installer/ and the
rest a release holds), so the update's first start is the real server's.
Between the two runs, invented settings, a saved library and a Continue
watching list are written where the installed copy keeps them. Checked
after the second run: all three are unchanged, the installed copy still
finds them in the same places, and it would skip onboarding.

Invented names only; nothing outside the temporary folder is touched.

Run: scripts/test.sh unit tests.test_reinstall_keeps_data
"""

import io
import json
import os
import subprocess
import sys
import tarfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from backend import app_paths, onboarding  # noqa: E402
from backend.settings import load_settings  # noqa: E402
import release  # noqa: E402
from tests.test_installer import NAME, InstallerTestCase  # noqa: E402

VERSION = "0.9.0"


def tracked_app_files():
    """[(path, tarinfo, bytes)] for this repo's files a release holds."""
    listed = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True,
                            check=True).stdout.decode("utf-8").split("\0")
    out = []
    for path in listed:
        if not path or not release.included(path) or not (ROOT / path).is_file():
            continue
        data = (ROOT / path).read_bytes()
        if path == "VERSION":
            data = f"{VERSION}\n".encode()
        info = tarfile.TarInfo(path)
        info.mode = 0o755 if os.access(ROOT / path, os.X_OK) else 0o644
        out.append((path, info, data))
    return out


class ReinstallKeepsData(InstallerTestCase):

    def setUp(self):
        super().setUp()
        files = tracked_app_files()
        self.archive = self.downloads / f"{NAME['ARCHIVE_NAME']}-{VERSION}.tar.gz"
        self.archive.write_bytes(release.build_archive(files, f"{NAME['ARCHIVE_NAME']}-{VERSION}"))
        Path(f"{self.archive}.sha256").write_text(
            release.sha256_line(self.archive.read_bytes(), self.archive.name), encoding="utf-8")
        # The made-up media folders the invented settings name.
        self.films = self.tmp / "media" / "Invented Films"
        self.shows = self.tmp / "media" / "Invented Shows"
        self.films.mkdir(parents=True)
        self.shows.mkdir(parents=True)

    def environ(self):
        return {"HOME": str(self.home)}

    def test_running_the_installer_again_keeps_settings_library_and_continue_watching(self):
        self.install()
        app = self.places["APP_DIR"]
        paths = app_paths.for_app(Path(os.path.realpath(app)), self.environ())
        self.assertTrue(paths.installed)
        settings_file = paths.settings_file
        settings_file.write_text(json.dumps(
            {"movies_path": str(self.films), "tv_path": str(self.shows)}) + "\n",
            encoding="utf-8")
        library = paths.data_dir / "library.json"
        library.write_text('{"invented": "saved library"}\n', encoding="utf-8")
        watching = paths.data_dir / "continue.json"
        watching.write_text('{"invented": "continue watching"}\n', encoding="utf-8")
        before = {p: p.read_bytes() for p in (settings_file, library, watching)}
        first_folder = os.path.realpath(app)

        result = self.install()
        self.assertIn(f"Installed now: {NAME['APP_NAME']} {VERSION}", result.stdout)
        self.assertIn(f"This archive:  {NAME['APP_NAME']} {VERSION}", result.stdout)
        self.assertIn("It started cleanly.", result.stdout)
        # The app files really were put in again.
        self.assertNotEqual(os.path.realpath(app), first_folder)

        for path, data in before.items():
            self.assertEqual(path.read_bytes(), data, path.name)
        again = app_paths.for_app(Path(os.path.realpath(app)), self.environ())
        self.assertTrue(again.installed)
        self.assertEqual((again.settings_file, again.data_dir), (settings_file, paths.data_dir))
        settings = load_settings(Path(os.path.realpath(app)), again)
        self.assertFalse(onboarding.needed(settings))
        self.assertEqual(Path(settings["data_dir"]), paths.data_dir)
        # Nothing of the person's was left inside the app files.
        for name in ("settings.json", "data"):
            self.assertFalse((app / name).exists(), name)


if __name__ == "__main__":
    unittest.main()
