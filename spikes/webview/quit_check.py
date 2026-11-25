# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Kettle spike (the webview spike): is anything left behind when the web view ends?

Starts the spike exactly as the Steam shortcut does (run-webview.sh), waits
for Home to load, then ends the window in two ways: a polite stop (what
Steam's "Exit game" sends first) and a hard kill (as if it crashed). After
each, it lists any app server or web engine process still running.

    python3 spikes/webview/quit_check.py
"""

import os
import signal
import subprocess
import time

from common import ROOT

LAUNCHER = os.path.join(ROOT, "spikes", "webview", "run-webview.sh")
LOG = os.path.join(ROOT, "logs", "webview-spike.log")
LEFTOVER_PATTERN = "backend.server|QtWebEngineProcess|window_pywebview"


def leftovers():
    out = subprocess.run(["pgrep", "-af", LEFTOVER_PATTERN], capture_output=True, text=True)
    return [line for line in out.stdout.splitlines() if "pgrep" not in line]


def wait_for_page(log_size_before, seconds=30):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            with open(LOG) as f:
                f.seek(log_size_before)
                if "GET /api/library/parsed" in f.read():
                    return True
        except FileNotFoundError:
            pass  # the launcher hasn't created the log yet
        time.sleep(0.2)
    return False


def one_case(name, sig):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    before = os.path.getsize(LOG) if os.path.exists(LOG) else 0
    launcher = subprocess.Popen([LAUNCHER])
    try:
        loaded = wait_for_page(before)
    finally:
        # run-webview.sh execs Python, so the launcher's process is the
        # window. Ended here whatever happened above.
        os.kill(launcher.pid, sig)
        launcher.wait(timeout=20)
    time.sleep(2)
    left = leftovers()
    print(f"{name}: Home loaded: {'yes' if loaded else 'no'}; "
          f"left behind: {left or 'nothing'}", flush=True)
    for line in left:
        os.kill(int(line.split()[0]), signal.SIGTERM)


def main():
    if leftovers():
        raise SystemExit(f"Something is already running: {leftovers()}")
    one_case("polite stop (SIGTERM, like Exit game)", signal.SIGTERM)
    one_case("hard kill (SIGKILL, like a crash)", signal.SIGKILL)


if __name__ == "__main__":
    main()
