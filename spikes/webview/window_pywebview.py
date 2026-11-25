# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Kettle spike (the webview spike), routes B and C: pywebview in a throwaway venv.

Starts the app's server the way launch.sh does, then opens Home in a
full-screen, frameless pywebview window. pywebview picks whichever web engine
the venv can reach (GTK + WebKit, or Qt + its web engine); KETTLE_WEBVIEW_GUI
forces one ("gtk" or "qt"). The server stops when this script ends, however
it ends (see common.py). Nothing in the app is changed.

    spikes/webview/.venv-c/bin/python spikes/webview/window_pywebview.py
"""

import os

import webview

from common import start_server, stop_server


def main():
    server, url = start_server()
    try:
        webview.create_window("Kettle (webview spike)", url,
                              fullscreen=True, frameless=True)
        webview.start(gui=os.environ.get("KETTLE_WEBVIEW_GUI"))
    finally:
        stop_server(server)


if __name__ == "__main__":
    main()
