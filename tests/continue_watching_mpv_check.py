# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The Continue watching quit script with the real mpv (the Continue watching work). Not part
of the unit tests: it needs mpv (system or Flatpak) and ffmpeg, and takes
about half a minute. No window opens (mpv runs with --vo=null).

Plays a 30-second test clip made with ffmpeg in a temporary folder, through
backend.mpv.play() exactly as the app does, and presses B (q) through mpv's
control socket. Checks the record and the frame the script saves, the small
picture, that the mpv log names no picture, and that playing to the end
says "finished". Also closes mpv as the app does when it closes mid-film,
and with a stop signal like Steam's "Exit game" (the server shutdown check): both keep the
position, the frame and mpv's resume position. Prints the timings: B to mpv
closed (with and without the script), the app saving the stop, and making
the small picture.

Run from the repo root:  python3 tests/continue_watching_mpv_check.py
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from backend import continue_watching as cw  # noqa: E402
from backend import mpv  # noqa: E402
from tests.mpv_quit_check import HEADLESS, Mpv  # noqa: E402

CLIP_SECONDS = 30.0


def picture_width(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width", "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    return int(out.stdout.strip() or 0)


def play(command, clip, work, name, drive, capture):
    """mpv.play() in a thread while `drive(mpv)` acts like the viewer.
    Returns (seconds from B to mpv closed, the log text)."""
    ipc = str(work / f"{name}.sock")
    log = work / f"{name}.log"
    extra = [f"--watch-later-dir={work / 'watch_later'}", f"--input-ipc-server={ipc}", *HEADLESS]
    done = {}

    def run():
        done["result"] = mpv.play(command, clip, log, extra, True, False, capture)
        done["closed"] = time.monotonic()

    thread = threading.Thread(target=run)
    thread.start()
    pressed = drive(Mpv(ipc))
    thread.join(timeout=120)
    if thread.is_alive():
        raise RuntimeError(f"{name}: mpv did not close")
    return done["closed"] - pressed, log.read_text(errors="replace")


def press_b_at(seconds):
    def drive(m):
        m.wait_for("time-pos", lambda v: v >= seconds)
        pressed = time.monotonic()
        m.send_only("keypress", "q")
        return pressed
    return drive


def app_asks_to_quit_at(seconds, ipc):
    """The app closing while the film plays (the server shutdown check): it asks mpv to quit."""
    def drive(m):
        m.wait_for("time-pos", lambda v: v >= seconds)
        pressed = time.monotonic()
        mpv.ask_to_quit(Path(ipc))
        return pressed
    return drive


def mpv_process(ipc):
    """Host pid of the mpv itself (inside the sandbox for the Flatpak),
    found by its control socket in its arguments."""
    for proc in Path("/proc").iterdir():
        try:
            name = (proc / "comm").read_text().strip()
            args = (proc / "cmdline").read_bytes()
        except OSError:
            continue
        if name in ("mpv", "mpv-bin") and ipc.encode() in args:
            return int(proc.name)
    return None


def stop_signal_at(seconds, ipc):
    """A stop signal straight to mpv, as Steam's "Exit game" sends (the server shutdown check)."""
    def drive(m):
        m.wait_for("time-pos", lambda v: v >= seconds)
        pressed = time.monotonic()
        os.kill(mpv_process(ipc), signal.SIGTERM)
        return pressed
    return drive


def play_to_end(m):
    m.wait_for("duration", lambda v: v > 0)
    m.command("seek", CLIP_SECONDS - 1.5, "absolute")
    return time.monotonic()


def main():
    status = mpv.detect("auto")
    if not status["available"] or not shutil.which("ffmpeg"):
        print("skipped: mpv or ffmpeg not found")
        return 0
    command = status["command"]
    results = []

    def check(text, ok):
        results.append((text, ok))

    work = Path(tempfile.mkdtemp(prefix="kettle-cw-check-", dir=mpv.SHARED_TMP))
    try:
        clip = work / "clip.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
                        "-i", f"testsrc2=size=1280x720:rate=25:duration={CLIP_SECONDS:g}",
                        "-c:v", "mpeg4", "-q:v", "3", str(clip)], check=True)

        # Without the script, for comparison.
        baseline, _ = play(command, clip, work, "baseline", press_b_at(3), None)

        # B with the script.
        capture = Path(tempfile.mkdtemp(prefix="kettle-quit-", dir=mpv.SHARED_TMP))
        closed, log = play(command, clip, work, "quit", press_b_at(3), capture)
        record = json.loads((capture / "record.json").read_text())
        check(f"B: record position {record.get('position'):.2f} s, length {record.get('duration')} s, not finished",
              3 <= record["position"] < 6 and abs(record["duration"] - CLIP_SECONDS) < 0.5
              and record["finished"] is False)
        check("B: the frame is saved", record["frame_saved"] is True and (capture / "frame.jpg").is_file())
        check("B: the mpv log names no picture and says the script saved",
              "frame.jpg" not in log and "kettle-quit" not in log and "Screenshot" not in log
              and "kettle_quit: saved at" in log)

        # The app's side: keep the stop, then make the small picture.
        store = cw.ContinueWatching(work / "data", [], lambda line: None)
        target = {"key": "0123456789abcdef", "kind": "movie", "source": "movies"}
        started = time.monotonic()
        # The clip is short: count it as stopped 10 minutes in, so it shows.
        stamp = store.record_stop(target, "clip.mp4", {**record, "position": 600, "duration": 7200},
                                  capture / "frame.jpg", time.time())
        saved = time.monotonic() - started
        check("the app keeps the stop with the full frame as the picture",
              stamp is not None and store.picture_file(target["key"]) is not None)
        started = time.monotonic()
        small = mpv.shrink_frame(command, capture / "frame.jpg", capture)
        shrink = time.monotonic() - started
        width = picture_width(small) if small else 0
        check(f"the small picture is {width} px wide", width == mpv.PICTURE_WIDTH)
        check("the small picture replaces the frame", store.replace_picture(target["key"], stamp, small))
        shutil.rmtree(capture, ignore_errors=True)

        # Closing the app while the film plays (the server shutdown check): the app asking
        # mpv to quit, and a stop signal straight to mpv ("Exit game").
        for name, drive in (("app asks mpv to quit", app_asks_to_quit_at(3, str(work / "asked.sock"))),
                            ("stop signal to mpv", stop_signal_at(3, str(work / "signal.sock")))):
            shutil.rmtree(work / "watch_later", ignore_errors=True)  # only this case's save counts
            capture = Path(tempfile.mkdtemp(prefix="kettle-quit-", dir=mpv.SHARED_TMP))
            sock = "asked" if name.startswith("app") else "signal"
            took, log = play(command, clip, work, sock, drive, capture)
            record = json.loads((capture / "record.json").read_text())
            check(f"{name}: position {record.get('position'):.2f} s and the frame saved, "
                  f"mpv closed in {took:.2f} s",
                  3 <= record["position"] < 6 and record["finished"] is False
                  and record["frame_saved"] is True and (capture / "frame.jpg").is_file())
            check(f"{name}: mpv saved its resume position",
                  any((work / "watch_later").iterdir()))
            check(f"{name}: the mpv log names no picture", "frame.jpg" not in log and "Screenshot" not in log)
            shutil.rmtree(capture, ignore_errors=True)

        # Played to the end.
        capture = Path(tempfile.mkdtemp(prefix="kettle-quit-", dir=mpv.SHARED_TMP))
        play(command, clip, work, "to-end", play_to_end, capture)
        record = json.loads((capture / "record.json").read_text())
        check("played to the end: finished, no frame",
              record["finished"] is True and record["frame_saved"] is False
              and not (capture / "frame.jpg").exists())
        shutil.rmtree(capture, ignore_errors=True)

        print(f"timings ({' '.join(command)}): B to mpv closed {baseline:.2f} s without the script, "
              f"{closed:.2f} s with it; the app saves the stop in {saved * 1000:.0f} ms; "
              f"the small picture takes {shrink:.2f} s (in the background)")
    finally:
        shutil.rmtree(work, ignore_errors=True)

    for text, ok in results:
        print(f"{'ok  ' if ok else 'FAIL'} {text}")
    failures = sum(not ok for _, ok in results)
    print("all good" if not failures else f"{failures} problem(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
