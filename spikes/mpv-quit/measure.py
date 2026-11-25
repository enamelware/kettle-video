# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Kettle spike (the mpv quit spike): play real files with run.py, drive mpv the way
the controller would (through mpv's control socket: pause, seek, the q key),
and check what was saved. Prints one JSON summary.

Read-only on the media: files are only played. Test resume saves go into a
temporary folder, never mpv's real one, so the real resume positions are
left alone. ffmpeg/ffprobe (already on SteamOS) are used only here, to check
the pictures; the prototype itself does not need them.

    python3 spikes/mpv-quit/measure.py [--mpv flatpak|system]
"""

import argparse
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run as runner  # noqa: E402

from backend.settings import load_settings  # noqa: E402

SETTINGS = load_settings()
MOVIES = Path(SETTINGS["movies_path"])
TV = Path(SETTINGS["tv_path"])
TEN_BIT = next(MOVIES.glob("Example.Film*/Example*10bit*.mkv"), None)
SAMPLE = next(TV.glob("Example Show*/Sample/Sample (Opening).mkv"), None)


class Mpv:
    """Just enough of mpv's JSON control socket."""

    def __init__(self, path, timeout=20):
        deadline = time.monotonic() + timeout
        while True:
            try:
                self.sock = socket.socket(socket.AF_UNIX)
                self.sock.connect(path)
                break
            except OSError:
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

    def wait_playing(self, timeout=20):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            pos = self.get("time-pos")
            if pos is not None and pos > 0.2:
                return pos
            time.sleep(0.1)
        raise RuntimeError("mpv did not start playing")

    def send_only(self, *args):
        self.sock.sendall((json.dumps({"command": list(args)}) + "\n").encode())


def start_run(file, command, out_dir, wl_dir, ipc, extra=(), capture=True):
    """run.run() in a thread, so this thread can drive mpv meanwhile."""
    result = {}
    args = [f"--watch-later-dir={wl_dir}", f"--input-ipc-server={ipc}", *extra]

    def go():
        if capture:
            result.update(runner.run(file, command, out_dir, args, keep_full=True))
        else:
            full = runner.kettle_mpv.build_command(command, Path(file), args)
            started = time.monotonic()
            done = subprocess.run(full, stdin=subprocess.DEVNULL,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
            ended = time.monotonic()
            result.update(mpv_exit=done.returncode, mpv_ended=ended,
                          mpv_seconds=round(ended - started, 3))

    thread = threading.Thread(target=go)
    thread.start()
    return thread, result


def saved_resume(wl_dir):
    """The start= value mpv's own resume save wrote, if any."""
    for entry in Path(wl_dir).iterdir():
        match = re.search(r"^start=([\d.]+)", entry.read_text(), re.M)
        if match:
            return float(match.group(1))
    return None


def rgb(source, width, height, position=None):
    """Raw RGB pixels of a picture, or of the video frame at `position`
    decoded by ffmpeg in software (no subtitles), at width x height."""
    seek = ["-ss", f"{position:.3f}"] if position is not None else []
    return subprocess.run(
        ["ffmpeg", "-v", "error", *seek, "-i", str(source), "-frames:v", "1", "-sn",
         "-vf", f"scale={width}:{height}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, check=True).stdout


def difference(a, b):
    """Average difference per colour value, 0 (identical) to 255."""
    return round(sum(abs(x - y) for x, y in zip(a, b)) / len(a), 2)


def colour_stats(pixels):
    """Average brightness and average saturation (max-min of R, G, B), 0-255."""
    n = len(pixels) // 3
    total = sat = 0
    for i in range(0, len(pixels), 3):
        r, g, b = pixels[i], pixels[i + 1], pixels[i + 2]
        total += r + g + b
        sat += max(r, g, b) - min(r, g, b)
    return {"brightness": round(total / (3 * n), 1), "saturation": round(sat / n, 1)}


def dimensions(image):
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "stream=width,height",
         "-of", "csv=p=0", str(image)], text=True).strip()
    w, h = out.split(",")
    return int(w), int(h)


def check_frame(file, summary):
    """Is the saved picture the frame at the saved position (and not one a
    second before or after)? Compared against ffmpeg's own decode."""
    position = summary["record"]["position"]
    picture = summary["picture"]
    w, h = dimensions(picture)
    mine = rgb(picture, w, h)
    candidates = {"same_moment": position, "one_second_before": max(position - 1, 0),
                  "one_second_after": position + 1}
    diffs = {k: difference(mine, rgb(file, w, h, t)) for k, t in candidates.items()}
    reference = rgb(file, w, h, position)
    return {
        "size": [w, h],
        "difference": diffs,
        "closest": min(diffs, key=diffs.get),
        "picture_colours": colour_stats(mine),
        "reference_colours": colour_stats(reference),
    }


def scenario(name, file, command, out_root, work, drive, extra=(), capture=True, wl=None):
    """Play `file`, let `drive(mpv)` act like the viewer, collect results."""
    wl = wl or Path(tempfile.mkdtemp(dir=work, prefix=f"{name}-wl-"))
    ipc = str(work / f"{name}.sock")
    out_dir = out_root / name
    thread, result = start_run(file, command, out_dir, wl, ipc, extra, capture)
    mpv = Mpv(ipc)
    mpv.wait_playing()
    info = drive(mpv) or {}
    thread.join(timeout=120)
    info.update(result)
    if "quit_sent" in info:
        info["quit_to_exit_seconds"] = round(info["mpv_ended"] - info.pop("quit_sent"), 3)
    info.pop("mpv_ended", None)
    info["resume_saved_at"] = saved_resume(wl)
    return info


def quit_playing(after=3.0):
    def drive(mpv):
        time.sleep(after)
        sent = time.monotonic()
        mpv.send_only("keypress", "q")
        return {"quit_sent": sent}
    return drive


def quit_paused_at(position):
    def drive(mpv):
        mpv.command("seek", position, "absolute+exact")
        time.sleep(1.0)
        mpv.command("set_property", "pause", True)
        time.sleep(1.0)
        info = {"pos_before_quit": mpv.get("time-pos"), "hwdec_current": mpv.get("hwdec-current")}
        info["quit_sent"] = time.monotonic()
        mpv.send_only("keypress", "q")
        return info
    return drive


def quit_with_subtitles_and_osd(mpv):
    """Pause where a subtitle is on screen (3:25 in the 10-bit film, a line
    of English dialogue), show on-screen text, then quit."""
    mpv.command("seek", 205.0, "absolute+exact")
    mpv.command("set_property", "pause", True)
    time.sleep(1.0)
    mpv.command("show-text", "KETTLE ON-SCREEN TEXT TEST", 10000)
    time.sleep(0.5)
    info = {"sub_text_on_screen": mpv.get("sub-text"), "quit_sent": time.monotonic()}
    mpv.send_only("keypress", "q")
    return info


def resume_rewind(command, out_root, work):
    """Quit with B at about 40 s, play again: the 5-second rewind must
    still start it about 5 seconds before the saved spot."""
    wl = Path(tempfile.mkdtemp(dir=work, prefix="resume-wl-"))
    first = scenario("resume_first", SAMPLE, command, out_root, work,
                     quit_paused_at(40.0), wl=wl)
    seen = {}

    def look(mpv):
        seen["started_at"] = mpv.get("time-pos")
        mpv.send_only("keypress", "q")
        return {}

    scenario("resume_second", SAMPLE, command, out_root, work, look, wl=wl)
    return {"saved_at": first["record"]["position"],
            "resume_saved_at": first["resume_saved_at"],
            "second_run_started_at": seen.get("started_at")}


def close_window(mpv):
    """The window's close button: mpv's CLOSE_WIN key, bound to quit."""
    time.sleep(2.0)
    mpv.send_only("keypress", "CLOSE_WIN")
    return {}


def play_to_end(mpv):
    return {}


def stop_signal(target):
    """Steam closing the app: a stop signal to the Flatpak wrapper only, to
    mpv only, or to both (wrapper and mpv inside the sandbox)."""
    def drive(mpv):
        time.sleep(2.0)
        pid = mpv.get("pid")
        # `flatpak run` becomes a bwrap process (the sandbox wrapper); mpv
        # runs as mpv-bin inside it. The oldest matching bwrap is the outer one.
        wrapper = subprocess.check_output(
            ["pgrep", "-f", "-o", r"^bwrap --args [0-9]+ -- mpv .*kettle_quit"], text=True).split()[0]
        inside = subprocess.run(["pgrep", "-f", r"^mpv-bin .*kettle_quit"],
                                capture_output=True, text=True).stdout.split()
        info = {"signal_to": target}
        if target in ("all", "mpv"):
            # Like Steam stopping everything the app started: mpv too, at
            # (almost) the same moment as the wrapper.
            for host_pid in inside:
                os.kill(int(host_pid), signal.SIGTERM)
        if target in ("all", "wrapper"):
            os.kill(int(wrapper), signal.SIGTERM)
        time.sleep(3.0)
        try:
            alive = mpv.command("get_property", "pid").get("error") == "success"
        except OSError:
            alive = False
        info["mpv_still_running_3s_later"] = alive
        info["mpv_pid_in_sandbox"] = pid
        if alive:
            mpv.send_only("quit")  # tidy up; this run's data is not counted
        return info
    return drive


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mpv", choices=["flatpak", "system"], default="flatpak")
    parser.add_argument("--only", nargs="*")
    ns = parser.parse_args()
    missing = [name for name, path in (
        ("the 10-bit film (Movies/Example.Film*/Example*10bit*.mkv)", TEN_BIT),
        ("the show's sample (TV Shows/Example Show*/Sample/Sample (Opening).mkv)", SAMPLE),
    ) if path is None]
    if missing:
        raise SystemExit("measure.py needs test files that aren't on this card: "
                         + "; ".join(missing))
    command = runner.mpv_command(ns.mpv)
    out_root = runner.default_out_dir() / f"measure-{ns.mpv}"
    if out_root.exists():
        shutil.rmtree(out_root)
    work = Path(tempfile.mkdtemp(prefix="kettle-measure-", dir="/tmp"))
    short = work / "short.mkv"
    # A short copy of the sample (3 s asked; stream copy cuts at keyframes, so
    # it comes out about 13 s), made in /tmp, never next to the media.
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "10", "-i", str(SAMPLE),
                    "-t", "3", "-c", "copy", str(short)], check=True)

    plans = {
        "playing_1080p_10bit": lambda: scenario(
            "playing_1080p_10bit", TEN_BIT, command, out_root, work,
            quit_playing_at(1200.0)),
        "paused_1080p_10bit_hwdec": lambda: scenario(
            "paused_1080p_10bit_hwdec", TEN_BIT, command, out_root, work,
            quit_paused_at(1800.0), extra=["--hwdec=auto"]),
        "paused_1080p_10bit_software": lambda: scenario(
            "paused_1080p_10bit_software", TEN_BIT, command, out_root, work,
            quit_paused_at(1800.0), extra=["--hwdec=no"]),
        "subtitles_and_osd": lambda: scenario(
            "subtitles_and_osd", TEN_BIT, command, out_root, work,
            quit_with_subtitles_and_osd, extra=["--sid=1"]),
        "short_file_quit": lambda: scenario(
            "short_file_quit", short, command, out_root, work, quit_playing(1.0)),
        "short_file_to_end": lambda: scenario(
            "short_file_to_end", short, command, out_root, work, play_to_end),
        "close_window": lambda: scenario(
            "close_window", SAMPLE, command, out_root, work, close_window),
        "resume_rewind": lambda: resume_rewind(command, out_root, work),
        "stop_wrapper_only": lambda: scenario(
            "stop_wrapper_only", SAMPLE, command, out_root, work, stop_signal("wrapper")),
        "stop_mpv_only": lambda: scenario(
            "stop_mpv_only", SAMPLE, command, out_root, work, stop_signal("mpv")),
        "stop_all_processes": lambda: scenario(
            "stop_all_processes", SAMPLE, command, out_root, work, stop_signal("all")),
    }
    for n in range(3):
        plans[f"quit_time_with_script_{n}"] = (lambda n=n: scenario(
            f"quit_time_with_script_{n}", TEN_BIT, command, out_root, work,
            quit_playing_at(600.0 + n * 300)))
        plans[f"quit_time_without_script_{n}"] = (lambda n=n: scenario(
            f"quit_time_without_script_{n}", TEN_BIT, command, out_root, work,
            quit_playing_at(600.0 + n * 300), capture=False))

    results = {"mpv": ns.mpv, "files": {"ten_bit": str(TEN_BIT), "sample": str(SAMPLE)}}
    for name, plan in plans.items():
        if ns.only and name not in ns.only:
            continue
        if ns.mpv == "system" and name.startswith("stop_"):
            continue
        try:
            info = plan()
        except Exception as exc:  # a spike: record and carry on
            info = {"error": repr(exc)}
        file = SAMPLE if name.startswith("stop_") else (
            short if name.startswith("short") else TEN_BIT)
        if info.get("picture") and info.get("record", {}).get("position") is not None:
            info["frame_check"] = check_frame(file, info)
        results[name] = info
        print(name, "done", file=sys.stderr)
    shutil.rmtree(work, ignore_errors=True)
    print(json.dumps(results, indent=2))


def quit_playing_at(position, after=3.0):
    def drive(mpv):
        mpv.command("seek", position, "absolute+exact")
        time.sleep(after)
        info = {"hwdec_current": mpv.get("hwdec-current"), "quit_sent": time.monotonic()}
        mpv.send_only("keypress", "q")
        return info
    return drive


if __name__ == "__main__":
    main()
