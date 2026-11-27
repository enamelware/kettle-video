# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The release script (the release script work): from a tag it builds the archive, its
checksum and the release notes. The archive holds the licence files and
only the tag's tracked app files, never settings.json, data/, logs/, tests,
spikes or anything untracked; the checksum matches; the notes are the
CHANGELOG entry; a missing tag, a tag that doesn't match VERSION, a missing
CHANGELOG or entry, a private word or a missing word list stop with a plain
message and write nothing. Every installer name comes from one file.

Only temporary git repos and temporary tags, and a temporary list of
invented words; no tag is ever made in this repo.

Run: scripts/test.sh unit tests.test_release
"""

import hashlib
import io
import os
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "tools" / "release.py"
NAMES = ROOT / "installer" / "names.env"
INSTALLER = ROOT / "installer" / "install.sh"
UPDATER = ROOT / "installer" / "update.py"
ONE_FILE = ROOT / "installer" / "one_file_install.py"
sys.path.insert(0, str(ROOT / "tools"))
import release  # noqa: E402

INVENTED = """# invented words only
[films and shows]
Quillmoor Abbey
"""

CHANGELOG = """# Changelog

## 0.2.0

- Plover mode for the Brindle screen.

## 0.1.0

- The first invented release.
"""


def git(repo, *args, check=True):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True,
                          check=check)


class ReleaseTestCase(unittest.TestCase):
    """A temporary repo shaped like the app, tagged v0.2.0, with files that
    must never ship tracked on purpose, and an untracked one."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.list = os.path.join(self.tmp, "words.txt")
        Path(self.list).write_text(INVENTED, encoding="utf-8")
        self.out = os.path.join(self.tmp, "out")
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(self.repo)
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.name", "Test")
        git(self.repo, "config", "user.email", "test@example.invalid")
        git(self.repo, "config", "commit.gpgsign", "false")
        git(self.repo, "config", "tag.gpgsign", "false")
        files = {
            "LICENSE": "GPL text\n",
            "THIRD_PARTY_LICENSES.md": "third-party list\n",
            "README.md": "readme\n",
            "VERSION": "0.2.0\n",
            "CHANGELOG.md": CHANGELOG,
            "installer/names.env": NAMES.read_text(encoding="utf-8"),
            "installer/install.sh": INSTALLER.read_text(encoding="utf-8"),
            "installer/update.py": UPDATER.read_text(encoding="utf-8"),
            "installer/one_file_install.py": ONE_FILE.read_text(encoding="utf-8"),
            "launch.sh": "#!/bin/sh\necho launch\n",
            "settings.example.json": "{}\n",
            "backend/app.py": "print('tagged')\n",
            "ui/index.html": "<p>ui</p>\n",
            "vendor/thing.LICENSE": "thing licence\n",
            "vendor/enamel/LICENSE": "enamel licence\n",
            "vendor/enamel/tokens.css": ":root {}\n",
            # Never shipped, even when tracked.
            "settings.json": '{"movies": "/somewhere"}\n',
            "data/library.json": "{}\n",
            "logs/launch.log": "a log\n",
            "tests/test_app.py": "# test\n",
            "spikes/try.py": "# spike\n",
            "docs/spikes/try.md": "spike notes\n",
            "tools/release.py": "# tool\n",
            "scripts/test.sh": "# script\n",
            ".claude/settings.json": "{}\n",
            "CLAUDE.md": "notes\n",
        }
        for path, text in files.items():
            self.write(path, text)
        os.chmod(os.path.join(self.repo, "launch.sh"), 0o755)
        git(self.repo, "add", "-f", ".")
        git(self.repo, "commit", "-q", "-m", "release")
        git(self.repo, "tag", "v0.2.0")
        # After the tag: an uncommitted change and an untracked file.
        self.write("backend/app.py", "print('not tagged')\n")
        self.write("backend/untracked.py", "# untracked\n")

    def write(self, path, text):
        full = Path(self.repo, path)
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(text, encoding="utf-8")

    def commit_and_tag(self, tag, message="more"):
        git(self.repo, "add", "-f", ".")
        git(self.repo, "commit", "-q", "-m", message)
        git(self.repo, "tag", tag)

    def run_release(self, tag, list_path=None):
        return subprocess.run(
            [sys.executable, str(SCRIPT), tag, "--repo", self.repo, "--out", self.out,
             "--list", list_path or self.list],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)

    def written(self):
        return sorted(os.listdir(self.out)) if os.path.isdir(self.out) else []

    def stem(self, version="0.2.0"):
        names = release.read_names(NAMES.read_text(encoding="utf-8"))
        return f"{names['ARCHIVE_NAME']}-{version}"


class BuildsTheRelease(ReleaseTestCase):

    def setUp(self):
        super().setUp()
        result = self.run_release("v0.2.0")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.archive = Path(self.out, f"{self.stem()}.tar.gz")
        with tarfile.open(self.archive) as tar:
            self.members = {m.name: m for m in tar.getmembers()}
            self.contents = {m.name: tar.extractfile(m).read()
                             for m in tar.getmembers() if m.isfile()}

    def path(self, name):
        return f"{self.stem()}/{name}"

    def test_writes_the_archive_its_checksum_and_the_notes(self):
        self.assertEqual(self.written(), sorted([
            f"{self.stem()}.tar.gz", f"{self.stem()}.tar.gz.sha256",
            f"{self.stem()}-notes.md", "install.sh", self.launcher_name()]))

    def launcher_name(self):
        return release.launcher_name(release.read_names(NAMES.read_text(encoding="utf-8")))

    def test_the_one_file_installer_is_a_desktop_launcher(self):
        # The one-file install work: one desktop entry, its Exec line running
        # the tagged program held in its comment lines, names written in.
        text = Path(self.out, self.launcher_name()).read_text(encoding="utf-8")
        names = release.read_names(NAMES.read_text(encoding="utf-8"))
        lines = text.splitlines()
        self.assertEqual(lines[0], "[Desktop Entry]")
        self.assertIn(f"Name=Install {names['APP_NAME']}", lines)
        self.assertIn("Type=Application", lines)
        execs = [line for line in lines if line.startswith("Exec=")]
        self.assertEqual(len(execs), 1)
        self.assertTrue(execs[0].endswith('" %k'))
        # Every line after the header is a comment, so the entry stays valid.
        body = lines[lines.index(""):]
        self.assertTrue(all(not line or line.startswith("#") for line in body))
        marker = body.index("## --- one-file installer ---")
        program = "\n".join(line[2:] for line in body[marker + 1:])
        for key in release.NAME_KEYS:
            self.assertIn(f'{key}="{names[key]}"', program)
        # Apart from the names, exactly the tagged program.
        def without_names(code):
            return re.sub(r"# --- names ---\n.*?# --- end names ---\n", "", code, flags=re.S)
        self.assertEqual(without_names(program + "\n"),
                         without_names(ONE_FILE.read_text(encoding="utf-8")))

    def test_the_launcher_starts_and_asks_before_going_online(self):
        launcher = Path(self.out, self.launcher_name())
        command = next(line for line in launcher.read_text(encoding="utf-8").splitlines()
                       if line.startswith("Exec="))[len("Exec="):]
        argv = shlex.split(command.replace("%k", shlex.quote(str(launcher))))
        home = Path(self.tmp, "home")
        home.mkdir()
        result = subprocess.run(argv, input="n\n\n", capture_output=True, text=True,
                                timeout=60, env={"HOME": str(home), "PATH": os.environ["PATH"],
                                                 "KETTLE_VIDEO_IN_TERMINAL": "1"})
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.assertIn("asks GitHub for the latest release", result.stdout)
        self.assertEqual(list(home.iterdir()), [])
        if shutil.which("desktop-file-validate"):
            checked = subprocess.run(["desktop-file-validate", str(launcher)],
                                     capture_output=True, text=True)
            self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)

    def test_install_sh_stands_on_its_own_next_to_the_archive(self):
        # The installer work: the names are written into the script, so it needs no
        # names.env beside it, and it stays runnable.
        script = Path(self.out, "install.sh")
        self.assertTrue(os.stat(script).st_mode & 0o100)
        text = script.read_text(encoding="utf-8")
        names = release.read_names(NAMES.read_text(encoding="utf-8"))
        for key in release.NAME_KEYS:
            self.assertIn(f'{key}="{names[key]}"', text)
        self.assertEqual(text.count(release.NAMES_START), 1)
        self.assertEqual(text.count(release.NAMES_END), 1)
        shell = subprocess.run(
            ["bash", "-c", 'eval "$(sed -n "/^# --- names ---$/,/^# --- end names ---$/p" "$1")"; '
             'printf "%s|%s" "$APP_ID" "$INSTALL_MARK"', "-", str(script)],
            capture_output=True, text=True, cwd=self.tmp)
        self.assertEqual(shell.stdout, f"{names['APP_ID']}|{names['INSTALL_MARK']}")

    def test_install_sh_carries_the_update_step(self):
        # The installer's update step: update.py is written in whole, exactly as tagged.
        text = Path(self.out, "install.sh").read_text(encoding="utf-8")
        self.assertEqual(text.count(release.UPDATE_START), 1)
        self.assertEqual(text.count(release.UPDATE_END), 1)
        shell = subprocess.run(
            ["bash", "-c", 'eval "$(sed -n "/^# --- update logic ---$/,/^# --- end update logic ---$/p" "$1")"; '
             'printf "%s" "$UPDATER_CODE"', "-", str(Path(self.out, "install.sh"))],
            capture_output=True, text=True, cwd=self.tmp)
        self.assertEqual(shell.stdout, UPDATER.read_text(encoding="utf-8"))
        self.assertIn(self.path("installer/update.py"), self.members)

    def test_the_archive_holds_the_licence_files(self):
        for name in ("LICENSE", "THIRD_PARTY_LICENSES.md", "vendor/thing.LICENSE",
                     "vendor/enamel/LICENSE"):
            self.assertIn(self.path(name), self.members, name)

    def test_the_archive_holds_the_app(self):
        for name in ("backend/app.py", "ui/index.html", "vendor/enamel/tokens.css",
                     "installer/names.env", "launch.sh", "VERSION", "CHANGELOG.md",
                     "README.md", "settings.example.json"):
            self.assertIn(self.path(name), self.members, name)

    def test_everything_is_inside_one_folder_named_from_names_env(self):
        for name in self.members:
            self.assertTrue(name.startswith(f"{self.stem()}/"), name)

    def test_nothing_from_the_device_or_development_ships(self):
        for name in self.members:
            inner = name.split("/", 1)[1]
            self.assertNotEqual(inner, "settings.json")
            for folder in ("data/", "logs/", "tests/", "spikes/", "docs/", "tools/",
                           "scripts/", ".claude/"):
                self.assertFalse(inner.startswith(folder), name)
            self.assertNotEqual(inner, "CLAUDE.md")

    def test_built_from_the_tag_never_the_working_folder(self):
        self.assertNotIn(self.path("backend/untracked.py"), self.members)
        self.assertEqual(self.contents[self.path("backend/app.py")], b"print('tagged')\n")

    def test_keeps_the_launcher_runnable(self):
        self.assertTrue(self.members[self.path("launch.sh")].mode & 0o100)

    def test_the_checksum_matches(self):
        line = Path(self.out, f"{self.stem()}.tar.gz.sha256").read_text(encoding="utf-8")
        digest = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        self.assertEqual(line, f"{digest}  {self.archive.name}\n")
        if shutil.which("sha256sum"):
            check = subprocess.run(["sha256sum", "-c", f"{self.archive.name}.sha256"],
                                   cwd=self.out, capture_output=True, text=True)
            self.assertEqual(check.returncode, 0, check.stdout + check.stderr)

    def test_the_notes_are_the_changelog_entry(self):
        notes = Path(self.out, f"{self.stem()}-notes.md").read_text(encoding="utf-8")
        self.assertIn("- Plover mode for the Brindle screen.", notes)
        self.assertIn("0.2.0", notes.splitlines()[0])
        self.assertNotIn("first invented release", notes)

    def test_the_same_tag_gives_the_same_archive(self):
        first = self.archive.read_bytes()
        shutil.rmtree(self.out)
        self.assertEqual(self.run_release("v0.2.0").returncode, 0)
        self.assertEqual(self.archive.read_bytes(), first)


class StopsPlainly(ReleaseTestCase):

    def assert_stops(self, result, *words):
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("Release stopped", result.stdout)
        self.assertNotIn("Traceback", result.stdout + result.stderr)
        for word in words:
            self.assertIn(word, result.stdout)
        self.assertEqual(self.written(), [])

    def test_a_missing_tag(self):
        self.assert_stops(self.run_release("v0.9.0"), "no tag called v0.9.0")

    def test_a_tag_that_does_not_match_version(self):
        git(self.repo, "tag", "v0.0.1-skeleton")
        self.assert_stops(self.run_release("v0.0.1-skeleton"), "VERSION says 0.2.0", "v0.2.0")

    def test_a_missing_changelog_entry(self):
        self.write("VERSION", "0.3.0\n")
        self.commit_and_tag("v0.3.0")
        self.assert_stops(self.run_release("v0.3.0"), "no entry for 0.3.0", "## 0.3.0")

    def test_a_missing_changelog(self):
        git(self.repo, "rm", "-q", "CHANGELOG.md")
        self.write("VERSION", "0.3.0\n")
        self.commit_and_tag("v0.3.0")
        self.assert_stops(self.run_release("v0.3.0"), "no CHANGELOG.md")

    def test_a_missing_installer(self):
        # The installer work: the installer always ships next to the archive.
        git(self.repo, "rm", "-q", "installer/install.sh")
        self.write("VERSION", "0.3.0\n")
        self.write("CHANGELOG.md", "## 0.3.0\n\n- Invented.\n\n" + CHANGELOG)
        self.commit_and_tag("v0.3.0")
        self.assert_stops(self.run_release("v0.3.0"), "installer/install.sh")

    def test_a_missing_one_file_installer(self):
        # The one-file install work: every release gets the one-file installer.
        git(self.repo, "rm", "-q", "installer/one_file_install.py")
        self.write("VERSION", "0.3.0\n")
        self.write("CHANGELOG.md", "## 0.3.0\n\n- Invented.\n\n" + CHANGELOG)
        self.commit_and_tag("v0.3.0")
        self.assert_stops(self.run_release("v0.3.0"), "installer/one_file_install.py")

    def test_a_one_file_installer_without_its_names_block(self):
        text = ONE_FILE.read_text(encoding="utf-8").replace("# --- end names ---\n", "")
        self.write("installer/one_file_install.py", text)
        self.write("VERSION", "0.3.0\n")
        self.write("CHANGELOG.md", "## 0.3.0\n\n- Invented.\n\n" + CHANGELOG)
        self.commit_and_tag("v0.3.0")
        self.assert_stops(self.run_release("v0.3.0"), "installer/one_file_install.py")

    def test_a_missing_update_step(self):
        # The installer's update step: install.sh carries the shared update step with it.
        git(self.repo, "rm", "-q", "installer/update.py")
        self.write("VERSION", "0.3.0\n")
        self.write("CHANGELOG.md", "## 0.3.0\n\n- Invented.\n\n" + CHANGELOG)
        self.commit_and_tag("v0.3.0")
        self.assert_stops(self.run_release("v0.3.0"), "installer/update.py")

    def test_an_update_step_that_cannot_be_written_in(self):
        # A line that would end the written-in text early is refused.
        self.write("installer/update.py", UPDATER.read_text(encoding="utf-8")
                   + f"\n{release.UPDATE_DELIMITER}\n")
        self.write("VERSION", "0.3.0\n")
        self.write("CHANGELOG.md", "## 0.3.0\n\n- Invented.\n\n" + CHANGELOG)
        self.commit_and_tag("v0.3.0")
        self.assert_stops(self.run_release("v0.3.0"), "installer/install.sh")

    def test_a_names_env_missing_a_name(self):
        # The installer review fixes: every name in NAME_KEYS is required.
        text = NAMES.read_text(encoding="utf-8")
        self.write("installer/names.env", "\n".join(
            line for line in text.splitlines() if not line.startswith("FIREFOX_PROFILE=")) + "\n")
        self.write("VERSION", "0.3.0\n")
        self.write("CHANGELOG.md", "## 0.3.0\n\n- Invented.\n\n" + CHANGELOG)
        self.commit_and_tag("v0.3.0")
        self.assert_stops(self.run_release("v0.3.0"), "missing FIREFOX_PROFILE")

    def test_a_missing_licence_file(self):
        git(self.repo, "rm", "-q", "THIRD_PARTY_LICENSES.md")
        self.commit_and_tag("v0.2.0-again")
        git(self.repo, "tag", "-d", "v0.2.0")
        git(self.repo, "tag", "v0.2.0", "v0.2.0-again")
        self.assert_stops(self.run_release("v0.2.0"), "THIRD_PARTY_LICENSES.md")

    def test_a_private_word_in_the_archive(self):
        self.write("backend/app.py", "# watched Quillmoor Abbey\n")
        self.commit_and_tag("v0.2.0-again")
        git(self.repo, "tag", "-d", "v0.2.0")
        git(self.repo, "tag", "v0.2.0", "v0.2.0-again")
        result = self.run_release("v0.2.0")
        self.assert_stops(result, "backend/app.py", "films and shows")
        self.assertNotIn("quillmoor", result.stdout.casefold())

    def test_a_private_word_where_a_shortcut_points(self):
        os.symlink("../Quillmoor Abbey/film.mkv", os.path.join(self.repo, "ui/poster.mkv"))
        self.commit_and_tag("v0.2.0-again")
        git(self.repo, "tag", "-d", "v0.2.0")
        git(self.repo, "tag", "v0.2.0", "v0.2.0-again")
        result = self.run_release("v0.2.0")
        self.assert_stops(result, "ui/poster.mkv", "films and shows")
        self.assertNotIn("quillmoor", result.stdout.casefold())

    def test_a_clean_shortcut_ships_as_a_shortcut(self):
        os.symlink("index.html", os.path.join(self.repo, "ui/start.html"))
        self.commit_and_tag("v0.2.0-again")
        git(self.repo, "tag", "-d", "v0.2.0")
        git(self.repo, "tag", "v0.2.0", "v0.2.0-again")
        self.assertEqual(self.run_release("v0.2.0").returncode, 0)
        with tarfile.open(Path(self.out, f"{self.stem()}.tar.gz")) as tar:
            member = tar.getmember(f"{self.stem()}/ui/start.html")
        self.assertTrue(member.issym())
        self.assertEqual(member.linkname, "index.html")

    def test_a_missing_word_list(self):
        self.assert_stops(self.run_release("v0.2.0", os.path.join(self.tmp, "none.txt")),
                          "word list is missing")

    # The release check work: the whole release check runs on what the release publishes,
    # not only the privacy guard. Built from parts so this file passes it.
    UNKNOWN_TITLE = "Zorb" + "lax Returns"
    OTHER_NOREPLY = "1234+someone" + "@users.noreply.github.com"

    def retag(self):
        self.commit_and_tag("v0.2.0-again")
        git(self.repo, "tag", "-d", "v0.2.0")
        git(self.repo, "tag", "v0.2.0", "v0.2.0-again")

    def test_a_title_not_on_the_invented_list_in_the_archive(self):
        self.write("backend/app.py", f"# plays {self.UNKNOWN_TITLE} (1999).m" + "kv\n")
        self.retag()
        result = self.run_release("v0.2.0")
        self.assert_stops(result, "backend/app.py", "a title not on the invented list")
        self.assertNotIn("zorb", result.stdout.casefold())

    def test_another_noreply_address_in_the_notes(self):
        self.write("CHANGELOG.md", CHANGELOG.replace(
            "- Plover mode for the Brindle screen.",
            f"- Plover mode, thanks to {self.OTHER_NOREPLY}."))
        self.retag()
        result = self.run_release("v0.2.0")
        self.assert_stops(result, "release notes",
                          "an email address other than the noreply address")
        self.assertNotIn("someone", result.stdout)

    def test_another_noreply_address_in_install_sh(self):
        self.write("installer/install.sh", INSTALLER.read_text(encoding="utf-8")
                   + f"\n# Questions: {self.OTHER_NOREPLY}\n")
        self.retag()
        result = self.run_release("v0.2.0")
        self.assert_stops(result, "install.sh",
                          "an email address other than the noreply address")
        self.assertNotIn("someone", result.stdout)


class OnePlaceForNames(unittest.TestCase):

    def test_names_env_holds_every_installer_name(self):
        names = release.read_names(NAMES.read_text(encoding="utf-8"))
        for key in release.NAME_KEYS:
            self.assertTrue(names.get(key), key)

    def test_one_reader_for_names_env(self):
        # The installer review fixes: the release reads names.env with the app's own reader.
        from backend import app_paths
        self.assertIs(release.read_names, app_paths.read_names)
        self.assertNotIn("def read_names", SCRIPT.read_text(encoding="utf-8"))

    def test_a_shell_reads_the_same_names(self):
        names = release.read_names(NAMES.read_text(encoding="utf-8"))
        shell = subprocess.run(
            ["bash", "-c", 'source "$1"; printf "%s\\n" "$APP_NAME" "$ARCHIVE_NAME"', "_",
             str(NAMES)], capture_output=True, text=True, check=True)
        self.assertEqual(shell.stdout.splitlines(), [names["APP_NAME"], names["ARCHIVE_NAME"]])

    def test_the_current_version_has_a_changelog_entry(self):
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertTrue(release.changelog_entry(changelog, version))

    def test_the_output_folder_is_ignored_by_git(self):
        result = git(ROOT, "check-ignore", "-q", "dist/x.tar.gz", check=False)
        self.assertEqual(result.returncode, 0)


class ChangelogEntry(unittest.TestCase):

    def test_takes_only_its_own_entry(self):
        self.assertEqual(release.changelog_entry(CHANGELOG, "0.1.0"),
                         "- The first invented release.\n")

    def test_accepts_bracketed_and_dated_headings(self):
        text = "## [1.0.0] - 2026-01-01\n\nNotes.\n\n## 0.9.0\n\nOld.\n"
        self.assertEqual(release.changelog_entry(text, "1.0.0"), "Notes.\n")

    def test_a_version_is_not_matched_by_its_start(self):
        self.assertIsNone(release.changelog_entry("## 0.2.0-dev\n\nx\n", "0.2.0"))


if __name__ == "__main__":
    unittest.main()
