# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Tests for how mpv is started (backend.mpv.build_command), the log that
play() writes from mpv's messages, and the 'resume' setting. Nothing real
is played: the log tests use a small fake mpv.

Run from the repo root:  python3 -m unittest discover -s tests -t . -v
"""

import contextlib
import io
import json
import os
import sys
import tempfile
import textwrap
import unittest
from unittest import mock
from pathlib import Path

from backend.mpv import (
    FLATPAK_APP_ID, LOG_OPTIONS, RESUME_REWIND_SCRIPT, START_FAILED, build_command, play,
)
from backend.settings import SettingsError, load_settings

SYSTEM = ["/usr/bin/mpv"]
FLATPAK = ["flatpak", "run", FLATPAK_APP_ID]
FILE = Path("/media/Example Show/Example Show - 01.mkv")


def build(command=SYSTEM, extra_args=(), resume=True):
    return build_command(command, FILE, list(extra_args), resume)


class BuildCommandTest(unittest.TestCase):
    def test_resume_on(self):
        args = build(resume=True)
        self.assertIn("--save-position-on-quit", args)
        self.assertNotIn("--no-resume-playback", args)
        self.assertEqual(args[0], "/usr/bin/mpv")
        self.assertEqual(args[-1], str(FILE))

    def test_resume_off(self):
        args = build(resume=False)
        self.assertIn("--no-resume-playback", args)
        self.assertNotIn("--save-position-on-quit", args)
        self.assertIn("--no-save-position-on-quit", args)

    def test_flatpak_prefix_unchanged(self):
        args = build(command=FLATPAK)
        self.assertEqual(args[:3], FLATPAK)
        self.assertIn("--save-position-on-quit", args)
        self.assertEqual(args[-1], str(FILE))

    def test_logging_options_unchanged(self):
        for resume in (True, False):
            args = build(resume=resume)
            self.assertIn("--fullscreen", args)
            for option in LOG_OPTIONS:
                self.assertIn(option, args)
            # mpv never writes the log itself: the Flatpak can't write there.
            self.assertFalse(any(a.startswith("--log-file") for a in args))

    def test_user_mpv_args_preserved_in_order(self):
        user = ["--hwdec=auto", "--script-opts=osc-scalefullscreen=1.5,osc-hidetimeout=4000"]
        args = build(extra_args=user)
        start = args.index(user[0])
        self.assertEqual(args[start:start + 2], user)
        self.assertEqual(args[-1], str(FILE))

    def test_no_duplicated_options(self):
        # The user's own value wins, and ours is not added a second time.
        args = build(extra_args=["--save-position-on-quit=no", "--fullscreen"], resume=True)
        self.assertEqual(sum(a.startswith("--save-position-on-quit") for a in args), 1)
        self.assertIn("--save-position-on-quit=no", args)
        self.assertEqual(args.count("--fullscreen"), 1)

        args = build(extra_args=["--resume-playback"], resume=False)
        self.assertNotIn("--no-resume-playback", args)
        self.assertIn("--resume-playback", args)

        args = build(extra_args=["--no-save-position-on-quit"], resume=True)
        self.assertNotIn("--save-position-on-quit", args)

    def test_no_option_appears_twice(self):
        for resume in (True, False):
            for user in ([], ["--hwdec=auto"], ["--fullscreen", "--no-resume-playback"]):
                args = build(extra_args=user, resume=resume)
                # --script may be given once per script.
                options = [a.split("=", 1)[0] for a in args
                           if a.startswith("--") and not a.startswith("--script=")]
                self.assertEqual(len(options), len(set(options)), (resume, user, args))

    def test_rewind_script_only_when_resume_on(self):
        script = f"--script={RESUME_REWIND_SCRIPT}"
        self.assertIn(script, build(resume=True))
        self.assertIn(script, build(command=FLATPAK, resume=True))
        self.assertNotIn(script, build(resume=False))

    def test_rewind_script_ships_with_the_app(self):
        self.assertTrue(RESUME_REWIND_SCRIPT.is_file())
        self.assertTrue(RESUME_REWIND_SCRIPT.is_absolute())

    def test_user_scripts_kept_alongside_ours(self):
        args = build(extra_args=["--script=/home/me/my.lua"], resume=True)
        self.assertIn("--script=/home/me/my.lua", args)
        self.assertIn(f"--script={RESUME_REWIND_SCRIPT}", args)


# Prints what mpv prints to its output, as seen on the Nova, then exits
# with the status given as its first argument.
FAKE_MPV = textwrap.dedent("""
    import sys
    print("   cplayer: \u25cf Video  --vid=1  (h264 640x360 24 fps)")
    print("        vd: Opening decoder h264")
    print("        vd: Using software decoding.")
    print("ffmpeg/video: h264: no frame!", file=sys.stderr)
    for i in range(500):
        print(f"AV: 00:00:{i % 60:02d} / 00:00:03 (0%) A-V:  0.000", end="\\r")
    print()
    print("   cplayer: VO: [gpu-next] 640x360 yuv420p")
    if sys.argv[1] != "0":
        print("[file] Cannot open file 'missing.mkv': No such file or directory")
        print("   cplayer: Failed to open missing.mkv.")
    print("   cplayer: Exiting... (End of file)")
    sys.exit(int(sys.argv[1]))
""")


class PlayLogTest(unittest.TestCase):
    """play() writes mpv's messages into the log itself."""

    def run_fake(self, status):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "fake_mpv.py"
            script.write_text(FAKE_MPV)
            log_path = Path(tmp) / "mpv-test.log"
            # -u: print at once, like mpv. The fake reads only argv[1].
            result = play([sys.executable, "-u", str(script), str(status)], FILE, log_path, ["--hwdec=auto"])
            return result, log_path.read_text()

    def test_log_holds_mpv_messages(self):
        result, log = self.run_fake(0)
        self.assertTrue(result["ok"])
        self.assertIn("vd: Opening decoder h264", log)
        self.assertIn("vd: Using software decoding.", log)
        self.assertIn("VO: [gpu-next] 640x360 yuv420p", log)
        # Error output is kept too, in order.
        self.assertLess(log.index("Opening decoder"), log.index("h264: no frame!"))

    def test_first_line_names_the_mpv_args(self):
        _, log = self.run_fake(0)
        self.assertEqual(log.splitlines()[0], "kettle-video: mpv_args = ['--hwdec=auto']")

    def test_no_progress_line_spam(self):
        _, log = self.run_fake(0)
        self.assertNotIn("AV:", log)
        self.assertLess(len(log), 1000)

    def test_failed_playback_hint_quotes_the_log(self):
        result, _ = self.run_fake(2)
        self.assertFalse(result["ok"])
        self.assertIn("status 2", result["error"])
        self.assertTrue(result["hint"])
        self.assertIn("Cannot open file 'missing.mkv'", result["log_tail"])

    def test_flatpak_failure_gets_the_same_hint(self):
        # The docs catch-up: the mpv Flatpak can already read the SD card, so a
        # failed Flatpak playback no longer talks about permissions.
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "flatpak"
            fake.write_text("#!/bin/sh\necho \"Cannot open file 'missing.mkv'\"\nexit 2\n")
            fake.chmod(0o755)
            with mock.patch.dict(os.environ, {"PATH": f"{tmp}{os.pathsep}{os.environ.get('PATH', '')}"}):
                result = play(["flatpak", "run", "io.mpv.Mpv"], FILE, Path(tmp) / "x.log")
        system_result, _ = self.run_fake(2)
        self.assertFalse(result["ok"])
        self.assertEqual(result["hint"], "Check that the file isn't corrupted or in an unsupported format.")
        self.assertEqual(result["hint"], system_result["hint"])
        self.assertNotIn("permission", result["hint"])

    def test_missing_mpv_still_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            with contextlib.redirect_stderr(io.StringIO()):
                result = play(["/nonexistent/mpv"], FILE, Path(tmp) / "x.log")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], START_FAILED)


class ResumeSettingTest(unittest.TestCase):
    def load(self, **extra):
        with tempfile.TemporaryDirectory() as tmp:
            data = {"movies_path": "/media/Movies", "tv_path": "/media/TV Shows", **extra}
            (Path(tmp) / "settings.json").write_text(json.dumps(data))
            return load_settings(Path(tmp))

    def test_on_by_default(self):
        self.assertIs(self.load()["resume"], True)

    def test_can_be_turned_off(self):
        self.assertIs(self.load(resume=False)["resume"], False)

    def test_must_be_true_or_false(self):
        with self.assertRaises(SettingsError):
            self.load(resume="yes")


if __name__ == "__main__":
    unittest.main()
