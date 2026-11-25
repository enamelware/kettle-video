# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The release check: each kind of thing that mustn't go public
is caught with its file and line, a private title is caught scrambled,
reversed and encoded, a title not on the invented list is caught, an
invented one passes, a clean folder passes, and no finding ever repeats what
it found. The release script runs it on everything it publishes.

Only temporary git repos and a temporary list of invented words; the real
list is never read. Anything the check would flag in this file itself is
built from parts at run time.

Run: scripts/test.sh unit tests.test_release_rules
"""

import base64
import codecs
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHECK = ROOT / "tools" / "release_check.py"
sys.path.insert(0, str(ROOT / "tools"))
import release_check  # noqa: E402

# Invented "private" words, standing in for the real list.
WORDS = """# invented words only
[card labels]
ZEPHYRCARD

[films and shows]
Quillmoor Abbey

[device names]
plover-handheld
"""
PRIVATE_TITLE = "Quillmoor Abbey"
MKV = ".m" + "kv"
# A made-up title that is on no list: an "unknown" title.
UNKNOWN = "Zorb" + "lax Returns"
INVENTED_LIST = "# invented\nExample Movie\nExample Show\n"


# Every temporary repo's commits get the same date and none of this
# machine's git settings, so a commit's name is the same on every run and
# every machine. With the clock in it, a short commit name came out all
# digits now and then (about one run in 40), which the check rightly doesn't
# read as a commit address, so the commit-address tests failed at random.
GIT_ENV = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
               GIT_AUTHOR_DATE="1700000000 +0000", GIT_COMMITTER_DATE="1700000000 +0000")


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True,
                          env=GIT_ENV)


def commit_address(repo, length):
    """HEAD's name cut to length, which the check must read as a commit
    address: hex with at least one letter and one digit."""
    name = git(repo, "rev-parse", "HEAD").stdout.strip()[:length]
    assert any(c.isdigit() for c in name) and any(c.isalpha() for c in name), (
        f"set-up: the fixed test commit's name {name} has no letter or no digit; "
        "change the commit date in GIT_ENV")
    return name


class ReleaseCheckCase(unittest.TestCase):
    """A temporary repo with a clean file, the invented list, and the
    invented word list."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.list = os.path.join(self.tmp, "words.txt")
        Path(self.list).write_text(WORDS, encoding="utf-8")
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(self.repo)
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.name", "Test")
        git(self.repo, "config", "user.email", "test@example.invalid")
        git(self.repo, "config", "commit.gpgsign", "false")
        self.write(release_check.INVENTED_TITLES, INVENTED_LIST)
        self.write("README.md", "# An invented app\n\nPlays `Example Movie (2001)" + MKV + "`.\n")
        self.commit("start")

    def write(self, path, text, binary=False):
        full = Path(self.repo, path)
        full.parent.mkdir(parents=True, exist_ok=True)
        if binary:
            full.write_bytes(text)
        else:
            full.write_text(text, encoding="utf-8")

    def commit(self, message="more"):
        git(self.repo, "add", "-f", ".")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", message)

    def run_check(self, *args, list_path=None):
        return subprocess.run(
            [sys.executable, str(CHECK), *args, "--repo", self.repo, "--list", list_path or self.list],
            capture_output=True, text=True, timeout=120)

    def findings(self, path, text):
        """Writes one file at line 2, commits it and runs the check."""
        self.write(path, "first line\n" + text + "\n")
        self.commit()
        return self.run_check()

    def assert_caught(self, path, text, kind, line=2):
        result = self.findings(path, text)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        where = path if line is None else f"{path}, line {line}"
        self.assertIn(f"RELEASE: {where}: {kind}", result.stdout)
        self.assertNotIn("Traceback", result.stdout + result.stderr)
        return result


class CleanFolder(ReleaseCheckCase):

    def test_a_clean_folder_passes(self):
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Release check: the tracked files clean.", result.stdout)

    def test_allowed_addresses_and_invented_titles_pass(self):
        self.write("docs/notes.md", "\n".join([
            "Commit as " + release_check.NOREPLY + ".",
            "Co-Authored-By: Claude <noreply" + "@anthropic.com>",
            "git clone git" + "@github.com:someone/repo.git",
            "Test data: a" + "@example.invalid, b" + "@example.com",
            "Example.Show.S01E02" + MKV,
            "[grp] Example Show - 07 [480p]" + MKV,
            "example.movie.2001.1080p.BluRay.x264-GRP" + MKV,
            "Colours #a1b2c3d and a hash 0123456789abcdef0123 that is not a commit.",
        ]) + "\n")
        self.commit()
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_a_missing_list_stops_the_check(self):
        result = self.run_check(list_path=os.path.join(self.tmp, "none.txt"))
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("word list is missing", result.stdout)


class PrivacyGuardRules(ReleaseCheckCase):
    """The privacy guard's own rules, with its list, apply as they are."""

    def test_a_private_word(self):
        self.assert_caught("docs/x.md", "Labelled zephyrcard", "private word (card labels)")

    def test_a_device_name(self):
        self.assert_caught("tests/x.py", "# on plover-handheld", "private word (device names)")

    def test_a_home_folder(self):
        self.assert_caught("docs/x.md", "Kept in /home/" + "zed/Videos",
                           "home folder written out in full (use ~/ or <user>)")

    def test_a_steam_user_folder_and_a_steam_id(self):
        self.assert_caught("docs/x.md", "steam/userdata/" + "12345678/config", "Steam user folder or Steam ID")
        self.assert_caught("docs/y.md", "id " + "7656119" + "8000000001", "Steam user folder or Steam ID")

    def test_a_picture_outside_the_approved_folders(self):
        self.write("docs/shot.png", b"\x89PNG\r\n\x1a\n\0\0", binary=True)
        self.commit()
        self.assertIn("RELEASE: docs/shot.png: picture outside the approved folders",
                      self.run_check().stdout)


class ScrambledAndEncoded(ReleaseCheckCase):

    def forms(self, text):
        return {
            "written in ROT13": codecs.encode(text, "rot13"),
            "written backwards": text[::-1],
            "encoded as base64": base64.b64encode(text.encode()).decode(),
            "encoded as hex": text.encode().hex(),
            "encoded with % escapes": urllib.parse.quote(text),
            "encoded as HTML entities": "".join(f"&#{ord(c)};" for c in text),
            "encoded as \\u escapes": "".join(f"\\u{ord(c):04x}" for c in text),
        }

    def test_a_private_title_in_every_form(self):
        for how, text in self.forms(PRIVATE_TITLE).items():
            with self.subTest(how=how):
                result = self.assert_caught("tests/x.py", f"NAME = '{text}'",
                                            f"private word (films and shows) {how}")
                self.assertNotIn("quillmoor", result.stdout.casefold())

    def test_an_unknown_title_in_every_form(self):
        for how, text in self.forms(UNKNOWN + " (1999)" + MKV).items():
            if how == "encoded as HTML entities":
                continue  # "&#46;" etc.: covered by the private title above
            with self.subTest(how=how):
                self.assert_caught("tests/x.py", f"NAME = '{text}'",
                                   f"a title not on the invented list, {how}")


class Titles(ReleaseCheckCase):

    def test_an_unknown_title_in_test_data_is_caught(self):
        result = self.assert_caught("tests/test_x.py", f'NAME = "{UNKNOWN} (1999){MKV}"',
                                    "a title not on the invented list")
        self.assertNotIn("zorb", result.stdout.casefold())

    def test_an_unknown_title_in_a_fixture_title_field(self):
        self.assert_caught("tests/fixtures/x.json", '{"title": "' + UNKNOWN + '"}',
                           "a title not on the invented list")

    def test_an_unknown_title_in_docs_and_code(self):
        self.assert_caught("docs/x.md", f"For example `{UNKNOWN}.S01E01{MKV}`.",
                           "a title not on the invented list")
        self.assert_caught("backend/x.py", f"# {UNKNOWN}{MKV}", "a title not on the invented list")

    def test_an_invented_title_passes(self):
        result = self.findings("tests/test_x.py", f'NAME = "Example Movie (1999){MKV}"\n'
                               '{"title": "Example Show"}')
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_adding_a_title_to_the_list_lets_it_pass(self):
        self.write("tests/test_x.py", f'NAME = "{UNKNOWN}{MKV}"\n')
        self.commit()
        self.assertEqual(self.run_check().returncode, 1)
        self.write(release_check.INVENTED_TITLES, INVENTED_LIST + UNKNOWN.replace(" ", ".") + "\n")
        self.commit()
        self.assertEqual(self.run_check().returncode, 0)

    def test_html_title_attributes_are_not_titles(self):
        result = self.findings("tests/page.html", '<button title="' + UNKNOWN + '">')
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_third_party_files_keep_their_examples(self):
        result = self.findings("vendor/lib/notes.py", f"# {UNKNOWN}{MKV} a" + "@author.example.io")
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_third_party_files_are_still_checked_for_private_words(self):
        self.assert_caught("vendor/lib/notes.py", "# " + PRIVATE_TITLE, "private word (films and shows)")

    def test_the_title_reader(self):
        cases = {
            "Example.Movie.2001.1080p.BluRay.x264-GRP" + MKV: "example movie",
            "[grp] Example Show - 07 - Some Title [480p]" + MKV: "example show",
            "Example Show S01E02" + MKV: "example show",
            "Example Film (2004) - pt1" + MKV: "example film",
            "e01" + MKV: "",
            "1080p" + MKV: "",
        }
        for name, title in cases.items():
            with self.subTest(name=name):
                self.assertEqual(release_check.title_of(name), title)

    def test_the_repo_lists_its_invented_titles(self):
        titles = release_check.invented_titles(ROOT)
        self.assertGreater(len(titles), 50)
        self.assertIn("example movie", titles)


class SteamClient(ReleaseCheckCase):
    """What Enamel's own clean-up rules out from Steam's client."""

    def test_names_values_and_debug_connections(self):
        gp = "g" + "p"
        cases = [
            ("ui/x.css", "color: var(--" + gp + "SystemColor);",
             "a name from Steam's client (its variable prefix, or its system or colour names)"),
            ("docs/x.md", "Values " + "extract" + "ed from the client.",
             "words for taking values out of Steam's files"),
            ("docs/y.md", "Measured on Steam client version " + "1700000000.",
             "a Steam client version"),
            ("tools/x.py", "URL = 'http://localhost:80" + "80/json" + "/list'",
             "a debug connection to the Steam client"),
        ]
        for path, text, kind in cases:
            with self.subTest(kind=kind):
                self.assert_caught(path, text, kind)

    def test_a_reference_folder(self):
        self.assert_caught("reference/steam-home.html", "<p>capture</p>",
                           "a reference folder of captures", line=None)


class OldNames(ReleaseCheckCase):
    """The rename checks' own rules, reused (the Kettle Video rename)."""

    def test_each_old_name(self):
        for text in ("The " + "Media" + " Player app", "Kettle " + "Watch is next",
                     "vendor/kettle" + "-ui/DESIGN.md", "github.com/steamos" + "tools/x"):
            with self.subTest(text=text):
                result = self.assert_caught("docs/x.md", text,
                                            "an old name of the app, the design system or the account")
                self.assertNotIn(text.casefold(), result.stdout.casefold())

    def test_dated_history_keeps_its_names(self):
        result = self.findings("docs/decisions.md", "## 2026-10-01 — Old\n\nThe " + "Media" + " Player.")
        self.assertEqual(result.returncode, 0, result.stdout)


class SecretsAndLocalFiles(ReleaseCheckCase):

    def test_secrets(self):
        for text in ("TOKEN = 'gh" + "p_" + "A1b2" * 9 + "'",
                     "-----BEGIN OPENSSH PRIVATE " + "KEY-----",
                     '"pass' + 'word": "hunter2hunter2"',
                     "api_key = 'sk-" + "x" * 30 + "'"):
            with self.subTest(text=text[:12]):
                result = self.assert_caught(".claude/settings.json", text, "something that looks like a secret")
                self.assertNotIn("hunter2", result.stdout)

    def test_a_secret_in_a_third_party_file(self):
        self.assert_caught("vendor/lib/x.py", "KEY = 'AKIA" + "ABCDEFGHIJKLMNOP'",
                           "something that looks like a secret")

    def test_files_that_hold_secrets(self):
        for path in (".env", "config/.env.local", "deploy/id_" + "ed25519", "certs/server.pem"):
            with self.subTest(path=path):
                self.assert_caught(path, "x", "a file that usually holds a secret", line=None)

    def test_tracked_local_claude_files(self):
        for path in (".claude/settings.local.json", "CLAUDE.local.md"):
            with self.subTest(path=path):
                self.assert_caught(path, "{}", "a local Claude Code file tracked by git", line=None)


class EmailsLinksAndCommits(ReleaseCheckCase):

    def test_emails_other_than_the_noreply_address(self):
        for text in ("Write to someone" + "@mailbox.example.io",
                     "1234+someone" + "@users.noreply.github.com"):
            with self.subTest(text=text):
                result = self.assert_caught("docs/x.md", text,
                                            "an email address other than the noreply address")
                self.assertNotIn("mailbox", result.stdout)

    def test_links_to_the_private_repos_commits_and_issues(self):
        base = "https://github.com/" + release_check.PRIVATE_REPO
        for text in (base + "/issues/12", base + "/pull/3", base + "/commit/abc1234",
                     release_check.PRIVATE_REPO + "#" + "40",
                     "https://github.com/someone/thing/commit/" + "abcdef1234567"):
            with self.subTest(text=text):
                self.assert_caught("CHANGELOG.md", text, "a link to this private repo's commits or issues")

    def test_a_commit_address_from_the_history(self):
        commit = commit_address(self.repo, 8)
        self.assert_caught("docs/x.md", f"Measured at {commit}.", "a commit address")

    def test_a_commit_address_looked_up_in_another_repo(self):
        # A copy without history: commits are looked up where they were made.
        commit = commit_address(self.repo, 9)
        copy = os.path.join(self.tmp, "copy")
        os.makedirs(copy)
        git(copy, "init", "-q", "-b", "main")
        git(copy, "config", "user.name", "Test")
        git(copy, "config", "user.email", "test@example.invalid")
        git(copy, "config", "commit.gpgsign", "false")
        Path(copy, "notes.md").write_text(f"At {commit}.\n", encoding="utf-8")
        git(copy, "add", ".")
        git(copy, "commit", "-q", "-m", "copy")
        run = lambda *extra: subprocess.run(
            [sys.executable, str(CHECK), "--repo", copy, "--list", self.list, *extra],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(run().returncode, 0, "not a commit of the copy itself")
        result = run("--history", self.repo)
        self.assertIn("RELEASE: notes.md, line 1: a commit address", result.stdout)

    def test_a_history_folder_that_is_not_a_repo_stops_the_check(self):
        # Never "clean" with commit addresses left unchecked.
        commit = commit_address(self.repo, 9)
        self.write("docs/x.md", f"At {commit}.\n")
        self.commit()
        plain = os.path.join(self.tmp, "not-a-repo")
        os.makedirs(plain)
        for folder in (plain, os.path.join(self.tmp, "missing")):
            with self.subTest(folder=os.path.basename(folder)):
                result = self.run_check("--history", folder)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("Release check FAILED", result.stdout)
                self.assertIn("commit addresses can't be looked up", result.stdout)
                self.assertNotIn("clean", result.stdout)
                self.assertNotIn("Traceback", result.stdout + result.stderr)

    def test_a_failing_lookup_is_never_taken_as_no_commits(self):
        plain = os.path.join(self.tmp, "not-a-repo")
        os.makedirs(plain)
        with self.assertRaises(release_check.HistoryProblem):
            release_check.known_commits(plain, ["abcdef1234"])


class Report(ReleaseCheckCase):

    def test_every_finding_names_file_line_and_kind_and_a_summary_counts_them(self):
        self.write("docs/a.md", "one\ntwo zephyrcard\n")
        self.write("docs/b.md", f"{UNKNOWN}{MKV}\n")
        self.commit()
        result = self.run_check()
        lines = [line for line in result.stdout.splitlines() if line.startswith("RELEASE: ")]
        self.assertEqual(lines, ["RELEASE: docs/a.md, line 2: private word (card labels)",
                                 "RELEASE: docs/b.md, line 1: a title not on the invented list"])
        self.assertIn("2 findings", result.stdout)
        self.assertNotIn("zephyr", result.stdout.casefold())
        self.assertNotIn("zorb", result.stdout.casefold())


class PassesOnItself(unittest.TestCase):
    """The check, its tests and the invented list hold nothing it flags, so
    they never stand in the way of a clean repo."""

    def test_its_own_files_are_clean(self):
        matcher = release_check.privacy_guard.Matcher(
            {"films and shows": [PRIVATE_TITLE], "device names": ["plover-handheld"]})
        check = release_check.Check(matcher, release_check.invented_titles(ROOT), history=str(ROOT))
        files = ("tools/release_check.py", "tests/test_release_rules.py", release_check.INVENTED_TITLES,
                 "tools/release.py")
        own = [line for line in check.run([(f, (ROOT / f).read_bytes()) for f in files])
               if "private word" not in line]  # the invented stand-ins are in this file on purpose
        self.assertEqual(own, [])


class History(ReleaseCheckCase):
    """The deep look: every version of every file and every message."""

    def test_finds_a_removed_secret_and_a_private_word_in_a_message(self):
        self.write("config.json", '{"token": "' + "tok" + "en1234567890" + '"}\n')
        self.commit("add config")
        self.write("config.json", "{}\n")
        self.commit("we watched " + PRIVATE_TITLE)
        result = self.run_check("history")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertRegex(result.stdout, r"RELEASE: config\.json \(first in commit \w+\), line 1: "
                                        r"something that looks like a secret")
        self.assertRegex(result.stdout, r"RELEASE: commit \w+ message, line 1: private word \(films and shows\)")
        self.assertNotIn("1234567890", result.stdout)
        self.assertNotIn("quillmoor", result.stdout.casefold())

    def test_a_clean_history_passes(self):
        result = self.run_check("history")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
