# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The playback controls with the real mpv (the playback controls work). Not part of the unit
tests: it needs mpv (system or Flatpak) and ffmpeg, and takes about half a
minute. No window opens (mpv runs with --vo=null) and no real media is used:
two short test clips are made with ffmpeg in a temporary folder.

Plays each clip through backend.mpv.play() exactly as the app does, and
presses keys through mpv's control socket the way Steam Input sends them:

  - A (Space) and a tap pause and play, and "Paused" is shown
  - D-pad Left / Right move 10 s, L1 / R1 one minute, many quick presses
    keep up
  - X (Backspace) steps through the subtitles and ends on Off; Y (a)
    through the audio tracks, with their names, "Track 2" for a track
    with neither language nor title
  - a clip with one audio track and no subtitles: "Only one audio track"
    and "No subtitles in this file"
  - D-pad Down, Enter and a few of mpv's own default keys (f, m, 9, s, i,
    a double tap) change nothing, and mpv's bar is off
  - B (q) still saves the Continue watching record and frame, and mpv's
    resume position
  - the log holds no errors from mpv, and the mpv version is printed

Run from the repo root:  python3 tests/playback_controls_mpv_check.py
"""

import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from backend import mpv  # noqa: E402
from backend.settings import load_settings  # noqa: E402
from tests.mpv_quit_check import HEADLESS, Mpv  # noqa: E402

CLIP_SECONDS = 150
# What Kettle hands mpv for a film in the saved library (the playback controls work, choice A).
KETTLE_TITLE = "Example Film (2019) · Part 2"

failures = []


def check(ok, what):
    print(("ok    " if ok else "FAIL  ") + what)
    if not ok:
        failures.append(what)


def make_clips(work):
    """many.mkv: English and Japanese audio, an English subtitle track, one
    with no language and no title, and one with only a title. one.mkv: one
    audio track, no subtitles."""
    srt = work / "sub.srt"
    srt.write_text("1\n00:00:00,000 --> 00:02:30,000\nHello\n", encoding="utf-8")
    video = ["-f", "lavfi", "-i", f"testsrc=size=160x90:rate=10:duration={CLIP_SECONDS}"]
    tone = ["-f", "lavfi", "-i", f"sine=frequency=440:duration={CLIP_SECONDS}"]
    encode = ["-c:v", "libx264", "-preset", "ultrafast", "-g", "10", "-c:a", "aac"]
    many, one = work / "many.mkv", work / "one.mkv"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", *video, *tone, *tone,
         "-i", str(srt), "-i", str(srt), "-i", str(srt),
         "-map", "0:v", "-map", "1:a", "-map", "2:a", "-map", "3:s", "-map", "4:s", "-map", "5:s",
         *encode, "-c:s", "srt",
         "-metadata:s:a:0", "language=eng", "-metadata:s:a:1", "language=jpn",
         "-metadata:s:s:0", "language=eng", "-metadata:s:s:1", "language=und",
         "-metadata:s:s:2", "language=und", "-metadata:s:s:2", "title=Commentary",
         str(many)], check=True)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", *video, *tone, "-map", "0:v", "-map", "1:a", *encode, str(one)],
        check=True)
    return many, one


def shown(log):
    return [line.split("shown: ", 1)[1] for line in log.splitlines() if "shown: " in line]


# The decoder's note that it can't draw straight into the window: expected
# with no window (--vo=null), and printed only because the log keeps the
# decoder's details.
EXPECTED = ("vd: DR failed - disabling.",)


def errors(log):
    """mpv's error and warning lines, other than the expected ones."""
    bad = []
    for line in log.splitlines():
        low = line.lower()
        if line.strip() in EXPECTED:
            continue
        if ("error" in low or "invalid" in low or "unknown" in low or "failed" in low
                or "not found" in low or "no such" in low):
            bad.append(line)
    return bad


def run(command, clip, work, name, drive, capture=None, title=None):
    ipc = str(work / f"{name}.sock")
    log = work / f"{name}.log"
    extra = [f"--watch-later-dir={work / 'watch_later'}", f"--input-ipc-server={ipc}", *HEADLESS]
    done = {}

    def play():
        done["result"] = mpv.play(command, clip, log, extra, True, False, capture, title=title)

    thread = threading.Thread(target=play)
    thread.start()
    m = Mpv(ipc)
    m.wait_for("time-pos", lambda v: v >= 0.5)
    try:
        drive(m)
    finally:
        try:
            m.send_only("quit")
        except OSError:
            pass  # mpv already closed (B)
        thread.join(timeout=60)
    if thread.is_alive():
        raise RuntimeError(f"{name}: mpv did not close")
    return done["result"], log.read_text(errors="replace")


def press(m, key, wait=0.3):
    m.command("keypress", key)
    time.sleep(wait)


def drive_many(m):
    check(m.get("osc") is False, "mpv's own bar (osc) is off")
    check(m.get("input-default-bindings") is False, "mpv's default keys are off")

    press(m, "SPACE")
    check(m.get("pause") is True, "A (Space) pauses")
    press(m, "SPACE")
    check(m.get("pause") is False, "A (Space) plays again")
    press(m, "MBTN_LEFT")
    check(m.get("pause") is True, "one tap pauses")
    press(m, "MBTN_LEFT")
    check(m.get("pause") is False, "one tap plays again")
    m.command("set_property", "pause", True)

    m.command("seek", 30, "absolute", "exact")
    time.sleep(0.3)
    start = m.get("time-pos")
    press(m, "RIGHT")
    check(abs(m.get("time-pos") - (start + 10)) < 2, "D-pad Right: 10 s forward")
    press(m, "LEFT")
    check(abs(m.get("time-pos") - start) < 2, "D-pad Left: 10 s back")
    press(m, "l")
    check(abs(m.get("time-pos") - (start + 60)) < 2, "R1 (l): 1 minute forward")
    press(m, "j")
    check(abs(m.get("time-pos") - start) < 2, "L1 (j): 1 minute back")
    for _ in range(8):
        press(m, "RIGHT", wait=0.03)
    time.sleep(0.6)
    check(abs(m.get("time-pos") - (start + 80)) < 3, "8 quick presses of Right: 80 s forward, nothing stuck")
    # Seeking shows the bar with elapsed and total time for about 2 s.
    status, shown_for = m.get("osd-status-msg"), m.get("osd-duration")
    check(status == "${time-pos} / ${duration}" and shown_for == 2000,
          f"seeking: the bar with elapsed and total time, 2 s ({status!r}, {shown_for} ms)")

    before = {p: m.get(p) for p in ("time-pos", "fullscreen", "mute", "volume", "sid", "aid", "speed")}
    for key in ("DOWN", "ENTER", "f", "m", "9", "0", "s", "i", "o", "MBTN_LEFT_DBL", "WHEEL_UP", "PGUP"):
        press(m, key, wait=0.15)
    time.sleep(0.4)
    after = {p: m.get(p) for p in before}
    check(before == after, f"Down, Enter and mpv's own keys change nothing ({after})")

    press(m, "UP")
    # D-pad Up: the title above elapsed and total time, for about 3 s.
    status, shown_for = m.get("osd-status-msg"), m.get("osd-duration")
    check(status == "${media-title}\n${time-pos} / ${duration}" and shown_for == 3000,
          f"D-pad Up: the title, elapsed and total time, 3 s ({status!r}, {shown_for} ms)")
    # The title is Kettle's, not the file name (the designer's choice A on the playback controls work).
    check(m.get("media-title") == KETTLE_TITLE,
          f"D-pad Up shows Kettle's title, not the file name ({m.get('media-title')!r})")
    press(m, "RIGHT")
    check(m.get("osd-status-msg") == "${time-pos} / ${duration}",
          "after D-pad Up, a seek shows the times only again")
    for key in ("BS", "BS", "BS", "BS"):
        press(m, key)
    press(m, "a")
    press(m, "a")


def drive_one(m):
    press(m, "BS")
    press(m, "a")
    check(m.get("aid") == 1, "Y with one audio track keeps it")


def drive_stop(m):
    m.command("seek", 40, "absolute", "exact")
    time.sleep(0.3)
    m.command("set_property", "pause", True)
    time.sleep(0.2)
    press(m, "q", wait=0.1)


def drive_stop_esc(m):
    m.command("seek", 20, "absolute", "exact")
    time.sleep(0.3)
    press(m, "ESC", wait=0.1)


def closes_on(key):
    """Press key; True if mpv closes within 3 seconds."""
    def drive(m):
        press(m, key, wait=0)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                if m.command("get_property", "pid").get("error") == "closed":
                    drive.closed = True
                    return
            except OSError:
                drive.closed = True
                return
            time.sleep(0.05)
    drive.closed = False
    return drive


def main():
    settings = load_settings(REPO)
    status = mpv.detect(settings["mpv_command"])
    if not status["available"] or not shutil.which("ffmpeg"):
        print("skipped: needs mpv and ffmpeg")
        return 0
    command = status["command"]
    version = subprocess.run([*command, "--version"], capture_output=True, text=True).stdout.splitlines()
    print(f"mpv: {version[0] if version else 'unknown'} ({status['via']})")

    with tempfile.TemporaryDirectory(dir=mpv.SHARED_TMP, prefix="kettle-controls-") as tmp:
        work = Path(tmp)
        many, one = make_clips(work)

        result, log = run(command, many, work, "many", drive_many, title=KETTLE_TITLE)
        check(result["ok"], "mpv closed normally (many tracks)")
        words = shown(log)
        print("  shown:", words)
        check(bool(words) and words[0].startswith("Paused | ") and words[0].endswith(" / 00:02:30"),
              "pausing shows Paused with elapsed and total time")
        subs = [w for w in words if w.startswith("Subtitles: ")]
        # mpv picks the English subtitles at the start, so X goes on from there.
        # Track 2 has neither language nor title; track 3 only a title.
        check(subs == ["Subtitles: Track 2", "Subtitles: Commentary", "Subtitles: Off", "Subtitles: English"],
              f"X steps Track 2, Commentary, Off, English ({subs})")
        audio = [w for w in words if w.startswith("Audio: ")]
        check(audio == ["Audio: Japanese", "Audio: English"], f"Y steps Japanese, English ({audio})")
        bad = errors(log)
        check(not bad, f"no errors in the mpv log ({bad})")

        result, log = run(command, one, work, "one", drive_one)
        words = shown(log)
        check(words == ["No subtitles in this file", "Only one audio track"],
              f"one track, no subtitles: the two messages ({words})")
        check(not errors(log), f"no errors in the mpv log ({errors(log)})")

        capture = work / "capture"
        capture.mkdir()
        result, log = run(command, many, work, "stop", drive_stop, capture)
        record_file = capture / "record.json"
        record = json.loads(record_file.read_text()) if record_file.is_file() else {}
        check(abs((record.get("position") or 0) - 40) < 1.5 and record.get("frame_saved") is True,
              f"B (q) saves the Continue watching record and frame ({record})")
        saved = list((work / "watch_later").glob("*"))
        check(len(saved) >= 1, "B (q) keeps mpv's resume position")
        check(not errors(log), f"no errors in the mpv log ({errors(log)})")

        def resumed(m):
            resumed.at = m.get("time-pos")
        run(command, many, work, "resume", resumed)
        check(abs(resumed.at - 35) < 1.5, f"played again, it starts 5 s before the stop ({resumed.at:.1f} s)")

        for key in ("q", "ESC"):
            drive = closes_on(key)
            run(command, one, work, f"plain-{key}", drive)
            check(drive.closed, f"without the Continue watching script, {key} still stops")

        capture = work / "capture-esc"
        capture.mkdir()
        run(command, many, work, "stop-esc", drive_stop_esc, capture)
        check((capture / "record.json").is_file() and (capture / "frame.jpg").is_file(),
              "keyboard Esc saves the Continue watching record and frame, like B")

    print("FAILED: " + "; ".join(failures) if failures else "all playback control checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
