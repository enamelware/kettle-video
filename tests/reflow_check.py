# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Two reflow behaviours of the responsive layout work in a real, headless Firefox. Not part
of the unit tests: it needs Firefox and takes about half a minute.

Uses the Marionette helper from loading_screen_check.py and the invented
films of home_shell_check.py; playing is faked. Steps:

  wrap     a narrow, tall window (320 wide, 720 tall): the two tabs wrap onto
           two lines, the app keeps --tab-strip-height at the strip's real
           height, the strip stays pinned at the top of the window (under the
           docked action bar from the Home actions work until the Home polish), a row moved to
           (down, then back up) is never under the second line of tabs, and
           the letter strip starts below the tabs
  message  a short window (640 by 400) with the page at its top and the
           focus on the lowest row wholly above the hint bar: an error, then
           "Playing…" appears above the lists and pushes them down; the
           focused row must still be wholly on screen, clear of the tabs and
           the hint bar. A control step first shows the error without the
           app's help, to prove the push would put the row under the hint
           bar. Since the Home actions work a rescan (r) shows in Enamel's toast,
           which pushes nothing: the focused row stays exactly where it was

Labelled by window width only (tests/window_sizes.py).

Run from the repo root:  python3 tests/reflow_check.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from backend import library_index  # noqa: E402
from backend.server import make_handler  # noqa: E402
from tests.home_shell_check import FILMS  # noqa: E402
from tests.loading_screen_check import UI_DIR, Marionette, free_port  # noqa: E402
from tests.window_sizes import FIREFOX_FLAG, WINDOW, set_window  # noqa: E402
from tests.test_parsed_library import TV_FILES  # noqa: E402

ENTER, UP, DOWN = "", "", ""
PLAYING_S = 4

STATE_JS = """
const visible = (el) => el && !el.hidden && getComputedStyle(el).display !== 'none' && !el.closest('[hidden]');
const box = (el) => { const r = el.getBoundingClientRect(); return {top: r.top, bottom: r.bottom, left: r.left, right: r.right, height: r.height}; };
const strip = document.getElementById('tab-strip');
const letters = document.querySelector('.source[data-source="movies"] [data-role="letters"]');
const rows = [...document.querySelectorAll('#library .file-row')].filter(visible);
const active = document.activeElement;
const hintTop = box(document.getElementById('hint-bar')).top;
return {
  ready: visible(document.getElementById('library')) && !visible(document.getElementById('loading')),
  viewport: [window.innerWidth, window.innerHeight],
  scrollY: window.scrollY,
  top: box(document.getElementById('action-bar')),
  strip: box(strip),
  tabTops: [...strip.querySelectorAll('.tab')].map(t => Math.round(t.getBoundingClientRect().top)),
  tabStripVar: getComputedStyle(document.documentElement).getPropertyValue('--tab-strip-height').trim(),
  letters: visible(letters) ? box(letters) : null,
  hintTop,
  rowCount: rows.length,
  // The lowest row wholly above the hint bar, in the keyboard's order.
  // A row keeps its scroll margin clear of the bars when moved to, so that
  // counts too (since the Home actions work the taller bar leaves rows closer to the edge).
  lowestInView: rows.reduce((last, r, i) => { const margin = parseFloat(getComputedStyle(r).scrollMarginBottom) || 0;
    return box(r).bottom + margin <= hintTop + 0.5 && box(r).top >= box(strip).bottom - 0.5 ? i : last; }, -1),
  focusedIndex: rows.indexOf(active),
  focused: rows.includes(active) ? box(active) : null,
  banner: visible(document.getElementById('error-banner')) ? box(document.getElementById('error-banner')) : null,
  playing: visible(document.getElementById('playing-status')) ? box(document.getElementById('playing-status')) : null,
  rescanning: visible(document.getElementById('scan-toast')) ? box(document.getElementById('scan-toast')) : null,
};
"""


def start_server(settings, logs_dir, mode):
    httpd_ref = {}
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
    port = httpd.server_address[1]
    base = make_handler(UI_DIR, logs_dir, settings, httpd_ref, port)
    playing_until = [0.0]
    scanning_until = [0.0]

    class Handler(base):
        def log_message(self, format, *args):
            pass

        def _handle_mpv_status(self):
            self._send_json(HTTPStatus.OK, {"available": True})

        def _handle_play(self):
            self._read_json_body()
            if mode[0] == "fail":
                return self._send_json(HTTPStatus.OK, {"started": False, "error": "Invented failure for the check."})
            playing_until[0] = time.time() + PLAYING_S
            self._send_json(HTTPStatus.OK, {"started": True})

        def _handle_status(self):
            state = "playing" if time.time() < playing_until[0] else "idle"
            self._send_json(HTTPStatus.OK, {"state": state, "last_result": {"ok": True}})

        # A rescan that stays "scanning" for a few seconds, so its toast can
        # be measured; then the real (idle) answer.
        def _handle_scan(self):
            scanning_until[0] = time.time() + PLAYING_S
            self._send_json(HTTPStatus.OK, {"started": True, "state": "scanning", "files_done": 1, "files_total": 4})

        def _handle_scan_status(self):
            if time.time() < scanning_until[0]:
                return self._send_json(HTTPStatus.OK, {"state": "scanning", "files_done": 1, "files_total": 4})
            return super()._handle_scan_status()

    httpd.RequestHandlerClass = Handler
    httpd_ref["server"] = httpd
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port


def wait(m, predicate, timeout):
    end = time.time() + timeout
    while time.time() < end:
        s = m.js(STATE_JS)
        if predicate(s):
            return s
        time.sleep(0.2)
    return m.js(STATE_JS)


def open_page(m, port, w, h):
    m.send("WebDriver:Navigate", {"url": f"http://127.0.0.1:{port}/"})
    set_window(m, w, h)  # after the page opens: opening a page resets the zoom
    return wait(m, lambda s: s["ready"], 30)


def px(value):
    try:
        return float(value.removesuffix("px"))
    except ValueError:
        return None


def check_wrap(m, port, check):
    size = "w320"
    s = open_page(m, port, 320, 720)
    check(f"wrap {size}: the page is 320x720", s["viewport"] == [320, 720], s["viewport"])
    check(f"wrap {size}: the two tabs sit on two lines", len(set(s["tabTops"])) == 2, s["tabTops"])
    var = px(s["tabStripVar"])
    check(f"wrap {size}: --tab-strip-height ({s['tabStripVar']}) follows the strip's real height ({s['strip']['height']:.1f})",
          var is not None and abs(var - s["strip"]["height"]) < 1, s)
    for _ in range(20):
        m.press(DOWN)
    for _ in range(6):
        m.press(UP)  # moving up, a row is scrolled to just under the tabs
    s = m.js(STATE_JS)
    check(f"wrap {size}: the page has scrolled, the Menu button with it, and the tab strip is pinned at the top",
          s["scrollY"] > 0 and abs(s["strip"]["top"]) < 1 and s["top"]["bottom"] <= 0.5, s)
    fb = s["focused"]
    check(f"wrap {size}: the row moved to is clear of both lines of tabs and of the hint bar",
          fb is not None and fb["top"] >= s["strip"]["bottom"] - 0.5 and fb["bottom"] <= s["hintTop"] + 0.5, s)
    if s["letters"] is not None:
        check(f"wrap {size}: the letter strip starts below both lines of tabs",
              s["letters"]["top"] >= s["strip"]["bottom"] - 1, s)


def focus_lowest(m, port, check, label):
    """Opens the page at 640 by 400 and moves the focus onto the lowest row
    wholly on screen, with the page still at its top."""
    s = open_page(m, port, 640, 400)
    target = s["lowestInView"]
    for _ in range(target + 1):  # the first Down goes from the tab to row 0
        m.press(DOWN)
    s = m.js(STATE_JS)
    check(f"{label} w640: the focus is on the lowest row on screen ({target}), page at its top",
          target >= 1 and s["focusedIndex"] == target and s["scrollY"] == 0, s)
    return s


def check_message(m, port, mode, check):
    # Control: the error shown without the app's help pushes the row under the hint bar.
    focus_lowest(m, port, check, "control")
    m.js("const b = document.getElementById('error-banner'); b.textContent = 'Invented failure for the check.';"
         " b.hidden = false; return true;")
    time.sleep(0.3)
    s = m.js(STATE_JS)
    pushed_under = s["focused"] is not None and s["focused"]["bottom"] > s["hintTop"] + 0.5
    check("control w640: shown on its own, the error pushes the focused row under the hint bar "
          "(so the steps below can tell)", pushed_under, s)

    for how, key in (("fail", "banner"), ("ok", "playing")):
        mode[0] = how
        focus_lowest(m, port, check, how)
        m.press(ENTER)
        s = wait(m, lambda s: s[key] is not None, 5)
        time.sleep(0.3)
        s = m.js(STATE_JS)
        what = "an error" if key == "banner" else "Playing…"
        fb = s["focused"]
        check(f"{how} w640: with {what} above the lists the focused row is still wholly on screen",
              s[key] is not None and fb is not None and s["focusedIndex"] >= 1
              and fb["top"] >= s["strip"]["bottom"] - 0.5 and fb["bottom"] <= s["hintTop"] + 0.5, s)
        if key == "playing":
            wait(m, lambda s: s["playing"] is None, PLAYING_S + 5)

    # A rescan (r on a film): since the Home actions work its progress is a toast, which pushes
    # nothing, so the focused row stays exactly where it was.
    mode[0] = "ok"
    before = focus_lowest(m, port, check, "rescan")
    m.press("r")
    s = wait(m, lambda s: s["rescanning"] is not None, 5)
    time.sleep(0.5)
    s = m.js(STATE_JS)
    fb = s["focused"]
    check("rescan w640: with the scan toast showing the focused row hasn't moved and is wholly on screen",
          s["rescanning"] is not None and fb is not None and s["focusedIndex"] == before["focusedIndex"]
          and abs(fb["top"] - before["focused"]["top"]) < 0.5 and fb["bottom"] <= s["hintTop"] + 0.5, s)
    wait(m, lambda s: s["rescanning"] is None, PLAYING_S + 5)


def main():
    results = []

    def check(text, ok, detail=None):
        results.append((text if ok or detail is None else f"{text}: {json.dumps(detail, default=str)}", ok))

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
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
        mode = ["ok"]
        httpd, port = start_server(settings, tmp, mode)
        home = tmp / "home"
        profile = home / ".var/app/org.mozilla.firefox/data/check-profile-reflow"
        profile.mkdir(parents=True)
        mport = free_port()
        (profile / "user.js").write_text(
            f'user_pref("marionette.port", {mport});\n'
            'user_pref("browser.shell.checkDefaultBrowser", false);\n'
            'user_pref("browser.aboutwelcome.enabled", false);\n'
        )
        env = dict(os.environ, HOME=str(home), MOZ_HEADLESS="1")
        cmd = ["--headless", "--marionette", FIREFOX_FLAG, "--no-remote", "-profile", str(profile), "about:blank"]
        ff = subprocess.Popen(
            ["firefox", *cmd] if shutil.which("firefox") else ["flatpak", "run", "org.mozilla.firefox", *cmd],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        m = None
        try:
            m = Marionette(mport)
            set_window(m, *WINDOW)
            for step in (lambda: check_wrap(m, port, check), lambda: check_message(m, port, mode, check)):
                try:
                    step()
                except Exception as exc:  # report and carry on with the next step
                    results.append((f"could not run a step ({exc!r})", False))
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
    for text, ok in results:
        print(f"{'ok  ' if ok else 'FAIL'} {text}")
    failures = sum(not ok for _, ok in results)
    print("all good" if not failures else f"{failures} problem(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
