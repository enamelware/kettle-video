# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Browse somewhere else (the Browse somewhere else work): the system's folder dialog. No real dialog
ever opens: PATH holds only a stand-in program, and Python's own Tk dialog is a
stand-in too. Every folder and settings file is invented, in a temporary folder.

Checks: the dialog is chosen in order, and none is found when none is there;
each is started as the spike says; exit 1 or empty output is a cancel, any other
failure says so, and the path must be a folder; through the server: the row's
answer, a picked folder with its place and name and never its path, the same
checks and messages as a listed folder, a folder already listed keeping its id,
a cancel changing nothing, the path never in an answer or a log line, the server
answering while the dialog is open, one dialog at a time, and closing a dialog.
From the series review (the first onboarding review fixes): a folder that can't be read says so and
can't be saved; one holding Kettle's own files is refused; a name ending in a
space is found at the next launch.

Run from the repo root:  python3 -m unittest tests.test_folder_dialog -v
"""

import contextlib
import http.client
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from backend import folder_dialog, folder_finder as ff, library_index, onboarding, server
from backend.settings import load_settings
from tests.test_folder_finder import make, snapshot

REPO = Path(__file__).resolve().parent.parent
UI_DIR = REPO / "ui"

STAND_IN = f"""#!{sys.executable}
import json, os, sys, time
here = os.path.dirname(os.path.abspath(__file__))
def path(name):
    return os.path.join(here, name)
with open(path("started"), "w") as f:
    json.dump(sys.argv[1:], f)
sys.stderr.write("noise from the dialog: /invented/secret-noise\\n")
while os.path.exists(path("hold")):
    time.sleep(0.02)
if os.path.exists(path("answer")):
    with open(path("answer"), "rb") as f:
        sys.stdout.buffer.write(f.read())
    sys.stdout.buffer.flush()
code = 0
if os.path.exists(path("exit")):
    with open(path("exit")) as f:
        code = int(f.read())
if code < 0:
    os.kill(os.getpid(), -code)  # a crash: ended by that signal
    time.sleep(10)
os._exit(code)
"""


class StandIn:
    """A folder that stands in for PATH, and tells its dialogs what to do."""

    def __init__(self, folder):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)

    def add(self, name):
        program = self.folder / name
        program.write_text(STAND_IN)
        program.chmod(program.stat().st_mode | stat.S_IXUSR)
        return program

    def answer(self, output, code=0):
        data = output if isinstance(output, bytes) else (str(output) + "\n").encode()
        (self.folder / "answer").write_bytes(data)
        (self.folder / "exit").write_text(str(code))

    def hold(self):
        (self.folder / "hold").touch()

    def release(self):
        (self.folder / "hold").unlink(missing_ok=True)

    def started(self):
        """The arguments of the last dialog started, or None."""
        try:
            return json.loads((self.folder / "started").read_text())
        except (FileNotFoundError, ValueError):
            return None

    def wait_started(self, timeout=10):
        end = time.time() + timeout
        while self.started() is None and time.time() < end:
            time.sleep(0.02)
        return self.started()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.stand_in = StandIn(self.root / "programs")
        self.env = mock.patch.dict(os.environ, {"PATH": str(self.stand_in.folder), "HOME": str(self.root / "home-dir")})
        self.env.start()
        self.addCleanup(self.env.stop)
        os.environ.pop("DISPLAY", None)  # no Tk unless a test asks for it


class FindTest(Base):
    def test_kdialog_comes_first(self):
        self.stand_in.add("zenity")
        self.stand_in.add("kdialog")
        self.assertEqual(folder_dialog.find(), "kdialog")

    def test_then_zenity(self):
        self.stand_in.add("zenity")
        self.assertEqual(folder_dialog.find(), "zenity")

    def python_stand_in(self, code):
        program = self.root / "python-stand-in"
        program.write_text(f"#!{sys.executable}\nimport sys\nsys.exit({code})\n")
        program.chmod(0o755)
        patch = mock.patch.object(folder_dialog, "PYTHON", str(program))
        patch.start()
        self.addCleanup(patch.stop)

    def test_then_tk_with_tkinter_and_a_display(self):
        self.python_stand_in(0)
        os.environ["DISPLAY"] = ":0"
        self.assertEqual(folder_dialog.find(), "tk")

    def test_no_tk_without_a_display(self):
        self.python_stand_in(0)
        self.assertIsNone(folder_dialog.find())

    def test_no_tk_without_tkinter(self):
        self.python_stand_in(1)
        os.environ["DISPLAY"] = ":0"
        self.assertIsNone(folder_dialog.find())

    def test_a_python_that_wont_start_is_no_tk(self):
        os.environ["DISPLAY"] = ":0"
        with mock.patch.object(folder_dialog, "PYTHON", str(self.root / "no-such-python")):
            self.assertIsNone(folder_dialog.find())

    def test_never_the_portal(self):
        text = (REPO / "backend" / "folder_dialog.py").read_text()
        self.assertNotIn("org.freedesktop", text)
        self.assertEqual(folder_dialog.PROGRAMS, ("kdialog", "zenity"))


class CommandTest(Base):
    def test_as_the_spike_says(self):
        self.assertEqual(folder_dialog.command("kdialog", "/h"),
                         ["kdialog", "--title", folder_dialog.TITLE, "--getexistingdirectory", "/h"])
        self.assertEqual(folder_dialog.command("zenity", "/h"),
                         ["zenity", "--file-selection", "--directory", f"--title={folder_dialog.TITLE}", "--filename=/h/"])
        tk = folder_dialog.command("tk", "/h")
        self.assertEqual(tk[0], folder_dialog.PYTHON)
        self.assertIn("askdirectory", tk[2])
        self.assertEqual(tk[3:], [folder_dialog.TITLE, "/h"])

    def test_it_starts_in_the_home_folder(self):
        self.stand_in.add("zenity")
        self.stand_in.answer("")
        process = folder_dialog.start("zenity")
        folder_dialog.wait(process)
        self.assertIn(f"--filename={self.root / 'home-dir'}/", self.stand_in.started())


class OutcomeTest(Base):
    def test_a_folder(self):
        folder = self.root / "A Folder "
        folder.mkdir()
        self.assertEqual(folder_dialog.outcome(0, os.fsencode(str(folder)) + b"\n"), ("picked", str(folder)))

    def test_exit_1_is_a_cancel_whatever_it_printed(self):
        self.assertEqual(folder_dialog.outcome(1, b""), ("cancelled", None))
        self.assertEqual(folder_dialog.outcome(1, str(self.root).encode()), ("cancelled", None))

    def test_empty_output_is_a_cancel(self):
        for output in (b"", b"\n", b"  \n"):
            with self.subTest(output=output):
                self.assertEqual(folder_dialog.outcome(0, output), ("cancelled", None))

    def test_kettles_own_stop_signal_is_a_cancel(self):
        self.assertEqual(folder_dialog.outcome(-15, b""), ("cancelled", None))

    def test_a_crash_failed(self):
        for code in (-6, -11, -9):  # abort, segmentation fault, killed
            with self.subTest(code=code):
                self.assertEqual(folder_dialog.outcome(code, b""), ("failed", None))

    def test_any_other_exit_failed(self):
        self.assertEqual(folder_dialog.outcome(255, str(self.root).encode()), ("failed", None))

    def test_the_path_must_be_a_folder(self):
        file = self.root / "a-file"
        file.touch()
        self.assertEqual(folder_dialog.outcome(0, str(file).encode()), ("not a folder", None))
        self.assertEqual(folder_dialog.outcome(0, str(self.root / "gone").encode()), ("not a folder", None))


class TkHelperTest(Base):
    """The Tk helper's own code, run with an invented tkinter: no window opens."""

    def run_helper(self, tkinter_code):
        package = self.root / "invented" / "tkinter"
        package.mkdir(parents=True, exist_ok=True)
        (package / "__init__.py").write_text(tkinter_code)
        (package / "filedialog.py").write_text("from tkinter import askdirectory\n")
        command = folder_dialog.command("tk", str(self.root))
        with mock.patch.dict(os.environ, {"PYTHONPATH": str(self.root / "invented")}):
            done = subprocess.run(command, capture_output=True, cwd=self.root, timeout=30)
        return folder_dialog.outcome(done.returncode, done.stdout)

    WORKS = "class Tk:\n    def withdraw(self):\n        pass\n"

    def test_a_window_that_cant_open_failed(self):
        # askdirectory is there, so it is Tk() itself that fails.
        code = "class Tk:\n    def __init__(self):\n        raise RuntimeError('no display')\ndef askdirectory(**kw):\n    return ''\n"
        self.assertEqual(self.run_helper(code), ("failed", None))

    def test_a_missing_tkinter_failed(self):
        self.assertEqual(self.run_helper("raise ImportError('no tkinter')\n"), ("failed", None))

    def test_a_cancel_is_a_cancel(self):
        for answer in ("''", "()"):
            with self.subTest(answer=answer):
                code = self.WORKS + f"def askdirectory(**kw):\n    return {answer}\n"
                self.assertEqual(self.run_helper(code), ("cancelled", None))

    def test_a_folder_comes_back(self):
        code = self.WORKS + f"def askdirectory(**kw):\n    return {str(self.root)!r}\n"
        self.assertEqual(self.run_helper(code), ("picked", str(self.root)))


class PickedTest(Base):
    def test_a_folder_inside_a_place(self):
        card = self.root / "CardLabel"
        make(str(card), ["Deep/Films/Alpha/a.mkv", "Deep/Films/Beta/b.mkv"])
        place = ff.Place("sd", "SD card", str(card))
        s = ff.picked(str(card / "Deep" / "Films"), ff.FolderSearch([place], [], 0))
        self.assertIs(s.place, place)
        self.assertEqual(s.trail, ["Deep", "Films"])
        answer = ff.folder_answer(s)
        self.assertEqual((answer["place"], answer["name"], answer["count_text"]), ("SD card", "Films", "2 videos in 2 folders"))
        self.assertEqual(answer["examples"], ["Alpha", "Beta"])

    def test_the_deepest_place_wins(self):
        home = self.root / "home-dir"
        card = home / "mounted"
        make(str(card), ["F/a.mkv"])
        places = [ff.Place("internal", "Internal storage", str(home)), ff.Place("sd", "SD card", str(card))]
        s = ff.picked(str(card / "F"), ff.FolderSearch(places, [], 0))
        self.assertEqual(s.place.name, "SD card")

    def test_a_folder_in_no_place_shows_only_its_own_name(self):
        make(str(self.root / "private-parent" / "Films"), ["a.mkv"])
        s = ff.picked(str(self.root / "private-parent" / "Films"), ff.FolderSearch([], [], 0))
        answer = ff.folder_answer(s)
        self.assertEqual((answer["place"], answer["trail"]), ("Somewhere else", ["Films"]))
        self.assertNotIn("private-parent", json.dumps(answer))

    def test_a_folder_with_no_videos_says_so(self):
        (self.root / "Empty").mkdir()
        s = ff.picked(str(self.root / "Empty"), ff.FolderSearch([], [], 0))
        self.assertEqual(ff.folder_answer(s)["count_text"], "No videos found")

    def locked(self, path):
        """A folder this user can't read (the first onboarding review fixes), put back afterwards."""
        if os.geteuid() == 0:
            self.skipTest("root can read everything")
        os.chmod(path, 0)
        self.addCleanup(os.chmod, path, 0o755)

    def test_a_folder_that_cant_be_read_never_says_no_videos(self):
        make(str(self.root / "Locked"), ["a.mkv"])
        self.locked(self.root / "Locked")
        s = ff.picked(str(self.root / "Locked"), ff.FolderSearch([], [], 0))
        answer = ff.folder_answer(s)
        self.assertEqual(answer["count_text"], "Couldn't be read")
        self.assertEqual(answer["problem"], ff.CANT_BE_READ)

    def test_an_unreadable_part_with_nothing_else_never_says_no_videos(self):
        make(str(self.root / "Top" / "Locked"), ["a.mkv"])
        self.locked(self.root / "Top" / "Locked")
        answer = ff.folder_answer(ff.picked(str(self.root / "Top"), ff.FolderSearch([], [], 0)))
        self.assertEqual(answer["count_text"], "No videos found in the parts Kettle could read")
        self.assertIsNone(answer["problem"])

    def test_an_unreadable_part_beside_videos_keeps_the_count(self):
        make(str(self.root / "Top"), ["Locked/a.mkv", "Open/b.mkv"])
        self.locked(self.root / "Top" / "Locked")
        answer = ff.folder_answer(ff.picked(str(self.root / "Top"), ff.FolderSearch([], [], 0)))
        self.assertEqual(answer["count_text"], "1 video")
        self.assertIsNone(answer["problem"])

    def test_out_of_time_the_count_stays_true(self):
        make(str(self.root / "Big"), ["a.mkv"])
        s = ff.picked(str(self.root / "Big"), ff.FolderSearch([], [], 0), time_limit=-1)
        self.assertEqual(ff.folder_answer(s)["count_text"], "Too big to search in time")

    def test_a_listed_folder_comes_back_as_itself_through_a_link(self):
        make(str(self.root / "Card"), ["Films/Alpha/a.mkv", "Films/Beta/b.mkv"])
        (self.root / "Link").symlink_to(self.root / "Card" / "Films")
        found = ff.search([ff.Place("sd", "SD card", str(self.root / "Card"))])
        self.assertEqual(ff.picked(str(self.root / "Link"), found).id, found.suggestions[0].id)


class ServerTest(Base):
    def setUp(self):
        super().setUp()
        self.card = self.root / "CardLabel"
        self.home = self.root / "home-of-someone"
        make(str(self.card), ["Films/Alpha/a.mkv", "Films/Beta/b.mkv", "Elsewhere/Inner/c.mkv"])
        make(str(self.home), ["Videos/Shows/Gamma/Season 1/e1.mkv", "Videos/Shows/Delta/e1.mkv"])
        self.outside = self.root / "private-parent" / "Outside"
        make(str(self.outside), ["Zeta/z.mkv"])
        (self.root / "logs").mkdir()
        self.settings_file = self.root / "settings.json"
        self.settings_file.write_text(json.dumps({"movies_path": "", "tv_path": "", "kept": [1]}))
        self.settings_before = self.settings_file.read_bytes()
        self.real_settings = REPO / "settings.json"
        self.real_before = self.real_settings.stat().st_mtime_ns if self.real_settings.exists() else None
        self.media_before = snapshot(str(self.card)), snapshot(str(self.home)), snapshot(str(self.outside))
        self.logged = []
        self.answers = []
        places = lambda: [ff.Place("internal", "Internal storage", str(self.home)),
                          ff.Place("sd", "SD card", str(self.card))]
        for target, name, value in ((ff, "list_places", places), (server, "_log", self.logged.append)):
            patch = mock.patch.object(target, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        settings = {"movies_path": "", "tv_path": "", "mpv_command": "auto", "mpv_args": [], "resume": False,
                    "keep_awake": False, "data_dir": str(self.root / "data")}
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        self.port = self.httpd.server_address[1]
        self.httpd_ref = {}
        with contextlib.redirect_stdout(io.StringIO()):
            base = server.make_handler(UI_DIR, self.root / "logs", settings, self.httpd_ref, self.port, None,
                                       self.settings_file)

        class Quiet(base):
            def log_message(self, format, *args):
                pass

        self.httpd.RequestHandlerClass = Quiet
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.addCleanup(self.stand_in.release)

    def tearDown(self):
        for text in self.answers + self.logged:
            for private in (self.tmp.name, "CardLabel" + os.sep, "private-parent", "home-of-someone", "secret-noise"):
                self.assertNotIn(private, text)
        self.assertEqual((snapshot(str(self.card)), snapshot(str(self.home)), snapshot(str(self.outside))),
                         self.media_before)
        after = self.real_settings.stat().st_mtime_ns if self.real_settings.exists() else None
        self.assertEqual(after, self.real_before)

    def request(self, method, path, body=None, raw=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        try:
            data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
            conn.request(method, path, body=data, headers={"Host": f"127.0.0.1:{self.port}",
                                                           "Content-Type": "application/json"})
            resp = conn.getresponse()
            text = resp.read().decode("utf-8")
        finally:
            conn.close()
        self.answers.append(text)
        return resp.status, json.loads(text)

    def search(self):
        status, answer = self.request("GET", "/api/onboarding/folders")
        self.assertEqual(status, 200)
        self.ids = {f["name"]: f["id"] for p in answer["places"] for f in p["folders"]}
        return answer

    def browse(self, movies=None):
        status, answer = self.request("POST", "/api/onboarding/browse", {"movies": movies})
        self.assertEqual(status, 200)
        return answer

    def pick(self, path, movies=None):
        self.stand_in.answer(path)
        return self.browse(movies)

    def test_the_search_says_whether_a_dialog_is_there(self):
        self.assertFalse(self.search()["browse"])
        self.stand_in.add("zenity")
        self.assertTrue(self.search()["browse"])

    def test_with_no_dialog_nothing_opens(self):
        self.search()
        answer = self.browse()
        self.assertEqual(answer, {"ok": False, "message": folder_dialog.OPEN_FAILED})
        self.assertIn("onboarding: no folder dialog found", self.logged)

    def test_a_picked_folder_gets_a_row_and_can_be_chosen(self):
        self.stand_in.add("kdialog")
        self.search()
        answer = self.pick(self.card / "Elsewhere" / "Inner")
        self.assertTrue(answer["ok"] and answer["picked"])
        self.assertIsNone(answer["message"])
        self.assertEqual(answer["place_kind"], "sd")
        self.assertEqual((answer["folder"]["place"], answer["folder"]["trail"]), ("SD card", ["Elsewhere", "Inner"]))
        self.assertIn("onboarding: folder dialog (kdialog): picked", self.logged)
        self.assertEqual(self.settings_file.read_bytes(), self.settings_before)  # shown, not saved yet
        status, saved = self.request("POST", "/api/onboarding/choose", {"movies": answer["folder"]["id"], "tv": None})
        self.assertEqual(saved, {"ok": True})
        self.assertEqual(json.loads(self.settings_file.read_text())["movies_path"], str(self.card / "Elsewhere" / "Inner"))
        self.answers.pop()  # checked just above

    def test_the_same_checks_and_messages_as_a_listed_folder(self):
        self.stand_in.add("kdialog")
        self.search()
        films = self.ids["Films"]
        self.assertEqual(self.pick(self.card / "Films", films)["message"], onboarding.SAME)
        (self.card / "Films" / "Old").mkdir()
        self.addCleanup((self.card / "Films" / "Old").rmdir)
        self.media_before = (snapshot(str(self.card)), *self.media_before[1:])
        self.assertEqual(self.pick(self.card / "Films" / "Old", films)["message"], onboarding.INSIDE_MOVIES)
        self.assertEqual(self.pick(self.card, films)["message"], onboarding.HOLDS_MOVIES)
        self.assertIsNone(self.pick(self.card / "Elsewhere", films)["message"])
        # And the choice itself is refused in the same words.
        held = self.pick(self.card, films)["folder"]["id"]
        self.assertEqual(self.request("POST", "/api/onboarding/choose", {"movies": films, "tv": held})[1],
                         {"ok": False, "message": onboarding.HOLDS_MOVIES})
        self.assertEqual(self.settings_file.read_bytes(), self.settings_before)

    def test_a_picked_folder_that_cant_be_read_says_so_and_cant_be_saved(self):
        # The first onboarding review fixes.
        if os.geteuid() == 0:
            self.skipTest("root can read everything")
        self.stand_in.add("kdialog")
        self.search()
        locked = self.root / "Locked"
        locked.mkdir()
        os.chmod(locked, 0)
        self.addCleanup(os.chmod, locked, 0o755)
        answer = self.pick(locked)
        self.assertEqual(answer["message"], ff.CANT_BE_READ)
        self.assertEqual(answer["folder"]["count_text"], "Couldn't be read")
        self.assertEqual(self.request("POST", "/api/onboarding/choose", {"movies": answer["folder"]["id"], "tv": None})[1],
                         {"ok": False, "message": ff.CANT_BE_READ})
        self.assertEqual(self.settings_file.read_bytes(), self.settings_before)
        # Readable now: the same folder can be chosen after all.
        os.chmod(locked, 0o755)
        answer = self.pick(locked)
        self.assertIsNone(answer["message"])
        self.assertEqual(self.request("POST", "/api/onboarding/choose", {"movies": answer["folder"]["id"], "tv": None})[1],
                         {"ok": True})

    def test_a_picked_folder_holding_kettles_files_is_refused(self):
        # The first onboarding review fixes: here the settings file sits in the invented folder itself.
        self.stand_in.add("kdialog")
        self.search()
        answer = self.pick(self.root)
        self.answers.pop()  # this folder's own name and what's in it, as for any picked folder
        self.assertEqual(answer["message"], onboarding.OWN_FILES_PICKED)
        self.assertIn("Browse somewhere else", onboarding.OWN_FILES_PICKED)
        self.assertEqual(answer["folder"]["problem"], onboarding.OWN_FILES_PICKED)
        self.assertEqual(self.request("POST", "/api/onboarding/choose", {"movies": answer["folder"]["id"], "tv": None})[1],
                         {"ok": False, "message": onboarding.OWN_FILES_PICKED})
        self.assertEqual(self.settings_file.read_bytes(), self.settings_before)
        self.assertIsNone(self.pick(self.card)["message"])

    def test_a_picked_name_ending_in_a_space_is_found_at_the_next_launch(self):
        # The first onboarding review fixes: it used to work until a restart, then "Folder not available".
        self.stand_in.add("kdialog")
        self.search()
        spaced = self.root / "Spaced Films "
        make(str(spaced), ["Alpha/a.mkv"])
        answer = self.pick(spaced)
        self.assertEqual(self.request("POST", "/api/onboarding/choose", {"movies": answer["folder"]["id"], "tv": None})[1],
                         {"ok": True})
        saved = load_settings(self.root)["movies_path"]
        self.assertEqual(saved, str(spaced))
        self.assertTrue(os.path.isdir(saved))
        self.assertEqual(library_index.availability({"movies": saved, "tv": ""})["movies"], True)

    def test_a_folder_already_listed_keeps_its_id(self):
        self.stand_in.add("kdialog")
        self.search()
        self.assertEqual(self.pick(self.card / "Films")["folder"]["id"], self.ids["Films"])

    def test_a_folder_in_no_place_never_gives_its_parents_away(self):
        self.stand_in.add("kdialog")
        self.search()
        answer = self.pick(self.outside)
        self.assertEqual((answer["folder"]["place"], answer["folder"]["name"], answer["place_kind"]),
                         ("Somewhere else", "Outside", "other"))

    def test_a_cancel_changes_nothing(self):
        self.stand_in.add("kdialog")
        self.search()
        for output, code in (("", 1), ("", 0)):
            with self.subTest(code=code):
                self.stand_in.answer(output, code)
                self.assertEqual(self.browse(), {"ok": True, "picked": False})
        self.assertEqual(self.logged.count("onboarding: folder dialog (kdialog): cancelled"), 2)
        self.assertEqual(self.settings_file.read_bytes(), self.settings_before)
        self.assertEqual(self.request("GET", "/api/onboarding"), (200, {"needed": True}))

    def test_a_failed_dialog_gets_a_plain_line_in_the_log(self):
        self.stand_in.add("kdialog")
        self.search()
        self.stand_in.answer(self.card, 255)
        self.assertEqual(self.browse(), {"ok": False, "message": folder_dialog.OPEN_FAILED})
        self.assertIn("onboarding: folder dialog (kdialog): failed", self.logged)

    def test_a_dialog_that_crashes_says_so_and_isnt_called_cancelled(self):
        self.stand_in.add("kdialog")
        self.search()
        self.stand_in.answer("", -6)
        self.assertEqual(self.browse(), {"ok": False, "message": folder_dialog.OPEN_FAILED})
        self.assertIn("onboarding: folder dialog (kdialog): failed", self.logged)
        self.assertNotIn("onboarding: folder dialog (kdialog): cancelled", self.logged)

    def test_a_dialog_that_cant_start_gets_a_plain_line_in_the_log(self):
        self.stand_in.add("kdialog")
        self.search()
        denied = PermissionError(13, "Permission denied", str(self.card))
        with mock.patch.object(folder_dialog.subprocess, "Popen", side_effect=denied):
            self.assertEqual(self.browse(), {"ok": False, "message": folder_dialog.OPEN_FAILED})
        self.assertIn("onboarding: folder dialog (kdialog) couldn't start (PermissionError)", self.logged)
        # And the next try isn't told one is already open.
        self.stand_in.answer("", 1)
        self.assertEqual(self.browse(), {"ok": True, "picked": False})

    def test_an_answer_that_isnt_a_folder(self):
        self.stand_in.add("kdialog")
        self.search()
        self.assertEqual(self.pick(self.card / "Films" / "Alpha" / "a.mkv"),
                         {"ok": False, "message": folder_dialog.NOT_A_FOLDER_MESSAGE})
        self.assertIn("onboarding: folder dialog (kdialog): not a folder", self.logged)

    def test_the_dialogs_own_error_output_never_reaches_the_log(self):
        self.stand_in.add("kdialog")
        self.search()
        out, err = io.StringIO(), io.StringIO()
        self.stand_in.answer("", 1)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.browse()
        self.assertNotIn("secret-noise", out.getvalue() + err.getvalue())
        with mock.patch.object(folder_dialog.subprocess, "Popen", wraps=subprocess.Popen) as popen:
            self.stand_in.answer("", 1)
            self.browse()
        self.assertEqual(popen.call_args.kwargs["stderr"], subprocess.DEVNULL)

    def open_dialog(self, movies=None):
        """A dialog held open, its request waiting on a thread."""
        self.stand_in.add("kdialog")
        self.search()
        self.stand_in.hold()
        result = {}

        def run():
            result["answer"] = self.browse(movies)

        thread = threading.Thread(target=run)
        thread.start()
        self.addCleanup(thread.join, 30)
        self.assertIsNotNone(self.stand_in.wait_started())
        return thread, result

    def test_the_server_keeps_answering_while_the_dialog_is_open(self):
        thread, result = self.open_dialog()
        for _ in range(5):
            started = time.monotonic()
            self.assertEqual(self.request("GET", "/api/onboarding"), (200, {"needed": True}))
            self.assertLess(time.monotonic() - started, 1)
        self.assertTrue(thread.is_alive())
        self.stand_in.answer("", 1)
        self.stand_in.release()
        thread.join(10)
        self.assertEqual(result["answer"], {"ok": True, "picked": False})

    def test_there_is_no_time_limit(self):
        with mock.patch.object(subprocess.Popen, "communicate", autospec=True,
                               side_effect=subprocess.Popen.communicate) as communicate:
            self.stand_in.add("kdialog")
            self.stand_in.answer("", 1)
            self.search()
            self.browse()
        self.assertEqual(communicate.call_args.kwargs, {})
        self.assertEqual(len(communicate.call_args.args), 1)

    def test_one_dialog_at_a_time(self):
        thread, _ = self.open_dialog()
        self.assertEqual(self.browse(), {"ok": False, "message": folder_dialog.ALREADY_OPEN})
        self.stand_in.answer("", 1)
        self.stand_in.release()
        thread.join(10)

    def test_b_closes_the_dialog_as_a_cancel(self):
        thread, result = self.open_dialog()
        self.assertEqual(self.request("POST", "/api/onboarding/browse/close", {}), (200, {"ok": True}))
        thread.join(10)
        self.assertEqual(result["answer"], {"ok": True, "picked": False})
        self.assertIn("onboarding: folder dialog (kdialog): cancelled", self.logged)

    def test_closing_with_no_dialog_open_does_nothing(self):
        self.assertEqual(self.request("POST", "/api/onboarding/browse/close", {}), (200, {"ok": True}))

    def test_the_server_stopping_leaves_no_dialog_running(self):
        thread, result = self.open_dialog()
        self.httpd_ref["finish_playback"]()
        thread.join(10)
        self.assertEqual(result["answer"], {"ok": True, "picked": False})
        # And none opens once it is closing.
        self.assertEqual(self.browse(), {"ok": False, "message": folder_dialog.ALREADY_OPEN})

    def test_a_request_that_isnt_a_choice_is_refused(self):
        self.stand_in.add("kdialog")
        for body in ({"movies": 5}, {"movies": ["x"]}, [1]):
            with self.subTest(body=body):
                self.assertEqual(self.request("POST", "/api/onboarding/browse", body)[0], 400)
        self.assertIsNone(self.stand_in.started())


if __name__ == "__main__":
    unittest.main()
