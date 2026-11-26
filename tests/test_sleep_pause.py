# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""A film stays paused where it was after sleep (the sleep pause fix).

The launch rehearsal found a film started over after the power button put
the device to sleep and woke it. A terminal can't make a real sleep, so
these tests play out what happens around one with a stand-in mpv (its
control socket) and the system's sleep messages as gdbus prints them:
about to sleep, mpv is paused and its spot remembered; on waking, a film
that moved is put back there, still paused, and play continues from it.
The real mpv is in tests/sleep_pause_mpv_check.py. The keep-awake lock
itself (idle only, so the power button still sleeps) stays covered by
tests/test_keep_awake.py.

Run from the repo root:  python3 -m unittest discover -s tests -t . -v
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from backend import mpv, sleep_pause

SLEEP = "/org/freedesktop/login1: org.freedesktop.login1.Manager.PrepareForSleep (true,)\n"
WAKE = "/org/freedesktop/login1: org.freedesktop.login1.Manager.PrepareForSleep (false,)\n"


class FakeMpv:
    """Just enough of mpv's control socket: pause, time-pos, seek and the
    on-screen text. Like mpv, it sends an event before each answer."""

    def __init__(self, path: Path, position: float = 62.0):
        self.state = {"pause": False, "time-pos": position, "duration": 146.0}
        self.commands = []
        self.shown = []
        self._server = socket.socket(socket.AF_UNIX)
        self._server.bind(str(path))
        self._server.listen(8)
        self._server.settimeout(0.1)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        while not self._stop.is_set():
            try:
                conn, _ = self._server.accept()
            except OSError:
                continue
            with conn, conn.makefile() as reader:
                line = reader.readline()
                if not line:
                    continue
                request = json.loads(line)
                data, error = self._run(request["command"])
                conn.sendall(json.dumps({"event": "property-change", "name": "time-pos"}).encode() + b"\n")
                answer = {"data": data, "error": error, "request_id": request.get("request_id", 0)}
                conn.sendall(json.dumps(answer).encode() + b"\n")

    def _run(self, command):
        self.commands.append(command)
        name, *args = command
        if name == "get_property" and args[0] in self.state:
            return self.state[args[0]], "success"
        if name == "set_property" and args[0] in self.state:
            self.state[args[0]] = args[1]
            return None, "success"
        if name == "seek" and args[1:] == ["absolute+exact"]:
            self.state["time-pos"] = float(args[0])
            return None, "success"
        if name == "expand-text":
            return f"Paused\n{self.state['time-pos']:.0f} / {self.state['duration']:.0f}", "success"
        if name == "show-text":
            self.shown.append(args[0])
            return None, "success"
        return None, "invalid parameter"

    def close(self):
        self._stop.set()
        self._thread.join(timeout=2)
        self._server.close()


class ParseTest(unittest.TestCase):
    def test_about_to_sleep(self):
        self.assertIs(sleep_pause.parse(SLEEP), True)

    def test_woken_up(self):
        self.assertIs(sleep_pause.parse(WAKE), False)

    def test_other_lines(self):
        for line in (
            "Monitoring signals on object /org/freedesktop/login1 owned by org.freedesktop.login1\n",
            "The name org.freedesktop.login1 is owned by :1.9\n",
            "/org/freedesktop/login1: org.freedesktop.login1.Manager.PrepareForShutdown (true,)\n",
            "/org/freedesktop/login1: org.freedesktop.DBus.Properties.PropertiesChanged ('x', {}, @as [])\n",
            "",
        ):
            self.assertIsNone(sleep_pause.parse(line), line)

    def test_listens_to_logind_on_the_system_bus(self):
        self.assertEqual(
            sleep_pause.monitor_command("/usr/bin/gdbus"),
            ["/usr/bin/gdbus", "monitor", "--system", "--dest", "org.freedesktop.login1",
             "--object-path", "/org/freedesktop/login1"],
        )


class AroundSleepTest(unittest.TestCase):
    """Sleep and wake as the messages arrive, against the stand-in mpv."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "mpv.sock"
        self.mpv = FakeMpv(self.path)
        self.log = []
        self.watch = sleep_pause.SleepPause(self.path, self.log.append, guard_seconds=0.3, check_seconds=0.05)

    def tearDown(self):
        self.mpv.close()
        self.tmp.cleanup()

    def test_film_is_paused_when_the_device_goes_to_sleep(self):
        self.watch.handle(SLEEP)
        self.assertIs(self.mpv.state["pause"], True)
        self.assertIn("going to sleep; film paused at 62.0 s", self.log[-1])

    def test_film_that_moved_on_waking_is_put_back_still_paused(self):
        # What the launch rehearsal saw: after waking, the film was near the start.
        self.watch.handle(SLEEP)
        self.mpv.state["time-pos"] = 0.0
        self.watch.handle(WAKE)
        self.assertAlmostEqual(self.mpv.state["time-pos"], 62.0)
        self.assertIs(self.mpv.state["pause"], True)
        self.assertIn(["seek", 62.0, "absolute+exact"], self.mpv.commands)
        self.assertTrue(any("moved to 0.0 s; put back at 62.0 s" in line for line in self.log), self.log)

    def test_film_that_moves_a_moment_after_waking_is_put_back_too(self):
        self.watch.handle(SLEEP)

        def jump_later():
            time.sleep(0.1)
            self.mpv.state["time-pos"] = 3.0

        jumper = threading.Thread(target=jump_later)
        jumper.start()
        self.watch.handle(WAKE)
        jumper.join()
        self.assertAlmostEqual(self.mpv.state["time-pos"], 62.0)

    def test_paused_text_shows_on_waking(self):
        self.watch.handle(SLEEP)
        self.watch.handle(WAKE)
        self.assertEqual(self.mpv.shown, ["Paused\n62 / 146"])
        self.assertIn(["show-text", "Paused\n62 / 146", sleep_pause.PAUSED_TEXT_MS], self.mpv.commands)

    def test_film_that_stayed_put_is_not_moved(self):
        self.watch.handle(SLEEP)
        self.mpv.state["time-pos"] = 62.4
        self.watch.handle(WAKE)
        self.assertNotIn("seek", [c[0] for c in self.mpv.commands])
        self.assertAlmostEqual(self.mpv.state["time-pos"], 62.4)

    def test_play_continues_from_the_spot(self):
        self.watch.handle(SLEEP)
        self.mpv.state["time-pos"] = 0.0
        self.watch.handle(WAKE)
        self.mpv.state["pause"] = False  # the viewer presses A
        self.assertAlmostEqual(self.mpv.state["time-pos"], 62.0)

    def test_viewer_pressing_play_after_waking_is_left_alone(self):
        self.watch.handle(SLEEP)
        self.mpv.state["pause"] = False
        self.mpv.state["time-pos"] = 80.0
        self.watch.handle(WAKE)
        self.assertNotIn("seek", [c[0] for c in self.mpv.commands])
        self.assertIs(self.mpv.state["pause"], False)

    def test_film_paused_before_sleep_stays_paused(self):
        self.mpv.state["pause"] = True
        self.watch.handle(SLEEP)
        self.watch.handle(WAKE)
        self.assertIs(self.mpv.state["pause"], True)
        self.assertAlmostEqual(self.mpv.state["time-pos"], 62.0)

    def test_waking_without_a_sleep_changes_nothing(self):
        self.watch.handle(WAKE)
        self.assertEqual(self.mpv.commands, [])

    def test_other_lines_change_nothing(self):
        self.watch.handle("The name org.freedesktop.login1 is owned by :1.9\n")
        self.assertEqual(self.mpv.commands, [])


class MpvGoneTest(unittest.TestCase):
    def test_no_mpv_to_pause_is_only_logged(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = []
            watch = sleep_pause.SleepPause(Path(tmp) / "none.sock", log.append, guard_seconds=0.2)
            watch.handle(SLEEP)
            watch.handle(WAKE)
        self.assertIn("mpv couldn't be paused", log[0])

    def test_ask_answers_false_without_mpv(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(sleep_pause.ask(Path(tmp) / "none.sock", ["get_property", "pause"]), (False, None))


class FakeDelayLock:
    """Records when the sleep delay lock is taken and let go."""

    def __init__(self, events):
        self.events = events

    def take(self):
        self.events.append("take")
        return True

    def release(self):
        self.events.append("release")


class DelayLockTest(unittest.TestCase):
    """The short sleep delay lock: the system waits for the pause, but
    never for long, and a sleep is never blocked (the power button fix)."""

    def test_asks_for_a_delay_never_a_block(self):
        command = sleep_pause.delay_lock_command("/usr/bin/systemd-inhibit")
        self.assertIn("--what=sleep", command)
        self.assertIn("--mode=delay", command)
        self.assertNotIn("--mode=block", command)
        self.assertEqual(command[-1], "cat")

    def test_let_go_right_after_the_pause(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mpv.sock"
            fake = FakeMpv(path)
            events = []
            original = fake._run

            def run(command):
                events.append(command[0])
                return original(command)

            fake._run = run
            try:
                watch = sleep_pause.SleepPause(path, [].append, delay_lock=FakeDelayLock(events))
                watch.handle(SLEEP)
            finally:
                fake.close()
        self.assertEqual(events[:2], ["set_property", "release"], events)

    def test_let_go_after_the_cap_when_mpv_does_not_answer(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mpv.sock"
            silent = socket.socket(socket.AF_UNIX)
            silent.bind(str(path))
            silent.listen(4)  # accepts, never answers
            events = []
            released = []
            lock = FakeDelayLock(events)
            lock.release = lambda: released.append(time.monotonic())
            watch = sleep_pause.SleepPause(path, [].append, delay_lock=lock, delay_cap_seconds=0.2)
            started = time.monotonic()
            threading.Thread(target=watch.going_to_sleep, daemon=True).start()
            self.assertTrue(wait_until(lambda: released, timeout=0.8), "let go by the cap")
            self.assertLess(released[0] - started, 0.6)
            silent.close()

    def test_taken_again_on_waking_and_let_go_at_the_end(self):
        events = []
        with tempfile.TemporaryDirectory() as tmp:
            watch = sleep_pause.SleepPause(Path(tmp) / "none.sock", [].append, guard_seconds=0.1,
                                           delay_lock=FakeDelayLock(events))
            watch.handle(SLEEP)
            watch.handle(WAKE)
            watch.stop()
        self.assertEqual(events, ["release", "take", "release"])

    def test_no_lock_tool_holds_nothing(self):
        lock = sleep_pause.DelayLock(None)
        self.assertFalse(lock.take())
        lock.release()

    def test_lock_tool_missing_is_logged(self):
        log = []
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            watch = sleep_pause.SleepPause(folder / "mpv.sock", log.append)
            watch.start(str(write_fake_monitor(folder)), delay_tool="/nonexistent/systemd-inhibit")
            watch.stop()
        self.assertEqual(log, [sleep_pause.DELAY_MISSING])


def kettle_delay_locks():
    listing = subprocess.run(["systemd-inhibit", "--list", "--no-pager"],
                             capture_output=True, text=True).stdout
    return [line for line in listing.splitlines() if sleep_pause.DELAY_WHY in line]


@unittest.skipUnless(shutil.which("systemd-inhibit") and shutil.which("busctl")
                     and os.path.exists("/run/dbus/system_bus_socket"),
                     "needs systemd-inhibit and a system bus")
class RealDelayLockTest(unittest.TestCase):
    """With the system's real lock tool."""

    def can_sleep(self):
        answer = subprocess.run(
            ["busctl", "call", "org.freedesktop.login1", "/org/freedesktop/login1",
             "org.freedesktop.login1.Manager", "CanSuspend"], capture_output=True, text=True)
        return answer.stdout.strip()

    def test_held_then_gone_and_sleep_still_allowed(self):
        before = self.can_sleep()
        lock = sleep_pause.DelayLock(shutil.which("systemd-inhibit"))
        self.assertTrue(lock.take())
        try:
            self.assertTrue(wait_until(lambda: kettle_delay_locks()), "the delay lock is listed")
            self.assertIn(" delay", kettle_delay_locks()[0])
            # A delay lock never turns a "yes" into "inhibited".
            self.assertEqual(self.can_sleep(), before)
            process = lock._process
        finally:
            lock.release()
        self.assertIsNotNone(process.poll())
        self.assertTrue(wait_until(lambda: not kettle_delay_locks()), "the delay lock is gone")

    def test_gone_when_the_app_ends_without_letting_go(self):
        script = (
            "import os, shutil, sys, time\n"
            f"sys.path.insert(0, {str(Path(__file__).resolve().parent.parent)!r})\n"
            "from backend import sleep_pause\n"
            "sleep_pause.DelayLock(shutil.which('systemd-inhibit')).take()\n"
            "time.sleep(1)\n"
            "os._exit(0)\n"
        )
        subprocess.run([sys.executable, "-c", script], check=True, timeout=20)
        self.assertTrue(wait_until(lambda: not kettle_delay_locks()), "no lock left behind")


def write_fake_monitor(folder: Path) -> Path:
    """A stand-in gdbus: prints the two sleep messages when the files
    'sleep' and 'wake' appear next to it, then waits to be stopped."""
    tool = folder / "gdbus"
    tool.write_text(
        f"#!{sys.executable}\n"
        "import pathlib, sys, time\n"
        "here = pathlib.Path(__file__).parent\n"
        "print('Monitoring signals on object /org/freedesktop/login1', flush=True)\n"
        f"for name, line in (('sleep', {SLEEP!r}), ('wake', {WAKE!r})):\n"
        "    while not (here / name).exists():\n"
        "        time.sleep(0.02)\n"
        "    sys.stdout.write(line)\n"
        "    sys.stdout.flush()\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    tool.chmod(0o755)
    return tool


def wait_until(test, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if test():
            return True
        time.sleep(0.02)
    return False


class MonitorTest(unittest.TestCase):
    """start() runs the monitor in the background and reacts to its lines."""

    def test_sleep_and_wake_from_the_monitor(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            fake = FakeMpv(folder / "mpv.sock")
            log = []
            watch = sleep_pause.SleepPause(folder / "mpv.sock", log.append, guard_seconds=0.3, check_seconds=0.05)
            try:
                watch.start(str(write_fake_monitor(folder)))
                (folder / "sleep").touch()
                self.assertTrue(wait_until(lambda: fake.state["pause"] is True), "paused for sleep")
                fake.state["time-pos"] = 0.0
                (folder / "wake").touch()
                self.assertTrue(wait_until(lambda: fake.state["time-pos"] == 62.0), "put back on waking")
                self.assertIs(fake.state["pause"], True)
            finally:
                watch.stop()
                fake.close()

    def test_stop_ends_the_monitor(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            watch = sleep_pause.SleepPause(folder / "mpv.sock", [].append).start(str(write_fake_monitor(folder)))
            process = watch._process
            watch.stop()
            self.assertIsNotNone(process.poll())

    def test_tool_missing_is_logged_and_playback_goes_on(self):
        log = []
        with mock.patch("backend.sleep_pause.shutil.which", return_value=None):
            watch = sleep_pause.SleepPause(Path("/nonexistent/mpv.sock"), log.append).start()
        watch.stop()
        self.assertEqual(log, [sleep_pause.TOOL_MISSING])

    def test_tool_that_cannot_start_is_logged(self):
        log = []
        watch = sleep_pause.SleepPause(Path("/nonexistent/mpv.sock"), log.append).start("/nonexistent/gdbus")
        watch.stop()
        self.assertIn("couldn't start", log[0])

    @unittest.skipUnless(shutil.which("gdbus") and os.path.exists("/run/dbus/system_bus_socket"),
                         "needs gdbus and a system bus")
    def test_real_gdbus_may_listen_to_logind(self):
        # No permission is needed to listen: gdbus keeps running instead of
        # stopping with an error.
        process = subprocess.Popen(sleep_pause.monitor_command(shutil.which("gdbus")),
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            first = process.stdout.readline()
            time.sleep(0.5)
            self.assertIsNone(process.poll(), first)
            self.assertIn("org.freedesktop.login1", first)
        finally:
            process.terminate()
            process.wait()
            process.stdout.close()


# Listens on --input-ipc-server like mpv and stays until told to quit.
FAKE_PLAYER = """#!{python}
import json, socket, sys
path = next(a.split("=", 1)[1] for a in sys.argv if a.startswith("--input-ipc-server="))
srv = socket.socket(socket.AF_UNIX)
srv.bind(path)
srv.listen(4)
srv.settimeout(20)
paused = False
while True:
    conn, _ = srv.accept()
    request = json.loads(conn.makefile().readline())
    command = request["command"]
    if command == ["quit"]:
        sys.exit(0)
    if command[0] == "set_property":
        paused = command[2]
    data = paused if command == ["get_property", "pause"] else 10.0
    conn.sendall(json.dumps({{"data": data, "error": "success", "request_id": request.get("request_id")}}).encode() + b"\\n")
    conn.close()
"""


class PlayTest(unittest.TestCase):
    """mpv.play() listens for sleep for exactly as long as mpv runs."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.player = self.folder / "fake-mpv"
        self.player.write_text(FAKE_PLAYER.format(python=sys.executable), encoding="utf-8")
        self.player.chmod(0o755)

    def tearDown(self):
        self.tmp.cleanup()

    def test_film_is_paused_for_sleep_during_play(self):
        control = self.folder / "mpv.sock"
        monitor = write_fake_monitor(self.folder)
        log_path = self.folder / "mpv.log"
        done = {}
        with mock.patch.object(sleep_pause, "MONITOR_TOOL", str(monitor)):
            thread = threading.Thread(target=lambda: done.update(
                result=mpv.play([str(self.player)], self.folder / "film.mkv", log_path,
                                control_socket=control)))
            thread.start()
            try:
                self.assertTrue(wait_until(control.exists), "mpv's control socket")
                (self.folder / "sleep").touch()
                self.assertTrue(wait_until(lambda: sleep_pause.ask(control, ["get_property", "pause"])[1] is True),
                                "paused for sleep")
            finally:
                mpv.ask_to_quit(control)
                thread.join(timeout=10)
        self.assertTrue(done["result"]["ok"], done)
        self.assertIn("pause on sleep: going to sleep; film paused at 10.0 s", log_path.read_text())

    def test_monitor_stops_when_mpv_closes(self):
        started = []
        real = sleep_pause.SleepPause

        def spy(*args, **kwargs):
            watch = real(*args, **kwargs)
            started.append(watch)
            return watch

        control = self.folder / "mpv.sock"
        monitor = write_fake_monitor(self.folder)
        with mock.patch.object(sleep_pause, "MONITOR_TOOL", str(monitor)), \
                mock.patch.object(sleep_pause, "SleepPause", side_effect=spy):
            thread = threading.Thread(target=mpv.play, args=(
                [str(self.player)], self.folder / "film.mkv", self.folder / "mpv.log"),
                kwargs={"control_socket": control})
            thread.start()
            self.assertTrue(wait_until(lambda: started and started[0]._process is not None), "monitor started")
            process = started[0]._process
            self.assertTrue(wait_until(control.exists))
            mpv.ask_to_quit(control)
            thread.join(timeout=10)
        self.assertIsNotNone(process.poll(), "the monitor ends with mpv")

    def test_no_control_socket_means_no_monitor(self):
        with mock.patch.object(sleep_pause, "SleepPause") as watch, \
                mock.patch("backend.mpv.subprocess.Popen") as popen:
            popen.return_value.stdout = iter(())
            popen.return_value.returncode = 0
            mpv.play(["mpv"], self.folder / "film.mkv", self.folder / "mpv.log")
        watch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
