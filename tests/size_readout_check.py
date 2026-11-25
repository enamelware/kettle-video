# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The size readout (the sizing spike) in a real, headless Firefox: the page as a
whole, at start. Not part of the unit tests: it needs Firefox.

Uses the Marionette helper from loading_screen_check.py and the server
from home_shell_check.py, with invented films. Cases, each a fresh start:

  on      "debug_size_readout": true: the launch log gets exactly one
          readout line, with the window's size in CSS pixels, the device
          pixel ratio, the screen's size and the zoom sentence, matching
          what the page measures; the library still opens as normal
  scaled  the same, with Firefox scaled to 125% as a scaled screen would
          (its zoom is reset when a page opens, so the scaling setting
          stands in for it; both reach the page the same way): it shows in
          the device pixel ratio
  off     setting missing: no readout line and the library opens as normal

Run from the repo root:  python3 tests/size_readout_check.py
"""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from backend import library_index, size_readout  # noqa: E402
from tests.home_shell_check import FILMS, start_server  # noqa: E402
from tests.loading_screen_check import Marionette, free_port  # noqa: E402
from tests.window_sizes import FIREFOX_FLAG, WINDOW, set_window  # noqa: E402

PAGE_JS = """
const loading = document.getElementById('loading');
return {
  library: !document.getElementById('library').hidden
           && (loading.hidden || getComputedStyle(loading).display === 'none'),
  sizes: {window_width: innerWidth, window_height: innerHeight, device_pixel_ratio: devicePixelRatio,
          screen_width: screen.width, screen_height: screen.height},
};
"""
ZOOM = 1.25  # Firefox scaled as a screen set to 125% would scale it


def readout_lines(log):
    return [line for line in log.getvalue().splitlines() if line.startswith("size readout:")]


def run_case(case, env, profile, check):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for rel in FILMS:
            (tmp / "Movies" / rel).parent.mkdir(parents=True, exist_ok=True)
            (tmp / "Movies" / rel).write_bytes(b"")
        settings = {"movies_path": str(tmp / "Movies"), "tv_path": str(tmp / "Movies"),
                    "mpv_command": "mpv", "mpv_args": [], "data_dir": str(tmp / "data")}
        if case != "off":
            settings["debug_size_readout"] = True
        roots = {"movies": settings["movies_path"], "tv": settings["tv_path"]}
        index = library_index.full_scan(roots, None, lambda done, total: None)
        library_index.save(Path(settings["data_dir"]) / library_index.FILE_NAME, index)
        log = io.StringIO()
        with contextlib.redirect_stdout(log):
            httpd, port = start_server("long", settings, tmp, [])
        mport = free_port()
        (profile / "user.js").write_text(
            f'user_pref("marionette.port", {mport});\n'
            'user_pref("browser.shell.checkDefaultBrowser", false);\n'
            'user_pref("browser.aboutwelcome.enabled", false);\n'
            + (f'user_pref("layout.css.devPixelsPerPx", "{ZOOM}");\n' if case == "scaled" else "")
        )
        cmd = ["--headless", "--marionette", FIREFOX_FLAG, "--no-remote", "-profile", str(profile), "about:blank"]
        ff = subprocess.Popen(
            ["firefox", *cmd] if shutil.which("firefox") else ["flatpak", "run", "org.mozilla.firefox", *cmd],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        m = None
        try:
            m = Marionette(mport)
            set_window(m, *WINDOW)
            with contextlib.redirect_stdout(log):
                m.send("WebDriver:Navigate", {"url": f"http://127.0.0.1:{port}/"})
                end = time.time() + 30
                s = m.js(PAGE_JS)
                while not (s["library"] and (case == "off" or readout_lines(log))) and time.time() < end:
                    time.sleep(0.2)
                    s = m.js(PAGE_JS)
                time.sleep(1)  # room for a second line, which must not come
            lines = readout_lines(log)
            check(f"{case}: the library opens as normal", s["library"], s)
            if case == "off":
                check("off: no readout line in the log", lines == [], lines)
                return
            check(f"{case}: exactly one readout line", len(lines) == 1, lines)
            check(f"{case}: the line holds what the page measures: {lines[:1]}",
                  lines == [size_readout.line(s["sizes"])], s["sizes"])
            text = lines[0] if lines else ""
            check(f"{case}: all four values are named",
                  all(part in text for part in ("window ", "device pixel ratio ", "screen ", "Firefox zoom: ")), text)
            if case == "on":
                check("on: the window is the check's window, at ratio 1",
                      (s["sizes"]["window_width"], s["sizes"]["window_height"]) == WINDOW
                      and s["sizes"]["device_pixel_ratio"] == 1, s["sizes"])
            else:
                check(f"scaled: Firefox scaled to {ZOOM:.0%} shows in the device pixel ratio",
                      abs(s["sizes"]["device_pixel_ratio"] - ZOOM) < 0.01, s["sizes"])
        finally:
            if m is not None:
                try:
                    m.send("Marionette:Quit", {"flags": ["eForceQuit"]})
                except (OSError, RuntimeError, ValueError):
                    pass
            ff.terminate()
            try:
                ff.wait(timeout=15)
            except subprocess.TimeoutExpired:
                ff.kill()
            httpd.shutdown()
            httpd.server_close()


def main():
    results = []

    def check(text, ok, detail=None):
        results.append((text if ok or detail is None else f"{text}: {json.dumps(detail, default=str)}", ok))

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        home = Path(tmp) / "home"
        env = dict(os.environ, HOME=str(home), MOZ_HEADLESS="1")
        for case in ("on", "scaled", "off"):
            profile = home / f".var/app/org.mozilla.firefox/data/check-profile-readout-{case}"
            profile.mkdir(parents=True)
            try:
                run_case(case, env, profile, check)
            except Exception as exc:
                results.append((f"{case}: could not run ({exc!r})", False))
    for text, ok in results:
        print(f"{'ok  ' if ok else 'FAIL'} {text}")
    failures = sum(not ok for _, ok in results)
    print("all good" if not failures else f"{failures} problem(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
