# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Closing the app while a film plays (the server shutdown check, option A): mpv gets a
control socket, the server asks it to quit normally before it stops, and
waits (a limited time) for mpv to close so the stop is kept: the Continue
watching tile comes back after a restart, with the full-size frame as its
picture. A stop signal to the server goes the same way. Uses a fake mpv;
the real one is in tests/continue_watching_mpv_check.py.

Run from the repo root:  python3 -m unittest discover -s tests -t . -v
"""

import contextlib
import http.client
import io
import json
import socket
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from backend import mpv, server
from backend.server import close_server, make_handler

UI_DIR = Path(__file__).resolve().parent.parent / "ui"

# Listens on --input-ipc-server like mpv; quits on {"command": ["quit"]}
# unless started with IGNORE in its arguments (then it ends 3 s later).
FAKE_MPV = """#!{python}
import json, socket, sys, time
path = next(a.split("=", 1)[1] for a in sys.argv if a.startswith("--input-ipc-server="))
ignore = "IGNORE" in sys.argv
srv = socket.socket(socket.AF_UNIX)
srv.bind(path)
srv.listen(1)
srv.settimeout(20)
try:
    conn, _ = srv.accept()
    line = conn.makefile().readline()
    if json.loads(line)["command"] == ["quit"] and not ignore:
        print("asked to quit", flush=True)
        sys.exit(0)
    time.sleep(3)
except socket.timeout:
    sys.exit(3)
"""


class BuildCommandTest(unittest.TestCase):
    def test_control_socket_added(self):
        args = mpv.build_command(["mpv"], Path("/x/film.mkv"), control_socket=Path("/tmp/k/mpv.sock"))
        self.assertIn("--input-ipc-server=/tmp/k/mpv.sock", args)
        self.assertEqual(args[-1], "/x/film.mkv")

    def test_control_socket_added_with_resume_off(self):
        args = mpv.build_command(["mpv"], Path("/x/film.mkv"), resume=False,
                                 control_socket=Path("/tmp/k/mpv.sock"))
        self.assertIn("--input-ipc-server=/tmp/k/mpv.sock", args)

    def test_no_control_socket_by_default(self):
        args = mpv.build_command(["mpv"], Path("/x/film.mkv"))
        self.assertFalse(any(a.startswith("--input-ipc-server") for a in args))

    def test_users_own_socket_wins(self):
        args = mpv.build_command(["mpv"], Path("/x/film.mkv"), ["--input-ipc-server=/tmp/mine"],
                                 control_socket=Path("/tmp/k/mpv.sock"))
        self.assertEqual([a for a in args if a.startswith("--input-ipc-server")],
                         ["--input-ipc-server=/tmp/mine"])


class AskToQuitTest(unittest.TestCase):
    def test_sends_quit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mpv.sock"
            received = []
            with socket.socket(socket.AF_UNIX) as srv:
                srv.bind(str(path))
                srv.listen(1)

                def accept():
                    conn, _ = srv.accept()
                    with conn:
                        received.append(conn.makefile().readline())

                t = threading.Thread(target=accept)
                t.start()
                self.assertTrue(mpv.ask_to_quit(path))
                t.join(5)
        self.assertEqual(json.loads(received[0]), {"command": ["quit"]})

    def test_no_socket_is_reported_not_raised(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(mpv.ask_to_quit(Path(tmp) / "missing.sock"))


class ServerMixin:
    """A real server on a free port, with a fake mpv, in a temporary folder."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.movies = self.root / "Movies"
        self.movies.mkdir()
        (self.movies / "Film.mkv").write_bytes(b"")
        self.logs = self.root / "logs"
        self.logs.mkdir()
        fake = self.root / "fake-mpv"
        fake.write_text(FAKE_MPV.format(python=sys.executable))
        fake.chmod(0o755)
        self.fake = str(fake)
        self.httpd = None
        self.out = io.StringIO()

    def tearDown(self):
        if self.httpd is not None:
            self.httpd.server_close()
        self.tmp.cleanup()

    def start(self, mpv_args=()):
        settings = {
            "movies_path": str(self.movies), "tv_path": str(self.movies),
            "mpv_command": self.fake, "mpv_args": list(mpv_args),
            "resume": True, "keep_awake": False, "data_dir": str(self.root / "data"),
        }
        self.ref = {}
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        self.port = self.httpd.server_address[1]
        with contextlib.redirect_stdout(self.out):
            base = make_handler(UI_DIR, self.logs, settings, self.ref, self.port)

        class Quiet(base):
            def log_message(self, format, *args):
                pass

        self.httpd.RequestHandlerClass = Quiet
        self.ref["server"] = self.httpd
        self.serving = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.serving.start()

    def request(self, method, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Content-Type": "application/json"} if body is not None else {}
        conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
        resp = conn.getresponse()
        data = json.loads(resp.read())
        conn.close()
        return data

    def play_and_wait_for_socket(self):
        """Play, and return the control folder made for this film."""
        before = set(Path("/tmp").glob("kettle-mpv-*"))
        self.assertEqual(self.request("POST", "/api/play", {"source": "movies", "path": "Film.mkv"}),
                         {"started": True, "keep_awake": False})
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            for folder in set(Path("/tmp").glob("kettle-mpv-*")) - before:
                if (folder / "mpv.sock").exists():
                    return folder
            time.sleep(0.05)
        self.fail("mpv's control socket never appeared")

    def close(self):
        started = time.monotonic()
        with contextlib.redirect_stdout(self.out):
            close_server(self.ref)
        self.serving.join(5)
        return time.monotonic() - started


class ServerClosingTest(ServerMixin, unittest.TestCase):
    def test_closing_asks_mpv_to_quit_and_waits_for_it(self):
        self.start()
        self.play_and_wait_for_socket()
        took = self.close()
        self.assertFalse(self.serving.is_alive(), "the server is still running")
        self.assertLess(took, 2.0)
        self.assertIn("mpv closed and the stop was kept", self.out.getvalue())
        log = next(self.logs.glob("mpv-*.log")).read_text()
        self.assertIn("asked to quit", log)

    def test_the_control_folder_is_removed_after_playback(self):
        self.start()
        folder = self.play_and_wait_for_socket()
        self.close()
        self.assertFalse(folder.exists())

    def test_an_mpv_that_wont_close_does_not_hold_the_server(self):
        self.start(["IGNORE"])
        self.play_and_wait_for_socket()
        with mock.patch.object(server, "PLAYBACK_CLOSE_WAIT", 0.5):
            took = self.close()
        self.assertFalse(self.serving.is_alive())
        self.assertLess(took, 2.0)
        self.assertIn("didn't close within 0.5 s", self.out.getvalue())

    def test_closing_with_nothing_playing_is_immediate(self):
        self.start()
        took = self.close()
        self.assertFalse(self.serving.is_alive())
        self.assertLess(took, 1.0)

    def test_the_apps_own_quit_waits_for_mpv_too(self):
        self.start()
        self.play_and_wait_for_socket()
        with contextlib.redirect_stdout(self.out):
            self.assertEqual(self.request("POST", "/api/shutdown", {}), {"ok": True})
            self.serving.join(5)
        self.assertFalse(self.serving.is_alive())
        self.assertIn("mpv closed and the stop was kept", self.out.getvalue())


# Like FAKE_MPV, and on the quit request it also writes what the real quit
# script writes while closing (position and frame). Every call is noted, so
# a picture-shrinking run (--vo-image-outdir) would show up.
FAKE_MPV_WITH_SCRIPT = """#!{python}
import json, pathlib, socket, sys
here = pathlib.Path(__file__).parent
with open(here / "calls.jsonl", "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
for a in sys.argv:
    if a.startswith("--vo-image-outdir="):
        pathlib.Path(a.split("=", 1)[1], "00000001.jpg").write_bytes(b"\\xff\\xd8 small picture")
        sys.exit(0)
path = next(a.split("=", 1)[1] for a in sys.argv if a.startswith("--input-ipc-server="))
out = next(a.split("kettle_quit-out_dir=", 1)[1] for a in sys.argv
           if a.startswith("--script-opts-append=kettle_quit-out_dir="))
srv = socket.socket(socket.AF_UNIX)
srv.bind(path)
srv.listen(1)
srv.settimeout(20)
conn, _ = srv.accept()
if json.loads(conn.makefile().readline())["command"] == ["quit"]:
    (pathlib.Path(out) / "frame.jpg").write_bytes(b"\\xff\\xd8 full frame")
    (pathlib.Path(out) / "record.json").write_text(json.dumps(
        {{"position": 1800, "duration": 7200, "finished": False, "frame_saved": True}}))
"""


class StopKeptWhenClosingTest(ServerMixin, unittest.TestCase):
    """The stop of a film playing when the app closes is kept for Continue
    watching, with the full-size frame as its picture (no time to shrink)."""

    def setUp(self):
        super().setUp()
        from tests.test_parsed_library import MOVIE_FILES
        self.film_rel = MOVIE_FILES[2]
        (self.movies / self.film_rel).parent.mkdir(parents=True, exist_ok=True)
        (self.movies / self.film_rel).write_bytes(b"")
        fake = self.root / "fake" / "mpv"
        fake.parent.mkdir()
        fake.write_text(FAKE_MPV_WITH_SCRIPT.format(python=sys.executable))
        fake.chmod(0o755)
        self.fake = str(fake)
        self.calls_file = fake.parent / "calls.jsonl"

    def scan(self):
        self.request("POST", "/api/library/scan", {})
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if self.request("GET", "/api/library/scan/status")["state"] == "idle":
                return
            time.sleep(0.1)
        self.fail("scan didn't finish")

    def test_closing_keeps_the_stop_and_the_full_size_picture(self):
        self.start()
        self.scan()
        before = set(Path("/tmp").glob("kettle-mpv-*"))
        self.assertEqual(self.request("POST", "/api/play", {"source": "movies", "path": self.film_rel}),
                         {"started": True, "keep_awake": False})
        deadline = time.monotonic() + 10
        while not any((f / "mpv.sock").exists() for f in set(Path("/tmp").glob("kettle-mpv-*")) - before):
            if time.monotonic() > deadline:
                self.fail("mpv's control socket never appeared")
            time.sleep(0.05)
        took = self.close()
        self.assertLess(took, 2.0)
        self.httpd.server_close()
        time.sleep(1.0)  # room for a shrinking run that shouldn't happen
        calls = [json.loads(line) for line in self.calls_file.read_text().splitlines()]
        self.assertFalse(any(a.startswith("--vo-image-outdir=") for c in calls for a in c),
                         "the picture was shrunk while the app was closing")

        # The next start shows the tile, at the position kept, with the full frame.
        self.start()
        items = self.request("GET", "/api/continue")["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["position"], 1800)
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", items[0]["picture"])
        resp = conn.getresponse()
        self.assertEqual((resp.status, resp.read()), (200, b"\xff\xd8 full frame"))
        conn.close()
        self.close()


class StopSignalTest(unittest.TestCase):
    """A stop signal to the server (launch.sh, Steam's "Exit game") goes
    through close_server, so a playing film is asked to quit first."""

    def test_stop_signal_closes_through_close_server(self):
        handlers = {}
        with tempfile.TemporaryDirectory() as tmp:
            settings = {
                "movies_path": tmp, "tv_path": tmp, "mpv_command": "mpv", "mpv_args": [],
                "resume": True, "keep_awake": False, "data_dir": tmp,
            }
            called = threading.Event()
            seen = []

            def fake_close(ref):
                seen.append(ref)
                called.set()

            with mock.patch.object(server, "repo_root", return_value=Path(tmp)), \
                    mock.patch.object(server, "load_settings", return_value=settings), \
                    mock.patch.object(server, "ThreadingHTTPServer") as fake_httpd, \
                    mock.patch.object(server.signal, "signal", lambda s, h: handlers.__setitem__(s, h)), \
                    mock.patch.object(server, "close_server", fake_close), \
                    contextlib.redirect_stdout(io.StringIO()):
                server.main()
                handlers[server.signal.SIGTERM](server.signal.SIGTERM, None)
                self.assertTrue(called.wait(5), "the stop signal didn't go through close_server")
        self.assertIs(seen[0]["server"], fake_httpd.return_value)
        self.assertTrue(callable(seen[0]["finish_playback"]))


if __name__ == "__main__":
    unittest.main()
