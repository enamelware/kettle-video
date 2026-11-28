# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The release flow (the release flow work, docs/RELEASING.md).

The release script ends with a summary and one question. Checked here,
with the GitHub CLI, git's remote and the network replaced by fakes (no
real gh is ever run, nothing goes online, no tag is made in this repo):

  - without the answer "yes" nothing is uploaded: no, an empty answer, the
    end of input, Ctrl+C, and a run with no one at a terminal (also as a
    real run of the script, with a stand-in gh that notes any call);
  - a yes makes a pre-release, never the latest, with the archive, its
    checksum, install.sh and the one-file installer attached and the
    notes as its text; nowhere does the script mark a release as the
    latest;
  - with the GitHub CLI missing or signed out it prints the website steps
    and uploads nothing.

And for the app, against a stand-in GitHub that answers "latest" the way
GitHub does (never a pre-release or a draft):

  - Check for updates never offers a newer pre-release or draft, and still
    offers the latest release; an answer marked pre-release or draft is
    never offered either;
  - Update and restart installs a release that started as a pre-release
    once it is marked as the latest (a fake release archive, the real
    shared update step);
  - nothing in a release install can ask for pre-releases: no other
    release address, no switch, no setting.

Run: scripts/test.sh unit tests.test_release_flow
"""

import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from backend import app_update, update_check
from tests.test_app_update import InstalledCopy, release_answer, wait_for
from tests.test_installer import make_archive
from tests.test_release import SCRIPT, ReleaseTestCase, release

ROOT = Path(__file__).resolve().parent.parent
TODAY = date(2026, 11, 27)
FAKE_GH = "/fake/bin/gh"


class FakeGh:
    """subprocess.run for gh: writes down every command; `gh auth status`
    answers signed_in, `gh release create` answers upload_code."""

    def __init__(self, signed_in=True, upload_code=0):
        self.signed_in = signed_in
        self.upload_code = upload_code
        self.commands = []

    def __call__(self, command, **kwargs):
        self.commands.append(list(command))
        if command[1:3] == ["auth", "status"]:
            code = 0 if self.signed_in else 1
        elif command[1:3] == ["release", "create"]:
            code = self.upload_code
        else:
            raise AssertionError(f"unexpected gh command: {command}")
        return subprocess.CompletedProcess(command, code, b"", b"")

    def uploads(self):
        return [c for c in self.commands if c[1:3] == ["release", "create"]]


def never_read(question):
    raise AssertionError("asked although no one is there to answer")


class TheScriptAsks(ReleaseTestCase):
    """The real build, from the temporary tagged repo, then the question
    with fakes for the answer and for gh."""

    def main(self, answer="yes", interactive=True, gh_installed=True, gh=None):
        gh = gh or FakeGh()

        def read(question):
            self.questions.append(question)
            if isinstance(answer, BaseException):
                raise answer
            return answer

        self.questions = []
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = release.main(
                ["v0.2.0", "--repo", self.repo, "--out", self.out, "--list", self.list],
                read=read if interactive else never_read, interactive=interactive,
                which=lambda name: FAKE_GH if gh_installed and name == "gh" else None, run=gh)
        return code, out.getvalue(), gh

    def expected_files(self):
        return [os.path.join(self.out, name) for name in (
            f"{self.stem()}.tar.gz", f"{self.stem()}.tar.gz.sha256", "install.sh",
            release.launcher_name(release.read_names(
                (ROOT / "installer" / "names.env").read_text(encoding="utf-8"))))]

    def test_without_a_yes_nothing_is_uploaded(self):
        for answer in ("", "no", "n", "y", "YES please", "yes yes", "ja", " ",
                       EOFError(), KeyboardInterrupt()):
            with self.subTest(answer=answer):
                code, said, gh = self.main(answer=answer)
                self.assertEqual(code, 0, said)
                self.assertEqual(len(self.questions), 1)
                self.assertEqual(gh.commands, [])
                self.assertIn("Nothing was uploaded", said)
                # The files are built all the same.
                self.assertEqual(len(self.written()), 5)

    def test_with_no_one_to_answer_nothing_is_uploaded(self):
        code, said, gh = self.main(interactive=False)
        self.assertEqual(code, 0, said)
        self.assertEqual(gh.commands, [])
        self.assertIn("nothing was uploaded", said)

    def test_a_real_run_with_no_terminal_asks_no_one_and_runs_no_gh(self):
        # The script as the designer runs it, but with no one at the
        # terminal and a stand-in gh first on PATH that notes any call.
        bin_dir = Path(self.tmp, "bin")
        bin_dir.mkdir()
        called = Path(self.tmp, "gh-was-called")
        gh = bin_dir / "gh"
        gh.write_text(f"#!/bin/sh\necho \"$@\" >> '{called}'\n", encoding="utf-8")
        gh.chmod(0o755)
        env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
        for stdin in (subprocess.DEVNULL, None):
            with self.subTest(stdin=stdin):
                result = subprocess.run(
                    [sys.executable, str(SCRIPT), "v0.2.0", "--repo", self.repo, "--out",
                     self.out, "--list", self.list],
                    input="yes\n" if stdin is None else None,
                    stdin=stdin, capture_output=True, text=True, timeout=60, env=env)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("nothing was uploaded", result.stdout)
                self.assertFalse(called.exists())

    def test_the_summary_names_the_files_and_the_notes(self):
        _code, said, _gh = self.main(answer="no")
        for path in self.expected_files():
            self.assertIn(os.path.basename(path), said)
        self.assertIn("- Plover mode for the Brindle screen.", said)
        self.assertIn("pre-release", said)
        self.assertIn("never as the latest", said)
        self.assertIn(f"github.com/{update_check.REPO}", said)
        self.assertEqual(self.questions, [release.QUESTION])
        self.assertIn("Type yes", release.QUESTION)

    def test_a_yes_makes_a_pre_release_never_the_latest(self):
        for answer in ("yes", "Yes", " YES \n"):
            with self.subTest(answer=answer):
                code, said, gh = self.main(answer=answer)
                self.assertEqual(code, 0, said)
                self.assertEqual(gh.commands[0], [FAKE_GH, "auth", "status", "--hostname",
                                                  "github.com"])
                [command] = gh.uploads()
                self.assertEqual(command[:4], [FAKE_GH, "release", "create", "v0.2.0"])
                self.assertEqual(command[4:8], self.expected_files())
                options = command[8:]
                self.assertIn("--prerelease", options)
                self.assertIn("--latest=false", options)
                self.assertIn("--verify-tag", options)
                self.assertNotIn("--latest", options)
                self.assertNotIn("--draft", options)
                self.assertEqual(options[options.index("--repo") + 1], update_check.REPO)
                self.assertEqual(options[options.index("--notes-file") + 1],
                                 os.path.join(self.out, f"{self.stem()}-notes.md"))
                self.assertEqual(options[options.index("--title") + 1], "Kettle Video 0.2.0")
                self.assertIn("as a pre-release", said)

    def test_the_script_never_marks_a_release_as_the_latest(self):
        source = Path(release.__file__).read_text(encoding="utf-8")
        self.assertEqual(re.findall(r"--latest[=\w]*", source), ["--latest=false"])
        for never in ("make_latest", "release edit", '"edit"', "'edit'"):
            self.assertNotIn(never, source)
        self.assertNotRegex(source, r"api\.github\.com")

    def test_gh_missing_prints_the_website_steps_and_uploads_nothing(self):
        code, said, gh = self.main(gh_installed=False)
        self.assertEqual(code, 0, said)
        self.assertEqual(gh.commands, [])
        self.assert_website_steps(said)

    def test_gh_signed_out_prints_the_website_steps_and_uploads_nothing(self):
        code, said, gh = self.main(gh=FakeGh(signed_in=False))
        self.assertEqual(code, 0, said)
        self.assertEqual(gh.uploads(), [])
        self.assertIn("isn't signed in", said)
        self.assert_website_steps(said)

    def assert_website_steps(self, said):
        self.assertIn("Nothing was uploaded", said)
        self.assertIn(f"https://github.com/{update_check.REPO}/releases/new", said)
        self.assertIn('Tick "Set as a pre-release"', said)
        self.assertIn('Leave "Set as the latest release" unticked', said)
        for path in self.expected_files():
            self.assertIn(os.path.basename(path), said)
        self.assertNotIn(str(Path.home()) + "/", said)

    def test_a_failed_upload_says_so(self):
        code, said, gh = self.main(gh=FakeGh(upload_code=1))
        self.assertEqual(code, 1)
        self.assertEqual(len(gh.uploads()), 1)
        self.assertIn("The upload didn't finish", said)

    def test_a_stopped_release_asks_nothing(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = release.main(["v9.9.9", "--repo", self.repo, "--out", self.out,
                                 "--list", self.list], read=never_read, interactive=True,
                                which=lambda name: FAKE_GH, run=FakeGh())
        self.assertEqual(code, 1)
        self.assertIn("Release stopped", out.getvalue())


# --- The app: Check for updates stays on the latest release ---

def github_release(version, prerelease=False, draft=False):
    return {**release_answer(version), "prerelease": prerelease, "draft": draft,
            "name": f"Kettle Video {version}"}


class StandInReleases:
    """GitHub's release information on this device, holding several
    releases. Like GitHub, "latest" is the newest full release, never a
    pre-release or a draft; the list holds them all. Writes down every
    path asked for."""

    def __init__(self, releases):
        self.releases = releases
        self.paths = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def do_GET(self):
                outer.paths.append(self.path)
                base = f"/repos/{update_check.REPO}/releases"
                if self.path == f"{base}/latest":
                    full = [r for r in outer.releases if not r["prerelease"] and not r["draft"]]
                    answer = full[-1] if full else None
                elif self.path == base:
                    answer = list(reversed(outer.releases))
                else:
                    answer = None
                data = json.dumps(answer if answer is not None else {"message": "Not Found"})
                self.send_response(200 if answer is not None else 404)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data.encode())

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        port = self.httpd.server_address[1]
        self.latest_url = f"http://127.0.0.1:{port}/repos/{update_check.REPO}/releases/latest"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class CheckStaysOnTheLatestRelease(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.root = self.tmp / "app"  # a release install: no git folder
        self.root.mkdir()

    def check(self, github, current):
        with mock.patch.object(update_check, "LATEST_URL", github.latest_url):
            return update_check.check(self.root, self.tmp / "data", current, TODAY,
                                      remote=never_read)

    def github(self, *releases):
        github = StandInReleases(list(releases))
        self.addCleanup(github.close)
        return github

    def test_a_newer_pre_release_and_draft_are_never_offered(self):
        github = self.github(github_release("1.0.0"), github_release("1.1.0"),
                             github_release("1.2.0", prerelease=True),
                             github_release("1.3.0", draft=True))
        result = self.check(github, "1.1.0")
        self.assertEqual(result["state"], "current", result)
        self.assertEqual(result["text"], "Up to date (v1.1.0)")
        self.assertEqual(github.paths, [f"/repos/{update_check.REPO}/releases/latest"])

    def test_the_latest_release_is_still_offered(self):
        github = self.github(github_release("1.0.0"), github_release("1.1.0"),
                             github_release("1.2.0", prerelease=True),
                             github_release("1.3.0", draft=True))
        result = self.check(github, "1.0.0")
        self.assertEqual(result["state"], "newer", result)
        self.assertEqual(result["version"], "1.1.0")
        self.assertEqual(github.paths, [f"/repos/{update_check.REPO}/releases/latest"])

    def test_an_answer_marked_pre_release_or_draft_is_never_offered(self):
        for marked in ({"prerelease": True}, {"draft": True}):
            with self.subTest(marked=marked):
                answer = {**github_release("9.0.0"), **marked}
                with self.assertRaises(update_check.CheckFailed):
                    update_check.release_result(answer, "1.0.0", "kettle-video")
                result = update_check.check(self.root, self.tmp / "data", "1.0.0", TODAY,
                                            fetch=lambda current: answer, remote=never_read)
                self.assertEqual(result["state"], "error")
                self.assertNotIn("release", result)


class UpdateAfterMarkingItLatest(InstalledCopy):
    """The release flow end to end, for an installed copy of 0.2.0: 0.3.0
    goes up as a pre-release (not offered), is marked as the latest (offered),
    and Update and restart installs it through the real shared step."""

    def test_offered_only_once_marked_latest_then_installs(self):
        make_archive(self.files, "0.3.0")
        github = StandInReleases([github_release("0.2.0"),
                                  github_release("0.3.0", prerelease=True)])
        self.addCleanup(github.close)
        data_dir = self.tmp / "check-data"

        def check():
            with mock.patch.object(update_check, "LATEST_URL", github.latest_url):
                return update_check.check(self.root, data_dir, "0.2.0", TODAY,
                                          remote=never_read)

        updater = self.updater()
        while_pre_release = check()
        self.assertEqual(while_pre_release["state"], "current", while_pre_release)
        self.assertFalse(updater.offered(while_pre_release, None).get("can_update"))
        self.assertIsNotNone(updater.start_update("0.3.0"))  # refused: never offered
        self.assertEqual(self.version(), "0.2.0")

        # The designer marks it as the latest on GitHub.
        github.releases[-1]["prerelease"] = False
        marked = check()
        self.assertEqual(marked["state"], "newer", marked)
        self.assertEqual(marked["version"], "0.3.0")
        self.assertTrue(updater.offered(marked, marked["release"]).get("can_update"))
        self.assertIsNone(updater.start_update("0.3.0"))
        wait_for(lambda: updater.status()["state"] not in app_update.RUNNING or self.restarts)
        new_root = Path(os.path.realpath(self.places["APP_DIR"]))
        self.assertEqual(self.restarts, [(new_root, "Updated to 0.3.0")], self.lines)
        self.assertEqual(self.version(), "0.3.0")
        self.assertEqual(self.theirs(), self.before)
        self.assertEqual(self.download_folders(), [])


# --- No switch for pre-releases in a release install ---

class NoSwitchForPreReleases(unittest.TestCase):

    def shipped(self):
        """The app's tracked files that a release archive holds, read from
        this folder (release.included decides), apart from vendored code."""
        listed = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True,
                                text=True, check=True).stdout.splitlines()
        return [p for p in listed if release.included(p) and not p.startswith("vendor/")
                and (ROOT / p).is_file()]

    def text(self, path):
        try:
            return (ROOT / path).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return ""

    def test_the_only_release_information_asked_for_is_the_latest(self):
        found = []
        for path in self.shipped():
            for url in re.findall(r"api\.github\.com/repos/[^\s\"'`)]*", self.text(path)):
                # Try a branch's open pull request list (development copies
                # only) is the one address that isn't release information.
                if path == "backend/try_branch.py" and "/pulls?" in url:
                    continue
                found.append(url)
                self.assertRegex(url, r"/releases/latest$", f"{path}: {url}")
        self.assertTrue(found)
        self.assertTrue(update_check.LATEST_URL.endswith("/releases/latest"))

    def test_no_switch_or_setting_names_pre_releases(self):
        # Pre-releases are named only where an answer marked as one is
        # refused, and in the version comparison's comments.
        allowed = {"backend/update_check.py", "installer/one_file_install.py",
                   "installer/update.py"}
        naming = {p for p in self.shipped() if re.search(r"pre.?releases?", self.text(p), re.I)}
        self.assertLessEqual(naming, allowed)
        for path in allowed:
            for line in self.text(path).splitlines():
                if "prerelease" in line and not line.strip().startswith("#"):
                    self.assertRegex(line, r'\.get\("prerelease"\) is (not False|True)', line)
        self.assertNotRegex(self.text("backend/settings.py"), r"(?i)pre.?release|draft")
        self.assertNotRegex(self.text("settings.example.json"), r"(?i)pre.?release|draft")


# --- The checklist ---

class TheChecklist(unittest.TestCase):

    def setUp(self):
        self.releasing = (ROOT / "docs" / "RELEASING.md").read_text(encoding="utf-8")

    def test_the_readme_links_to_it_where_it_talks_about_contributing(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        line = next(line for line in readme.splitlines() if "contributions" in line)
        self.assertIn("(docs/RELEASING.md)", line)

    def test_it_lists_the_steps_in_order(self):
        steps = ["CHANGELOG", "VERSION", "git tag", "tools/release.py", "Not offered yet",
                 "update test", "clean install", "Mark it as the latest",
                 "Update and restart, once"]
        places = [self.releasing.index(step) for step in steps]
        self.assertEqual(places, sorted(places))
        self.assertIn("unmark the release as the latest straight away", self.releasing)
        self.assertIn("Gaming Mode", self.releasing)

    def test_it_names_every_file_the_upload_attaches(self):
        for name in ("kettle-video-<version>.tar.gz", ".sha256", "install.sh",
                     "install-kettle-video.desktop"):
            self.assertIn(name, self.releasing)

    def test_it_says_what_users_see(self):
        self.assertIn("## What users see", self.releasing)
        self.assertIn("a pre-release never reaches it", self.releasing)
        self.assertIn("anyone can see a pre-release on the Releases page", self.releasing)

    def test_the_public_text_check_passes_on_it_and_the_readme(self):
        sys.path.insert(0, str(ROOT / "tools"))
        import public_text
        for path in ("docs/RELEASING.md", "README.md"):
            with self.subTest(path=path):
                text = (ROOT / path).read_text(encoding="utf-8")
                self.assertEqual(public_text.findings(path, text), [])
                self.assertIn(path, public_text.published_files(ROOT))


if __name__ == "__main__":
    unittest.main()
