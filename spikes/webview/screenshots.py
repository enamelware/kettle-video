# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Kettle spike (the webview spike): Home in the Qt web view and in Firefox, side by side.

Starts the app's server on the real library (as launch.sh does), then takes
a screenshot of Home at 16:10 (1280x800) and 4:3 (1024x768) in the Route C
web view (Qt's web engine, in a briefly visible window) and in a hidden Firefox (driven
the same way as the browser checks in tests/). Needs the Route C venv:

    spikes/webview/.venv-c/bin/python spikes/webview/screenshots.py OUT_DIR
"""

import base64
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tests.loading_screen_check import SIZES, Marionette  # noqa: E402

from common import free_port, start_server, stop_server  # noqa: E402

SETTLE_MS = 4000


def webview_shots(url, out):
    # A real (briefly visible) window: Qt's "offscreen" mode cannot use the
    # Deck's graphics chip and captures only the page background.
    from PyQt6.QtCore import QTimer, QUrl
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv[:1])
    queue = list(SIZES.items())
    view = QWebEngineView()

    def next_size():
        if not queue:
            app.quit()
            return
        name, (w, h) = queue.pop(0)
        view.resize(w, h)
        view.load(QUrl(url))
        QTimer.singleShot(SETTLE_MS, lambda: (
            view.grab().save(str(out / f"webview-{name}.png")), next_size()))

    view.show()
    next_size()
    app.exec()


def firefox_shots(url, out):
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        # The Firefox Flatpak only sees its own folder under HOME.
        profile = Path(tmp) / ".var/app/org.mozilla.firefox/data/spike-profile"
        profile.mkdir(parents=True)
        mport = free_port()
        (profile / "user.js").write_text(
            f'user_pref("marionette.port", {mport});\n'
            'user_pref("browser.shell.checkDefaultBrowser", false);\n'
            'user_pref("browser.aboutwelcome.enabled", false);\n')
        cmd = ["flatpak", "run", "org.mozilla.firefox", "--headless", "--marionette",
               "--no-remote", "-profile", str(profile), "about:blank"]
        ff = subprocess.Popen(cmd, env=dict(os.environ, HOME=tmp, MOZ_HEADLESS="1"),
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        m = Marionette(mport)
        try:
            for name, (w, h) in SIZES.items():
                m.send("WebDriver:SetWindowRect", {"width": w, "height": h})
                m.send("WebDriver:Navigate", {"url": url})
                time.sleep(SETTLE_MS / 1000)
                png = base64.b64decode(m.send("WebDriver:TakeScreenshot", {})["value"])
                (out / f"firefox-{name}.png").write_bytes(png)
        finally:
            try:
                m.send("Marionette:Quit", {"flags": ["eForceQuit"]})
            except (OSError, RuntimeError, ValueError):
                pass
            ff.terminate()
            ff.wait(timeout=15)


def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    server, url = start_server(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        firefox_shots(url, out)
        webview_shots(url, out)
    finally:
        stop_server(server)
    print(f"screenshots: {out}")


if __name__ == "__main__":
    main()
