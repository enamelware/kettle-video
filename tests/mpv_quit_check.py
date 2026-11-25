# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The mpv quit spike with the real mpv (Flatpak by default): the capture
script in spikes/mpv-quit/ must save the right record and picture when B (q)
is pressed, and leave resume as it is. Not part of the unit tests: it needs
mpv and ffmpeg and takes about half a minute.

It plays a 30-second test clip made with ffmpeg in a temporary folder (no
real media is used), with no window and no sound, and drives mpv through its
control socket like the controller would. Resume saves go to a temporary
folder, never mpv's real one. Cases:

  paused     seek to 12 s, pause, show a big magenta subtitle and on-screen
             text, press q: position, duration, paused, a 640 px picture of
             that exact frame, video only, colours not washed out, and mpv's
             resume save at the same position; mpv exits with status 0
  playing    press q while playing: the picture is the frame at the saved
             position
  resume     play the paused case's file again: it starts 5 s earlier
  to_end     let the clip play to the end: record marked finished, no picture
  close      close the window: record marked "other", no picture

Run from the repo root:  python3 tests/mpv_quit_check.py [--mpv flatpak|system]
"""

import argparse
import importlib.util
import json
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

RUN_PY = REPO / "spikes" / "mpv-quit" / "run.py"
CLIP_SECONDS = 30.0
MAGENTA = "#FF00FF"
HEADLESS = ["--vo=null", "--ao=null", "--hwdec=no"]


def load_runner():
    spec = importlib.util.spec_from_file_location("mpv_quit_run", RUN_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = load_runner()


class Mpv:
    """Just enough of mpv's JSON control socket."""

    def __init__(self, path, timeout=30):
        deadline = time.monotonic() + timeout
        while True:
            try:
                self.sock = socket.socket(socket.AF_UNIX)
                self.sock.connect(path)
                break
            except OSError:
                self.sock.close()
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.05)
        self.file = self.sock.makefile("r")
        self.next_id = 0

    def command(self, *args):
        self.next_id += 1
        rid = self.next_id
        self.sock.sendall((json.dumps({"command": list(args), "request_id": rid}) + "\n").encode())
        for line in self.file:
            reply = json.loads(line)
            if reply.get("request_id") == rid:
                return reply
        return {"error": "closed"}

    def get(self, name):
        return self.command("get_property", name).get("data")

    def wait_for(self, name, test, timeout=30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = self.get(name)
            if value is not None and test(value):
                return value
            time.sleep(0.02)
        raise RuntimeError(f"mpv: {name} never became ready")

    def send_only(self, *args):
        self.sock.sendall((json.dumps({"command": list(args)}) + "\n").encode())


def rgb(source, width, height, position=None):
    seek = ["-ss", f"{position:.3f}"] if position is not None else []
    return subprocess.run(
        ["ffmpeg", "-v", "error", *seek, "-i", str(source), "-frames:v", "1", "-sn",
         "-vf", f"scale={width}:{height}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, check=True).stdout


def size(image):
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "stream=width,height",
         "-of", "csv=p=0", str(image)], text=True).strip()
    w, h = out.split(",")[:2]
    return int(w), int(h)


def difference(a, b):
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def stats(pixels, width):
    """Average brightness and saturation, the black level (average of the
    top black band, rows 5 to 25 at 640 px: lifted blacks are what "washed
    out" looked like in the spike) and how many pixels are the test's
    magenta, all 0-255."""
    n = len(pixels) // 3
    total = sat = magenta = 0
    for i in range(0, len(pixels), 3):
        r, g, b = pixels[i], pixels[i + 1], pixels[i + 2]
        total += r + g + b
        sat += max(r, g, b) - min(r, g, b)
        if r > 200 and g < 70 and b > 200:
            magenta += 1
    band = pixels[5 * width * 3:25 * width * 3]
    return {"brightness": total / (3 * n), "saturation": sat / n,
            "black": sum(band) / len(band), "magenta": magenta}


def saved_resume(wl_dir):
    for entry in Path(wl_dir).iterdir():
        match = re.search(r"^start=([\d.]+)", entry.read_text(), re.M)
        if match:
            return float(match.group(1))
    return None


class Check:
    def __init__(self, command, work):
        self.command = command
        self.work = work
        self.out = work / "data"
        self.clip = work / "clip.mkv"
        self.subs = work / "clip.srt"
        self.failures = []

    def expect(self, case, ok, what):
        print(f"  {'ok  ' if ok else 'FAIL'} {case}: {what}")
        if not ok:
            self.failures.append(f"{case}: {what}")

    def make_clip(self):
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
             # Colours turn 36 degrees a second, so frames a second apart
             # differ everywhere; softened so JPEG loss stays small.
             # Black bands top and bottom, like a widescreen film, to spot
             # lifted blacks.
             "-i", f"testsrc2=size=1280x560:rate=25:duration={CLIP_SECONDS:g},"
                   "hue=H=2*PI*t/10,gblur=sigma=3,pad=1280:720:0:80:black",
             "-c:v", "mpeg4", "-q:v", "3", str(self.clip)], check=True)
        self.subs.write_text("1\n00:00:00,000 --> 00:00:40,000\nMMMMMM\n")

    def play(self, name, drive, wl, extra=()):
        """run.run() in a thread while `drive(mpv)` acts like the viewer."""
        ipc = str(self.work / f"{name}.sock")
        args = [f"--watch-later-dir={wl}", f"--input-ipc-server={ipc}", *HEADLESS, *extra]
        result = {}
        thread = threading.Thread(target=lambda: result.update(
            runner.run(self.clip, self.command, self.out / name, args)))
        thread.start()
        try:
            info = drive(Mpv(ipc)) or {}
        finally:
            thread.join(timeout=120)
        if thread.is_alive():
            raise RuntimeError(f"{name}: mpv did not close")
        info.update(result)
        info["resume_saved_at"] = saved_resume(wl)
        return info

    def check_picture(self, case, info, position):
        picture = info.get("picture")
        self.expect(case, bool(picture) and Path(picture).is_file(), "a picture was saved")
        if not picture or not Path(picture).is_file():
            return
        w, h = size(picture)
        self.expect(case, w == 640, f"picture is 640 px wide (got {w}x{h})")
        mine = rgb(picture, w, h)
        diffs = {t: difference(mine, rgb(self.clip, w, h, t))
                 for t in (position, max(position - 1, 0), position + 1)}
        closest = min(diffs, key=diffs.get)
        others = [d for t, d in diffs.items() if t != position]
        self.expect(case, closest == position and diffs[position] * 2 < min(others),
                    f"picture is the frame at {position:.2f} s "
                    f"(differences: {', '.join(f'{t:.2f}s={d:.1f}' for t, d in diffs.items())})")
        a, b = stats(mine, w), stats(rgb(self.clip, w, h, position), w)
        self.expect(case, abs(a["brightness"] - b["brightness"]) < 4
                    and abs(a["black"] - b["black"]) < 4
                    and abs(a["saturation"] - b["saturation"]) < 6,
                    f"colours not washed out (brightness {a['brightness']:.1f} vs "
                    f"{b['brightness']:.1f}, black level {a['black']:.1f} vs {b['black']:.1f}, "
                    f"saturation {a['saturation']:.1f} vs {b['saturation']:.1f})")
        return a, b

    def paused(self):
        case = "paused"
        wl = Path(tempfile.mkdtemp(dir=self.work, prefix="paused-wl-"))
        with_subs = self.work / "with-subtitles.jpg"

        def drive(mpv):
            mpv.wait_for("time-pos", lambda v: v > 0.2)
            mpv.command("seek", 12.0, "absolute+exact")
            mpv.command("set_property", "pause", True)
            time.sleep(1.0)
            mpv.command("show-text", "OSD OSD OSD", 20000)
            time.sleep(0.3)
            # Proof the subtitle and text really are on screen: a picture
            # that includes them, for comparison.
            mpv.command("screenshot-to-file", str(with_subs), "subtitles")
            pos = mpv.get("time-pos")
            mpv.send_only("keypress", "q")
            return {"pos_before_quit": pos}

        info = self.play(case, drive, wl, [
            f"--sub-file={self.subs}", "--sid=1", "--sub-font-size=150",
            f"--sub-color={MAGENTA}", "--sub-border-size=0", "--sub-shadow-offset=0",
            "--osd-font-size=150", f"--osd-color={MAGENTA}", "--osd-border-size=0"])
        record = info.get("record") or {}
        self.expect(case, info.get("mpv_exit") == 0, f"mpv exit status 0 (got {info.get('mpv_exit')})")
        pos = record.get("position")
        self.expect(case, pos is not None and abs(pos - info["pos_before_quit"]) < 0.05,
                    f"record position {pos} matches mpv's {info['pos_before_quit']}")
        dur = record.get("duration")
        self.expect(case, dur is not None and abs(dur - CLIP_SECONDS) < 0.2,
                    f"record duration {dur} is the clip's {CLIP_SECONDS:g} s")
        self.expect(case, record.get("paused") is True, "record says it was paused")
        self.expect(case, record.get("finished") is False and record.get("how") == "b",
                    "record is a B quit, not finished")
        self.expect(case, record.get("file") == str(self.clip), "record names the file")
        self.expect(case, isinstance(record.get("quit_at"), (int, float))
                    and abs(record["quit_at"] - time.time()) < 120, "record has the time of quit")
        resume = info["resume_saved_at"]
        self.expect(case, resume is not None and pos is not None and abs(resume - pos) < 0.05,
                    f"mpv's resume save ({resume}) is the same moment as the record")
        if pos is None:
            return None
        found = self.check_picture(case, info, pos)
        if found:
            w, h = size(info["picture"])
            shown = stats(rgb(with_subs, w, h), w)["magenta"]
            mine, reference = found
            self.expect(case, shown > reference["magenta"] + 2000,
                        f"test is meaningful: subtitle/text visible on screen "
                        f"({shown} vs {reference['magenta']} magenta pixels)")
            # JPEG noise adds a few; the subtitle and text add thousands.
            added = shown - reference["magenta"]
            self.expect(case, mine["magenta"] - reference["magenta"] < added / 4,
                        f"picture is video only: no subtitle or on-screen text "
                        f"({mine['magenta']} vs {reference['magenta']} magenta pixels)")
        return wl, pos

    def playing(self):
        case = "playing"
        wl = Path(tempfile.mkdtemp(dir=self.work, prefix="playing-wl-"))

        def drive(mpv):
            mpv.wait_for("time-pos", lambda v: v > 3.0)
            mpv.send_only("keypress", "q")

        info = self.play(case, drive, wl)
        record = info.get("record") or {}
        self.expect(case, info.get("mpv_exit") == 0, f"mpv exit status 0 (got {info.get('mpv_exit')})")
        self.expect(case, record.get("paused") is False, "record says it was playing")
        pos = record.get("position")
        self.expect(case, pos is not None and pos > 3.0, f"record position {pos} is after 3 s")
        resume = info["resume_saved_at"]
        self.expect(case, resume is not None and pos is not None and abs(resume - pos) < 0.05,
                    f"mpv's resume save ({resume}) is the same moment as the record")
        if pos is not None:
            self.check_picture(case, info, pos)

    def resume(self, wl, saved):
        case = "resume"

        def drive(mpv):
            start = mpv.wait_for("time-pos", lambda v: True)
            mpv.send_only("keypress", "q")
            return {"started_at": start}

        info = self.play(case, drive, wl)
        start = info["started_at"]
        self.expect(case, abs(start - (saved - 5)) < 0.6,
                    f"second play starts 5 s before the saved {saved:.2f} s (started at {start:.2f})")

    def to_end(self):
        case = "to_end"
        wl = Path(tempfile.mkdtemp(dir=self.work, prefix="end-wl-"))

        def drive(mpv):
            mpv.wait_for("time-pos", lambda v: v > 0.2)
            mpv.command("seek", CLIP_SECONDS - 2, "absolute")

        info = self.play(case, drive, wl)
        record = info.get("record") or {}
        self.expect(case, info.get("mpv_exit") == 0, f"mpv exit status 0 (got {info.get('mpv_exit')})")
        self.expect(case, record.get("finished") is True and record.get("how") == "end",
                    "record marked finished")
        pos = record.get("position")
        self.expect(case, pos is not None and abs(pos - CLIP_SECONDS) < 0.2,
                    f"finished position {pos} is the end")
        self.expect(case, record.get("frame_saved") is False and "picture" not in info,
                    "no picture at the end")
        self.expect(case, info["resume_saved_at"] is None, "mpv saves no resume position at the end")

    def close(self):
        case = "close"
        wl = Path(tempfile.mkdtemp(dir=self.work, prefix="close-wl-"))

        def drive(mpv):
            mpv.wait_for("time-pos", lambda v: v > 2.0)
            mpv.send_only("keypress", "CLOSE_WIN")

        info = self.play(case, drive, wl)
        record = info.get("record") or {}
        self.expect(case, record.get("how") == "other" and record.get("finished") is False,
                    "record marked other, not finished")
        self.expect(case, record.get("position") is not None, "record has the last position")
        self.expect(case, "picture" not in info, "no picture")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mpv", choices=["flatpak", "system"], default="flatpak")
    ns = parser.parse_args()
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        print("skipped: ffmpeg/ffprobe not found")
        return 0
    try:
        command = runner.mpv_command(ns.mpv)
    except SystemExit as exc:
        print(f"skipped: {exc}")
        return 0
    if ns.mpv == "flatpak" and subprocess.run(
            ["flatpak", "info", runner.kettle_mpv.FLATPAK_APP_ID], capture_output=True).returncode:
        print("skipped: the mpv Flatpak is not installed")
        return 0
    # /tmp: the Flatpak mpv can write there (socket, resume saves, frame).
    work = Path(tempfile.mkdtemp(prefix="kettle-quit-check-", dir="/tmp"))
    check = Check(command, work)
    try:
        check.make_clip()
        for name in ("paused", "playing", "to_end", "close"):
            print(name)
            try:
                found = getattr(check, name)()
            except Exception as exc:
                check.failures.append(f"{name}: {exc!r}")
                print(f"  FAIL {name}: {exc!r}")
                continue
            if name == "paused" and found:
                print("resume")
                try:
                    check.resume(*found)
                except Exception as exc:
                    check.failures.append(f"resume: {exc!r}")
                    print(f"  FAIL resume: {exc!r}")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if check.failures:
        print(f"\n{len(check.failures)} problem(s):")
        for failure in check.failures:
            print(f"- {failure}")
        return 1
    print("\nall passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
