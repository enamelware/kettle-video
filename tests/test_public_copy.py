# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The clean public copy (the clean copy work): tools/public_copy.py builds
a copy with no history from the tracked files at one commit only, in a new
folder, as one commit by Enamelware with the noreply address and no remote;
it refuses a folder that already exists and leaves it untouched, and it runs
the release check on the copy, with commit addresses looked up in the repo
it was copied from.

Only temporary git repos and a temporary list of invented words; the real
list is never read.

Run: scripts/test.sh unit tests.test_public_copy
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "tools" / "public_copy.py"
sys.path.insert(0, str(ROOT / "tools"))
import public_copy  # noqa: E402
import release_check  # noqa: E402

# Invented "private" words, standing in for the real list.
WORDS = """# invented words only
[card labels]
ZEPHYRCARD

[device names]
plover-handheld
"""
PRIVATE = "ZEPHYR" + "CARD"
NOREPLY = "335260252+enamelware@users.noreply.github.com"


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True,
                          check=True).stdout


class PublicCopyCase(unittest.TestCase):
    """A temporary source repo with tracked, untracked, ignored and changed
    files, and the invented word list."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.list = self.tmp / "words.txt"
        self.list.write_text(WORDS, encoding="utf-8")
        self.repo = self.tmp / "source"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.name", "Test")
        git(self.repo, "config", "user.email", "test@example.invalid")
        git(self.repo, "config", "commit.gpgsign", "false")
        self.write(release_check.INVENTED_TITLES, "# invented\nExample Movie\n")
        self.write("README.md", "# An invented app\n\nFirst words.\n")
        self.write(".gitignore", "settings.json\ndata/\n")
        self.write("run.sh", "#!/bin/sh\necho hello\n")
        (self.repo / "run.sh").chmod(0o755)
        self.write("docs/notes.md", "Notes.\n")
        os.symlink("docs/notes.md", self.repo / "notes-link.md")
        self.commit("start")
        self.first = git(self.repo, "rev-parse", "HEAD").strip()
        self.write("docs/more.md", "More notes.\n")
        self.commit("more")
        # What only lives on this machine: never in the copy.
        self.write("settings.json", '{"movies": "/somewhere"}\n')
        self.write("data/library.json", "{}\n")
        self.write("scratch.txt", "untracked\n")
        self.write("README.md", "# An invented app\n\nChanged, not committed.\n")
        self.write("staged.md", "staged, not committed\n")
        git(self.repo, "add", "staged.md")
        self.out = self.tmp / "copy"

    def write(self, path, text):
        full = self.repo / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(text, encoding="utf-8")

    def commit(self, message):
        git(self.repo, "add", "--all")
        git(self.repo, "commit", "-q", "-m", message)

    def build(self, **kwargs):
        kwargs.setdefault("repo", self.repo)
        kwargs.setdefault("list_path", self.list)
        return public_copy.build(self.out, **kwargs)

    def copied(self):
        return set(git(self.out, "ls-files").split())

    def run_script(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args, "--repo", str(self.repo),
                               "--list", str(self.list)],
                              capture_output=True, text=True, timeout=120)


class TrackedFilesOnly(PublicCopyCase):

    def test_the_copy_holds_exactly_the_committed_tracked_files(self):
        self.assertEqual(self.build(), [])
        tracked = set(git(self.repo, "ls-tree", "-r", "--name-only", "HEAD").split())
        self.assertEqual(self.copied(), tracked)
        on_disk = {str(p.relative_to(self.out)) for p in self.out.rglob("*")
                   if (p.is_file() or p.is_symlink()) and ".git" not in p.relative_to(self.out).parts}
        self.assertEqual(on_disk, tracked)

    def test_nothing_untracked_ignored_staged_or_changed_gets_in(self):
        self.build()
        for path in ("settings.json", "data", "scratch.txt", "staged.md"):
            with self.subTest(path=path):
                self.assertFalse((self.out / path).exists())
        self.assertIn("First words.", (self.out / "README.md").read_text(encoding="utf-8"))
        self.assertNotIn("not committed", (self.out / "README.md").read_text(encoding="utf-8"))

    def test_modes_and_shortcuts_are_kept(self):
        self.build()
        self.assertTrue(os.access(self.out / "run.sh", os.X_OK))
        self.assertFalse(os.access(self.out / "README.md", os.X_OK))
        self.assertTrue((self.out / "notes-link.md").is_symlink())
        self.assertEqual(os.readlink(self.out / "notes-link.md"), "docs/notes.md")

    def test_ref_copies_an_earlier_commit(self):
        self.build(ref=self.first)
        self.assertNotIn("docs/more.md", self.copied())
        self.assertIn("docs/notes.md", self.copied())

    def test_an_unknown_ref_builds_nothing(self):
        with self.assertRaises(public_copy.CopyProblem):
            self.build(ref="no-such-ref")
        self.assertFalse(self.out.exists())


class NoHistoryAndTheIdentity(PublicCopyCase):

    def test_one_commit_by_enamelware_with_the_noreply_address(self):
        self.build()
        log = git(self.out, "log", "--format=%an|%ae|%cn|%ce").splitlines()
        self.assertEqual(log, [f"Enamelware|{NOREPLY}|Enamelware|{NOREPLY}"])

    def test_later_commits_in_the_copy_use_the_same_identity(self):
        self.build()
        self.assertEqual(git(self.out, "config", "--local", "user.name").strip(), "Enamelware")
        self.assertEqual(git(self.out, "config", "--local", "user.email").strip(), NOREPLY)

    def test_no_commit_of_the_source_is_in_the_copy(self):
        self.build()
        for commit in (self.first, git(self.repo, "rev-parse", "HEAD").strip()):
            with self.subTest(commit=commit):
                found = subprocess.run(["git", "cat-file", "-e", f"{commit}^{{commit}}"],
                                       cwd=self.out, capture_output=True)
                self.assertNotEqual(found.returncode, 0)

    def test_no_remote_and_nothing_pushed(self):
        self.build()
        self.assertEqual(git(self.out, "remote").strip(), "")


class RefusesWhatIsThere(PublicCopyCase):

    def test_an_existing_folder_is_left_untouched(self):
        self.out.mkdir()
        (self.out / "keep.txt").write_text("mine\n", encoding="utf-8")
        with self.assertRaises(public_copy.CopyProblem) as caught:
            self.build()
        self.assertIn("already exists", str(caught.exception))
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), ["keep.txt"])
        self.assertEqual((self.out / "keep.txt").read_text(encoding="utf-8"), "mine\n")

    def test_an_empty_existing_folder_is_refused_too(self):
        self.out.mkdir()
        with self.assertRaises(public_copy.CopyProblem):
            self.build()
        self.assertEqual(list(self.out.iterdir()), [])

    def test_an_existing_file_is_refused(self):
        self.out.write_text("a file\n", encoding="utf-8")
        with self.assertRaises(public_copy.CopyProblem):
            self.build()
        self.assertEqual(self.out.read_text(encoding="utf-8"), "a file\n")

    def test_a_missing_parent_folder_is_refused(self):
        self.out = self.tmp / "not-there" / "copy"
        with self.assertRaises(public_copy.CopyProblem):
            self.build()
        self.assertFalse((self.tmp / "not-there").exists())

    def test_a_missing_word_list_builds_nothing(self):
        with self.assertRaises(public_copy.CopyProblem):
            self.build(list_path=self.tmp / "no-list.txt")
        self.assertFalse(self.out.exists())


class RunsTheReleaseCheck(PublicCopyCase):

    def test_a_clean_copy_passes(self):
        result = self.run_script(str(self.out))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("the copy is clean", result.stdout)
        self.assertIn("Nothing was published", result.stdout)

    def test_a_private_word_in_a_tracked_file_is_found(self):
        self.write("docs/notes.md", f"From {PRIVATE}.\n")
        self.commit("leak")
        result = self.run_script(str(self.out))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("RELEASE: docs/notes.md, line 1:", result.stdout)
        self.assertIn("must not go public", result.stdout)
        self.assertNotIn(PRIVATE, result.stdout)

    def test_a_commit_address_of_the_source_is_found(self):
        self.write("docs/notes.md", f"See {self.first[:10]}.\n")
        self.commit("address")
        findings = self.build()
        self.assertIn("docs/notes.md, line 1: a commit address", findings)

    def test_an_existing_folder_exits_2_and_says_so(self):
        self.out.mkdir()
        result = self.run_script(str(self.out))
        self.assertEqual(result.returncode, 2)
        self.assertIn("already exists", result.stdout)


if __name__ == "__main__":
    unittest.main()
