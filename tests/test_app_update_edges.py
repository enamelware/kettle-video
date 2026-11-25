# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Update and restart, and Pull the latest version: the edges (the Update and restart work).

Added by the test check, beside tests/test_app_update.py, for what it
didn't reach. Nothing here goes online; installed copies are invented ones
in a temporary home (tests/test_app_update.py's InstalledCopy), and the
development copy is a local git folder.

  - Cancel still works after the archive is in, while its checksum file
    downloads: nothing is installed and nothing changes;
  - when the install step itself fails to run, nothing restarts and the
    toast says plainly what to do;
  - when a rollback leaves the app folder somewhere else, nothing restarts
    into it and the toast says to run the installer again;
  - the pull checks again for changes just before it moves the copy on, so
    a change made while fetching is never gone over;
  - the server: Pull refuses while a film plays, a copy that isn't a
    development one is told it can't, and no film starts while a pull runs;
  - the server's start: it restarts in place only after stopping, never
    when the app is being closed meanwhile, closes cleanly if the restart
    can't happen, and keeps the restart's note away from what it starts.

Run: scripts/test.sh unit tests.test_app_update_edges
"""

import os
import threading
import unittest
from pathlib import Path
from unittest import mock

from backend import app_update, mpv, update_check
from backend import server as server_module
# The module, not its classes: their own tests run there, not again here.
from tests import test_app_update as base
from tests.test_installer import make_archive

wait_for = base.wait_for


class UpdateEdges(base.InstalledCopy):

    def test_cancel_while_the_checksum_downloads_installs_nothing(self):
        make_archive(self.files, "0.3.0")
        installed, holder = [], {}

        def download(url, dest, agent, cancel, progress, limit=app_update.MAX_DOWNLOAD):
            if url.endswith(".sha256"):
                # The viewer presses B now: the archive is in, installing hasn't started.
                self.assertTrue(holder["updater"].cancel())
            return self.downloads_stand_in(url, dest, agent, cancel, progress, limit)

        updater = self.updater(download=download, installer=lambda *a, **k: installed.append(a))
        holder["updater"] = updater
        status = self.run_update(updater)
        self.assertEqual(status, {"state": app_update.CANCELLED, "text": app_update.CANCELLED_TEXT})
        self.assertEqual(installed, [])
        self.assertEqual(self.restarts, [])
        self.assert_nothing_changed()

    def test_an_install_step_that_fails_to_run_restarts_nothing(self):
        make_archive(self.files, "0.3.0")

        def broken_installer(*args, **kwargs):
            raise RuntimeError("stand-in: the shared step broke")

        status = self.run_update(self.updater(installer=broken_installer))
        self.assertEqual(status["state"], app_update.FAILED)
        self.assertEqual(status["text"], "Couldn't update to 0.3.0. Try again later, or run the installer again.")
        self.assertEqual(self.restarts, [])
        self.assertEqual(self.download_folders(), [])
        self.assertEqual(self.theirs(), self.before)

    def test_a_rollback_that_leaves_the_app_elsewhere_restarts_nothing(self):
        make_archive(self.files, "0.3.0")
        app_dir = self.places["APP_DIR"]
        elsewhere = app_dir.parent / "versions" / "invented-elsewhere"

        def rolled_back_elsewhere(*args, **kwargs):
            elsewhere.mkdir()
            os.remove(app_dir)
            os.symlink(elsewhere, app_dir)
            return type("Result", (), {"outcome": "rolled back", "message": "Rolled back."})()

        status = self.run_update(self.updater(installer=rolled_back_elsewhere))
        self.assertEqual(self.restarts, [])
        self.assertEqual(status["state"], app_update.FAILED)
        self.assertEqual(status["text"], "The update to 0.3.0 didn't work and 0.2.0 couldn't be put back. "
                                         "Run the installer again.")
        self.assertEqual(self.theirs(), self.before)

    def test_a_refusal_by_the_shared_step_restarts_nothing(self):
        make_archive(self.files, "0.3.0")
        result = type("Result", (), {"outcome": "stopped", "message": "Stopped: invented reason."})()
        status = self.run_update(self.updater(installer=lambda *a, **k: result))
        self.assertEqual(status["state"], app_update.FAILED)
        self.assertEqual(status["text"], "Couldn't update to 0.3.0, so nothing was changed. Try again later.")
        self.assertEqual(self.restarts, [])
        self.assert_nothing_changed()


class PullEdges(unittest.TestCase):
    """A development copy behind a newer main (the same set-up as there)."""

    setUp = base.PullTheLatestVersion.setUp
    finish = base.PullTheLatestVersion.finish

    def test_a_change_made_while_fetching_is_never_pulled_over(self):
        calls = []

        def git(root, args, timeout):
            calls.append(args[0])
            done = update_check._git(root, args, timeout)
            if args[0] == "fetch":
                (self.copy / "app.txt").write_text("a change of its own, made while fetching\n")
            return done

        updater = app_update.Updater(self.copy, self.lines.append,
                                     restart=lambda root, note: self.restarts.append((root, note)),
                                     is_playing=lambda: False, git=git)
        self.assertIsNone(updater.start_pull())
        status = self.finish(updater)
        self.assertEqual(status, {"state": app_update.FAILED, "text": app_update.LOCAL_CHANGES})
        self.assertIn("fetch", calls)
        self.assertNotIn("merge", calls)
        self.assertEqual((self.copy / "app.txt").read_text(), "a change of its own, made while fetching\n")
        self.assertEqual(self.restarts, [])


class ServerPull(unittest.TestCase):
    """Pull the latest version through the server, with git replaced."""

    setUp = base.TheServer.setUp
    start = base.TheServer.start
    request = base.TheServer.request

    def pull_stand_in(self):
        self.pulls = []
        self.pull_gate = threading.Event()
        self.pull_gate.set()

        def pull_main(updater):
            self.pulls.append(True)
            self.pull_gate.wait(10)
            return app_update.LOCAL_CHANGES, None

        patcher = mock.patch.object(app_update.Updater, "_pull_main", pull_main)
        patcher.start()
        self.addCleanup(patcher.stop)

    def development(self, on):
        patcher = mock.patch.object(update_check, "is_development", lambda root: on)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_copy_that_isnt_a_development_one_cant_pull(self):
        self.pull_stand_in()
        self.start()
        status, answer = self.request("POST", "/api/updates/pull", {})
        self.assertEqual((status, answer), (409, {"ok": False, "text": app_update.CANT_UPDATE_HERE}))
        self.assertEqual(self.pulls, [])

    def test_no_pull_while_a_film_plays(self):
        self.development(True)
        self.pull_stand_in()
        self.start()
        found = {"available": True, "command": ["mpv"], "via": "configured"}
        stop = threading.Event()
        with mock.patch.object(mpv, "detect", return_value=found), \
                mock.patch.object(mpv, "play", side_effect=lambda *a, **k: stop.wait(10) and {"ok": True}):
            code, _ = self.request("POST", "/api/play", {"source": "movies", "path": "Invented Film (2001).mkv"})
            self.assertEqual(code, 200)
            status, answer = self.request("POST", "/api/updates/pull", {})
            stop.set()
        self.assertEqual((status, answer), (409, {"ok": False, "text": app_update.NOT_WHILE_PLAYING}))
        self.assertEqual(self.pulls, [])

    def test_no_film_starts_while_a_pull_runs_then_it_says_why(self):
        self.development(True)
        self.pull_stand_in()
        self.pull_gate.clear()
        self.start()
        status, answer = self.request("POST", "/api/updates/pull", {})
        self.assertEqual(status, 200)
        self.assertEqual(answer["state"], app_update.PULLING)
        found = {"available": True, "command": ["mpv"], "via": "configured"}
        with mock.patch.object(mpv, "detect", return_value=found), \
                mock.patch.object(mpv, "play", return_value={"ok": True}) as play:
            code, said = self.request("POST", "/api/play", {"source": "movies", "path": "Invented Film (2001).mkv"})
        self.assertEqual((code, said), (409, {"error": "updating"}))
        play.assert_not_called()
        # B does nothing to a pull: only a download can be cancelled.
        self.assertEqual(self.request("POST", "/api/updates/cancel", {}), (200, {"ok": False}))
        self.pull_gate.set()
        wait_for(lambda: self.request("GET", "/api/updates/status")[1]["state"] == app_update.FAILED, 10)
        self.assertEqual(self.request("GET", "/api/updates/status")[1]["text"], app_update.LOCAL_CHANGES)
        self.assertEqual(self.restarts, [])


class ServerStart(unittest.TestCase):
    """backend.server.main(): the restart after the server stopped."""

    def run_main(self, after_serve, restart=None):
        seen = {}

        def serve(root, environ, port, ref):
            seen["ref"] = dict(ref)
            seen["note_in_environ"] = app_update.NOTE_ENV in os.environ
            after_serve(ref)

        restarts = []
        patches = [mock.patch.object(server_module.vendor_path, "use_vendor", lambda: None),
                   mock.patch.object(server_module.signal, "signal", lambda *a: None),
                   mock.patch.object(server_module, "serve", serve),
                   mock.patch.object(server_module, "_log", lambda text: None),
                   mock.patch.object(app_update, "restart_in_place",
                                     restart or (lambda root, note: restarts.append((root, note)))),
                   mock.patch.dict(os.environ, {app_update.NOTE_ENV: "Updated to 9.0.0"})]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        server_module.main()
        return seen, restarts

    def test_restarts_in_place_after_the_server_stopped(self):
        root = Path("/invented/new")
        seen, restarts = self.run_main(lambda ref: ref.update(restart=(root, "Updated to 9.1.0")))
        self.assertEqual(restarts, [(root, "Updated to 9.1.0")])

    def test_the_note_is_for_the_page_only(self):
        seen, _ = self.run_main(lambda ref: None)
        self.assertEqual(seen["ref"]["update_note"], "Updated to 9.0.0")
        # Never passed on to mpv or anything else this server starts.
        self.assertFalse(seen["note_in_environ"])

    def test_no_restart_when_the_app_is_being_closed(self):
        root = Path("/invented/new")
        _, restarts = self.run_main(lambda ref: ref.update(restart=(root, "Updated to 9.1.0"), stopping=True))
        self.assertEqual(restarts, [])

    def test_no_restart_after_a_plain_stop(self):
        _, restarts = self.run_main(lambda ref: None)
        self.assertEqual(restarts, [])

    def test_a_restart_that_cant_happen_closes_the_app_plainly(self):
        def cannot(root, note):
            raise OSError(2, "invented: no such file")

        with self.assertRaises(SystemExit) as stopped:
            self.run_main(lambda ref: ref.update(restart=(Path("/invented/new"), "n")), restart=cannot)
        self.assertEqual(stopped.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
