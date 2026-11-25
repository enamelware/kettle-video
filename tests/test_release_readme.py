# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta
"""The first public release's README, screenshots and notes (the v1.0.0 release work).

Every screenshot the README shows is a 1280 by 800 PNG in docs/screenshots/,
every one is used, every credited film has its credit line and a linked
licence version, the screenshots folder says the same, the README carries
the trademark and no-endorsement lines and links only to files that exist,
and VERSION and CHANGELOG.md say 1.0.0.
Run: scripts/test.sh unit tests.test_release_readme
"""

import re
import struct
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "docs" / "screenshots"
README = (ROOT / "README.md").read_text(encoding="utf-8")
CREDIT = "(CC) Blender Foundation \\| studio.blender.org"
FILMS = {
    "Big Buck Bunny (2008)": "3.0",
    "Elephants Dream (2006)": "2.5",
    "Sintel (2010)": "3.0",
    "Caminandes 2: Gran Dillama (2013)": "4.0",
}


def png_size(path):
    data = path.read_bytes()[:24]
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", data[16:24])


def shown():
    return re.findall(r"!\[[^\]]*\]\((docs/screenshots/[^)]+)\)", README)


class Screenshots(unittest.TestCase):
    def test_four_or_five_shots_each_a_1280_by_800_png(self):
        paths = shown()
        self.assertTrue(4 <= len(paths) <= 5, paths)
        for rel in paths:
            with self.subTest(rel=rel):
                self.assertEqual(png_size(ROOT / rel), (1280, 800))

    def test_every_shot_in_the_folder_is_used(self):
        used = {Path(p).name for p in shown()}
        on_disk = {p.name for p in SHOTS.glob("*.png")}
        self.assertEqual(on_disk, used)


class Credits(unittest.TestCase):
    def test_each_film_has_its_credit_and_linked_licence(self):
        for text in (README, (SHOTS / "README.md").read_text(encoding="utf-8")):
            for film, version in FILMS.items():
                with self.subTest(film=film):
                    row = next(line for line in text.splitlines() if line.startswith(f"| {film} |"))
                    self.assertIn(CREDIT, row)
                    self.assertIn(f"[CC BY {version}](https://creativecommons.org/licenses/by/{version}/)", row)

    def test_the_licence_and_endorsement_lines(self):
        for text in (README, (SHOTS / "README.md").read_text(encoding="utf-8")):
            flat = " ".join(text.split())
            self.assertIn("under the films' licences above, not under Kettle Video's GPL", flat)
            self.assertIn("Kettle Video is not affiliated with or endorsed by the Blender Foundation.", flat)

    def test_the_trademark_line(self):
        self.assertIn("Kettle Video is not affiliated with Valve. Steam and Steam Deck are trademarks of "
                      "Valve Corporation.", README)


class Links(unittest.TestCase):
    def test_every_file_link_exists(self):
        for target in re.findall(r"\]\(([^)#]+)(?:#[^)]*)?\)", README):
            if target.startswith("http"):
                continue
            with self.subTest(target=target):
                self.assertTrue((ROOT / target).exists())


class PointersFromTheApp(unittest.TestCase):
    """What the installer and the start-up error screen send people to in
    the README is there."""

    def test_the_installer_names_a_readme_section_that_has_the_keys(self):
        install = (ROOT / "installer" / "install.sh").read_text(encoding="utf-8")
        names = re.findall(r'README, under \\"([^"\\]+)\\"', install)
        self.assertTrue(names, "the installer no longer points into the README")
        for name in names:
            with self.subTest(section=name):
                found = re.search(rf"^## {re.escape(name)}\n(.*?)(?=^## |\Z)", README, re.M | re.S)
                self.assertTrue(found, f"no README section {name!r}")
                self.assertIn("A = Space, B = q", found.group(1))

    def test_the_readme_names_the_settings_and_logs_folders(self):
        # backend/startup_error.py says "see the README" for both.
        self.assertIn("~/.config/kettle-video/settings.json", README)
        self.assertIn("~/.local/state/kettle-video/logs", README)


class Version(unittest.TestCase):
    def test_version_and_changelog(self):
        self.assertEqual((ROOT / "VERSION").read_text(encoding="utf-8").strip(), "1.0.0")
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertRegex(changelog, r"\n## 1\.0\.0\n")
        self.assertLess(changelog.index("\n## 1.0.0\n"), changelog.index("\n## 0.1.0-dev\n"))


if __name__ == "__main__":
    unittest.main()
