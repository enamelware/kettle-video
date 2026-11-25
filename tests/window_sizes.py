# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta
"""The window sizes the browser checks use (the responsive layout work).

No layout is tied to a screen size, a device or an aspect ratio, so the
checks run across a range of widths, labelled by width only: from
Enamel's smallest supported box (20rem wide by 15rem tall, 320 by 240 at
the browser's normal font size) to very wide. None of them is a target.
"""

import math
import time

SIZES = {
    "w320": (320, 240),
    "w640": (640, 720),
    "w1024": (1024, 768),
    "w1280": (1280, 800),
    "w1920": (1920, 1080),
    "w2560": (2560, 1080),
}

# The window a check uses when the size doesn't matter to what it checks.
WINDOW = SIZES["w1280"]

# Headless Firefox won't make a window narrower than this many CSS pixels.
FIREFOX_MIN_WIDTH = 500
# Firefox must be started with this flag for set_zoom (Marionette's chrome
# context); every check that starts Firefox passes it.
FIREFOX_FLAG = "--remote-allow-system-access"


def set_zoom(m, zoom):
    """The browser's own zoom (as Ctrl and + does) for the open tab, kept
    while the tab moves between pages."""
    m.send("Marionette:SetContext", {"value": "chrome"})
    try:
        m.js("Services.prefs.setBoolPref('browser.zoom.siteSpecific', false);"
             f"gBrowser.selectedBrowser.fullZoom = {zoom}; return true;")
    finally:
        m.send("Marionette:SetContext", {"value": "content"})


def set_window(m, w, h):
    """Make the page itself w by h CSS pixels, as in kiosk mode. Narrower
    than Firefox allows a window to be, the page is zoomed in, so it lays out
    w CSS pixels wide in a wider window: what a screen that narrow shows.
    Opening another page resets the zoom, so call this after opening it."""
    set_zoom(m, 1 if w >= FIREFOX_MIN_WIDTH else (FIREFOX_MIN_WIDTH + 20) / w)
    for _ in range(6):
        inner = m.js("return [window.innerWidth, window.innerHeight, window.devicePixelRatio];")
        if inner[:2] == [w, h]:
            return
        rect = m.send("WebDriver:GetWindowRect")
        rect = rect.get("value", rect)
        # Zoomed, one CSS pixel is several window pixels and the page's size
        # is rounded down, so a short step is rounded up.
        step = [math.copysign(math.ceil(abs(want - got) * inner[2]), want - got)
                for want, got in zip((w, h), inner)]
        m.send("WebDriver:SetWindowRect", {"width": rect["width"] + int(step[0]),
                                           "height": rect["height"] + int(step[1])})
        time.sleep(0.3)
