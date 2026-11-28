# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Try a branch, Back to main and Restore data (the "Try a branch" work).

backend/try_branch.py and its part of backend/app_update.py, on invented
development copies: a local clone of a local remote in a temporary folder,
with an invented settings.json and data folder. GitHub's pull request list
and the installer's start check are stand-ins; nothing here goes online,
and this repository's own git state is never touched.

  - the rows appear only on a development copy with its own data folder,
    never on a release install;
  - nothing runs, and nothing goes online, without the designer's action;
  - branches with an open pull request come first, with issue number and
    title; without the pull request list, branches are still listed;
  - both switches refuse with local changes and leave the copy untouched;
  - the data is backed up before every switch into the data folder's own
    "backups" folder, without media files; a failed backup stops the
    switch; only the last 3 backups are kept;
  - a branch that doesn't start cleanly is left again, its backup removed;
  - Restore asks for the newest backup by its id, names its branch and
    date, and puts the data back exactly;
  - a data folder that isn't the copy's own is never backed up or restored.

Run: scripts/test.sh unit tests.test_try_branch
"""

import contextlib
import http.client
import io
import json
import os
import shutil
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from backend import app_update, try_branch, update_check
from backend import server as server_module
from backend.server import make_handler
from tests.test_app_update import UI_DIR, git, wait_for

PULLS = [{"branch": "issue-40", "number": 41, "title": "Movies detail screen"},
         {"branch": "issue-42", "number": 43, "title": "Refs #43: Invented season picker"},
         {"branch": "gone-away", "number": 44, "title": "A branch no longer there"}]


def snapshot(folder: Path, skip=()) -> dict:
    """Every file under folder: its bytes, or where a shortcut points."""
    found = {}
    for path in sorted(Path(folder).rglob("*")):
        rel = path.relative_to(folder).as_posix()
        if rel.split("/")[0] in skip:
            continue
        if path.is_symlink():
            found[rel] = ("link", os.readlink(path))
        elif path.is_file():
            found[rel] = path.read_bytes()
        else:
            found[rel] = "folder"
    return found


class DevelopmentCopy(unittest.TestCase):
    """An invented development copy on main, with branches on its remote."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        remote, work = self.tmp / "remote.git", self.tmp / "work"
        git(self.tmp, "init", "--quiet", "--bare", "-b", "main", str(remote))
        git(self.tmp, "clone", "--quiet", str(remote), str(work))
        (work / "VERSION").write_text("0.2.0-dev\n")
        (work / "app.txt").write_text("invented main\n")
        (work / ".gitignore").write_text("/settings.json\ndata/\nlogs/\n")
        git(work, "add", ".")
        git(work, "commit", "--quiet", "-m", "one")
        git(work, "push", "--quiet", "origin", "main")
        for branch in ("issue-40", "issue-42", "tidy-words"):
            git(work, "switch", "--quiet", "-c", branch, "main")
            (work / "app.txt").write_text(f"invented {branch}\n")
            git(work, "commit", "--quiet", "-am", branch)
            git(work, "push", "--quiet", "origin", branch)
        self.work = work
        self.copy = self.tmp / "copy"
        git(self.tmp, "clone", "--quiet", str(remote), str(self.copy))
        self.settings_file = self.copy / "settings.json"
        self.settings_file.write_text(json.dumps({"movies": str(self.tmp / "Films"), "tv": ""}) + "\n")
        self.data = self.copy / "data"
        (self.data / "thumbnails").mkdir(parents=True)
        (self.data / "library.json").write_text('{"invented": "library"}\n')
        (self.data / "continue.json").write_text('{"invented": "continue"}\n')
        (self.data / "thumbnails" / "a1.jpg").write_bytes(b"\xff\xd8invented")
        (self.tmp / "Films").mkdir()
        self.film = self.tmp / "Films" / "Invented Film (2001).mkv"
        self.film.write_bytes(b"invented film bytes")
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.lines, self.restarts, self.git_calls, self.pull_calls, self.checks = [], [], [], [], []
        self.pulls = list(PULLS)
        self.start_ok = (True, "")
        self.clock = datetime(2026, 11, 27, 14, 5, 0)

    def fake_pulls(self, version):
        self.pull_calls.append(version)
        if isinstance(self.pulls, Exception):
            raise self.pulls
        return self.pulls

    def now(self):
        self.clock += timedelta(minutes=1)
        return self.clock

    def updater(self, playing=False, data_dir=True, media=None):
        def recording_git(root, args, timeout):
            self.git_calls.append(args[0])
            return update_check._git(root, args, timeout)

        def start_check(root, environ):
            self.checks.append((Path(root), git(root, "rev-parse", "--abbrev-ref", "HEAD")))
            return self.start_ok

        return app_update.Updater(
            self.copy, self.lines.append,
            restart=lambda root, note: self.restarts.append((Path(root), note)),
            is_playing=lambda: playing, git=recording_git, environ={"HOME": str(self.home)},
            data_dir=self.data if data_dir else None, settings_file=self.settings_file if data_dir else None,
            media_roots=lambda: media if media is not None else [str(self.tmp / "Films"), ""],
            pulls=self.fake_pulls, start_check=start_check, now=self.now)

    def finish(self, updater, restarts=None):
        count = len(self.restarts) if restarts is None else restarts
        wait_for(lambda: updater.status()["state"] not in app_update.RUNNING or len(self.restarts) > count, 30)
        return updater.status()

    def branch(self):
        return git(self.copy, "rev-parse", "--abbrev-ref", "HEAD")

    def switch(self, updater, branch="issue-40"):
        updater.list_branches()
        count = len(self.restarts)
        self.assertIsNone(updater.start_switch(branch))
        self.finish(updater, count)


class OnlyOnDevelopmentCopies(DevelopmentCopy):

    def test_a_release_install_has_no_branch_rows_and_runs_none(self):
        (self.copy / "kettle-video-installed").write_text("")
        updater = self.updater()
        self.assertFalse(updater.can_switch())
        self.assertIsNone(updater.branch_state())
        self.assertEqual(updater.list_branches(), {"ok": False, "text": app_update.CANT_UPDATE_HERE})
        self.assertEqual(updater.start_switch("issue-40"), app_update.CANT_UPDATE_HERE)
        self.assertEqual(updater.start_back_to_main(), app_update.CANT_UPDATE_HERE)
        self.assertEqual(updater.start_restore("20261127-140600"), app_update.CANT_UPDATE_HERE)
        self.assertEqual(self.branch(), "main")
        self.assertEqual(self.pull_calls, [])
        self.assertFalse((self.data / try_branch.BACKUPS).exists())

    def test_a_copy_that_isnt_a_git_checkout_has_none(self):
        shutil.rmtree(self.copy / ".git")
        self.assertIsNone(self.updater().branch_state())

    def test_without_its_own_data_folder_none(self):
        # A fresh start, and tests that pass no settings file.
        updater = self.updater(data_dir=False)
        self.assertIsNone(updater.branch_state())
        self.assertEqual(updater.start_back_to_main(), app_update.CANT_UPDATE_HERE)

    def test_on_main_the_state_reads_the_device_only(self):
        state = self.updater().branch_state()
        self.assertEqual(state, {"on": None, "restore": None})
        self.assertNotIn("fetch", self.git_calls)
        self.assertNotIn("ls-remote", self.git_calls)
        self.assertEqual(self.pull_calls, [])


class TheList(DevelopmentCopy):

    def test_open_pull_requests_first_with_issue_number_and_title(self):
        answer = self.updater().list_branches()
        self.assertTrue(answer["ok"])
        self.assertTrue(answer["titles"])
        rows = [(r["branch"], r["label"], r["desc"], r["pull"]) for r in answer["branches"]]
        self.assertEqual(rows, [
            ("issue-42", "#42 · Invented season picker", None, True),
            ("issue-40", "#40 · Movies detail screen", None, True),
            ("tidy-words", "tidy-words", None, False),
        ])
        self.assertEqual(self.pull_calls, ["0.2.0-dev"])
        self.assertEqual(self.branch(), "main")

    def test_a_pull_request_branch_not_named_after_its_issue_keeps_its_name_under_the_title(self):
        rows = try_branch.picker_list(["main", "tidy-words"],
                                      [{"branch": "tidy-words", "number": 44, "title": "Invented tidy-up"}], "main")
        self.assertEqual([(r["label"], r["desc"]) for r in rows], [("#44 · Invented tidy-up", "tidy-words")])

    def test_without_the_pull_request_list_the_branches_are_still_listed(self):
        self.pulls = update_check.CheckFailed("GitHub answered 403")
        answer = self.updater().list_branches()
        self.assertTrue(answer["ok"])
        self.assertFalse(answer["titles"])
        self.assertEqual([r["label"] for r in answer["branches"]], ["issue-40", "issue-42", "tidy-words"])

    def test_no_connection(self):
        git(self.copy, "remote", "set-url", "origin", str(self.tmp / "gone.git"))
        answer = self.updater().list_branches()
        self.assertFalse(answer["ok"])
        self.assertIn(answer["text"], (try_branch.LIST_LATER, try_branch.LIST_OFFLINE))

    def test_the_branch_the_copy_is_on_is_marked(self):
        git(self.copy, "switch", "--quiet", "issue-40")
        rows = self.updater().list_branches()["branches"]
        self.assertEqual([r["branch"] for r in rows if r["current"]], ["issue-40"])

    def test_only_a_listed_branch_is_switched_to(self):
        updater = self.updater()
        self.assertEqual(updater.start_switch("issue-40"), try_branch.NOT_LISTED)
        updater.list_branches()
        self.assertEqual(updater.start_switch("main"), try_branch.NOT_LISTED)
        self.assertEqual(updater.start_switch("../elsewhere"), try_branch.NOT_LISTED)
        self.assertEqual(self.branch(), "main")


class Switching(DevelopmentCopy):

    def test_backs_up_then_switches_then_restarts_in_place(self):
        before = snapshot(self.data)
        settings_before = self.settings_file.read_bytes()
        updater = self.updater()
        self.switch(updater)
        self.assertEqual(self.branch(), "issue-40")
        self.assertEqual((self.copy / "app.txt").read_text(), "invented issue-40\n")
        self.assertEqual(self.restarts, [(self.copy, "Now on #40 · Movies detail screen")])
        self.assertEqual(self.checks, [(self.copy, "issue-40")])
        backups = try_branch.list_backups(self.data)
        self.assertEqual(len(backups), 1)
        self.assertEqual(snapshot(backups[0]["path"] / "data"), before)
        self.assertEqual((backups[0]["path"] / "settings.json").read_bytes(), settings_before)
        self.assertEqual((backups[0]["from"], backups[0]["to"]), ("main", "issue-40"))
        # The switch itself changes none of the data.
        self.assertEqual(snapshot(self.data, skip=("backups",)), before)
        self.assertEqual(self.settings_file.read_bytes(), settings_before)

    def test_never_copies_media_and_keeps_shortcuts_as_shortcuts(self):
        os.symlink(self.film, self.data / "a-shortcut.mkv")
        self.switch(self.updater())
        backup = try_branch.list_backups(self.data)[0]["path"]
        copied = backup / "data" / "a-shortcut.mkv"
        self.assertTrue(copied.is_symlink())
        self.assertNotIn(b"invented film bytes", b"".join(
            p.read_bytes() for p in backup.rglob("*") if p.is_file() and not p.is_symlink()))
        self.assertEqual(self.film.read_bytes(), b"invented film bytes")

    def test_refuses_with_local_changes_and_leaves_everything(self):
        (self.copy / "app.txt").write_text("a change of its own\n")
        updater = self.updater()
        self.switch(updater)
        self.assertEqual(updater.status(), {"state": app_update.FAILED, "text": try_branch.LOCAL_CHANGES})
        self.assertEqual(self.branch(), "main")
        self.assertEqual((self.copy / "app.txt").read_text(), "a change of its own\n")
        self.assertEqual(try_branch.list_backups(self.data), [])
        self.assertEqual(self.restarts, [])

    def test_back_to_main_refuses_with_local_changes_too(self):
        self.switch(self.updater())
        (self.copy / "app.txt").write_text("a change of its own\n")
        updater = self.updater()
        self.assertIsNone(updater.start_back_to_main())
        self.finish(updater)
        self.assertEqual(updater.status()["text"], try_branch.LOCAL_CHANGES)
        self.assertEqual(self.branch(), "issue-40")
        self.assertEqual(len(try_branch.list_backups(self.data)), 1)

    def test_a_failed_backup_stops_the_switch(self):
        updater = self.updater()
        with mock.patch.object(try_branch, "make_backup", side_effect=OSError(28, "No space left")):
            self.switch(updater)
        self.assertEqual(updater.status()["text"], try_branch.BACKUP_FAILED)
        self.assertEqual(self.branch(), "main")
        self.assertEqual(self.restarts, [])

    def test_a_backup_cut_short_leaves_nothing_behind(self):
        real = try_branch._copy_entry

        def failing(source, target):
            if source.name == "continue.json":
                raise OSError(28, "No space left")
            return real(source, target)

        updater = self.updater()
        with mock.patch.object(try_branch, "_copy_entry", failing):
            self.switch(updater)
        self.assertEqual(updater.status()["text"], try_branch.BACKUP_FAILED)
        self.assertEqual(list((self.data / "backups").iterdir()), [])
        self.assertEqual(self.branch(), "main")

    def test_only_the_last_three_backups_are_kept(self):
        made = []
        for branch in ("issue-40", "issue-42", "tidy-words", "issue-40"):
            # Each switch restarts the app, so each has a new updater.
            self.switch(self.updater(), branch)
            made.append(try_branch.list_backups(self.data)[0]["id"])
        kept = [b["id"] for b in try_branch.list_backups(self.data)]
        self.assertEqual(kept, list(reversed(made[1:])))
        self.assertFalse((self.data / "backups" / made[0]).exists())

    def test_a_branch_that_does_not_start_is_left_again(self):
        self.start_ok = (False, "it stopped as soon as it started.")
        updater = self.updater()
        self.switch(updater)
        self.assertEqual(self.branch(), "main")
        self.assertEqual(self.checks, [(self.copy, "issue-40")])
        self.assertEqual(try_branch.list_backups(self.data), [])
        self.assertEqual(self.restarts, [])
        self.assertEqual(updater.status()["text"], try_branch.didnt_start_text(
            "#40 · Movies detail screen", "main", "it stopped as soon as it started."))

    def test_a_local_branch_with_commits_of_its_own_is_never_moved(self):
        git(self.copy, "switch", "--quiet", "-c", "issue-40")
        (self.copy / "app.txt").write_text("its own\n")
        git(self.copy, "commit", "--quiet", "-am", "its own")
        mine = git(self.copy, "rev-parse", "HEAD")
        git(self.copy, "switch", "--quiet", "main")
        updater = self.updater()
        self.switch(updater)
        self.assertEqual(updater.status()["text"], try_branch.OWN_COMMITS.format(branch="issue-40"))
        self.assertEqual(git(self.copy, "rev-parse", "issue-40"), mine)
        self.assertEqual(self.branch(), "main")
        self.assertEqual(try_branch.list_backups(self.data), [])

    def test_a_branch_gone_from_the_remote(self):
        updater = self.updater()
        updater.list_branches()
        git(self.work, "push", "--quiet", "origin", "--delete", "tidy-words")
        self.assertIsNone(updater.start_switch("tidy-words"))
        self.finish(updater)
        self.assertEqual(updater.status()["text"], try_branch.NO_SUCH_BRANCH)
        self.assertEqual(self.branch(), "main")

    def test_never_during_playback(self):
        updater = self.updater(playing=True)
        updater.list_branches()
        self.assertEqual(updater.start_switch("issue-40"), app_update.NOT_WHILE_PLAYING)
        self.assertEqual(self.branch(), "main")
        git(self.copy, "switch", "--quiet", "issue-40")
        self.assertEqual(updater.start_back_to_main(), app_update.NOT_WHILE_PLAYING)
        self.assertEqual(updater.start_restore("20261127-140600"), try_branch.NO_BACKUP)
        self.assertEqual(self.branch(), "issue-40")

    def test_back_to_main_never_goes_online(self):
        self.switch(self.updater())
        self.git_calls.clear()
        updater = self.updater()
        self.assertEqual(updater.branch_state()["on"], {"branch": "issue-40", "label": "#40 · Movies detail screen"})
        self.assertIsNone(updater.start_back_to_main())
        self.finish(updater, 1)
        self.assertEqual(self.branch(), "main")
        self.assertEqual(self.restarts[-1], (self.copy, "Back on main"))
        self.assertNotIn("fetch", self.git_calls)
        self.assertNotIn("ls-remote", self.git_calls)
        self.assertEqual(len(self.pull_calls), 1)  # only the first list
        self.assertEqual([(b["from"], b["to"]) for b in try_branch.list_backups(self.data)],
                         [("issue-40", "main"), ("main", "issue-40")])
        self.assertEqual(self.updater().start_back_to_main(), try_branch.ALREADY_ON_MAIN)


class Restoring(DevelopmentCopy):

    def test_restore_names_the_branch_and_date_and_puts_the_data_back_exactly(self):
        before = snapshot(self.data)
        settings_before = self.settings_file.read_bytes()
        self.switch(self.updater())
        # On the branch, the app changes things.
        (self.data / "library.json").write_text('{"changed": "on the branch"}\n')
        (self.data / "thumbnails" / "a1.jpg").unlink()
        (self.data / "new-on-branch.json").write_text("{}\n")
        self.settings_file.write_text('{"movies": "elsewhere"}\n')
        updater = self.updater()
        state = updater.branch_state()
        restore = state["restore"]
        self.assertEqual(restore["text"], "Saved 27 November at 14:06, on main")
        self.assertIn("27 November at 14:06, on main", restore["question"])
        self.assertIsNone(updater.start_restore(restore["id"]))
        self.finish(updater, 1)
        self.assertEqual(snapshot(self.data, skip=("backups",)), before)
        self.assertEqual(self.settings_file.read_bytes(), settings_before)
        self.assertEqual(self.restarts[-1], (self.copy, "Your data is back as it was on 27 November at 14:06"))
        # The backup stays, and nothing is left from the restore itself.
        self.assertEqual([p.name for p in (self.data / "backups").iterdir()], [restore["id"]])
        self.assertEqual(self.branch(), "issue-40")

    def test_only_the_newest_backup_and_only_by_its_id(self):
        updater = self.updater()
        self.assertEqual(updater.start_restore("20261127-140600"), try_branch.NO_BACKUP)
        self.switch(self.updater())
        self.switch(self.updater(), "issue-42")
        updater = self.updater()
        oldest = try_branch.list_backups(self.data)[-1]["id"]
        self.assertEqual(updater.start_restore(oldest), try_branch.NO_BACKUP)
        self.assertEqual(updater.start_restore("../../elsewhere"), try_branch.NO_BACKUP)

    def test_a_restore_cut_short_puts_back_what_was_there(self):
        self.switch(self.updater())
        (self.data / "library.json").write_text('{"changed": "on the branch"}\n')
        now = snapshot(self.data, skip=("backups",))
        real_rename = os.rename
        placed = {"n": 0}

        def failing(source, target):
            # The second file put in place fails, once: the rest is undone.
            if Path(target).parent == self.data and Path(source).parent.name.startswith(".restoring-"):
                placed["n"] += 1
                if placed["n"] == 2:
                    raise OSError(5, "invented failure")
            return real_rename(source, target)

        updater = self.updater()
        with mock.patch.object(try_branch.os, "rename", failing):
            self.assertIsNone(updater.start_restore(try_branch.list_backups(self.data)[0]["id"]))
            self.finish(updater, 1)
        self.assertEqual(updater.status()["text"], try_branch.RESTORE_FAILED)
        self.assertEqual(snapshot(self.data, skip=("backups",)), now)
        self.assertEqual(len(self.restarts), 1)


class TheDataFolderIsTheCopysOwn(DevelopmentCopy):

    def test_a_data_folder_inside_a_media_folder_is_refused(self):
        updater = self.updater(media=[str(self.copy)])
        self.switch(updater)
        self.assertEqual(updater.status()["text"], try_branch.UNSAFE_DATA)
        self.assertEqual(self.branch(), "main")
        self.assertFalse((self.data / "backups").exists())

    def test_a_data_folder_holding_a_media_folder_is_refused(self):
        updater = self.updater(media=[str(self.data / "Films")])
        self.switch(updater)
        self.assertEqual(updater.status()["text"], try_branch.UNSAFE_DATA)

    def test_an_installed_copys_data_is_never_touched(self):
        installed = self.home / ".local" / "share" / "kettle-video" / "data"
        installed.mkdir(parents=True)
        (installed / "library.json").write_text('{"installed": true}\n')
        self.data = installed
        updater = self.updater()
        self.switch(updater)
        self.assertEqual(updater.status()["text"], try_branch.UNSAFE_DATA)
        self.assertEqual(sorted(p.name for p in installed.iterdir()), ["library.json"])
        self.assertEqual(updater.start_restore("20261127-140600"), try_branch.NO_BACKUP)


class PureParts(unittest.TestCase):

    def test_the_pull_request_request_carries_no_token(self):
        request = try_branch.pulls_request("1.0.1")
        self.assertEqual(request.full_url,
                         "https://api.github.com/repos/enamelware/kettle-video/pulls?state=open&per_page=100")
        self.assertEqual({k.lower() for k in request.headers}, {"user-agent", "accept"})

    def test_only_what_the_picker_needs_from_githubs_answer(self):
        answer = [{"number": 7, "title": " Invented ", "head": {"ref": "issue-6", "sha": "x"},
                   "user": {"login": "someone"}}, {"number": "8"}, "junk"]
        self.assertEqual(try_branch.pulls_from(answer), [{"branch": "issue-6", "number": 7, "title": "Invented"}])
        self.assertEqual(try_branch.pulls_from({"message": "rate limited"}), [])

    def test_backup_names_and_prune_touch_only_the_apps_own_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            folder = data / "backups"
            folder.mkdir()
            (folder / "someone-elses").mkdir()
            (folder / ".making-x").mkdir()
            for minute in range(5):
                try_branch.make_backup(data, data / "none.json", {"from": "main"},
                                       datetime(2026, 1, 1, 10, minute), keep=3)
            names = sorted(p.name for p in folder.iterdir())
            self.assertEqual(names, ["20260101-100200", "20260101-100300", "20260101-100400", "someone-elses"])


class TheServer(DevelopmentCopy):
    """The server's side, on the invented development copy."""

    def start(self, settings_file=True):
        settings = {"movies_path": str(self.tmp / "Films"), "tv_path": "", "mpv_command": "mpv",
                    "mpv_args": [], "resume": False, "keep_awake": False, "data_dir": str(self.data)}
        for target, name, value in ((app_update, "load_installer", lambda root: mock.Mock(
                                        started_cleanly=lambda root, environ: (True, ""))),
                                    (try_branch, "fetch_pulls", self.fake_pulls),
                                    (server_module, "_log", self.lines.append),
                                    (server_module, "request_restart",
                                     lambda ref, root, note: self.restarts.append((root, note)))):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        self.port = httpd.server_address[1]
        with contextlib.redirect_stdout(io.StringIO()):
            base = make_handler(self.copy / "ui", self.tmp, settings, {"server": httpd}, self.port,
                                settings_file=self.settings_file if settings_file else None)

        class Quiet(base):
            def log_message(self, format, *args):
                pass

        httpd.RequestHandlerClass = Quiet
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)

    def request(self, method, path, body=None):
        with contextlib.redirect_stdout(io.StringIO()):
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
            headers = {"Content-Type": "application/json"} if body is not None else {}
            conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
            resp = conn.getresponse()
            data = json.loads(resp.read() or b"null")
            conn.close()
        return resp.status, data

    def settings_branches(self):
        (self.copy / "ui").mkdir(exist_ok=True)
        status, answer = self.request("GET", "/api/settings")
        self.assertEqual(status, 200)
        return answer["updates"]["branches"]

    def test_settings_say_where_the_copy_is_and_nothing_goes_online(self):
        self.start()
        self.assertEqual(self.settings_branches(), {"on": None, "restore": None})
        self.assertEqual(self.pull_calls, [])

    def test_without_its_own_settings_file_no_rows(self):
        self.start(settings_file=False)
        self.assertIsNone(self.settings_branches())

    def test_list_switch_and_follow(self):
        self.start()
        self.assertEqual(self.request("POST", "/api/branches/switch", {"branch": "issue-40"}),
                         (409, {"ok": False, "text": try_branch.NOT_LISTED}))
        status, answer = self.request("POST", "/api/branches/list", {})
        self.assertEqual(status, 200)
        self.assertEqual(answer["branches"][1]["label"], "#40 · Movies detail screen")
        status, answer = self.request("POST", "/api/branches/switch", {"branch": "issue-40"})
        self.assertEqual(status, 200)
        self.assertTrue(answer["ok"])
        wait_for(lambda: self.restarts, 30)
        self.assertEqual(self.restarts, [(self.copy, "Now on #40 · Movies detail screen")])
        status, answer = self.request("GET", "/api/updates/status")
        self.assertIn("running", answer)
        self.assertEqual(self.settings_branches()["on"]["label"], "#40 · Movies detail screen")
        self.assertEqual(self.request("POST", "/api/branches/switch", {})[0], 400)
        self.assertEqual(self.request("POST", "/api/branches/restore", {"id": "nope"}),
                         (409, {"ok": False, "text": try_branch.NO_BACKUP}))


if __name__ == "__main__":
    unittest.main()
