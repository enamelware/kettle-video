# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Update and restart, and Pull the latest version (the Update and restart work).

backend/app_update.py, with the network replaced throughout: GitHub's
downloads by stand-ins that copy invented archives from a temporary folder
(or by a stand-in server on this device, for the download itself), the
copy's remote by a local git folder, and every other way out by fakes that
fail the test if touched (tests/test_updates.py's no_way_out). Installed
copies are invented ones (tests/test_installer.py) in a temporary home
folder, updated by the real shared update step (installer/update.py, the installer's update step).
Nothing here goes online or touches the real installed copy.

  - a checksum mismatch stops the update with nothing changed;
  - a failed download changes nothing, and the install step is never run;
  - a failed install or first start rolls back to the previous version and
    restarts it in place, with plain words for the toast;
  - the data folder (settings, library, logs) is byte-for-byte unchanged;
  - no update starts during playback, and no film starts during an update;
  - Cancel during the download leaves everything as it was;
  - the shared update logic is called, with no second checksum check or
    rollback here;
  - the development pull runs only on the action and refuses with local
    changes (or off main, or moved away from it);
  - the server's side: what the page is offered, the status it follows,
    the note after a restart, given once.

The restart in place through the real launch.sh is tests/test_restart_in_place.py.

Run: scripts/test.sh unit tests.test_app_update
"""

import contextlib
import http.client
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from backend import app_update, mpv, update_check
from backend import server as server_module
from backend.server import make_handler
from tests.test_installer import BROKEN_SERVER, ROOT, make_archive, snapshot
from tests.test_update import UpdateTestCase
from tests.test_updates import no_way_out

UI_DIR = ROOT / "ui"
BASE = app_update.DOWNLOAD_BASE


def release_answer(version, size=41_943_040, base=BASE):
    """GitHub's answer for an invented release, with its two files."""
    name = f"kettle-video-{version}.tar.gz"
    return {"tag_name": f"v{version}", "body": "- Invented change",
            "assets": [{"name": name, "size": size, "browser_download_url": f"{base}v{version}/{name}"},
                       {"name": f"{name}.sha256", "size": 90,
                        "browser_download_url": f"{base}v{version}/{name}.sha256"},
                       {"name": "install.sh", "size": 9000,
                        "browser_download_url": f"{base}v{version}/install.sh"}]}


class StandInDownloads:
    """GitHub's release files, copied from a local folder. Writes down each
    file asked for. gate: while cleared, the archive's download waits part
    way (so Cancel can be pressed); it checks Cancel between pieces, as the
    real download does."""

    def __init__(self, folder, fail=None):
        self.folder = Path(folder)
        self.asked = []
        self.fail = fail
        self.gate = threading.Event()
        self.gate.set()
        self.halfway = threading.Event()

    def __call__(self, url, dest, user_agent, cancel, progress, limit=app_update.MAX_DOWNLOAD):
        self.asked.append((url, user_agent))
        if self.fail is not None:
            raise self.fail
        data = (self.folder / url.rsplit("/", 1)[1]).read_bytes()
        pieces = [data[i:i + 4096] for i in range(0, len(data), 4096)] or [b""]
        with open(dest, "wb") as out:
            for number, piece in enumerate(pieces):
                if number == len(pieces) // 2:
                    self.halfway.set()
                    self.gate.wait(10)
                if cancel.is_set():
                    raise app_update.Cancelled()
                out.write(piece)
                progress(out.tell(), len(data))


def wait_for(predicate, timeout=60):
    end = time.time() + timeout
    while not predicate():
        if time.time() > end:
            raise AssertionError("waited too long")
        time.sleep(0.05)


class InstalledCopy(UpdateTestCase):
    """An invented installed copy (version 0.2.0) in a temporary home, with
    a person's settings, data and logs, and an Updater for it."""

    def setUp(self):
        super().setUp()
        self.install()
        self.put_things_in_place()
        self.before = self.theirs()
        self.root = Path(os.path.realpath(self.places["APP_DIR"]))
        self.files = self.tmp / "github"
        self.files.mkdir()
        self.lines, self.restarts = [], []
        self.playing = False
        self.downloads_stand_in = StandInDownloads(self.files)

    def updater(self, **extra):
        env = {"HOME": str(self.home), "PATH": os.environ["PATH"], "LANG": "C.UTF-8"}
        options = {"environ": env, "download": self.downloads_stand_in, **extra}
        return app_update.Updater(self.root, self.lines.append,
                                  restart=lambda root, note: self.restarts.append((Path(root), note)),
                                  is_playing=lambda: self.playing, **options)

    def offer(self, updater, version="0.3.0"):
        release = release_answer(version)
        result = update_check.release_result(release, "0.2.0", "kettle-video")
        return updater.offered(result, release)

    def run_update(self, updater, version="0.3.0"):
        self.offer(updater, version)
        self.assertIsNone(updater.start_update(version))
        wait_for(lambda: updater.status()["state"] not in app_update.RUNNING or self.restarts)
        return updater.status()

    def assert_nothing_changed(self):
        self.assertEqual(self.version(), "0.2.0")
        self.assertEqual(Path(os.path.realpath(self.places["APP_DIR"])), self.root)
        self.assertEqual(self.versions(), [self.root.name])
        self.assertEqual(self.theirs(), self.before)
        self.assertEqual(self.download_folders(), [])

    def download_folders(self):
        return [p.name for p in self.places["APP_DIR"].parent.iterdir()
                if p.name.startswith(app_update.DOWNLOAD_PREFIX)]


class WhatThePageIsOffered(InstalledCopy):

    def test_an_installed_copy_is_offered_update_and_restart_with_its_size(self):
        result = self.offer(self.updater())
        self.assertTrue(result["can_update"])
        self.assertEqual(result["download_text"], "About 40 MB")
        self.assertEqual(result["text"], "Version 0.3.0 is available")

    def test_files_from_anywhere_else_are_never_offered(self):
        updater = self.updater()
        for base in ("https://example.invalid/", "http://github.com/enamelware/kettle-video/releases/download/",
                     "https://github.com/someone-else/kettle-video/releases/download/"):
            with self.subTest(base=base):
                release = release_answer("0.3.0", base=base)
                result = updater.offered(update_check.release_result(release, "0.2.0", "kettle-video"), release)
                self.assertNotIn("can_update", result)
                self.assertEqual(updater.start_update("0.3.0"), app_update.NOT_OFFERED)

    def test_a_release_without_its_checksum_is_not_offered(self):
        release = release_answer("0.3.0")
        release["assets"] = release["assets"][:1]
        updater = self.updater()
        result = updater.offered(update_check.release_result(release, "0.2.0", "kettle-video"), release)
        self.assertNotIn("can_update", result)

    def test_a_copy_that_is_not_the_installed_one_is_never_offered_it(self):
        elsewhere = self.tmp / "unpacked"
        shutil.copytree(self.root, elsewhere, symlinks=True)
        updater = app_update.Updater(elsewhere, self.lines.append, restart=lambda r, n: None,
                                     is_playing=lambda: False, environ={"HOME": str(self.home)})
        release = release_answer("0.3.0")
        result = updater.offered(update_check.release_result(release, "0.2.0", "kettle-video"), release)
        self.assertNotIn("can_update", result)

    def test_only_a_version_that_was_offered_starts(self):
        updater = self.updater()
        self.assertEqual(updater.start_update("0.3.0"), app_update.NOT_OFFERED)  # no check yet
        self.offer(updater)
        self.assertEqual(updater.start_update("9.9.9"), app_update.NOT_OFFERED)
        self.assertEqual(self.downloads_stand_in.asked, [])

    def test_sizes(self):
        self.assertEqual(app_update.size_text(41_943_040), "About 40 MB")
        self.assertEqual(app_update.size_text(300_000), "Less than 1 MB")
        self.assertIsNone(app_update.size_text(None))


class UpdateAndRestart(InstalledCopy):

    def test_updates_through_the_shared_step_then_restarts_in_place(self):
        make_archive(self.files, "0.3.0")
        status = self.run_update(self.updater())
        new_root = Path(os.path.realpath(self.places["APP_DIR"]))
        self.assertEqual(self.restarts, [(new_root, "Updated to 0.3.0")], self.lines)
        self.assertEqual(status["state"], app_update.RESTARTING)
        self.assertEqual(self.version(), "0.3.0")
        self.assertEqual(self.versions(), [new_root.name])  # the previous version went
        self.assertEqual(self.theirs(), self.before)
        self.assertEqual(self.download_folders(), [])
        # The shared step's own words, in the launch log.
        self.assertIn("update: The checksum matches.", self.lines)
        self.assertIn("update: Checking that Kettle Video 0.3.0 starts cleanly", self.lines)

    def test_asks_for_the_archive_and_its_checksum_only_with_the_plain_user_agent(self):
        make_archive(self.files, "0.3.0")
        self.run_update(self.updater())
        self.assertEqual(self.downloads_stand_in.asked, [
            (f"{BASE}v0.3.0/kettle-video-0.3.0.tar.gz", "Kettle-Video/0.2.0"),
            (f"{BASE}v0.3.0/kettle-video-0.3.0.tar.gz.sha256", "Kettle-Video/0.2.0")])

    def test_progress_then_installing(self):
        make_archive(self.files, "0.3.0", extra={"ui/big.bin": (os.urandom(300_000), 0o644)})
        self.downloads_stand_in.gate.clear()
        updater = self.updater()
        self.offer(updater)
        self.assertIsNone(updater.start_update("0.3.0"))
        self.downloads_stand_in.halfway.wait(10)
        wait_for(lambda: updater.status()["text"] != "Downloading 0.3.0… 0%")
        self.assertRegex(updater.status()["text"], r"^Downloading 0\.3\.0… [1-9]\d?%$")
        self.downloads_stand_in.gate.set()
        wait_for(lambda: self.restarts)
        self.assertEqual(self.restarts[0][1], "Updated to 0.3.0")

    def test_a_checksum_mismatch_stops_with_nothing_changed(self):
        archive = make_archive(self.files, "0.3.0")
        Path(f"{archive}.sha256").write_text("0" * 64 + f"  {archive.name}\n")
        status = self.run_update(self.updater())
        self.assertEqual(status["state"], app_update.FAILED)
        self.assertEqual(status["text"], "The download of 0.3.0 was damaged, so nothing was changed. "
                                         "Try again later.")
        self.assertEqual(self.restarts, [])
        self.assert_nothing_changed()

    def test_a_failed_download_changes_nothing_and_installs_nothing(self):
        for fail, words in ((app_update.DownloadFailed("stand-in", offline=True),
                             "Couldn't download 0.3.0: no connection. Nothing was changed."),
                            (app_update.DownloadFailed("stand-in"),
                             "Couldn't download 0.3.0 right now. Nothing was changed. Try again later.")):
            with self.subTest(words=words):
                installed = []
                self.downloads_stand_in.fail = fail
                status = self.run_update(self.updater(installer=lambda *a, **k: installed.append(a)))
                self.assertEqual(status, {"state": app_update.FAILED, "text": words})
                self.assertEqual(installed, [])
                self.assertEqual(self.restarts, [])
                self.assert_nothing_changed()

    def test_a_first_start_that_fails_rolls_back_and_restarts_the_previous_version(self):
        make_archive(self.files, "0.3.0", server=BROKEN_SERVER)
        status = self.run_update(self.updater())
        self.assertEqual(self.restarts, [(self.root, "The update to 0.3.0 didn't work, so 0.2.0 was put "
                                                     "back as it was.")], self.lines)
        self.assertEqual(status["state"], app_update.RESTARTING)
        self.assertTrue(any("Rolled back" in line for line in self.lines), self.lines)
        self.assert_nothing_changed()

    def test_a_failed_install_step_rolls_back_too(self):
        make_archive(self.files, "0.3.0")
        installer = app_update.load_installer(self.root)

        def switch_fails(app_dir, folder):
            raise OSError(28, "No space left on device")

        with mock.patch.object(installer, "_point_app_at", side_effect=switch_fails):
            status = self.run_update(self.updater(installer=installer.install))
        self.assertEqual(status["state"], app_update.RESTARTING)
        self.assertEqual(self.restarts, [(self.root, "The update to 0.3.0 didn't work, so 0.2.0 was put "
                                                     "back as it was.")], self.lines)
        self.assert_nothing_changed()

    def test_cancel_during_the_download_leaves_everything_as_it_was(self):
        make_archive(self.files, "0.3.0", extra={"ui/big.bin": (os.urandom(300_000), 0o644)})
        self.downloads_stand_in.gate.clear()
        installed = []
        updater = self.updater(installer=lambda *a, **k: installed.append(a))
        self.offer(updater)
        self.assertIsNone(updater.start_update("0.3.0"))
        self.downloads_stand_in.halfway.wait(10)
        self.assertTrue(updater.cancel())
        self.downloads_stand_in.gate.set()
        wait_for(lambda: updater.status()["state"] not in app_update.RUNNING)
        self.assertEqual(updater.status(), {"state": app_update.CANCELLED, "text": app_update.CANCELLED_TEXT})
        self.assertEqual(installed, [])
        self.assertEqual(self.restarts, [])
        self.assert_nothing_changed()

    def test_cancel_does_nothing_once_installing_has_started(self):
        make_archive(self.files, "0.3.0")
        gate, started = threading.Event(), threading.Event()
        real = app_update.load_installer(self.root).install

        def slow_install(*args, **kwargs):
            started.set()
            gate.wait(10)
            return real(*args, **kwargs)

        updater = self.updater(installer=slow_install)
        self.offer(updater)
        updater.start_update("0.3.0")
        started.wait(10)
        self.assertEqual(updater.status()["state"], app_update.INSTALLING)
        self.assertEqual(updater.status()["text"], "Installing…")
        self.assertFalse(updater.cancel())
        gate.set()
        wait_for(lambda: self.restarts)
        self.assertEqual(self.version(), "0.3.0")

    def test_no_update_starts_during_playback(self):
        make_archive(self.files, "0.3.0")
        self.playing = True
        updater = self.updater()
        self.offer(updater)
        self.assertEqual(updater.start_update("0.3.0"), app_update.NOT_WHILE_PLAYING)
        self.assertEqual(updater.status()["state"], app_update.IDLE)
        self.assertEqual(self.downloads_stand_in.asked, [])
        self.assert_nothing_changed()

    def test_one_update_at_a_time(self):
        make_archive(self.files, "0.3.0", extra={"ui/big.bin": (os.urandom(300_000), 0o644)})
        self.downloads_stand_in.gate.clear()
        updater = self.updater()
        self.offer(updater)
        self.assertIsNone(updater.start_update("0.3.0"))
        self.assertEqual(updater.start_update("0.3.0"), app_update.ALREADY_UPDATING)
        self.assertEqual(updater.start_pull(), app_update.CANT_UPDATE_HERE)  # not a git copy
        self.downloads_stand_in.gate.set()
        wait_for(lambda: self.restarts)

    def test_a_download_folder_left_by_a_power_cut_goes_with_the_next_update(self):
        left = self.places["APP_DIR"].parent / f"{app_update.DOWNLOAD_PREFIX}abc123"
        left.mkdir()
        (left / "kettle-video-0.3.0.tar.gz").write_bytes(b"half")
        make_archive(self.files, "0.3.0")
        self.run_update(self.updater())
        self.assertEqual(self.download_folders(), [])


class OneCodePath(unittest.TestCase):
    """The checksum check and the rollback live in installer/update.py only."""

    def test_no_second_checksum_or_rollback_here(self):
        source = (ROOT / "backend" / "app_update.py").read_text(encoding="utf-8")
        for word in ("hashlib", "sha256(", "hexdigest", "_point_app_at", "os.replace", "os.rename",
                     "rollback(", "tarfile"):
            with self.subTest(word=word):
                self.assertNotIn(word, source)
        self.assertIn('load_installer(self.root).install', source)

    def test_the_install_step_used_is_the_copys_own_shared_one(self):
        installer = app_update.load_installer(ROOT)
        self.assertEqual(Path(installer.__file__), ROOT / "installer" / "update.py")
        self.assertTrue(callable(installer.install))


class TheDownload(unittest.TestCase):
    """The real download, against a stand-in GitHub on this device."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.data = os.urandom(200_000)
        self.requests = []
        self.gate = threading.Event()
        self.gate.set()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def do_GET(self):
                outer.requests.append({"path": self.path, "headers": dict(self.headers.items())})
                self.send_response(200)
                self.send_header("Content-Length", str(len(outer.data)))
                self.end_headers()
                try:
                    self.wfile.write(outer.data[:100_000])
                    self.wfile.flush()
                    outer.gate.wait(10)
                    self.wfile.write(outer.data[100_000:])
                except OSError:
                    pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        base = f"http://127.0.0.1:{self.httpd.server_address[1]}/"
        patcher = mock.patch.object(app_update, "DOWNLOAD_BASE", base)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.url = f"{base}v1.1.0/kettle-video-1.1.0.tar.gz"

    def test_downloads_with_progress_and_sends_nothing_else(self):
        seen = []
        dest = self.tmp / "file"
        app_update.download(self.url, dest, "Kettle-Video/1.0.0", threading.Event(),
                            lambda done, total: seen.append((done, total)))
        self.assertEqual(dest.read_bytes(), self.data)
        self.assertEqual(seen[0], (0, len(self.data)))
        self.assertEqual(seen[-1], (len(self.data), len(self.data)))
        headers = {k.lower(): v for k, v in self.requests[0]["headers"].items()}
        self.assertEqual(headers["user-agent"], "Kettle-Video/1.0.0")
        self.assertNotIn("cookie", headers)
        self.assertEqual(sorted(headers), ["accept", "accept-encoding", "connection", "host", "user-agent"])
        self.assertEqual(len(self.requests), 1)

    def test_cancel_between_pieces(self):
        cancel = threading.Event()
        self.gate.clear()

        def progress(done, total):
            if done >= 50_000:
                cancel.set()
                self.gate.set()

        with self.assertRaises(app_update.Cancelled):
            app_update.download(self.url, self.tmp / "file", "Kettle-Video/1.0.0", cancel, progress)

    def test_too_big_stops(self):
        with self.assertRaises(app_update.DownloadFailed):
            app_update.download(self.url, self.tmp / "file", "Kettle-Video/1.0.0", threading.Event(),
                                lambda d, t: None, limit=10_000)

    def test_only_this_apps_release_addresses(self):
        with self.assertRaises(app_update.DownloadFailed):
            app_update.download("https://example.invalid/file", self.tmp / "file", "Kettle-Video/1.0.0",
                                threading.Event(), lambda d, t: None)
        self.assertEqual(self.requests, [])

    def test_the_real_address_is_this_apps_github_releases(self):
        self.assertEqual(BASE, "https://github.com/enamelware/kettle-video/releases/download/")


def git(cwd, *args):
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          env=dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null",
                                   GIT_AUTHOR_NAME="Invented", GIT_AUTHOR_EMAIL="invented@example.invalid",
                                   GIT_COMMITTER_NAME="Invented", GIT_COMMITTER_EMAIL="invented@example.invalid"))
    if done.returncode != 0:
        raise AssertionError(done.stderr)
    return done.stdout.strip()


class PullTheLatestVersion(unittest.TestCase):
    """A development copy: a local clone of a local remote, nothing online."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        remote, work = self.tmp / "remote.git", self.tmp / "work"
        git(self.tmp, "init", "--quiet", "--bare", "-b", "main", str(remote))
        git(self.tmp, "clone", "--quiet", str(remote), str(work))
        (work / "VERSION").write_text("0.2.0-dev\n")
        (work / "app.txt").write_text("invented one\n")
        git(work, "add", ".")
        git(work, "commit", "--quiet", "-m", "one")
        git(work, "push", "--quiet", "origin", "main")
        self.copy = self.tmp / "copy"
        git(self.tmp, "clone", "--quiet", str(remote), str(self.copy))
        (self.copy / "settings.json").write_text("{}\n")  # untracked, like the real one
        # Main moves on, from elsewhere.
        (work / "app.txt").write_text("invented two\n")
        git(work, "commit", "--quiet", "-am", "two")
        git(work, "push", "--quiet", "origin", "main")
        self.newer = git(work, "rev-parse", "HEAD")
        self.before = git(self.copy, "rev-parse", "HEAD")
        self.lines, self.restarts, self.git_calls = [], [], []

    def updater(self, playing=False):
        def recording_git(root, args, timeout):
            self.git_calls.append(args[0])
            return update_check._git(root, args, timeout)

        return app_update.Updater(self.copy, self.lines.append,
                                  restart=lambda root, note: self.restarts.append((Path(root), note)),
                                  is_playing=lambda: playing, git=recording_git)

    def finish(self, updater):
        wait_for(lambda: updater.status()["state"] not in app_update.RUNNING or self.restarts, 30)
        return updater.status()

    def test_offered_on_a_newer_main_without_going_online(self):
        updater = self.updater()
        result = updater.offered({"state": "newer", "text": "A newer version is on main (abc1234)",
                                  "development": True}, None)
        self.assertTrue(result["can_pull"])
        self.assertNotIn("can_update", result)
        self.assertEqual(self.git_calls, [])

    def test_pulls_only_on_the_action_then_restarts_in_place(self):
        updater = self.updater()
        self.assertEqual(self.git_calls, [])
        self.assertIsNone(updater.start_pull())
        self.finish(updater)
        self.assertEqual(git(self.copy, "rev-parse", "HEAD"), self.newer)
        self.assertEqual((self.copy / "app.txt").read_text(), "invented two\n")
        self.assertEqual(self.restarts, [(self.copy, f"Updated to the latest version ({self.newer[:7]})")])
        self.assertEqual((self.copy / "settings.json").read_text(), "{}\n")

    def test_refuses_with_local_changes(self):
        (self.copy / "app.txt").write_text("a change of the copy's own\n")
        updater = self.updater()
        updater.start_pull()
        status = self.finish(updater)
        self.assertEqual(status, {"state": app_update.FAILED, "text": app_update.LOCAL_CHANGES})
        self.assertEqual(git(self.copy, "rev-parse", "HEAD"), self.before)
        self.assertEqual((self.copy / "app.txt").read_text(), "a change of the copy's own\n")
        self.assertNotIn("fetch", self.git_calls)
        self.assertEqual(self.restarts, [])

    def test_refuses_with_staged_changes(self):
        (self.copy / "new.txt").write_text("staged\n")
        git(self.copy, "add", "new.txt")
        updater = self.updater()
        updater.start_pull()
        self.assertEqual(self.finish(updater)["text"], app_update.LOCAL_CHANGES)
        self.assertEqual(git(self.copy, "rev-parse", "HEAD"), self.before)

    def test_refuses_off_main(self):
        git(self.copy, "switch", "--quiet", "-c", "issue-1")
        updater = self.updater()
        updater.start_pull()
        self.assertEqual(self.finish(updater)["text"], app_update.NOT_ON_MAIN)
        self.assertEqual(git(self.copy, "rev-parse", "HEAD"), self.before)

    def test_refuses_when_the_copy_moved_away_from_main(self):
        (self.copy / "other.txt").write_text("a commit main doesn't have\n")
        git(self.copy, "add", "other.txt")
        git(self.copy, "commit", "--quiet", "-m", "elsewhere")
        mine = git(self.copy, "rev-parse", "HEAD")
        updater = self.updater()
        updater.start_pull()
        self.assertEqual(self.finish(updater)["text"], app_update.MOVED_AWAY)
        self.assertEqual(git(self.copy, "rev-parse", "HEAD"), mine)
        self.assertEqual(self.restarts, [])

    def test_already_up_to_date_does_not_restart(self):
        git(self.copy, "pull", "--quiet", "--ff-only")
        updater = self.updater()
        updater.start_pull()
        status = self.finish(updater)
        self.assertEqual(status, {"state": app_update.IDLE, "text": f"Already up to date ({self.newer[:7]})"})
        self.assertEqual(self.restarts, [])

    def test_never_during_playback(self):
        updater = self.updater(playing=True)
        self.assertEqual(updater.start_pull(), app_update.NOT_WHILE_PLAYING)
        self.assertEqual(self.git_calls, [])

    def test_no_connection(self):
        git(self.copy, "remote", "set-url", "origin", str(self.tmp / "gone.git"))
        updater = self.updater()
        updater.start_pull()
        status = self.finish(updater)
        self.assertEqual(status["state"], app_update.FAILED)
        self.assertIn(status["text"], (app_update.PULL_OFFLINE, app_update.PULL_LATER))
        self.assertEqual(git(self.copy, "rev-parse", "HEAD"), self.before)

    def failing_git(self, fail_on):
        """git that fails the way fail_on(args, calls) says, else the real one."""
        calls = []

        def run(root, args, timeout):
            calls.append(args)
            problem = fail_on(args, calls)
            if problem is not None:
                raise problem
            return update_check._git(root, args, timeout)

        return app_update.Updater(self.copy, self.lines.append,
                                   restart=lambda root, note: self.restarts.append((Path(root), note)),
                                   is_playing=lambda: False, git=run)

    def assert_says_try_later(self, updater):
        self.assertIsNone(updater.start_pull())
        status = self.finish(updater)
        self.assertEqual(status, {"state": app_update.FAILED, "text": app_update.PULL_LATER})
        self.assertEqual(self.restarts, [])

    def test_git_that_cannot_run_ends_in_plain_words(self):
        updater = self.failing_git(lambda args, calls: FileNotFoundError(2, "No such file", "git"))
        self.assert_says_try_later(updater)
        self.assertEqual(git(self.copy, "rev-parse", "HEAD"), self.before)

    def test_git_failing_part_way_ends_in_plain_words(self):
        updater = self.failing_git(lambda args, calls: RuntimeError("invented") if args[0] == "fetch" else None)
        self.assert_says_try_later(updater)
        self.assertEqual(git(self.copy, "rev-parse", "HEAD"), self.before)

    def test_the_last_commit_lookup_timing_out_ends_in_plain_words(self):
        git(self.copy, "pull", "--quiet", "--ff-only")  # nothing new: the lookup comes last
        heads = []

        def fail_on(args, calls):
            if args[:1] == ["rev-parse"]:
                heads.append(args)
                if len(heads) == 3:
                    return update_check.CheckFailed("no answer in time")
            return None

        self.assert_says_try_later(self.failing_git(fail_on))

    def test_an_installed_copy_never_pulls(self):
        (self.copy / "kettle-video-installed").write_text("installed\n")
        self.assertEqual(self.updater().start_pull(), app_update.CANT_UPDATE_HERE)
        self.assertEqual(self.git_calls, [])


class TheServer(unittest.TestCase):
    """The server's side, with the network and the restart replaced."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        (self.tmp / "Films").mkdir()
        (self.tmp / "Films" / "Invented Film (2001).mkv").write_bytes(b"\0")
        (self.tmp / "share").mkdir()
        self.restarts = []
        self.gate = threading.Event()
        self.gate.set()

        def download(url, dest, agent, cancel, progress, limit=0):
            progress(0, 10)
            self.gate.wait(10)
            if cancel.is_set():
                raise app_update.Cancelled()
            raise app_update.DownloadFailed("stand-in")

        for target, name, value in ((update_check, "is_development", lambda root: False),
                                    (update_check, "fetch_latest", lambda version: release_answer("9.0.0")),
                                    (app_update, "installed_app_dir",
                                     lambda root, environ=None: self.tmp / "share" / "app"),
                                    (app_update, "download", download),
                                    (server_module, "request_restart",
                                     lambda ref, root, note: self.restarts.append(note))):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def start(self, httpd_ref=None):
        settings = {"movies_path": str(self.tmp / "Films"), "tv_path": "", "mpv_command": "mpv",
                    "mpv_args": [], "resume": False, "keep_awake": False, "data_dir": str(self.tmp / "data")}
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        self.port = httpd.server_address[1]
        ref = {"server": httpd, **(httpd_ref or {})}
        with contextlib.redirect_stdout(io.StringIO()):
            base = make_handler(UI_DIR, self.tmp, settings, ref, self.port)

        class Quiet(base):
            def log_message(self, format, *args):
                pass

        httpd.RequestHandlerClass = Quiet
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)

    def request(self, method, path, body=None):
        with contextlib.redirect_stdout(io.StringIO()):
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
            headers = {"Content-Type": "application/json"} if body is not None else {}
            conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
            resp = conn.getresponse()
            data = json.loads(resp.read() or b"null")
            conn.close()
        return resp.status, data

    def test_the_check_offers_update_and_restart_and_keeps_the_addresses_to_itself(self):
        self.start()
        status, answer = self.request("POST", "/api/updates/check", {})
        self.assertEqual(status, 200)
        self.assertTrue(answer["can_update"])
        self.assertEqual(answer["download_text"], "About 40 MB")
        self.assertNotIn("release", answer)
        self.assertNotIn("github.com", json.dumps(answer))

    def test_nothing_starts_before_a_check(self):
        self.start()
        status, answer = self.request("POST", "/api/updates/install", {"version": "9.0.0"})
        self.assertEqual((status, answer), (409, {"ok": False, "text": app_update.NOT_OFFERED}))

    def test_status_and_cancel_then_play_works_again(self):
        self.start()
        self.request("POST", "/api/updates/check", {})
        _, first = self.request("GET", "/api/updates/status")
        self.assertEqual(first["state"], "idle")
        self.gate.clear()
        status, answer = self.request("POST", "/api/updates/install", {"version": "9.0.0"})
        self.assertEqual(status, 200)
        self.assertTrue(answer["ok"])
        self.assertEqual(answer["boot"], first["boot"])
        _, now = self.request("GET", "/api/updates/status")
        self.assertEqual(now["state"], "downloading")
        # No film starts while it runs.
        found = {"available": True, "command": ["mpv"], "via": "configured"}
        with mock.patch.object(mpv, "detect", return_value=found), \
                mock.patch.object(mpv, "play", return_value={"ok": True}) as play:
            code, said = self.request("POST", "/api/play", {"source": "movies", "path": "Invented Film (2001).mkv"})
        self.assertEqual((code, said), (409, {"error": "updating"}))
        play.assert_not_called()
        self.assertEqual(self.request("POST", "/api/updates/cancel", {}), (200, {"ok": True}))
        self.gate.set()
        wait_for(lambda: self.request("GET", "/api/updates/status")[1]["state"] == "cancelled", 10)
        self.assertEqual(self.request("POST", "/api/updates/cancel", {}), (200, {"ok": False}))

    def test_no_update_while_a_film_plays(self):
        self.start()
        self.request("POST", "/api/updates/check", {})
        found = {"available": True, "command": ["mpv"], "via": "configured"}
        stop = threading.Event()
        with mock.patch.object(mpv, "detect", return_value=found), \
                mock.patch.object(mpv, "play", side_effect=lambda *a, **k: stop.wait(10) and {"ok": True}):
            code, _ = self.request("POST", "/api/play", {"source": "movies", "path": "Invented Film (2001).mkv"})
            self.assertEqual(code, 200)
            status, answer = self.request("POST", "/api/updates/install", {"version": "9.0.0"})
            stop.set()
        self.assertEqual((status, answer), (409, {"ok": False, "text": app_update.NOT_WHILE_PLAYING}))

    def test_the_note_after_a_restart_is_given_once(self):
        self.start({"update_note": "Updated to 9.0.0"})
        self.assertEqual(self.request("POST", "/api/updates/note", {}), (200, {"note": "Updated to 9.0.0"}))
        self.assertEqual(self.request("POST", "/api/updates/note", {}), (200, {"note": None}))

    def test_nothing_here_goes_online_by_itself(self):
        with no_way_out(self) as tried:
            self.start()
            for path in ("/api/updates/status", "/api/settings"):
                self.request("GET", path)
            self.request("POST", "/api/updates/note", {})
            self.request("POST", "/api/updates/install", {"version": "9.0.0"})
            self.request("POST", "/api/updates/cancel", {})
            time.sleep(1)
        self.assertEqual(tried, [])


class TheRestart(unittest.TestCase):
    """The server's restart is the same process becoming the new version."""

    def test_restart_in_place_replaces_this_process_from_the_new_folder(self):
        calls = []
        with mock.patch.object(os, "chdir", lambda path: calls.append(("chdir", path))), \
                mock.patch.object(os, "execve", lambda *a: calls.append(("execve",) + a)):
            app_update.restart_in_place(Path("/invented/new"), "Updated to 9.0.0", {"HOME": "/invented"})
        self.assertEqual(calls[0], ("chdir", Path("/invented/new")))
        _, program, argv, env = calls[1]
        self.assertEqual(argv[1:], ["-u", "-m", "backend.server"])
        self.assertEqual(env, {"HOME": "/invented", app_update.NOTE_ENV: "Updated to 9.0.0"})

    def test_the_server_restarts_only_after_stopping_and_never_when_closing(self):
        source = (ROOT / "backend" / "server.py").read_text(encoding="utf-8")
        main = source[source.index("def main():"):]
        self.assertLess(main.index("serve(repo_root()"), main.index("app_update.restart_in_place"))
        self.assertIn('if restart and not httpd_ref.get("stopping"):', main)
        self.assertRegex(main, re.compile(r'def _handle_signal.*\n\s+httpd_ref\["stopping"\] = True'))


if __name__ == "__main__":
    unittest.main()
