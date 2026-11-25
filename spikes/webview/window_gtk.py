# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Kettle spike (the webview spike), Route A: no new package at all.

Starts the app's server the way launch.sh does (python3 -m backend.server on
KETTLE_VIDEO_PORT), then opens Home in a full-screen, frameless window made
from the system's own GTK 3 and WebKit2GTK. The server stops when this
script ends, however it ends (see common.py). Nothing in the app is changed.

    python3 spikes/webview/window_gtk.py

Exits with a plain message if this device has no WebKit2GTK.
"""

import sys

import gi

from common import start_server, stop_server

gi.require_version("Gtk", "3.0")
try:
    gi.require_version("WebKit2", "4.1")
except ValueError:
    try:
        gi.require_version("WebKit2", "4.0")
    except ValueError:
        sys.exit("Route A not possible here: WebKit2GTK is not installed "
                 "(would need a system change).")
from gi.repository import Gtk, WebKit2  # noqa: E402


def main():
    server, url = start_server()
    try:
        window = Gtk.Window(title="Kettle (webview spike)")
        window.set_decorated(False)
        view = WebKit2.WebView()
        view.load_uri(url)
        window.add(view)
        window.connect("destroy", Gtk.main_quit)
        window.show_all()
        window.fullscreen()
        Gtk.main()
    finally:
        stop_server(server)


if __name__ == "__main__":
    main()
