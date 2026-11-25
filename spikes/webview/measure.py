# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Kettle spike (the webview spike): launch time and memory, webview vs Firefox kiosk.

Each run starts the app's server (as launch.sh does, with
KETTLE_VIDEO_LAUNCH_START set so the server prints "page loaded N s after
launch"), opens Home in either the Route C pywebview window or the Flatpak
Firefox in kiosk mode (same flags and profile as launch.sh), waits for the
page, lets it settle, then adds up the memory (PSS: each process's own memory
plus its fair share of memory it shares with others) of every process the
window started. The server is not counted in either case. Then everything is
closed and the run checks nothing is left.

    python3 spikes/webview/measure.py webview|firefox [RUNS]
"""

import os
import queue
import subprocess
import sys
import threading
import time

from common import ROOT, start_server, stop_server

VENV_PYTHON = os.path.join(ROOT, "spikes", "webview", ".venv-c", "bin", "python")
FIREFOX_PROFILE = os.path.expanduser(
    "~/.var/app/org.mozilla.firefox/data/kettle-video-profile")
SETTLE_SECONDS = 5
LOAD_LIMIT_SECONDS = 60


def window_command(kind, url):
    if kind == "webview":
        code = ("import webview; webview.create_window('Kettle', %r, "
                "fullscreen=True, frameless=True); webview.start()" % url)
        return [VENV_PYTHON, "-c", code]
    return ["flatpak", "run", "org.mozilla.firefox", "--no-remote",
            "-profile", FIREFOX_PROFILE, "-kiosk", url]


def children_map():
    kids = {}
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            with open(f"/proc/{name}/stat") as f:
                ppid = int(f.read().rsplit(")", 1)[1].split()[1])
        except OSError:
            continue
        kids.setdefault(ppid, []).append(int(name))
    return kids


def descendants(pid):
    kids, found, todo = children_map(), [], [pid]
    while todo:
        p = todo.pop()
        found.append(p)
        todo.extend(kids.get(p, []))
    return found


def pss_mb(pids):
    total_kb = 0
    for pid in pids:
        try:
            with open(f"/proc/{pid}/smaps_rollup") as f:
                for line in f:
                    if line.startswith("Pss:"):
                        total_kb += int(line.split()[1])
        except OSError:
            pass
    return total_kb / 1024


def wait_for_page_loaded(server):
    """Seconds from launch to the server's "page loaded" line, or None if it
    doesn't come within LOAD_LIMIT_SECONDS. The server's messages are read in
    a helper thread, so a silent server can't make this wait forever."""
    lines = queue.Queue()
    threading.Thread(target=lambda: [lines.put(line) for line in server.stdout],
                     daemon=True).start()
    deadline = time.monotonic() + LOAD_LIMIT_SECONDS
    while (left := deadline - time.monotonic()) > 0:
        try:
            line = lines.get(timeout=left)
        except queue.Empty:
            break
        if line.startswith("page loaded"):
            return float(line.split()[2])
    return None


def one_run(kind):
    started = time.time()
    server, url = start_server({"KETTLE_VIDEO_LAUNCH_START": str(started)},
                               text=True, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT)
    window = None
    try:
        window = subprocess.Popen(window_command(kind, url),
                                  stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL)
        loaded = wait_for_page_loaded(server)
        if loaded is None:
            return None, 0, 0
        time.sleep(SETTLE_SECONDS)
        pids = descendants(window.pid)
        memory = pss_mb(pids)
        return loaded, memory, len(pids)
    finally:
        if window is not None:
            for pid in reversed(descendants(window.pid)):
                try:
                    os.kill(pid, 15)
                except OSError:
                    pass
            window.wait(timeout=20)
        stop_server(server)


def leftovers():
    out = subprocess.run(["pgrep", "-f", "backend.server|QtWebEngineProcess|"
                          "kettle-video-profile"], capture_output=True, text=True)
    return out.stdout.split()


def main():
    kind = sys.argv[1]
    runs = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    for n in range(1, runs + 1):
        loaded, memory, count = one_run(kind)
        time.sleep(3)
        left = leftovers()
        if loaded is None:
            print(f"{kind} run {n}: FAILED, the page never loaded within "
                  f"{LOAD_LIMIT_SECONDS} s; left behind: {left or 'nothing'}",
                  flush=True)
            continue
        print(f"{kind} run {n}: page loaded {loaded} s after launch, "
              f"memory {memory:.0f} MB over {count} processes, "
              f"left behind: {left or 'nothing'}", flush=True)


if __name__ == "__main__":
    main()
