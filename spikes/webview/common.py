# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Kettle spike (the webview spike): helpers shared by the spike's scripts.

start_server() starts the app's server the way launch.sh does (python3 -m
backend.server on KETTLE_VIDEO_PORT) and asks Linux to stop it the moment
the script that started it ends, however it ends: window closed, stopped
from the Steam menu, or crashed. So no server is ever left behind.
"""

import ctypes
import os
import signal
import socket
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PR_SET_PDEATHSIG = 1


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for_port(port, seconds=10):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.05)
    return False


def _stop_with_parent():
    ctypes.CDLL(None, use_errno=True).prctl(PR_SET_PDEATHSIG, signal.SIGTERM)


def start_server(extra_env=None, **popen_args):
    """Start the server on a free port; return (process, url). Exits with a
    message if the server never opens its port."""
    port = free_port()
    env = dict(os.environ, KETTLE_VIDEO_PORT=str(port), **(extra_env or {}))
    server = subprocess.Popen(["python3", "-u", "-m", "backend.server"], cwd=ROOT,
                              env=env, preexec_fn=_stop_with_parent, **popen_args)
    if not wait_for_port(port):
        server.terminate()
        server.wait(timeout=10)
        sys.exit("The app's server never opened its port (see its messages above).")
    return server, f"http://127.0.0.1:{port}/"


def stop_server(server):
    server.terminate()
    server.wait(timeout=10)
