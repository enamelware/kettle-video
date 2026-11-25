# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Kettle spike (the folder dialog spike), Question 2 from the terminal: the automatic
part, on a device in Desktop Mode.

Starts server.py the way launch.sh starts the app's server (python3 -u,
from the project folder, in the background, output to a log). For each
dialog this device has, asks the server to open it in folder mode, and
while it is open asks the server for /api/ping every 0.2 s. After a few
seconds the dialog is closed by the script (nobody picks a folder here;
the designer does that by hand). Prints one line per dialog: whether it
opened, how it ended, and whether the server kept answering meanwhile.
No folder names are printed.

    python3 spikes/folder-dialog/auto_check.py [seconds-open]
"""

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def request(port, path, method="GET", timeout=5):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method, data=b"" if method == "POST" else None)
    with urllib.request.urlopen(req, timeout=timeout) as answer:
        return json.loads(answer.read())


def ping_while(port, running, stats):
    while running.is_set():
        started = time.monotonic()
        try:
            request(port, "/api/ping", timeout=2)
            stats["answered"] += 1
            stats["slowest"] = max(stats["slowest"], time.monotonic() - started)
        except OSError:
            stats["missed"] += 1
        time.sleep(0.2)


def main():
    seconds_open = float(sys.argv[1]) if len(sys.argv) > 1 else 4
    port = free_port()
    log = tempfile.NamedTemporaryFile("w+", prefix="folder-dialog-auto-", suffix=".log", delete=False)
    env = {**os.environ, "KETTLE_SPIKE_PORT": str(port)}
    server = subprocess.Popen([sys.executable, "-u", os.path.join(HERE, "server.py")], cwd=ROOT,
                              stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, env=env)
    try:
        for _ in range(50):
            try:
                request(port, "/api/ping", timeout=1)
                break
            except OSError:
                time.sleep(0.2)
        checks = request(port, "/api/checks", timeout=15)
        print(f"session: {os.environ.get('XDG_SESSION_TYPE', '?')}, desktop: {os.environ.get('XDG_CURRENT_DESKTOP', '?')}")
        for check in checks:
            if not check["available"]:
                print(f"{check['name']:8} not available: {check['result']}")
                continue
            stats = {"answered": 0, "missed": 0, "slowest": 0.0}
            running = threading.Event()
            running.set()
            pinger = threading.Thread(target=ping_while, args=(port, running, stats))
            pinger.start()
            try:
                record = request(port, f"/api/open/{check['name']}?close_after={seconds_open}",
                                 method="POST", timeout=seconds_open + 30)
            except OSError as err:
                record = {"result": "error", "detail": f"no answer from the server: {err}"}
            running.clear()
            pinger.join()
            print(f"{check['name']:8} {record['result']}"
                  f"{' (' + record['detail'] + ')' if record.get('detail') else ''}"
                  f"{', ' + record['where'] if record.get('where') else ''}; "
                  f"server answered {stats['answered']} pings while it was open, missed {stats['missed']}, "
                  f"slowest {stats['slowest'] * 1000:.0f} ms")
            time.sleep(1)
        request(port, "/api/quit", method="POST")
        server.wait(timeout=10)
        print(f"server stopped (exit {server.returncode})")
    finally:
        if server.poll() is None:
            server.terminate()
        log.close()
        os.unlink(log.name)


if __name__ == "__main__":
    main()
