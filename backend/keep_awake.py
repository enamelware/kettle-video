# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Keep the device awake while mpv runs (the keep-awake work).

mpv is started under systemd-inhibit, the system's "stay awake" lock tool.
The lock is held by that tool for exactly as long as the command it starts,
so it ends when mpv quits, crashes or is closed by Steam. Reasoning and
limits: docs/decisions.md, "Keep the device awake during playback".
"""

import shutil
import subprocess
import threading

LOCK_TOOL = "systemd-inhibit"
WHO = "Kettle"
WHY = "Playing a video"
# Blocks only the screen dimming/blanking on idle. Never "sleep": that lock
# also refuses a sleep the viewer asks for with the power button (the power button fix).
WHAT = "idle"

TOOL_MISSING_WARNING = (
    "keep_awake: the system's stay-awake lock (systemd-inhibit) is missing or was refused, "
    "so the screen may dim or turn off during the film. "
    "Playing without it."
)


def find_lock_tool():
    """The path of a working systemd-inhibit, or None.

    The tool can be installed but refused the lock (no login session, a
    permission rule); it would then stop with an error and never start mpv.
    So it first takes the same kind of lock around a command that does
    nothing ("true"), which takes a few milliseconds; only if that works is
    it used for the film.
    """
    path = shutil.which(LOCK_TOOL)
    if path is None:
        return None
    try:
        result = subprocess.run(
            [path, *_lock_options(), "true"], capture_output=True, timeout=5
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return path if result.returncode == 0 else None


def _lock_options() -> list:
    return [f"--what={WHAT}", f"--who={WHO}", f"--why={WHY}", "--mode=block"]


def wrap_command(args: list, keep_awake: bool, lock_tool):
    """(the command to run, a warning or None). Pure: no I/O.

    keep_awake on and a lock tool: mpv runs under the lock. keep_awake off:
    unchanged. No lock tool: unchanged, plus a warning for the log.
    """
    args = list(args)
    if not keep_awake:
        return args, None
    if not lock_tool:
        return args, TOOL_MISSING_WARNING
    return [lock_tool, *_lock_options(), *args], None


# --- Step 0 diagnostics (temporary) -----------------------------------------
# While a film plays, the mpv log lists the system's stay-awake locks a few
# seconds after the start and then every 60 seconds, to see afterwards whether
# the lock was held during a Gaming Mode session. Remove this section, and the
# two lines in mpv.play() that use it, once the designer has confirmed the lock
# on both devices (docs/decisions.md, "Keep the device awake during playback").

DIAGNOSTICS_FIRST_DELAY = 3
DIAGNOSTICS_INTERVAL = 60


def list_locks() -> list:
    """The system's current locks, one log line each."""
    path = shutil.which(LOCK_TOOL)
    if path is None:
        return ["kettle-video: locks: systemd-inhibit not found"]
    try:
        result = subprocess.run(
            [path, "--list", "--no-pager"],
            capture_output=True, text=True, errors="replace", timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return [f"kettle-video: locks: could not list ({type(exc).__name__})"]
    lines = (result.stdout + result.stderr).splitlines()
    return [f"kettle-video: locks: {line}" for line in lines if line.strip()]


def start_lock_diagnostics(write):
    """Write the lock list with write(line) until the returned event is set."""
    stop = threading.Event()

    def run():
        if stop.wait(DIAGNOSTICS_FIRST_DELAY):
            return
        while True:
            for line in list_locks():
                write(line)
            if stop.wait(DIAGNOSTICS_INTERVAL):
                return

    threading.Thread(target=run, daemon=True).start()
    return stop
