# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The privacy guard (the privacy guard work): it catches a private word in a staged file,
a commit message and a pushed commit, catches full home folder paths, Steam
IDs and stray pictures, passes invented names, never prints the word it
found, and fails when the list is missing or empty. The setup script puts
it in front of every commit and push, the quick and full checks run it, and
the storage spike's checker uses it.

Only ever uses a temporary list of invented words and temporary git repos;
the real list is never read.

Run: scripts/test.sh unit tests.test_privacy_guard
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
GUARD = ROOT / "tools" / "privacy_guard.py"
sys.path.insert(0, str(ROOT / "tools"))
import install_privacy_hooks  # noqa: E402
import privacy_guard  # noqa: E402

INVENTED = """# invented words only
[card labels]
ZEPHYRCARD

[films and shows]
Quillmoor Abbey
Brackenfold

[device names]
plover-handheld
"""


def git(repo, *args, env=None, check=True):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True,
                          env=env, check=check)


class GuardTestCase(unittest.TestCase):
    """A temporary git repo and a temporary list of invented words."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.list = os.path.join(self.tmp, "words.txt")
        Path(self.list).write_text(INVENTED, encoding="utf-8")
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(self.repo)
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.name", "Test")
        git(self.repo, "config", "user.email", "test@example.invalid")
        git(self.repo, "config", "commit.gpgsign", "false")

    def write(self, path, text):
        full = Path(self.repo, path)
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(text, encoding="utf-8")

    def guard(self, *args, list_path=None, stdin=""):
        return subprocess.run(
            [sys.executable, str(GUARD), *args, "--list", list_path or self.list],
            cwd=self.repo, capture_output=True, text=True, input=stdin, timeout=30)


class StagedAndMessage(GuardTestCase):

    def test_catches_a_planted_word_in_a_staged_file(self):
        self.write("notes.md", "line one\nWe watched quillmoor abbey last night\n")
        git(self.repo, "add", "notes.md")
        result = self.guard("staged")
        self.assertEqual(result.returncode, 1)
        self.assertIn("notes.md (staged), line 2", result.stdout)
        self.assertIn("films and shows", result.stdout)

    def test_never_prints_the_word_it_found(self):
        self.write("notes.md", "Brackenfold and ZEPHYRCARD\n")
        git(self.repo, "add", "notes.md")
        out = self.guard("staged").stdout.casefold()
        for word in ("brackenfold", "zephyrcard"):
            self.assertNotIn(word, out)

    def test_catches_a_word_in_a_file_name(self):
        self.write("Brackenfold-notes.txt", "nothing here\n")
        git(self.repo, "add", ".")
        result = self.guard("staged")
        self.assertEqual(result.returncode, 1)
        self.assertIn("in the file's name", result.stdout)

    def test_catches_a_planted_word_in_a_commit_message(self):
        message = os.path.join(self.tmp, "MSG")
        Path(message).write_text("Fix the plover-handheld layout\n", encoding="utf-8")
        result = self.guard("message", message)
        self.assertEqual(result.returncode, 1)
        self.assertIn("commit message, line 1: private word (device names)", result.stdout)

    def test_comment_lines_of_a_commit_message_are_ignored(self):
        message = os.path.join(self.tmp, "MSG")
        Path(message).write_text("Tidy the list\n# On branch Brackenfold\n", encoding="utf-8")
        self.assertEqual(self.guard("message", message).returncode, 0)

    def test_invented_names_pass(self):
        self.write("tests/sample.py", 'NAMES = ["Ostrava Nights", "Heron Lake (2001)"]\n'
                                      'PATH = "/run/media/<user>/<card-1>/Films"\n'
                                      'HOME = "~/Videos"\n')
        git(self.repo, "add", ".")
        result = self.guard("staged")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("clean", result.stdout)

    def test_whole_words_only(self):
        # "Brackenfolds" or "ZEPHYRCARDS" are other words, not the private ones.
        self.write("a.md", "Brackenfoldsome and ZEPHYRCARDS\n")
        git(self.repo, "add", ".")
        self.assertEqual(self.guard("staged").returncode, 0)


class PatternsWithoutTheList(unittest.TestCase):
    """The checks that need no list."""

    def kinds(self, text, path="notes.md"):
        matcher = privacy_guard.Matcher({"films and shows": ["Brackenfold"]})
        return [kind for _, kind in privacy_guard.line_findings(text, matcher, path)]

    # Built from pieces so this file passes the guard itself.
    NAME = "some" + "person"

    def test_full_home_folder_paths_are_caught(self):
        for text in (f"/home/{self.NAME}/Videos", f"see /var/home/{self.NAME}/x",
                     f"`/run/media/{self.NAME}/CARD`", f"/Users/{self.NAME}/Movies"):
            self.assertEqual(self.kinds(text),
                             ["home folder written out in full (use ~/ or <user>)"], text)

    def test_placeholders_and_other_paths_pass(self):
        for text in ("/home/<user>/Videos", "/run/media/<card label>/Films",
                     'f"/home/{user}"', "/var/home/$USER", "~/Videos",
                     "/somewhere/home/Videos", "Read(//run/media/**)",
                     "under /run/media/, /media/ or /mnt/"):
            self.assertEqual(self.kinds(text), [], text)

    def test_steam_folders_and_ids_are_caught(self):
        steam_id = str(privacy_guard.STEAM_ID64_BASE + 123456)
        for text in ("userdata/" + "1234567/config", f"id {steam_id}"):
            self.assertEqual(self.kinds(text), ["Steam user folder or Steam ID"], text)

    def test_emails_other_than_noreply_are_caught(self):
        self.assertEqual(self.kinds("mail someone" + "@mailbox.example.io"), ["email address"])
        for text in ("1+name" + "@users.noreply.github.com", "git@github.com:owner/repo",
                     "a@example.invalid", "Co-Authored-By: Claude <noreply@anthropic.com>"):
            self.assertEqual(self.kinds(text), [], text)

    def test_third_party_files_are_checked_against_the_list_only(self):
        line = f"author{'@'}mailbox.example.io /home/{self.NAME}"
        self.assertEqual(self.kinds(line, "vendor/x/a.py"), [])
        self.assertEqual(self.kinds("Brackenfold", "vendor/x/a.py"), ["private word (films and shows)"])

    def test_pictures_and_logs_outside_approved_folders(self):
        matcher = privacy_guard.Matcher({})
        self.assertEqual(privacy_guard.path_findings("docs/shot.png", matcher),
                         ["picture outside the approved folders"])
        self.assertEqual(privacy_guard.path_findings("ui/icon.png", matcher), [])
        self.assertEqual(privacy_guard.path_findings("logs/run.log", matcher), ["log file"])
        # Only new files: a picture already tracked is not reported again on a change.
        self.assertEqual(privacy_guard.path_findings("docs/shot.png", matcher, added=False), [])

    def test_the_screenshots_folder_is_approved_and_nothing_beside_it(self):
        # The README's screenshots change often, so the folder is approved (the
        # v1.0.0 release work); a folder of the repo, never a device's path.
        matcher = privacy_guard.Matcher({})
        for path in ("docs/screenshots/home.png", "docs/screenshots/design-system/x-w320.png"):
            with self.subTest(path=path):
                self.assertEqual(privacy_guard.path_findings(path, matcher), [])
        for path in ("docs/screenshots.png", "docs/screenshots-old/home.png", "docs/spikes/shot.png",
                     "screenshots/home.png"):
            with self.subTest(path=path):
                self.assertEqual(privacy_guard.path_findings(path, matcher),
                                 ["picture outside the approved folders"])
        for folder in privacy_guard.APPROVED_PICTURE_FOLDERS:
            with self.subTest(folder=folder):
                self.assertFalse(folder.startswith(("/", "~")), "approved folders are repo folders")
                self.assertTrue(folder.endswith("/"))


class MissingOrEmptyList(GuardTestCase):

    def test_fails_when_the_list_is_missing(self):
        self.write("a.md", "fine\n")
        git(self.repo, "add", ".")
        result = self.guard("staged", list_path=os.path.join(self.tmp, "nowhere.txt"))
        self.assertEqual(result.returncode, 2)
        self.assertIn("FAILED", result.stdout)
        self.assertIn("missing", result.stdout)

    def test_fails_when_the_list_is_empty(self):
        empty = os.path.join(self.tmp, "empty.txt")
        Path(empty).write_text("# only notes\n[films and shows]\n\n", encoding="utf-8")
        result = self.guard("tracked", list_path=empty)
        self.assertEqual(result.returncode, 2)
        self.assertIn("empty", result.stdout)

    def test_a_name_in_brackets_is_a_word_not_a_category(self):
        # Never printed as the "kind" of a finding, as a category would be.
        listed = os.path.join(self.tmp, "brackets.txt")
        Path(listed).write_text("[films and shows]\n[Grebe] Halloway Pond [720p]\nQuillmoor Abbey\n",
                                encoding="utf-8")
        found = privacy_guard.read_list(listed)
        self.assertEqual(found, {"films and shows": ["[Grebe] Halloway Pond [720p]", "Quillmoor Abbey"]})
        self.write("a.md", "Quillmoor Abbey and [Grebe] Halloway Pond [720p]\n")
        git(self.repo, "add", ".")
        result = self.guard("staged", list_path=listed)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("halloway", result.stdout.casefold())
        self.assertIn("private word (films and shows)", result.stdout)

    def test_count_gives_numbers_only(self):
        result = self.guard("count")
        self.assertEqual(result.returncode, 0)
        self.assertIn("films and shows 2", result.stdout)
        self.assertNotIn("Brackenfold", result.stdout)


class Push(GuardTestCase):

    def test_catches_a_word_in_a_commit_about_to_be_pushed(self):
        self.write("a.md", "fine\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-q", "-m", "First")
        self.write("a.md", "fine\nQuillmoor Abbey\n")
        git(self.repo, "commit", "-q", "-am", "Second")
        head = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        line = f"refs/heads/main {head} refs/heads/main {'0' * 40}\n"
        result = self.guard("push", stdin=line)
        self.assertEqual(result.returncode, 1)
        self.assertIn("changes, line 1: private word (films and shows)", result.stdout)

    def test_a_clean_push_passes(self):
        self.write("a.md", "fine\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-q", "-m", "First")
        head = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        line = f"refs/heads/main {head} refs/heads/main {'0' * 40}\n"
        self.assertEqual(self.guard("push", stdin=line).returncode, 0)


class Hooks(GuardTestCase):
    """The setup script puts the guard in front of every commit and push."""

    def setUp(self):
        super().setUp()
        tools = Path(self.repo, "tools")
        tools.mkdir()
        shutil.copy(GUARD, tools / "privacy_guard.py")
        # The hooks read the list from its usual place under the home folder,
        # so the test points the home folder at its own temporary one.
        home = Path(self.tmp, "home")
        (home / "Development" / ".privacy-guard").mkdir(parents=True)
        shutil.copy(self.list, home / "Development" / ".privacy-guard" / "words.txt")
        self.env = dict(os.environ, HOME=str(home))
        self.env.pop("GIT_DIR", None)
        self.env.pop("GIT_INDEX_FILE", None)

    def test_installs_the_three_hooks(self):
        self.assertEqual(install_privacy_hooks.install(self.repo),
                         {"pre-commit": "written", "commit-msg": "written", "pre-push": "written"})
        self.assertEqual(install_privacy_hooks.install(self.repo),
                         {"pre-commit": "unchanged", "commit-msg": "unchanged", "pre-push": "unchanged"})
        for name in ("pre-commit", "commit-msg", "pre-push"):
            self.assertTrue(os.access(Path(self.repo, ".git", "hooks", name), os.X_OK))

    def test_keeps_a_hook_it_did_not_write(self):
        hook = Path(self.repo, ".git", "hooks", "pre-commit")
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        self.assertEqual(install_privacy_hooks.install(self.repo)["pre-commit"], "kept (not ours)")
        self.assertEqual(hook.read_text(encoding="utf-8"), "#!/bin/sh\nexit 0\n")

    def test_a_commit_with_a_private_word_is_stopped(self):
        install_privacy_hooks.install(self.repo)
        self.write("a.md", "Brackenfold\n")
        git(self.repo, "add", "a.md", env=self.env)
        result = git(self.repo, "commit", "-m", "Notes", env=self.env, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Privacy guard", result.stdout + result.stderr)
        self.assertEqual(git(self.repo, "rev-list", "--all", env=self.env).stdout, "")

    def test_a_private_word_in_the_message_is_stopped(self):
        install_privacy_hooks.install(self.repo)
        self.write("a.md", "fine\n")
        git(self.repo, "add", "a.md", env=self.env)
        result = git(self.repo, "commit", "-m", "Notes on ZEPHYRCARD", env=self.env, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(git(self.repo, "rev-list", "--all", env=self.env).stdout, "")

    def test_a_clean_commit_goes_through(self):
        install_privacy_hooks.install(self.repo)
        self.write("a.md", "Ostrava Nights, an invented show\n")
        git(self.repo, "add", "a.md", env=self.env)
        result = git(self.repo, "commit", "-m", "Notes", env=self.env, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class Build(unittest.TestCase):
    """build writes the list from an invented card, keeps what was added by
    hand, and makes the file readable only by its owner."""

    def test_build_from_an_invented_card(self):
        from backend import folder_finder as ff
        with tempfile.TemporaryDirectory() as tmp:
            card = os.path.join(tmp, "ZEPHYRCARD")
            for rel in ("Films/Quillmoor (1999)/Quillmoor.mkv",
                        "Films/Brackenfold/Brackenfold.mp4",
                        "Films/Brackenfold/Sample/s.mkv"):
                path = os.path.join(card, rel)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as f:
                    f.truncate(ff.MIN_VIDEO_BYTES)
            words = os.path.join(tmp, "list", "words.txt")
            os.makedirs(os.path.dirname(words))
            Path(words).write_text("[added by hand]\nplover-handheld\n", encoding="utf-8")
            places = [ff.Place("internal", "Internal storage", tmp),
                      ff.Place("sd", "SD card", card)]
            nothing = {"device names": set(), "network names": set(),
                       "bluetooth names": set(), "steam ids": set()}
            with mock.patch.object(ff, "list_places", return_value=places), \
                    mock.patch.object(privacy_guard, "device_words", return_value=nothing):
                counts = privacy_guard.build(words)
            found = privacy_guard.read_list(words)
            self.assertEqual(os.stat(words).st_mode & 0o777, 0o600)
        self.assertEqual(found["card labels"], ["ZEPHYRCARD"])
        for word in ("Quillmoor (1999)", "Quillmoor", "Brackenfold"):
            self.assertIn(word, found["films and shows"])
        self.assertNotIn("Sample", found["films and shows"])
        self.assertEqual(found["added by hand"], ["plover-handheld"])
        self.assertEqual(counts["card labels"], 1)

    def test_a_library_in_the_home_folder_adds_nothing(self):
        # The sample library lives in the home folder (the sample library guard fix): its names
        # must never become private words, while a card's still do.
        from backend import folder_finder as ff
        with tempfile.TemporaryDirectory() as tmp:
            home = os.path.join(tmp, "home")
            card = os.path.join(tmp, "WREN")
            for rel in ("home/Videos/kettle-sample-library/Movies/Fernhollow (2004)/Fernhollow.mkv",
                        "home/Videos/kettle-sample-library/Movies/Glimmerwick (2006)/Glimmerwick.mkv",
                        "WREN/Films/Glimmerwick (2006)/Glimmerwick.mkv"):
                path = os.path.join(tmp, rel)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as f:
                    f.truncate(ff.MIN_VIDEO_BYTES)
            places = [{"kind": "internal", "path": home, "label": "home"},
                      {"kind": "sd", "path": card, "label": "WREN"}]

            def walk(top):
                return ff._Walk(deadline=float("inf")).walk(top)

            labels, titles = privacy_guard.card_words(
                places, walk, ff.suggest, lambda w: bool(ff.SEASON_LIKE.match(w)))
        self.assertEqual(labels, {"WREN"})
        self.assertIn("Glimmerwick", titles)
        for word in ("Fernhollow", "Fernhollow (2004)", "kettle-sample-library", "home"):
            self.assertNotIn(word, titles)


class WhereItRuns(unittest.TestCase):

    def test_quick_and_full_checks_run_the_guard(self):
        text = (ROOT / "scripts" / "test.sh").read_text(encoding="utf-8")
        self.assertIn("python3 tools/privacy_guard.py tracked", text)
        quick = text[text.index("\nquick() {"):text.index("\nfull() {")]
        full = text[text.index("\nfull() {"):text.index("\ncase ")]
        self.assertIn("privacy ||", quick)
        self.assertIn("privacy ||", full)

    def test_the_spike_checker_uses_the_guard(self):
        text = (ROOT / "spikes" / "storage" / "privacy_check.py").read_text(encoding="utf-8")
        self.assertIn("privacy_guard.card_words", text)

    def test_claude_md_has_the_rule(self):
        text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        rule = next((line for line in text.splitlines()
                     if line.startswith("- **Never commit anything from my devices")), "")
        self.assertIn("must pass before any commit or push", rule)
        self.assertIn("--no-verify", rule)
        self.assertIn("invented names only", rule)


if __name__ == "__main__":
    unittest.main(verbosity=2)
