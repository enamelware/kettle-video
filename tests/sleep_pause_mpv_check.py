# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""A film stays paused where it was after sleep, with the real mpv (the
sleep pause fix). Not part of the unit tests: it needs mpv (system or
Flatpak) and ffmpeg, and takes about 15 seconds. No window opens (mpv runs
with --vo=null) and no real media is used: a short test clip is made with
ffmpeg in a temporary folder. No browser screen is driven: it covers
playback only.

A terminal can't put the device to sleep, so the system's sleep messages
come from a stand-in for gdbus, and the jump the launch rehearsal saw on
waking (the film back near the start) is made by seeking. Plays the clip
through backend.mpv.play() exactly as the app does, with its control
socket:

  - about to sleep: mpv is paused, and the mpv log says where
  - on waking after the jump: the film is back at that spot, still paused,
    and "Paused" with the times is on screen
  - on waking with no jump: nothing moves
  - A (Space) then plays on from the spot
  - quitting still saves mpv's resume position, and the log holds no errors

Run from the repo root:  python3 tests/sleep_pause_mpv_check.py
"""

import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from backend import mpv, sleep_pause  # noqa: E402
from backend.settings import load_settings  # noqa: E402
from tests.mpv_quit_check import HEADLESS, Mpv  # noqa: E402
from tests.playback_controls_mpv_check import errors  # noqa: E402
from tests.test_sleep_pause import write_fake_monitor  # noqa: E402

CLIP_SECONDS = 120

failures = []


def check(ok, what):
    print(("ok    " if ok else "FAIL  ") + what)
    if not ok:
        failures.append(what)


def make_clip(work):
    clip = work / "clip.mkv"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y",
         "-f", "lavfi", "-i", f"testsrc=size=160x90:rate=10:duration={CLIP_SECONDS}",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={CLIP_SECONDS}",
         "-c:v", "libx264", "-preset", "ultrafast", "-g", "10", "-c:a", "aac", str(clip)],
        check=True)
    return clip


def wait_for(test, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if test():
            return True
        time.sleep(0.05)
    return False


def run(command, clip, work, name, drive):
    """Play clip as the app does, with a stand-in gdbus in its own folder."""
    folder = work / name
    folder.mkdir()
    monitor = write_fake_monitor(folder)
    control = folder / "mpv.sock"
    log = folder / "mpv.log"
    extra = [f"--watch-later-dir={work / 'watch_later'}", *HEADLESS]
    done = {}
    original = sleep_pause.MONITOR_TOOL
    sleep_pause.MONITOR_TOOL = str(monitor)
    try:
        thread = threading.Thread(target=lambda: done.update(
            result=mpv.play(command, clip, log, extra, True, False, control_socket=control)))
        thread.start()
        m = Mpv(str(control))
        m.wait_for("time-pos", lambda v: v >= 0.5)
        try:
            drive(m, folder)
        finally:
            try:
                m.send_only("quit")
            except OSError:
                pass  # mpv already closed (B)
            thread.join(timeout=60)
    finally:
        sleep_pause.MONITOR_TOOL = original
    if thread.is_alive():
        raise RuntimeError(f"{name}: mpv did not close")
    return done["result"], log.read_text(errors="replace")


def drive_jump(m, folder):
    m.command("seek", 50, "absolute", "exact")
    time.sleep(1)
    (folder / "sleep").touch()
    check(wait_for(lambda: m.get("pause") is True), "about to sleep: mpv is paused")
    spot = m.get("time-pos")
    # What the launch rehearsal saw on waking: the film back near the start.
    m.command("seek", 0, "absolute", "exact")
    time.sleep(0.3)
    (folder / "wake").touch()
    check(wait_for(lambda: abs((m.get("time-pos") or 0) - spot) < 0.5),
          f"on waking: the film is back at its spot ({m.get('time-pos')} s, spot {spot:.1f} s)")
    check(m.get("pause") is True, "on waking: still paused")
    m.command("keypress", "SPACE")
    time.sleep(1.5)
    position = m.get("time-pos") or 0
    check(m.get("pause") is False and spot + 0.5 < position < spot + 3,
          f"A plays on from the spot ({position:.1f} s, spot {spot:.1f} s)")
    drive_jump.spot = spot  # run() then quits, as B does


def drive_still(m, folder):
    m.command("seek", 30, "absolute", "exact")
    time.sleep(0.5)
    (folder / "sleep").touch()
    wait_for(lambda: m.get("pause") is True)
    spot = m.get("time-pos")
    (folder / "wake").touch()
    time.sleep(1)
    check(abs((m.get("time-pos") or 0) - spot) < 0.2 and m.get("pause") is True,
          f"waking with no jump: nothing moves ({m.get('time-pos')} s, spot {spot:.1f} s)")


def main():
    settings = load_settings(REPO)
    status = mpv.detect(settings["mpv_command"])
    if not status["available"] or not shutil.which("ffmpeg"):
        print("skipped: needs mpv and ffmpeg")
        return 0
    command = status["command"]
    version = subprocess.run([*command, "--version"], capture_output=True, text=True).stdout.splitlines()
    print(f"mpv: {version[0] if version else 'unknown'} ({status['via']})")

    with tempfile.TemporaryDirectory(dir=mpv.SHARED_TMP, prefix="kettle-sleep-") as tmp:
        work = Path(tmp)
        clip = make_clip(work)

        result, log = run(command, clip, work, "jump", drive_jump)
        check(result["ok"], "mpv closed normally")
        check("pause on sleep: going to sleep; film paused at" in log, "the mpv log says where it paused")
        check("pause on sleep: the film had moved to" in log, "the mpv log says the film was put back")
        spot = f"{int(drive_jump.spot) // 60:02d}:{int(drive_jump.spot) % 60:02d}"
        check(f"pause on sleep: shown: Paused | 00:{spot} / 00:02:00" in log,
              "on waking: Paused with the times of the spot is on screen")
        check(len(list((work / "watch_later").glob("*"))) >= 1, "quitting still keeps mpv's resume position")
        check(not errors(log), f"no errors in the mpv log ({errors(log)})")
        if errors(log):
            print(log)

        result, log = run(command, clip, work, "still", drive_still)
        check(result["ok"], "mpv closed normally (no jump)")
        check("had moved" not in log, "no jump: the log says nothing was moved")

    print("FAILED: " + "; ".join(failures) if failures else "all sleep pause checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
