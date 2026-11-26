# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Pause a playing film when the device goes to sleep (the sleep pause fix).

The launch rehearsal found that a film started over after the power button
put the device to sleep and woke it, instead of staying where it was. The
logs showed one play request and one mpv for the whole film, and no page
reload, so the jump came from inside mpv after waking; a terminal can't
make a real sleep, and a frozen mpv keeps its place (docs/decisions.md,
"A film stays paused where it was after sleep").

So while mpv runs, this listens for logind's PrepareForSleep message on the
system bus, read with the system's gdbus tool, and holds a short sleep
"delay" lock so the system waits for the pause (see DELAY_CAP_SECONDS):
- about to sleep: mpv is paused through its control socket, the lock is let
  go and the spot is remembered;
- woken up: the lock is taken again, and for a few seconds, if the film has
  moved away from that spot while still paused, it is put back there, and
  mpv's usual "Paused" text shows. Pressing play continues from the spot.

Limits: the watch after waking lasts WAKE_GUARD_SECONDS, so a jump later
than that is not put back, and a film that is playing again (taken to be
the viewer pressing A, even if something else started it) is left alone.

mpv stays an external process and keeps its own resume positions; this only
sends it the same commands its keys do. Without gdbus (or a control
socket), a film plays as before and the mpv log says so.
"""

import json
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Optional

MONITOR_TOOL = "gdbus"
LOGIN1 = "org.freedesktop.login1"
LOGIN1_PATH = "/org/freedesktop/login1"
# gdbus prints each signal as one line:
#   /org/freedesktop/login1: org.freedesktop.login1.Manager.PrepareForSleep (true,)
SIGNAL = f"{LOGIN1}.Manager.PrepareForSleep"

# After waking, how long the spot is kept, and how often it is checked.
WAKE_GUARD_SECONDS = 3.0
WAKE_CHECK_SECONDS = 0.25
# A film this far from its spot has moved (mpv's own position wobbles by a
# frame or two).
MOVED_SECONDS = 1.0
# The same words and time as pressing A (backend/mpv_scripts/playback_controls.lua).
PAUSED_TEXT = "Paused\n${time-pos} / ${duration}"
PAUSED_TEXT_MS = 3000

ASK_TIMEOUT = 1.0

# Without a "delay" lock the system goes straight on into sleep when it
# sends PrepareForSleep, and may freeze mpv before the pause lands. With
# one, it waits until the lock is let go: Kettle lets go as soon as mpv is
# paused, and at the latest after DELAY_CAP_SECONDS. The system has its own
# cap too (logind's InhibitDelayMaxSec, 5 seconds by default), so the lock
# only ever postpones a sleep, never blocks it (the power button fix).
DELAY_TOOL = "systemd-inhibit"
DELAY_WHY = "Pausing the film before sleep"
DELAY_CAP_SECONDS = 2.0

LOG_PREFIX = "kettle-video: pause on sleep:"
TOOL_MISSING = f"{LOG_PREFIX} off ({MONITOR_TOOL} not found); a film keeps playing through sleep"
DELAY_MISSING = (f"{LOG_PREFIX} no sleep delay lock ({DELAY_TOOL} not found or couldn't start); "
                 "the pause may come after the sleep has started")


def monitor_command(tool: str) -> list:
    """Listen to logind's signals on the system bus. gdbus subscribes like
    any app does, so it needs no permission, and prints each line at once."""
    return [tool, "monitor", "--system", "--dest", LOGIN1, "--object-path", LOGIN1_PATH]


def delay_lock_command(tool: str) -> list:
    """A sleep "delay" lock held for as long as cat runs. cat ends when its
    input closes: when Kettle lets go, and also if Kettle itself ends, so
    the lock can never outlive the app."""
    return [tool, "--what=sleep", "--mode=delay", "--who=Kettle", f"--why={DELAY_WHY}", "cat"]


class DelayLock:
    """The sleep delay lock: take() while a film plays, release() once mpv
    is paused for sleep. Without the lock tool, nothing is held."""

    def __init__(self, tool: Optional[str]):
        self._tool = tool
        self._process = None
        self._lock = threading.Lock()

    @property
    def held(self) -> bool:
        return self._process is not None

    def take(self) -> bool:
        with self._lock:
            if self._tool is None or self._process is not None:
                return self._process is not None
            try:
                self._process = subprocess.Popen(
                    delay_lock_command(self._tool), stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            except (OSError, ValueError, subprocess.SubprocessError):
                self._process = None
            return self._process is not None

    def release(self) -> None:
        with self._lock:
            process, self._process = self._process, None
        if process is None:
            return
        process.stdin.close()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def parse(line: str) -> Optional[bool]:
    """True: about to sleep. False: woken up. None: any other line."""
    _, sep, rest = line.partition(f" {SIGNAL} ")
    if not sep:
        return None
    args = rest.strip()
    if args.startswith("(true"):
        return True
    if args.startswith("(false"):
        return False
    return None


def ask(control_socket: Path, command: list, timeout: float = ASK_TIMEOUT):
    """Send mpv one command; (True, its answer's data), or (False, None) if
    mpv couldn't be reached or refused. mpv also sends events on the same
    connection, so the answer is the line with our request_id."""
    request = {"command": command, "request_id": 1}
    deadline = time.monotonic() + timeout
    try:
        with socket.socket(socket.AF_UNIX) as sock:
            sock.settimeout(timeout)
            sock.connect(str(control_socket))
            sock.sendall(json.dumps(request).encode() + b"\n")
            buffer = b""
            while time.monotonic() < deadline:
                chunk = sock.recv(4096)
                if not chunk:
                    return False, None
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    try:
                        answer = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(answer, dict) and answer.get("request_id") == 1:
                        return answer.get("error") == "success", answer.get("data")
    except OSError:
        pass
    return False, None


def _seconds(value) -> Optional[float]:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


class SleepPause:
    """Pauses mpv for sleep and keeps its spot on waking. handle() takes
    one line from the monitor; start() runs the monitor itself."""

    def __init__(self, control_socket: Path, write: Callable[[str], None],
                 guard_seconds: float = WAKE_GUARD_SECONDS, check_seconds: float = WAKE_CHECK_SECONDS,
                 delay_lock: Optional[DelayLock] = None, delay_cap_seconds: float = DELAY_CAP_SECONDS):
        self._socket = control_socket
        self._delay = delay_lock or DelayLock(None)
        self._delay_cap = delay_cap_seconds
        self._write = write
        self._guard = guard_seconds
        self._check = check_seconds
        self._spot = None
        self._stopped = threading.Event()
        self._process = None
        self._reader = None

    def handle(self, line: str) -> None:
        going = parse(line)
        if going is True:
            self.going_to_sleep()
        elif going is False:
            self.woken_up()

    def going_to_sleep(self) -> None:
        # The system waits for the delay lock: let go once mpv is paused, or
        # after the cap if mpv doesn't answer in time.
        cap = threading.Timer(self._delay_cap, self._delay.release)
        cap.daemon = True
        cap.start()
        try:
            paused, _ = ask(self._socket, ["set_property", "pause", True])
        finally:
            self._delay.release()
            cap.cancel()
        _, position = ask(self._socket, ["get_property", "time-pos"])
        self._spot = _seconds(position)
        if not paused:
            self._write(f"{LOG_PREFIX} going to sleep; mpv couldn't be paused")
        elif self._spot is None:
            self._write(f"{LOG_PREFIX} going to sleep; film paused")
        else:
            self._write(f"{LOG_PREFIX} going to sleep; film paused at {self._spot:.1f} s")

    def woken_up(self) -> None:
        self._delay.take()  # ready for the next sleep
        spot, self._spot = self._spot, None
        if spot is None:
            self._write(f"{LOG_PREFIX} woken up")
            return
        self._write(f"{LOG_PREFIX} woken up; keeping the film at {spot:.1f} s")
        shown = False
        deadline = time.monotonic() + self._guard
        while not self._stopped.is_set():
            reached, paused = ask(self._socket, ["get_property", "pause"])
            if not reached:
                return  # mpv has closed
            if paused is not True:
                return  # the viewer pressed play: their film from here
            _, position = ask(self._socket, ["get_property", "time-pos"])
            position = _seconds(position)
            if position is not None and abs(position - spot) > MOVED_SECONDS:
                ask(self._socket, ["seek", spot, "absolute+exact"])
                self._write(f"{LOG_PREFIX} the film had moved to {position:.1f} s; put back at {spot:.1f} s")
                shown = False
            if not shown:
                self._show_paused()
                shown = True
            if time.monotonic() >= deadline:
                return
            self._stopped.wait(self._check)

    def _show_paused(self) -> None:
        # A command sent as a list isn't expanded by mpv, so the times are
        # filled in first, the way mpv shows them.
        expanded, text = ask(self._socket, ["expand-text", PAUSED_TEXT])
        if expanded and isinstance(text, str):
            ask(self._socket, ["show-text", text, PAUSED_TEXT_MS])
            # Like the playback controls, so a check can read what was shown.
            one_line = text.replace("\n", " | ")
            self._write(f"{LOG_PREFIX} shown: {one_line}")

    def start(self, tool: Optional[str] = None, delay_tool: Optional[str] = None) -> "SleepPause":
        """Take the delay lock and run the monitor in the background until stop()."""
        tool = tool or shutil.which(MONITOR_TOOL)
        if tool is None:
            self._write(TOOL_MISSING)
            return self
        self._delay = DelayLock(delay_tool or shutil.which(DELAY_TOOL))
        if not self._delay.take():
            self._write(DELAY_MISSING)
        try:
            self._process = subprocess.Popen(
                monitor_command(tool), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
            )
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            self._write(f"{LOG_PREFIX} off ({MONITOR_TOOL} couldn't start: {type(exc).__name__})")
            return self
        self._reader = threading.Thread(target=self._read, args=(self._process.stdout,), daemon=True)
        self._reader.start()
        return self

    def _read(self, stream) -> None:
        with stream:
            for line in stream:
                if self._stopped.is_set():
                    return
                try:
                    self.handle(line)
                except Exception as exc:  # never let a sleep message stop playback
                    self._write(f"{LOG_PREFIX} skipped a message ({type(exc).__name__})")

    def stop(self) -> None:
        self._stopped.set()
        self._delay.release()
        process, self._process = self._process, None
        if process is None:
            return
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        # The monitor's output ends with it; a wake still being handled
        # stops at its next check.
        self._reader.join(timeout=2)
