# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Fresh start and pretend-mpv-is-missing (the fresh start mode).

Everything happens in temporary folders: a pretend app folder with its own
settings.json and "real" data folder, invented media files, a fake mpv
that only notes how it was started, and a temporary stand-in for /tmp
where fresh-start folders are made. The real data folder, mpv's real
resume positions and the real media folders are never touched.

Checks: with no option the data folder is exactly where it is today; fresh
start uses a new, empty folder (with mpv's own empty resume folder) and
the real data folder is byte-for-byte unchanged after a session that scans
and plays; the fresh folder is deleted on quit, and a leftover one at the
next fresh start, while nothing else is ever deleted; the mpv-missing
option makes the mpv check report missing, alone and with fresh start; no
answer from the app holds an absolute path, a failed film's included;
Continue watching and its pictures from normal use don't show in fresh
start, a stop there lands only in the fresh folder, and normal use
afterwards shows the real list as it was.

Fresh start opens onboarding (the fresh start onboarding work): both folders count as not set
whatever settings.json says, and the same file without fresh start doesn't
ask; a whole session (choose, scan, play with a stand-in, quit) leaves the
real settings.json and data folder byte-for-byte unchanged, also with no real
settings.json at all, through "Browse somewhere else" (a stand-in dialog) and
after a failed save; the folders chosen are used for that session and are gone
at the next fresh start, after a quit and after a crash's leftover; every other
setting still comes from the real file; no path in any answer or log line.

Run from the repo root:  python3 -m unittest tests.test_launch_options -v
"""

import contextlib
import http.client
import io
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from backend import folder_finder, launch_options, library_index, mpv, onboarding, server
from backend.launch_options import FRESH_START, PRETEND_NO_MPV
from backend.settings import load_settings
from tests.test_folder_dialog import StandIn
from tests.test_parsed_library import MOVIE_FILES, TV_FILES

# Notes every start in calls.jsonl beside it, then ends as a film would.
# With a next-stop.json beside it, it also writes what the real quit script
# writes (the Continue watching record and frame), names the film it played
# (as the real mpv does) and ends with that plan's exit status; run to make
# the small picture, it writes one.
FAKE_MPV = """#!/usr/bin/env python3
import json, pathlib, sys
here = pathlib.Path(__file__).parent
args = sys.argv[1:]
with open(here / "calls.jsonl", "a") as f:
    f.write(json.dumps(args) + "\\n")
for a in args:
    if a.startswith("--vo-image-outdir="):
        pathlib.Path(a.split("=", 1)[1], "00000001.jpg").write_bytes(b"\\xff\\xd8 small picture")
        sys.exit(0)
print("[cplayer] Playing")
plan_file = here / "next-stop.json"
if plan_file.exists():
    plan = json.loads(plan_file.read_text())
    print("[cplayer] Playing: " + args[-1])
    for a in args:
        if a.startswith("--script-opts-append=kettle_quit-out_dir="):
            out = pathlib.Path(a.split("kettle_quit-out_dir=", 1)[1])
            (out / "frame.jpg").write_bytes(b"\\xff\\xd8 full frame")
            (out / "record.json").write_text(json.dumps(plan["record"]))
    sys.exit(plan.get("exit", 0))
"""

# Someone's own mpv option, which fresh start must still win over.
USER_WATCH_LATER = "--watch-later-dir=/home/someone/.local/state/mpv/watch_later"


def snapshot(folder: Path) -> dict:
    """Every file and folder under folder, with each file's bytes."""
    found = {}
    for path in sorted(folder.rglob("*")):
        rel = path.relative_to(folder).as_posix()
        found[rel] = path.read_bytes() if path.is_file() else "<folder>"
    return found


def dead_pid() -> int:
    """The number of a process that has ended."""
    child = subprocess.Popen(["true"])
    child.wait()
    return child.pid


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class OptionsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.parent = Path(self.tmp.name) / "tmp"
        self.parent.mkdir()

    def test_an_option_is_on_only_when_it_says_so(self):
        for value in ("1", "true", "TRUE", "yes", "on", " 1 "):
            self.assertTrue(launch_options.is_on({FRESH_START: value}, FRESH_START), value)
        for value in ("", "0", "false", "no", "off", "2", "fresh"):
            self.assertFalse(launch_options.is_on({FRESH_START: value}, FRESH_START), value)
        self.assertFalse(launch_options.is_on({}, FRESH_START))

    def test_no_option_keeps_the_data_folder_where_it_is_today(self):
        root = Path(self.tmp.name) / "app"
        root.mkdir()
        (root / "settings.json").write_text(json.dumps({"movies_path": "/m", "tv_path": "/t"}))
        settings = load_settings(root)
        options = launch_options.choose(settings, {}, self.parent)
        self.assertEqual(options.data_dir, root / "data")
        self.assertFalse(options.fresh_start)
        self.assertIsNone(options.watch_later_dir)
        self.assertFalse(options.pretend_no_mpv)
        self.assertEqual(list(self.parent.iterdir()), [])

    def test_no_option_follows_the_data_dir_setting(self):
        options = launch_options.choose({"data_dir": "/somewhere/else"}, {PRETEND_NO_MPV: "1"}, self.parent)
        self.assertEqual(options.data_dir, Path("/somewhere/else"))
        self.assertTrue(options.pretend_no_mpv)
        self.assertFalse(options.fresh_start)

    def test_fresh_start_makes_a_new_empty_folder(self):
        options = launch_options.choose({"data_dir": "/real/data"}, {FRESH_START: "1"}, self.parent)
        self.assertTrue(options.fresh_start)
        root = options.fresh_root
        self.assertEqual(root.parent, self.parent)
        self.assertTrue(root.name.startswith("kettle-fresh-"))
        self.assertEqual(options.data_dir, root / "data")
        self.assertEqual(options.watch_later_dir, root / "watch_later")
        self.assertEqual(list(options.data_dir.iterdir()), [])
        self.assertEqual(list(options.watch_later_dir.iterdir()), [])
        self.assertEqual(root.stat().st_mode & 0o777, 0o700)
        self.assertTrue(launch_options.is_fresh_folder(root, self.parent))
        # A second fresh start while this one runs gets its own folder.
        other = launch_options.choose({"data_dir": "/real/data"}, {FRESH_START: "1"}, self.parent)
        self.assertNotEqual(other.fresh_root, root)
        self.assertTrue(root.is_dir())

    def test_removing_the_fresh_folder(self):
        root = launch_options.make_fresh(self.parent)
        (root / "data" / "library.json").write_text("{}")
        (root / "watch_later" / "ABC123").write_text("start=12.0\n")
        self.assertTrue(launch_options.remove_fresh(root, self.parent))
        self.assertFalse(root.exists())
        self.assertEqual(list(self.parent.iterdir()), [])

    def test_only_a_fresh_start_folder_is_ever_removed(self):
        keep = {}
        # A folder of the right name but without the app's mark file.
        unmarked = self.parent / "kettle-fresh-unmarked"
        (unmarked / "data").mkdir(parents=True)
        (unmarked / "data" / "library.json").write_text("precious")
        # The mark file's name, but not the app's words in it.
        wrong_mark = self.parent / "kettle-fresh-wrong"
        wrong_mark.mkdir()
        (wrong_mark / launch_options.MARK_NAME).write_text("something else\npid 1\n")
        # A real fresh-start folder somewhere other than the temporary place.
        elsewhere = Path(self.tmp.name) / "elsewhere"
        elsewhere.mkdir()
        outside = launch_options.make_fresh(elsewhere)
        # A marked folder with another name.
        renamed = launch_options.make_fresh(self.parent)
        renamed = renamed.rename(self.parent / "my-folder")
        # A link named like a fresh folder, pointing at a marked folder.
        target = launch_options.make_fresh(elsewhere)
        link = self.parent / "kettle-fresh-link"
        link.symlink_to(target, target_is_directory=True)
        # A file named like one.
        plain_file = self.parent / "kettle-fresh-file"
        plain_file.write_text("not a folder")
        for path in (unmarked, wrong_mark, outside, renamed, target, link, plain_file):
            keep[path] = snapshot(path) if path.is_dir() and not path.is_symlink() else path.lstat().st_mode
        for path in (unmarked, wrong_mark, outside, renamed, link, plain_file):
            self.assertFalse(launch_options.remove_fresh(path, self.parent), path)
        self.assertEqual(launch_options.clean_leftovers(self.parent), 0)
        self.assertEqual(launch_options.clean_leftovers(elsewhere.parent), 0)
        for path, before in keep.items():
            now = snapshot(path) if path.is_dir() and not path.is_symlink() else path.lstat().st_mode
            self.assertEqual(now, before, path)

    def test_leftovers_are_cleaned_up_at_the_next_fresh_start(self):
        leftover = launch_options.make_fresh(self.parent)
        (leftover / "data" / "library.json").write_text("{}")
        mark = leftover / launch_options.MARK_NAME
        mark.write_text(f"{launch_options.MARK_FIRST_LINE}\npid {dead_pid()}\n")
        # One still in use by a running copy of the app (this test's parent
        # process stands in for it) is kept.
        in_use = launch_options.make_fresh(self.parent)
        (in_use / launch_options.MARK_NAME).write_text(f"{launch_options.MARK_FIRST_LINE}\npid {os.getppid()}\n")
        unmarked = self.parent / "kettle-fresh-unmarked"
        unmarked.mkdir()
        options = launch_options.choose({"data_dir": "/real/data"}, {FRESH_START: "1"}, self.parent)
        self.assertFalse(leftover.exists())
        self.assertTrue(in_use.is_dir())
        self.assertTrue(unmarked.is_dir())
        self.assertTrue(options.fresh_root.is_dir())
        self.assertEqual(set(self.parent.iterdir()), {in_use, unmarked, options.fresh_root})

    def test_normal_use_never_cleans_anything(self):
        leftover = launch_options.make_fresh(self.parent)
        (leftover / launch_options.MARK_NAME).write_text(f"{launch_options.MARK_FIRST_LINE}\npid {dead_pid()}\n")
        launch_options.choose({"data_dir": "/real/data"}, {}, self.parent)
        self.assertTrue(leftover.is_dir())

    def test_fresh_start_counts_both_folders_as_not_set_and_saves_in_its_own_folder(self):
        real_file = Path("/real/app/settings.json")
        settings = {"movies_path": "/m", "tv_path": "/t", "data_dir": "/real/data", "mpv_args": ["--x"]}
        before = dict(settings)
        options = launch_options.choose(settings, {FRESH_START: "1"}, self.parent)
        session, saves_to = launch_options.for_session(settings, options, real_file)
        self.assertEqual(session, {"movies_path": "", "tv_path": "", "mpv_args": ["--x"],
                                   "data_dir": str(options.fresh_root / "data")})
        self.assertEqual(saves_to, options.fresh_root / "settings.json")
        self.assertEqual(settings, before)

    def test_no_option_keeps_the_folders_and_the_real_settings_file(self):
        real_file = Path("/real/app/settings.json")
        settings = {"movies_path": "/m", "tv_path": "/t", "data_dir": "/real/data"}
        options = launch_options.choose(settings, {PRETEND_NO_MPV: "1"}, self.parent)
        session, saves_to = launch_options.for_session(settings, options, real_file)
        self.assertEqual(session, settings)
        self.assertEqual(saves_to, real_file)


class BuildCommandTest(unittest.TestCase):
    def test_fresh_start_gives_mpv_its_own_resume_folder_last(self):
        folder = Path("/tmp/kettle-fresh-x/watch_later")
        for resume in (True, False):
            args = mpv.build_command(["mpv"], Path("/m/film.mkv"), [USER_WATCH_LATER], resume,
                                     watch_later_dir=folder)
            found = [a for a in args if a.startswith("--watch-later-dir=")]
            # mpv takes the last one given: fresh start's.
            self.assertEqual(found[-1], f"--watch-later-dir={folder}")
            self.assertLess(args.index(USER_WATCH_LATER), args.index(found[-1]))
            self.assertEqual(args[-1], "/m/film.mkv")

    def test_normal_use_leaves_mpv_its_own_resume_folder(self):
        args = mpv.build_command(["mpv"], Path("/m/film.mkv"), [], True)
        self.assertFalse([a for a in args if a.startswith("--watch-later")])


class AppTest(unittest.TestCase):
    """The whole backend, started as launch.sh starts it (server.serve),
    from a pretend app folder."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.root = base / "app"
        self.root.mkdir()
        self.parent = base / "tmp"
        self.parent.mkdir()
        self.movies = base / "Movies"
        self.tv = base / "TV Shows"
        for folder, files in ((self.movies, MOVIE_FILES), (self.tv, TV_FILES)):
            for rel in files:
                (folder / rel).parent.mkdir(parents=True, exist_ok=True)
                (folder / rel).write_bytes(b"")
        self.fake = base / "fake" / "mpv"
        self.fake.parent.mkdir()
        self.fake.write_text(FAKE_MPV)
        self.fake.chmod(0o755)
        (self.root / "settings.json").write_text(json.dumps({
            "movies_path": str(self.movies), "tv_path": str(self.tv), "mpv_command": str(self.fake),
            "mpv_args": [USER_WATCH_LATER], "keep_awake": False,
        }))
        # The "real" data folder: a saved library, a Continue watching list
        # and a picture.
        self.data = self.root / "data"
        index = library_index.full_scan({"movies": str(self.movies), "tv": str(self.tv)}, None, lambda *a: None)
        library_index.save(self.data / library_index.FILE_NAME, index)
        (self.data / "continue.json").write_text('{"version": 1, "items": {}}')
        (self.data / "thumbnails").mkdir()
        (self.data / "thumbnails" / "abc.jpg").write_bytes(b"\xff\xd8 picture")
        self.media_before = {"movies": snapshot(self.movies), "tv": snapshot(self.tv)}
        self.logged = []
        # The folder search finds only the invented folders, never the device's.
        place = folder_finder.Place("internal", "Internal storage", str(base))
        found = [folder_finder.Suggestion(folder_finder.folder_id(str(folder)), str(folder), place, [folder.name], 1, 1, [])
                 for folder in (self.movies, self.tv)]
        self.movies_id, self.tv_id = found[0].id, found[1].id
        for patch in (mock.patch.object(server, "_log", self.logged.append),
                      mock.patch.object(folder_finder, "search", lambda: folder_finder.FolderSearch([place], found, 0.0))):
            patch.start()
            self.addCleanup(patch.stop)
        self.thread = None

    def tearDown(self):
        if self.thread is not None and self.thread.is_alive():
            self.httpd_ref["server"].shutdown()
            self.thread.join(10)
        self.assertEqual({"movies": snapshot(self.movies), "tv": snapshot(self.tv)}, self.media_before)

    def start(self, environ):
        self.port = free_port()
        self.httpd_ref = {}
        out = io.StringIO()

        def run():
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                server.serve(self.root, environ, self.port, self.httpd_ref, self.parent)

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        end = time.time() + 10
        while time.time() < end:
            try:
                self.request("GET", "/api/status")
                return
            except OSError:
                time.sleep(0.05)
        self.fail("the server didn't start")

    def request(self, method, path, body=None, raw=False):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            headers = {"Host": f"127.0.0.1:{self.port}"}
            data = None
            if body is not None:
                data = json.dumps(body).encode()
                headers["Content-Type"] = "application/json"
            conn.request(method, path, body=data, headers=headers)
            resp = conn.getresponse()
            answer = resp.read()
            return resp.status, (answer if raw else json.loads(answer))
        finally:
            conn.close()

    def choose_folders(self):
        """What onboarding's two screens send: the search, then the choice."""
        self.assertEqual(self.request("GET", "/api/onboarding/folders")[0], 200)
        answer = self.request("POST", "/api/onboarding/choose", {"movies": self.movies_id, "tv": self.tv_id})[1]
        self.assertEqual(answer, {"ok": True})

    def plan(self, position, exit_status=0, frame=True):
        """What the fake mpv does next: stop at position (seconds), saving
        the frame or not, and end with exit_status."""
        record = {"position": position, "duration": 7200.0, "finished": False, "frame_saved": frame}
        (self.fake.parent / "next-stop.json").write_text(json.dumps({"record": record, "exit": exit_status}))

    def scan(self):
        self.request("POST", "/api/library/scan", {})
        self.assertTrue(self.wait_idle("/api/library/scan/status")["last_result"]["ok"])

    def wait_small_picture(self, link):
        """The small picture replaces the frame in the background: wait for
        it, so nothing is still writing when the app quits."""
        end = time.time() + 10
        while time.time() < end:
            code, body = self.request("GET", link, raw=True)
            if code == 200 and body == b"\xff\xd8 small picture":
                return
            time.sleep(0.05)
        self.fail("the small picture never replaced the frame")

    def quit(self):
        self.assertEqual(self.request("POST", "/api/shutdown", {}), (200, {"ok": True}))
        self.thread.join(10)
        self.assertFalse(self.thread.is_alive())

    def wait_idle(self, path, state_key="state"):
        end = time.time() + 15
        while time.time() < end:
            status, answer = self.request("GET", path)
            if answer[state_key] not in ("scanning", "playing"):
                return answer
            time.sleep(0.05)
        self.fail(f"{path} never went idle")

    def calls(self):
        calls_file = self.fake.parent / "calls.jsonl"
        return [json.loads(line) for line in calls_file.read_text().splitlines()] if calls_file.exists() else []

    def play_first_film(self):
        status, answer = self.request("POST", "/api/play", {"source": "movies", "path": MOVIE_FILES[2]})
        self.assertEqual((status, answer.get("started")), (200, True), answer)
        return self.wait_idle("/api/status")

    def fresh_folders(self):
        return [p for p in self.parent.iterdir() if p.name.startswith("kettle-fresh-")]

    def assertNoAbsolutePath(self, where, value):
        if isinstance(value, str):
            self.assertNotIn(self.tmp.name, value, where)
            self.assertNotIn("/tmp/", value, where)
            # Page addresses (/api/…) are fine; a file system path is not.
            if value.startswith("/"):
                self.assertTrue(value.startswith("/api/"), f"{where}: {value!r}")
        elif isinstance(value, dict):
            for key, item in value.items():
                self.assertNoAbsolutePath(where, key)
                self.assertNoAbsolutePath(where, item)
        elif isinstance(value, list):
            for item in value:
                self.assertNoAbsolutePath(where, item)

    def test_fresh_start_leaves_the_real_data_untouched(self):
        real_before = snapshot(self.data)
        self.start({FRESH_START: "1"})
        answers = {"dev": self.request("GET", "/api/dev")[1]}
        self.assertEqual(answers["dev"], {"fresh_start": True})
        [fresh] = self.fresh_folders()
        self.assertEqual(snapshot(fresh / "data"), {})
        self.assertEqual(snapshot(fresh / "watch_later"), {})
        answers["mpv-status"] = self.request("GET", "/api/mpv-status")[1]
        self.assertTrue(answers["mpv-status"]["available"])
        # A brand-new user: no saved library, nothing to continue.
        answers["parsed before"] = self.request("GET", "/api/library/parsed")[1]
        self.assertFalse(answers["parsed before"]["movies"]["has_library"])
        self.assertFalse(answers["parsed before"]["tv"]["has_library"])
        answers["continue before"] = self.request("GET", "/api/continue")[1]
        self.assertEqual(answers["continue before"], {"items": []})
        self.choose_folders()
        # Scan, play, remove missing: everything lands in the fresh folder.
        answers["scan"] = self.request("POST", "/api/library/scan", {})[1]
        answers["scan status"] = self.wait_idle("/api/library/scan/status")
        self.assertTrue(answers["scan status"]["last_result"]["ok"])
        self.assertIn(library_index.FILE_NAME, snapshot(fresh / "data"))
        answers["status"] = self.play_first_film()
        self.assertTrue(answers["status"]["last_result"]["ok"], answers["status"])
        [args] = self.calls()
        later = [a for a in args if a.startswith("--watch-later-dir=")]
        self.assertEqual(later[-1], f"--watch-later-dir={fresh / 'watch_later'}")
        answers["parsed after"] = self.request("GET", "/api/library/parsed")[1]
        self.assertTrue(answers["parsed after"]["movies"]["has_library"])
        answers["continue after"] = self.request("GET", "/api/continue")[1]
        answers["remove"] = self.request("POST", "/api/library/remove-missing", {})[1]
        for where, answer in answers.items():
            self.assertNoAbsolutePath(where, answer)
        self.quit()
        self.assertEqual(self.fresh_folders(), [])
        self.assertEqual(list(self.parent.iterdir()), [])
        self.assertEqual(snapshot(self.data), real_before)
        self.assertIn("fresh start: folder deleted", self.logged)

    def test_continue_watching_and_its_pictures_stay_apart(self):
        # Normal use first: a stop at 30:00 goes into the real Continue
        # watching list, with its picture.
        self.start({})
        self.plan(1800)
        self.play_first_film()
        [real_item] = self.request("GET", "/api/continue")[1]["items"]
        self.assertEqual(real_item["position"], 1800)
        self.wait_small_picture(real_item["picture"])
        self.quit()
        real_before = snapshot(self.data)
        self.assertEqual(len(list((self.data / "thumbnails").iterdir())), 2)  # setUp's and this one
        # Fresh start: none of it shows, and a stop there lands only in the
        # fresh folder.
        self.start({FRESH_START: "1"})
        [fresh] = self.fresh_folders()
        self.assertEqual(self.request("GET", "/api/continue")[1], {"items": []})
        self.choose_folders()
        self.scan()
        self.plan(600)
        self.play_first_film()
        answer = self.request("GET", "/api/continue")[1]
        [fresh_item] = answer["items"]
        self.assertEqual(fresh_item["position"], 600)
        self.wait_small_picture(fresh_item["picture"])
        self.assertNoAbsolutePath("continue", answer)
        self.assertIn("continue.json", snapshot(fresh / "data"))
        self.assertEqual(len(list((fresh / "data" / "thumbnails").iterdir())), 1)
        self.assertEqual(snapshot(self.data), real_before)
        self.quit()
        self.assertEqual(self.fresh_folders(), [])
        self.assertEqual(snapshot(self.data), real_before)
        # Back to normal use: the real list, as it was.
        self.start({})
        [item] = self.request("GET", "/api/continue")[1]["items"]
        self.assertEqual((item["id"], item["position"]), (real_item["id"], 1800))
        self.quit()

    def test_a_failed_film_names_no_location(self):
        # mpv's log path and its last lines (which name the film) stay in
        # the backend, in normal use and in fresh start alike.
        for environ in ({}, {FRESH_START: "1"}):
            with self.subTest(environ=environ):
                self.start(environ)
                if environ:
                    self.choose_folders()
                    self.scan()
                self.plan(300, exit_status=2, frame=False)
                status = self.play_first_film()
                result = status["last_result"]
                self.assertFalse(result["ok"], status)
                self.assertEqual(result["error"], "mpv exited with status 2")
                self.assertTrue(result["hint"])
                self.assertNotIn("log", result)
                self.assertNotIn("log_tail", result)
                self.assertNoAbsolutePath("status", status)
                self.quit()
                self.assertEqual(self.fresh_folders(), [])

    def test_no_option_uses_the_real_data_folder(self):
        self.start({})
        self.assertEqual(self.request("GET", "/api/dev")[1], {})
        self.assertTrue(self.request("GET", "/api/library/parsed")[1]["movies"]["has_library"])
        before = (self.data / library_index.FILE_NAME).read_bytes()
        self.request("POST", "/api/library/scan", {})
        self.wait_idle("/api/library/scan/status")
        # The scan saved into the real data folder, as today.
        self.assertNotEqual((self.data / library_index.FILE_NAME).read_bytes(), before)
        self.assertTrue(self.request("GET", "/api/library/parsed")[1]["tv"]["has_library"])
        self.play_first_film()
        [args] = self.calls()
        self.assertEqual([a for a in args if a.startswith("--watch-later-dir=")], [USER_WATCH_LATER])
        self.quit()
        self.assertEqual(list(self.parent.iterdir()), [])

    def test_a_leftover_is_cleaned_up_when_a_fresh_start_begins(self):
        leftover = launch_options.make_fresh(self.parent)
        (leftover / launch_options.MARK_NAME).write_text(f"{launch_options.MARK_FIRST_LINE}\npid {dead_pid()}\n")
        self.start({FRESH_START: "1"})
        self.assertFalse(leftover.exists())
        self.assertEqual(len(self.fresh_folders()), 1)
        self.quit()
        self.assertEqual(self.fresh_folders(), [])

    def test_a_stop_signal_also_deletes_the_fresh_folder(self):
        # What launch.sh's stop does: the same close as Quit.
        self.start({FRESH_START: "1"})
        self.assertEqual(len(self.fresh_folders()), 1)
        server.close_server(self.httpd_ref)
        self.thread.join(10)
        self.assertEqual(self.fresh_folders(), [])

    def test_pretend_mpv_is_missing(self):
        for environ in ({PRETEND_NO_MPV: "1"}, {PRETEND_NO_MPV: "1", FRESH_START: "1"}):
            with self.subTest(environ=environ):
                self.start(environ)
                if FRESH_START in environ:
                    self.choose_folders()
                status = self.request("GET", "/api/mpv-status")[1]
                self.assertEqual(status, {"available": False, "install_hint": mpv.INSTALL_HINT})
                code, answer = self.request("POST", "/api/play", {"source": "movies", "path": MOVIE_FILES[2]})
                self.assertEqual(code, 503)
                self.assertEqual(answer["hint"], mpv.INSTALL_HINT)
                self.assertEqual(self.calls(), [])
                dev = self.request("GET", "/api/dev")[1]
                self.assertEqual(dev.get("fresh_start", False), FRESH_START in environ)
                self.assertNoAbsolutePath("mpv-status", status)
                self.quit()
                self.assertEqual(self.fresh_folders(), [])

    def test_without_the_option_mpv_is_found(self):
        self.start({PRETEND_NO_MPV: "0"})
        self.assertTrue(self.request("GET", "/api/mpv-status")[1]["available"])
        self.quit()

    # --- Fresh start opens onboarding (the fresh start onboarding work) ---

    def needed(self):
        return self.request("GET", "/api/onboarding")[1]["needed"]

    def real_settings(self):
        """The real file's bytes and its identity: a rewrite with the same
        bytes would still show."""
        file = self.root / "settings.json"
        info = file.stat()
        return file.read_bytes(), info.st_ino, info.st_mtime_ns

    def test_with_both_folders_set_only_fresh_start_asks_for_them(self):
        self.start({})
        self.assertFalse(self.needed())
        self.quit()
        self.start({FRESH_START: "1"})
        self.assertTrue(self.needed())
        self.quit()
        self.start({})
        self.assertFalse(self.needed())
        self.quit()

    def test_a_whole_session_leaves_the_real_settings_and_data_alone(self):
        settings_before, data_before = self.real_settings(), snapshot(self.data)
        self.start({FRESH_START: "1"})
        [fresh] = self.fresh_folders()
        self.assertTrue(self.needed())
        # Nothing to play, and nothing to scan, before the folders are chosen.
        self.assertEqual(self.request("POST", "/api/play", {"source": "movies", "path": MOVIE_FILES[2]})[0], 400)
        self.choose_folders()
        self.assertFalse(self.needed())
        # Home as for a new user: the folders are there, with no library yet.
        parsed = self.request("GET", "/api/library/parsed")[1]
        self.assertFalse(parsed["movies"]["has_library"])
        self.assertTrue(parsed["movies"]["folder_set"] and parsed["tv"]["folder_set"])
        self.scan()
        parsed = self.request("GET", "/api/library/parsed")[1]
        self.assertTrue(parsed["movies"]["has_library"] and parsed["tv"]["has_library"])
        self.assertTrue(self.play_first_film()["last_result"]["ok"])
        # The film played is from the folder chosen.
        self.assertEqual(self.calls()[0][-1], str(self.movies / MOVIE_FILES[2]))
        self.assertEqual(self.real_settings(), settings_before)
        saved = json.loads((fresh / "settings.json").read_text())
        self.assertEqual(saved, {"movies_path": str(self.movies), "tv_path": str(self.tv)})
        self.quit()
        self.assertEqual(self.real_settings(), settings_before)
        self.assertEqual(snapshot(self.data), data_before)
        self.assertEqual(self.fresh_folders(), [])
        self.assertEqual(list(self.root.glob(".settings-*")), [])

    def test_no_real_settings_file_stays_no_settings_file(self):
        (self.root / "settings.json").unlink()
        self.start({FRESH_START: "1", PRETEND_NO_MPV: "1"})
        self.choose_folders()
        self.assertFalse(self.needed())
        self.quit()
        self.assertFalse((self.root / "settings.json").exists())

    def test_a_folder_from_the_dialog_stays_in_the_session_too(self):
        stand_in = StandIn(Path(self.tmp.name) / "programs")
        stand_in.add("kdialog")
        settings_before = self.real_settings()
        with mock.patch.dict(os.environ, {"PATH": str(stand_in.folder)}):
            self.start({FRESH_START: "1"})
            [fresh] = self.fresh_folders()
            self.assertEqual(self.request("GET", "/api/onboarding/folders")[0], 200)
            stand_in.answer(self.tv)
            answer = self.request("POST", "/api/onboarding/browse", {"movies": None})[1]
            self.assertTrue(answer["picked"], answer)
            self.assertIsNone(answer["message"])
            self.assertNoAbsolutePath("browse", answer)
            self.assertEqual(self.real_settings(), settings_before)
            choice = {"movies": None, "tv": answer["folder"]["id"]}
            self.assertEqual(self.request("POST", "/api/onboarding/choose", choice)[1], {"ok": True})
            self.assertEqual(json.loads((fresh / "settings.json").read_text())["tv_path"], str(self.tv))
            self.assertEqual(self.real_settings(), settings_before)
            self.quit()
        self.assertEqual(self.real_settings(), settings_before)

    def test_a_failed_save_never_falls_back_on_the_real_file(self):
        settings_before = self.real_settings()
        self.start({FRESH_START: "1"})
        [fresh] = self.fresh_folders()
        self.assertEqual(self.request("GET", "/api/onboarding/folders")[0], 200)
        fresh.chmod(0o500)  # the session's folder can't be written
        try:
            answer = self.request("POST", "/api/onboarding/choose", {"movies": self.movies_id, "tv": self.tv_id})[1]
            self.assertEqual(answer, {"ok": False, "message": onboarding.SAVE_FAILED})
            self.assertEqual(self.real_settings(), settings_before)
            # Still asking, and nothing is half chosen.
            self.assertTrue(self.needed())
            self.assertEqual(self.request("POST", "/api/play", {"source": "movies", "path": MOVIE_FILES[2]})[0], 400)
        finally:
            fresh.chmod(0o700)
        # It can be tried again once the save works.
        self.choose_folders()
        self.assertEqual(self.real_settings(), settings_before)
        self.quit()
        self.assertEqual(self.real_settings(), settings_before)
        self.assertEqual(self.fresh_folders(), [])

    def test_the_choice_is_gone_at_the_next_fresh_start_after_a_quit(self):
        self.start({FRESH_START: "1"})
        self.choose_folders()
        self.assertFalse(self.needed())
        self.quit()
        self.start({FRESH_START: "1"})
        self.assertTrue(self.needed())
        self.assertEqual(self.request("POST", "/api/play", {"source": "movies", "path": MOVIE_FILES[2]})[0], 400)
        self.assertEqual(self.request("GET", "/api/library")[1]["movies"]["reason"], "No folder chosen")
        self.quit()

    def test_the_choice_is_gone_at_the_next_fresh_start_after_a_crash(self):
        self.start({FRESH_START: "1"})
        [fresh] = self.fresh_folders()
        self.choose_folders()
        self.scan()
        # What a crash leaves behind: this session's folder, its maker gone.
        crashed = self.parent / "kettle-fresh-crashed"
        shutil.copytree(fresh, crashed)
        (crashed / launch_options.MARK_NAME).write_text(f"{launch_options.MARK_FIRST_LINE}\npid {dead_pid()}\n")
        self.assertIn(str(self.movies), (crashed / "settings.json").read_text())
        self.quit()
        self.start({FRESH_START: "1"})
        self.assertFalse(crashed.exists())
        self.assertTrue(self.needed())
        self.assertFalse(self.request("GET", "/api/library/parsed")[1]["movies"]["has_library"])
        self.quit()

    def test_every_other_setting_still_comes_from_the_real_file(self):
        file = self.root / "settings.json"
        file.write_text(json.dumps({**json.loads(file.read_text()), "dev_auto_update": True, "debug_size_readout": True}))
        before = file.read_bytes()
        self.start({FRESH_START: "1"})
        self.assertTrue(self.request("GET", "/api/dev")[1]["size_readout"])
        self.choose_folders()
        self.scan()
        status, answer = self.request("POST", "/api/play", {"source": "movies", "path": MOVIE_FILES[2]})
        # keep_awake is on unless the file says otherwise, and this one does.
        self.assertEqual((status, answer["keep_awake"]), (200, False))
        self.wait_idle("/api/status")
        # mpv_command and mpv_args: the stand-in mpv ran, with the real file's option.
        self.assertIn(USER_WATCH_LATER, self.calls()[0])
        self.quit()
        # A "dev_auto_update" line left from before the never-online work is kept, unused.
        self.assertEqual(file.read_bytes(), before)

    def test_a_mistake_in_the_real_file_still_stops_a_fresh_start(self):
        file = self.root / "settings.json"
        file.write_text('{"movies_path": null, "tv_path": ""}')
        with contextlib.redirect_stderr(io.StringIO()) as said, self.assertRaises(SystemExit):
            server.serve(self.root, {FRESH_START: "1"}, free_port(), {}, self.parent)
        self.assertIn("movies_path", said.getvalue())
        self.assertEqual(self.fresh_folders(), [])

    def test_no_path_in_any_answer_or_log_line(self):
        self.start({FRESH_START: "1"})
        answers = {"needed": self.request("GET", "/api/onboarding")[1],
                   "folders": self.request("GET", "/api/onboarding/folders")[1],
                   "choose": self.request("POST", "/api/onboarding/choose",
                                          {"movies": self.movies_id, "tv": self.tv_id})[1]}
        self.scan()
        answers["parsed"] = self.request("GET", "/api/library/parsed")[1]
        answers["status"] = self.play_first_film()
        for where, answer in answers.items():
            self.assertNoAbsolutePath(where, answer)
        self.quit()
        for line in self.logged:
            self.assertNotIn(self.tmp.name, line)
        self.assertIn("onboarding: movies chosen, tv chosen, settings saved", self.logged)


if __name__ == "__main__":
    unittest.main()
