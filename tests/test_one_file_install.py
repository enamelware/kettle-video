# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The one-file installer, installer/one_file_install.py (the one-file
install work, issue "One-file install").

GitHub is replaced by a fake that serves an invented release (a small
test archive holding the real installer/install.sh, update.py and
names.env), and the windows by a fake that records what was said and
gives set answers. The real install.sh then runs in a temporary home
folder with the stand-ins of tests/test_installer.py (flatpak, mpv,
sudo). Checked: only GitHub's latest full release is used, and an answer
marked pre-release or draft is refused; nothing goes online before the
first yes; a checksum mismatch, no connection or GitHub unreachable each
say so and install nothing; an install over an existing copy names both
versions and keeps all its data; the mpv question from the window reaches
install.sh; the temporary files are always removed.

Run: scripts/test.sh unit tests.test_one_file_install
"""

import importlib.util
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tarfile
import unittest
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from backend import app_paths, update_check  # noqa: E402
from tests.test_installer import NAME, SCRIPT, InstallerTestCase, make_archive  # noqa: E402

SOURCE = ROOT / "installer" / "one_file_install.py"
_spec = importlib.util.spec_from_file_location("one_file_install", SOURCE)
one_file = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(one_file)

TAG_BASE = one_file.DOWNLOAD_BASE


class Answer(io.BytesIO):
    """A fake web answer."""

    def __init__(self, data):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}


class FakeGitHub:
    """Serves set answers by address and records every request."""

    def __init__(self):
        self.pages = {}
        self.asked = []

    def __call__(self, request, timeout):
        url = request.full_url
        self.asked.append(url)
        page = self.pages.get(url)
        if page is None:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        if isinstance(page, BaseException):
            raise page
        return Answer(page)

    def publish(self, archive, tag, prerelease=False, draft=False, checksum=None):
        """archive (with its .sha256 beside it) as GitHub's latest release."""
        archive = Path(archive)
        sums = Path(f"{archive}.sha256")
        assets = []
        for path in (archive, sums):
            url = f"{TAG_BASE}{tag}/{path.name}"
            self.pages[url] = path.read_bytes()
            assets.append({"name": path.name, "browser_download_url": url,
                           "size": path.stat().st_size})
        if checksum is not None:
            self.pages[f"{TAG_BASE}{tag}/{sums.name}"] = checksum
        self.pages[one_file.LATEST_URL] = json.dumps({
            "tag_name": tag, "draft": draft, "prerelease": prerelease,
            "assets": assets}).encode()


class FakeWindow:
    """Records what the viewer is shown; answers questions in order."""

    terminal = False

    def __init__(self, answers=()):
        self.answers = list(answers)
        self.asked, self.steps, self.infos, self.errors = [], [], [], []

    def ask(self, text, yes, no):
        self.asked.append(text)
        return self.answers.pop(0) if self.answers else False

    def step(self, text, percent=None):
        self.steps.append(text)

    def hide(self):
        pass

    def info(self, text):
        self.infos.append(text)

    def error(self, text):
        self.errors.append(text)


def release_archive(folder, version):
    """An invented release archive that holds the real installer."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    return make_archive(folder, version, extra={
        "installer/install.sh": (SCRIPT.read_bytes(), 0o755)})


class OneFileTestCase(InstallerTestCase):

    def setUp(self):
        super().setUp()
        self.github = FakeGitHub()
        self.temp = self.tmp / "temp"
        self.temp.mkdir()
        self.release = release_archive(self.tmp / "release-0.2.0", "0.2.0")
        self.github.publish(self.release, "v0.2.0")

    def which(self, name):
        return shutil.which(name, path=str(self.bin))

    def run_one_file(self, answers=(True, True), **extra):
        window = FakeWindow(answers)
        code = one_file.install(window, open_url=self.github, environ=self.env(**extra),
                                which=self.which, temp_parent=self.temp)
        return code, window

    @property
    def app(self):
        return self.places["APP_DIR"]

    @property
    def desktop_file(self):
        return self.home / ".local/share/applications" / NAME["DESKTOP_ENTRY"]

    def installed(self):
        return one_file.installed_version(self.app, NAME["INSTALL_MARK"])

    def assert_temp_removed(self):
        self.assertEqual(list(self.temp.iterdir()), [])


class InstallsTheLatestRelease(OneFileTestCase):

    def test_a_fresh_install_from_the_latest_full_release(self):
        code, window = self.run_one_file(answers=(True,))
        self.assertEqual(code, 0, window.errors)
        self.assertEqual(self.installed(), "0.2.0")
        # It asked GitHub for the latest release, then took that release's
        # two files, and nothing else.
        self.assertEqual(self.github.asked, [
            one_file.LATEST_URL,
            f"{TAG_BASE}v0.2.0/{self.release.name}",
            f"{TAG_BASE}v0.2.0/{self.release.name}.sha256"])
        # It said where, then success with the next step.
        self.assertIn(str(self.app), window.asked[0])
        self.assertIn("Kettle Video 0.2.0", " ".join(window.steps))
        self.assertIn("Add to Steam", window.infos[-1])
        self.assertEqual(window.errors, [])
        # The same install as install.sh: the menu entry is there too.
        self.assertTrue(self.desktop_file.is_file())
        self.assert_temp_removed()

    def test_nothing_goes_online_before_the_first_yes(self):
        code, window = self.run_one_file(answers=(False,))
        self.assertEqual(code, one_file.CANCELLED)
        self.assertEqual(self.github.asked, [])
        self.assertIn("GitHub", window.asked[0])
        self.assertIsNone(self.installed())
        self.assert_temp_removed()

    def test_a_pre_release_answer_is_refused(self):
        self.github.publish(self.release, "v0.2.0", prerelease=True)
        code, window = self.run_one_file()
        self.assertEqual(code, 1)
        self.assertEqual(self.github.asked, [one_file.LATEST_URL])
        self.assertIn("Nothing was installed.", window.errors[0])
        self.assertIsNone(self.installed())
        self.assert_temp_removed()

    def test_a_draft_answer_is_refused(self):
        self.github.publish(self.release, "v0.2.0", draft=True)
        code, window = self.run_one_file()
        self.assertEqual(code, 1)
        self.assertEqual(self.github.asked, [one_file.LATEST_URL])
        self.assertIsNone(self.installed())

    def test_only_this_repos_release_addresses_are_downloaded(self):
        answer = json.loads(self.github.pages[one_file.LATEST_URL])
        for asset in answer["assets"]:
            asset["browser_download_url"] = "https://example.invalid/" + asset["name"]
        self.github.pages[one_file.LATEST_URL] = json.dumps(answer).encode()
        code, window = self.run_one_file()
        self.assertEqual(code, 1)
        self.assertEqual(self.github.asked, [one_file.LATEST_URL])
        self.assertIn("Nothing was installed.", window.errors[0])

    def test_the_repo_is_the_apps_own(self):
        self.assertEqual(one_file.REPO, update_check.REPO)
        self.assertTrue(one_file.LATEST_URL.startswith("https://"))
        self.assertTrue(one_file.LATEST_URL.endswith("/releases/latest"))


class InstallsNothing(OneFileTestCase):

    def assert_nothing_installed(self, code, window, *words):
        self.assertEqual(code, 1)
        self.assertEqual(len(window.errors), 1, window.errors)
        for word in (*words, "Nothing was installed."):
            self.assertIn(word, window.errors[0])
        self.assertFalse(self.app.exists())
        self.assertFalse(self.desktop_file.exists())
        self.assert_temp_removed()

    def test_a_checksum_mismatch(self):
        self.github.publish(self.release, "v0.2.0",
                            checksum=f"{'0' * 64}  {self.release.name}\n".encode())
        code, window = self.run_one_file()
        self.assert_nothing_installed(code, window, "doesn't match its checksum")

    def test_a_checksum_for_another_file(self):
        good = Path(f"{self.release}.sha256").read_text(encoding="utf-8").split()[0]
        self.github.publish(self.release, "v0.2.0",
                            checksum=f"{good}  something-else.tar.gz\n".encode())
        code, window = self.run_one_file()
        self.assert_nothing_installed(code, window, "doesn't match its checksum")

    def test_offline(self):
        self.github.pages[one_file.LATEST_URL] = urllib.error.URLError(
            socket.gaierror(-3, "Temporary failure in name resolution"))
        code, window = self.run_one_file()
        self.assert_nothing_installed(code, window, "no internet connection")

    def test_no_network_at_all(self):
        self.github.pages[one_file.LATEST_URL] = urllib.error.URLError(
            OSError(101, "Network is unreachable"))
        code, window = self.run_one_file()
        self.assert_nothing_installed(code, window, "no internet connection")

    def test_the_connection_drops_during_the_download(self):
        self.github.pages[f"{TAG_BASE}v0.2.0/{self.release.name}"] = urllib.error.URLError(
            socket.gaierror(-3, "Temporary failure in name resolution"))
        code, window = self.run_one_file()
        self.assert_nothing_installed(code, window, "no internet connection")

    def test_github_unreachable(self):
        self.github.pages[one_file.LATEST_URL] = urllib.error.HTTPError(
            one_file.LATEST_URL, 503, "Service Unavailable", {}, None)
        code, window = self.run_one_file()
        self.assert_nothing_installed(code, window, "GitHub couldn't be reached", "503")

    def test_github_does_not_answer_in_time(self):
        self.github.pages[one_file.LATEST_URL] = TimeoutError()
        code, window = self.run_one_file()
        self.assert_nothing_installed(code, window, "GitHub couldn't be reached")

    def test_a_release_without_the_installer_inside(self):
        (self.tmp / "bare").mkdir()
        self.github.publish(make_archive(self.tmp / "bare", "0.2.0"), "v0.2.0")
        code, window = self.run_one_file()
        self.assert_nothing_installed(code, window, "other way to install")

    def test_temporary_files_are_removed_even_after_an_unexpected_failure(self):
        def broken(*args, **kwargs):
            raise RuntimeError("invented failure")
        window = FakeWindow((True,))
        with self.assertRaises(RuntimeError):
            one_file.install(window, open_url=self.github, environ=self.env(),
                             which=self.which, temp_parent=self.temp, run=broken)
        self.assert_temp_removed()


class OverAnExistingCopy(OneFileTestCase):

    def setUp(self):
        super().setUp()
        code, window = self.run_one_file(answers=(True,))
        self.assertEqual(code, 0, window.errors)
        paths = app_paths.for_app(Path(os.path.realpath(self.app)), {"HOME": str(self.home)})
        self.assertTrue(paths.installed)
        self.kept = {
            paths.settings_file: json.dumps({"movies_path": "/invented/Films",
                                             "tv_path": "/invented/Shows"}) + "\n",
            paths.data_dir / "library.json": '{"invented": "saved library"}\n',
            paths.data_dir / "continue.json": '{"invented": "continue watching"}\n',
            paths.logs_dir / "launch.log": "invented log line\n",
            # The kiosk window's Firefox profile (launch.sh makes it in
            # ~/.mozilla, or in Flatpak Firefox's data folder).
            self.home / ".mozilla" / NAME["FIREFOX_PROFILE"] / "prefs.js":
                'user_pref("invented.setting", true);\n',
            self.home / ".var/app/org.mozilla.firefox/data" / NAME["FIREFOX_PROFILE"]
            / "storage.sqlite": "invented browser storage\n",
        }
        for path, text in self.kept.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        self.newer = release_archive(self.tmp / "release-0.3.0", "0.3.0")
        self.github.publish(self.newer, "v0.3.0")

    def assert_data_kept(self):
        for path, text in self.kept.items():
            self.assertEqual(path.read_text(encoding="utf-8"), text, path.name)

    def test_names_both_versions_and_keeps_all_data(self):
        code, window = self.run_one_file(answers=(True, True))
        self.assertEqual(code, 0, window.errors)
        self.assertIn("Kettle Video 0.2.0 is installed", window.asked[1])
        self.assertIn("Kettle Video 0.3.0 in its place", window.asked[1])
        self.assertEqual(self.installed(), "0.3.0")
        self.assert_data_kept()
        self.assert_temp_removed()

    def test_the_same_version_again_keeps_all_data(self):
        self.github.publish(self.release, "v0.2.0")
        code, window = self.run_one_file(answers=(True, True))
        self.assertEqual(code, 0, window.errors)
        self.assertEqual(self.installed(), "0.2.0")
        self.assert_data_kept()

    def test_a_no_to_the_versions_changes_nothing_and_downloads_nothing(self):
        self.github.asked.clear()
        code, window = self.run_one_file(answers=(True, False))
        self.assertEqual(code, one_file.CANCELLED)
        self.assertEqual(self.github.asked, [one_file.LATEST_URL])
        self.assertEqual(self.installed(), "0.2.0")
        self.assert_data_kept()
        self.assert_temp_removed()

    def test_an_older_release_is_installed_only_after_a_yes(self):
        older = release_archive(self.tmp / "release-0.1.0", "0.1.0")
        self.github.publish(older, "v0.1.0")
        code, window = self.run_one_file(answers=(True, True, False))
        self.assertEqual(code, one_file.CANCELLED)
        self.assertIn("newer than the latest release", window.asked[2])
        self.assertEqual(self.installed(), "0.2.0")
        self.assert_temp_removed()

        code, window = self.run_one_file(answers=(True, True, True))
        self.assertEqual(code, 0, window.errors)
        self.assertEqual(self.installed(), "0.1.0")
        self.assert_data_kept()

    def test_a_checksum_mismatch_leaves_the_installed_copy(self):
        self.github.publish(self.newer, "v0.3.0", checksum=b"0" * 64 + b"  x\n")
        code, window = self.run_one_file(answers=(True, True))
        self.assertEqual(code, 1)
        self.assertIn("Kettle Video 0.2.0 is still installed", window.errors[0])
        self.assertEqual(self.installed(), "0.2.0")
        self.assert_data_kept()
        self.assert_temp_removed()


class Mpv(OneFileTestCase):

    def test_missing_mpv_is_asked_in_the_window_and_a_no_installs_nothing(self):
        code, window = self.run_one_file(answers=(True, False))
        self.assertEqual(code, 0, window.errors)
        self.assertIn("flatpak install flathub io.mpv.Mpv", window.asked[1])
        self.assertFalse(any(line.startswith("install") for line in self.logged("flatpak")))
        self.assertIn("mpv: not installed", window.infos[-1])

    def test_a_yes_in_the_window_runs_the_one_flathub_command(self):
        code, window = self.run_one_file(answers=(True, True))
        self.assertEqual(code, 0, window.errors)
        installs = [line for line in self.logged("flatpak") if line.startswith("install")]
        self.assertEqual(installs, ["install --assumeyes flathub io.mpv.Mpv"])

    def test_an_installed_mpv_is_not_asked_about(self):
        self.stub("mpv", "#!/bin/sh\nexit 0\n")
        code, window = self.run_one_file(answers=(True,))
        self.assertEqual(code, 0, window.errors)
        self.assertEqual(len(window.asked), 1)
        self.assertIn("mpv: already installed", window.infos[-1])

    def test_in_a_terminal_install_sh_asks_itself(self):
        lines, answers = [], iter(["y", "n"])
        terminal = one_file.TerminalUI(write=lines.append, read=lambda prompt: next(answers))
        ran = []

        def run(argv, **kwargs):
            # The terminal's own input, here none: install.sh's question
            # counts as a no and the install still finishes.
            ran.append(subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True,
                                      text=True, **kwargs))
            return ran[-1]

        code = one_file.install(terminal, open_url=self.github, environ=self.env(),
                                which=self.which, temp_parent=self.temp, run=run)
        self.assertEqual(code, 0)
        self.assertEqual(len(ran), 1)
        self.assertNotIn(one_file.MPV_ANSWER, ran[0].args)
        self.assertIn("Install mpv now with that command? [y/N]", ran[0].stdout)
        self.assertEqual(self.installed(), "0.2.0")
        self.assert_temp_removed()


class TheLauncher(unittest.TestCase):

    def test_bootstrap_fits_a_quoted_exec_value(self):
        for character in '"`$\\%\n':
            self.assertNotIn(character, one_file.BOOTSTRAP)
        self.assertIn(f"'{one_file.MARKER}'", one_file.BOOTSTRAP)

    def test_never_uses_sudo_or_steam_files(self):
        text = SOURCE.read_text(encoding="utf-8")
        self.assertNotIn('"sudo"', text)
        self.assertNotIn("steamapps", text)
        self.assertNotIn("userdata", text)


class WhatTheViewerSees(unittest.TestCase):

    def test_a_window_when_the_desktop_has_a_dialog_tool(self):
        environ = {"DISPLAY": ":0"}
        has = lambda *names: (lambda name: f"/usr/bin/{name}" if name in names else None)  # noqa: E731
        self.assertIsInstance(one_file.choose_ui("t", environ, has("kdialog", "zenity")),
                              one_file.ZenityUI)
        self.assertIsInstance(one_file.choose_ui("t", environ, has("kdialog")), one_file.KDialogUI)
        self.assertIsInstance(one_file.choose_ui("t", environ, has(), lambda: True),
                              one_file.TerminalUI)
        self.assertIsNone(one_file.choose_ui("t", environ, has(), lambda: False))

    def test_without_a_window_it_opens_itself_in_a_terminal(self):
        started = []
        found = one_file.open_in_terminal(
            ["python3", "-I", "launcher"], {"HOME": "/invented"},
            which=lambda name: "/usr/bin/konsole" if name == "konsole" else None,
            popen=lambda argv, env: started.append((argv, env)))
        self.assertTrue(found)
        argv, env = started[0]
        self.assertEqual(argv, ["/usr/bin/konsole", "-e", "python3", "-I", "launcher"])
        self.assertEqual(env[one_file.IN_TERMINAL], "1")
        # Opened that way, it waits for Enter before the window closes.
        self.assertTrue(one_file.choose_ui("t", env, lambda name: None).pause)

    def test_kdialog_asks_with_plain_buttons(self):
        calls = []

        class Done:
            returncode = 0
            stdout = "org.kde.kdialog-1 /ProgressDialog\n"

        window = one_file.KDialogUI("Install", run=lambda argv, **kw: calls.append(argv) or Done())
        self.assertTrue(window.ask("Install it?", "Install", "Cancel"))
        self.assertEqual(calls[0][:3], ["kdialog", "--title", "Install"])
        self.assertIn("--yesno", calls[0])
        window.step("Downloading…", 40)
        self.assertIn("--progressbar", calls[1])
        self.assertTrue(any("variant:int32:40" in argv for argv in calls[2:]))
        window.hide()
        self.assertTrue(calls[-1][-1].endswith("ProgressDialog.close"))


if __name__ == "__main__":
    unittest.main()
