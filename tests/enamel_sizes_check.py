# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Enamel's sizes on Home (the Enamel 0.8.0 upgrade), in a real, headless Firefox.
Not part of the unit tests: it needs Firefox and takes about half a minute.

Screen: Home, with 40 invented films and the invented shows. At every window
width in tests/window_sizes.py, at the browser's normal font size, it checks
that the app draws Enamel's sizes, Steam's baseline: a list row at
least 64 px tall with body text 24 px (growing by at most a fifth on very
wide pages), the Menu button at least a button's 60 px, its row a button
plus the tight space above and below (68 px on one line; since the Home polish there is
no bar behind it and no --shell-bar-height), a tab at least the 44 px touch target
with small text, the hint bar at least 60 px, and the Continue watching row's
gap Enamel's shelf gap (20 px). Then it sets Enamel's one root size,
--en-root-size, to 112.5% and checks that the rows, the letter strip and the
bars all grow by an eighth with it: the app's own sizes follow the root size
(rem or tokens, never fixed pixels). The app itself never sets the root size.
Since Enamel 0.11.0 (the Enamel 0.11.0 upgrade) the root size works through zoom: the root font
size stays the viewer's own 16 px, and the text is checked as drawn.

Screenshots go to the folder given as the first argument.

Run from the repo root:  python3 tests/enamel_sizes_check.py [screenshot-dir]
"""

import base64
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

from backend import library_index  # noqa: E402
from tests.home_shell_check import DOWN, FILMS, start_server  # noqa: E402
from tests.loading_screen_check import Marionette, free_port  # noqa: E402
from tests.window_sizes import SIZES, WINDOW, set_window, FIREFOX_FLAG  # noqa: E402
from tests.test_parsed_library import TV_FILES  # noqa: E402


STATE_JS = """
const shown = (el) => !!el && el.getClientRects().length > 0 && !el.closest('[hidden]');
const h = (el) => el.getBoundingClientRect().height;
const px = (el, prop) => parseFloat(getComputedStyle(el)[prop]);
const root = document.documentElement;
const rows = [...document.querySelectorAll('#library .file-row.en-row')].filter(shown);
const bar = document.getElementById('action-bar');
const menu = bar.querySelector('.en-button');
const tabs = [...document.querySelectorAll('#tab-strip .tab')];
const strip = document.querySelector('.letter-strip');
return {
  W: root.clientWidth,
  rootSize: getComputedStyle(root).getPropertyValue('--en-root-size').trim(),
  rootFont: px(root, 'fontSize'),
  rows: rows.length,
  rowMin: Math.min(...rows.map(h)),
  rowText: px(rows[0], 'fontSize'),
  // The text as drawn: since Enamel 0.11.0 (the Enamel 0.11.0 upgrade) --en-root-size scales
  // through zoom, which the computed font size doesn't include.
  rowTextDrawn: px(rows[0], 'fontSize') * (rows[0].currentCSSZoom || 1),
  menu: h(menu),
  bar: h(bar),
  tabMin: Math.min(...tabs.map(h)),
  tabText: px(tabs[0], 'fontSize'),
  hint: h(document.getElementById('hint-bar')),
  shelfGap: getComputedStyle(document.querySelector('.continue-row')).columnGap,
  letterStrip: strip && shown(strip) ? strip.getBoundingClientRect().width : null,
};
"""

def check_sizes(m, shots_dir, check):
    for size, (w, h) in SIZES.items():
        set_window(m, w, h)
        time.sleep(0.4)
        (shots_dir / f"sizes-{size}.png").write_bytes(
            base64.b64decode(m.send("WebDriver:TakeScreenshot", {})["value"]))
        s = m.js(STATE_JS)
        # Text grows by at most a fifth on pages wider than 100rem.
        grows = s["W"] > 1600
        body_ok = 24 <= s["rowText"] <= 28.8 + 0.1 if grows else abs(s["rowText"] - 24) < 0.1
        small_ok = 18.6 <= s["tabText"] <= 22.4 + 0.1 if grows else abs(s["tabText"] - 56 / 3) < 0.1
        check(f"{size}: the app leaves Enamel's root size alone (100%, 16 px)",
              s["rootSize"] == "100%" and s["rootFont"] == 16, s)
        check(f"{size}: list rows at least 64 px ({s['rowMin']:.1f}), body text {s['rowText']:.1f} px",
              s["rows"] > 0 and s["rowMin"] >= 64 - 0.5 and body_ok, s)
        check(f"{size}: the Menu button at least a button's 60 px ({s['menu']:.1f})", s["menu"] >= 60 - 0.5, s)
        check(f"{size}: the Menu button's row is a button plus its padding, 68 px ({s['bar']:.1f})",
              abs(s["bar"] - 68) < 1, s)
        check(f"{size}: tabs at least the 44 px touch target ({s['tabMin']:.1f}), small text {s['tabText']:.2f} px",
              s["tabMin"] >= 44 - 0.5 and small_ok, s)
        check(f"{size}: the hint bar at least 60 px ({s['hint']:.1f})", s["hint"] >= 60 - 0.5, s)
        check(f"{size}: the Continue watching row's gap is Enamel's shelf gap, 20 px", s["shelfGap"] == "20px", s)


def check_root_size(m, shots_dir, check):
    """Enamel's one root size scales the app's own sizes with the components."""
    set_window(m, *WINDOW)
    time.sleep(0.4)
    before = m.js(STATE_JS)
    m.js("document.documentElement.style.setProperty('--en-root-size', '112.5%'); return true;")
    time.sleep(0.6)
    after = m.js(STATE_JS)
    (shots_dir / "sizes-root-112.png").write_bytes(
        base64.b64decode(m.send("WebDriver:TakeScreenshot", {})["value"]))
    m.js("document.documentElement.style.removeProperty('--en-root-size'); return true;")

    def grew(key):
        return before[key] and after[key] and abs(after[key] / before[key] - 1.125) < 0.02

    # Since Enamel 0.11.0 (the Enamel 0.11.0 upgrade) the root size scales everything through zoom
    # and never touches the root font size, which stays the viewer's own.
    check("root size 112.5%: the page's root font stays the viewer's 16 px", after["rootFont"] == 16, after)
    for key, what in (("rowMin", "list rows"), ("rowTextDrawn", "body text as drawn"), ("menu", "the Menu button"),
                      ("bar", "the Menu button's row"),
                      ("hint", "the hint bar"), ("letterStrip", "the letter strip")):
        check(f"root size 112.5%: {what}, an eighth bigger ({before[key]} to {after[key]})",
              grew(key), [before, after])


def run(env, profile, shots_dir, check):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for base, files in ((tmp / "Movies", FILMS), (tmp / "TV Shows", TV_FILES)):
            for rel in files:
                (base / rel).parent.mkdir(parents=True, exist_ok=True)
                (base / rel).write_bytes(b"")
        settings = {"movies_path": str(tmp / "Movies"), "tv_path": str(tmp / "TV Shows"),
                    "mpv_command": "mpv", "mpv_args": [], "data_dir": str(tmp / "data")}
        roots = {"movies": settings["movies_path"], "tv": settings["tv_path"]}
        index = library_index.full_scan(roots, None, lambda done, total: None)
        library_index.save(Path(settings["data_dir"]) / library_index.FILE_NAME, index)
        httpd, port = start_server("long", settings, tmp, [])
        mport = free_port()
        (profile / "user.js").write_text(
            f'user_pref("marionette.port", {mport});\n'
            'user_pref("browser.shell.checkDefaultBrowser", false);\n'
            'user_pref("browser.aboutwelcome.enabled", false);\n'
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
            m.send("WebDriver:Navigate", {"url": f"http://127.0.0.1:{port}/"})
            end = time.time() + 30
            while time.time() < end and not m.js(
                    "return !!document.querySelector('#library .file-row') && document.getElementById('loading').hidden;"):
                time.sleep(0.2)
            m.press(DOWN)  # onto the first film, so the letter strip shows
            time.sleep(0.3)
            check_sizes(m, shots_dir, check)
            check_root_size(m, shots_dir, check)
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
    shots_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="enamel-sizes-"))
    shots_dir.mkdir(parents=True, exist_ok=True)
    results = []

    def check(text, ok, detail=None):
        results.append((text if ok or detail is None else f"{text}: {json.dumps(detail, default=str)}", ok))

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        home = Path(tmp) / "home"
        env = dict(os.environ, HOME=str(home), MOZ_HEADLESS="1")
        profile = home / ".var/app/org.mozilla.firefox/data/check-profile-sizes"
        profile.mkdir(parents=True)
        try:
            run(env, profile, shots_dir, check)
        except Exception as exc:
            results.append((f"could not run ({exc!r})", False))
    for text, ok in results:
        print(f"{'ok  ' if ok else 'FAIL'} {text}")
    print(f"screenshots: {shots_dir}")
    failures = sum(not ok for _, ok in results)
    print("all good" if not failures else f"{failures} problem(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
