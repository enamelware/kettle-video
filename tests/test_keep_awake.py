# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Keep the device awake while a film plays (the keep-awake work): the pure function
that wraps the player command in the system's stay-awake lock, mpv's own
stop-screensaver option, the keep_awake setting, and play() with a fake
lock tool, a missing one, and (when this device has it) the real one.
The power button fix: the lock asks only for "idle", never "sleep", so the power
button can always sleep the device, and it still ends however the film ends.

Run from the repo root:  python3 -m unittest discover -s tests -t . -v
"""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from backend import keep_awake as awake
from backend.mpv import FLATPAK_APP_ID, START_FAILED, build_command, play
from backend.settings import SettingsError, load_settings

SYSTEM = ["/usr/bin/mpv"]
FLATPAK = ["flatpak", "run", FLATPAK_APP_ID]
FILE = Path("/media/Movies/Film.mkv")
TOOL = "/usr/bin/systemd-inhibit"


def assert_idle_only(test, args):
    """The lock asks for "idle" and nothing else: never "sleep", which would
    also refuse a sleep the viewer asks for with the power button (the power button fix)."""
    whats = [a for a in args if a.startswith("--what=")]
    test.assertEqual(whats, ["--what=idle"], args)
    test.assertFalse(any("sleep" in a for a in whats), args)


class WrapCommandTest(unittest.TestCase):
    def check_wrapped(self, command):
        args = build_command(command, FILE)
        wrapped, warning = awake.wrap_command(args, True, TOOL)
        self.assertIsNone(warning)
        self.assertEqual(wrapped[0], TOOL)
        assert_idle_only(self, wrapped)
        self.assertIn("--who=Kettle", wrapped)
        self.assertIn("--why=Playing a video", wrapped)
        self.assertIn("--mode=block", wrapped)
        # The player command follows, whole and unchanged.
        self.assertEqual(wrapped[-len(args):], args)
        self.assertEqual(len(wrapped), 5 + len(args))

    def test_lock_on_wraps_system_mpv(self):
        self.check_wrapped(SYSTEM)

    def test_lock_on_wraps_flatpak_mpv(self):
        self.check_wrapped(FLATPAK)

    def test_setting_off_means_no_wrapping(self):
        for command in (SYSTEM, FLATPAK):
            args = build_command(command, FILE)
            self.assertEqual(awake.wrap_command(args, False, TOOL), (args, None))

    def test_tool_missing_means_no_wrapping_and_a_warning(self):
        for command in (SYSTEM, FLATPAK):
            args = build_command(command, FILE)
            wrapped, warning = awake.wrap_command(args, True, None)
            self.assertEqual(wrapped, args)
            self.assertEqual(warning, awake.TOOL_MISSING_WARNING)
            self.assertIn("systemd-inhibit", warning)

    def test_never_asks_for_sleep(self):
        # The power button fix: the lock may only stop the screen going off by itself.
        self.assertEqual(awake.WHAT, "idle")
        self.assertNotIn("sleep", awake.WHAT.split(":"))
        assert_idle_only(self, awake._lock_options())

    def test_does_not_change_the_list_it_was_given(self):
        args = build_command(SYSTEM, FILE)
        before = list(args)
        awake.wrap_command(args, True, TOOL)
        self.assertEqual(args, before)


class StopScreensaverTest(unittest.TestCase):
    def test_stays_on(self):
        for command in (SYSTEM, FLATPAK):
            for resume in (True, False):
                args = build_command(command, FILE, [], resume)
                self.assertIn("--stop-screensaver=yes", args)
                self.assertNotIn("--no-stop-screensaver", args)
                self.assertNotIn("--stop-screensaver=no", args)
                wrapped, _ = awake.wrap_command(args, True, TOOL)
                self.assertIn("--stop-screensaver=yes", wrapped)


class KeepAwakeSettingTest(unittest.TestCase):
    def load(self, **extra):
        with tempfile.TemporaryDirectory() as tmp:
            data = {"movies_path": "/media/Movies", "tv_path": "/media/TV Shows", **extra}
            (Path(tmp) / "settings.json").write_text(json.dumps(data))
            return load_settings(Path(tmp))

    def test_on_when_left_out(self):
        self.assertIs(self.load()["keep_awake"], True)

    def test_can_be_turned_off(self):
        self.assertIs(self.load(keep_awake=False)["keep_awake"], False)

    def test_must_be_true_or_false(self):
        with self.assertRaises(SettingsError):
            self.load(keep_awake="yes")

    def test_example_settings_have_it_on(self):
        example = Path(__file__).resolve().parent.parent / "settings.example.json"
        self.assertIs(json.loads(example.read_text())["keep_awake"], True)


# A fake mpv: prints one line, then exits with the status given.
FAKE_MPV = textwrap.dedent("""\
    import sys, time
    print("VO: [gpu-next] 640x360 yuv420p", flush=True)
    time.sleep(float(sys.argv[2]) if len(sys.argv) > 2 else 0)
    sys.exit(int(sys.argv[1]))
""")

# A fake lock tool: records its arguments, then runs the command after them.
FAKE_TOOL = textwrap.dedent("""\
    #!{python}
    import json, os, subprocess, sys
    with open({record!r}, "w") as f:
        json.dump(sys.argv[1:], f)
    if sys.argv[1:2] == ["--list"]:
        sys.exit(0)
    start = next(i for i, a in enumerate(sys.argv) if i and not a.startswith("--"))
    sys.exit(subprocess.call(sys.argv[start:]))
""")


class PlayWithLockTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.script = self.dir / "fake_mpv.py"
        self.script.write_text(FAKE_MPV)
        self.log = self.dir / "mpv.log"
        self.record = self.dir / "tool-args.json"
        tool = self.dir / "systemd-inhibit"
        tool.write_text(FAKE_TOOL.format(python=sys.executable, record=str(self.record)))
        tool.chmod(0o755)
        self.tool = tool

    def tearDown(self):
        self.tmp.cleanup()

    def mpv(self, status=0, seconds=0):
        return [sys.executable, "-u", str(self.script), str(status), str(seconds)]

    def run_play(self, command, keep_awake=True, lock_tool="fake"):
        tool = str(self.tool) if lock_tool == "fake" else lock_tool
        with mock.patch.object(awake, "find_lock_tool", return_value=tool), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            result = play(command, FILE, self.log, [], True, keep_awake)
        log = self.log.read_text() if self.log.exists() else ""
        return result, log, err.getvalue()

    def test_mpv_runs_under_the_lock(self):
        result, log, _ = self.run_play(self.mpv())
        self.assertTrue(result["ok"])
        recorded = json.loads(self.record.read_text())
        assert_idle_only(self, recorded)
        self.assertIn("--who=Kettle", recorded)
        self.assertEqual(recorded[recorded.index(sys.executable):][:3], self.mpv()[:3])
        self.assertIn("VO: [gpu-next]", log)
        self.assertIn("keep_awake = on", log.splitlines()[1])

    def test_failure_status_passes_through_the_lock(self):
        result, _, _ = self.run_play(self.mpv(status=2))
        self.assertFalse(result["ok"])
        self.assertIn("status 2", result["error"])
        assert_idle_only(self, json.loads(self.record.read_text()))

    def test_setting_off_runs_mpv_directly(self):
        result, log, _ = self.run_play(self.mpv(), keep_awake=False)
        self.assertTrue(result["ok"])
        self.assertFalse(self.record.exists())
        self.assertIn("keep_awake = off", log)

    def test_tool_missing_plays_normally_with_a_warning(self):
        result, log, err = self.run_play(self.mpv(), lock_tool=None)
        self.assertTrue(result["ok"])
        self.assertFalse(self.record.exists())
        self.assertIn(awake.TOOL_MISSING_WARNING, log)
        self.assertIn(awake.TOOL_MISSING_WARNING, err)
        self.assertIn("VO: [gpu-next]", log)

    def test_missing_mpv_still_reported_under_the_lock(self):
        result, _, _ = self.run_play(["/nonexistent/mpv"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], START_FAILED)

    def test_find_lock_tool_none_when_not_installed(self):
        with mock.patch.object(awake.shutil, "which", return_value=None):
            self.assertIsNone(awake.find_lock_tool())

    def test_find_lock_tool_none_when_it_does_not_work(self):
        broken = self.dir / "broken"
        broken.write_text("#!/bin/sh\nexit 1\n")
        broken.chmod(0o755)
        with mock.patch.object(awake.shutil, "which", return_value=str(broken)):
            self.assertIsNone(awake.find_lock_tool())

    def refusing_tool(self):
        """Lists locks fine, but is refused any new lock, like a session or
        permission rule that forbids it."""
        folder = self.dir / "refusing"
        folder.mkdir()
        tool = folder / "systemd-inhibit"
        tool.write_text('#!/bin/sh\n[ "$1" = "--list" ] && exit 0\n'
                        'echo "Failed to inhibit: Access denied" >&2\nexit 1\n')
        tool.chmod(0o755)
        return folder

    def test_find_lock_tool_tries_a_real_lock_first(self):
        with mock.patch.object(awake.shutil, "which", return_value=str(self.tool)):
            self.assertEqual(awake.find_lock_tool(), str(self.tool))
        recorded = json.loads(self.record.read_text())
        assert_idle_only(self, recorded)
        self.assertIn("--who=Kettle", recorded)
        self.assertEqual(recorded[-1], "true")

    def test_find_lock_tool_none_when_the_lock_is_refused(self):
        tool = self.refusing_tool() / "systemd-inhibit"
        with mock.patch.object(awake.shutil, "which", return_value=str(tool)):
            self.assertIsNone(awake.find_lock_tool())

    def test_refused_lock_plays_normally_with_a_warning(self):
        folder = self.refusing_tool()
        path = f"{folder}{os.pathsep}{os.environ.get('PATH', '')}"
        with mock.patch.dict(os.environ, {"PATH": path}), \
                contextlib.redirect_stderr(io.StringIO()):
            result = play(self.mpv(), FILE, self.log, [], True, True)
        log = self.log.read_text()
        self.assertTrue(result["ok"])
        self.assertIn("VO: [gpu-next]", log)
        self.assertIn(awake.TOOL_MISSING_WARNING, log)

    def test_step0_lists_the_locks_in_the_log(self):
        lines = ["kettle-video: locks: WHO  WHY", "kettle-video: locks: Kettle  Playing a video"]
        with mock.patch.object(awake, "DIAGNOSTICS_FIRST_DELAY", 0), \
                mock.patch.object(awake, "DIAGNOSTICS_INTERVAL", 0.2), \
                mock.patch.object(awake, "list_locks", return_value=lines):
            result, log, _ = self.run_play(self.mpv(seconds=0.7))
        self.assertTrue(result["ok"])
        self.assertIn("kettle-video: locks: Kettle  Playing a video", log)
        # At the start, then again at each interval.
        self.assertGreaterEqual(log.count("Kettle  Playing a video"), 2)


@unittest.skipUnless(awake.find_lock_tool(), "this device has no working systemd-inhibit")
class RealLockTest(unittest.TestCase):
    """On this device: the lock is in the system's list while the player
    runs and gone once it ends, also after a crash."""

    def kettle_locks(self):
        out = subprocess.run(["systemd-inhibit", "--list", "--no-pager"],
                             capture_output=True, text=True).stdout
        return [line for line in out.splitlines() if "Kettle" in line]

    @staticmethod
    def can_suspend():
        """The system's read-only answer to "may this device sleep now?"
        ("yes", "challenge", "inhibited", ...), or None if it can't be asked.
        Asking never makes the device sleep."""
        try:
            out = subprocess.run(
                ["busctl", "call", "org.freedesktop.login1", "/org/freedesktop/login1",
                 "org.freedesktop.login1.Manager", "CanSuspend"],
                capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            return None
        parts = out.stdout.split()
        return parts[1].strip('"') if out.returncode == 0 and len(parts) == 2 else None

    def check(self, status):
        before = self.can_suspend()
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "fake_mpv.py"
            script.write_text(FAKE_MPV)
            seen = []
            during = []

            def watch():
                time.sleep(0.5)
                seen.extend(self.kettle_locks())
                during.append(self.can_suspend())

            watcher = threading.Thread(target=watch)
            watcher.start()
            log_path = Path(tmp) / "x.log"
            # Step 0 lists the real locks half a second in, while mpv runs.
            with contextlib.redirect_stderr(io.StringIO()), \
                    mock.patch.object(awake, "DIAGNOSTICS_FIRST_DELAY", 0.5):
                result = play([sys.executable, "-u", str(script), str(status), "1.5"],
                              FILE, log_path, [], True, True)
            watcher.join()
            log = log_path.read_text()
        self.assertTrue(any("Playing a video" in line for line in seen), seen)
        # The power button fix: the held lock is "idle" only, so a sleep the viewer asks
        # for still goes through: wherever the system said "yes" before the
        # film, it still says "yes" with Kettle's lock held.
        for line in seen:
            self.assertIn("idle", line)
            self.assertNotIn("sleep", line)
        if before == "yes":
            self.assertEqual(during, ["yes"])
        self.assertEqual(self.kettle_locks(), [])
        # The Step 0 lines are in the film's log, and show Kettle's lock.
        step0 = [line for line in log.splitlines() if line.startswith("kettle-video: locks:")]
        self.assertTrue(any("Kettle" in line and "Playing a video" in line for line in step0), log)
        return result

    def test_lock_held_while_playing_and_gone_after(self):
        self.assertTrue(self.check(0)["ok"])

    def test_lock_gone_after_a_crash(self):
        self.assertFalse(self.check(3)["ok"])

    def test_lock_gone_when_the_app_is_closed(self):
        # Steam closing the app stops the lock tool itself. The player may
        # keep running for a moment (the Flatpak doesn't pass the stop on),
        # but the lock must already be gone, so the device can sleep.
        import backend.mpv as mpv_module
        real_popen = subprocess.Popen
        started = []

        def recording_popen(*args, **kwargs):
            proc = real_popen(*args, **kwargs)
            command = args[0] if args else kwargs.get("args")
            # Only the film's lock tool, not the quick test lock or the
            # Step 0 listing (they share the same subprocess module).
            if command[-1] != "true" and "--list" not in command:
                started.append(proc)
            return proc

        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "fake_mpv.py"
            script.write_text(FAKE_MPV)
            seen_before, seen_after = [], []

            def close_app():
                time.sleep(0.5)
                seen_before.extend(self.kettle_locks())
                started[0].terminate()
                started[0].wait()
                time.sleep(0.3)
                seen_after.extend(self.kettle_locks())

            closer = threading.Thread(target=close_app)
            with contextlib.redirect_stderr(io.StringIO()), \
                    mock.patch.object(mpv_module.subprocess, "Popen", recording_popen):
                closer.start()
                play([sys.executable, "-u", str(script), "0", "2"],
                     FILE, Path(tmp) / "x.log", [], True, True)
            closer.join()
        self.assertTrue(any("Playing a video" in line for line in seen_before), seen_before)
        self.assertEqual(seen_after, [])
        self.assertEqual(self.kettle_locks(), [])


if __name__ == "__main__":
    unittest.main()
