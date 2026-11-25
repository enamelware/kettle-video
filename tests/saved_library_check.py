# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Drive the saved library screens in a real, headless Firefox (the saved library work).
Not part of the unit tests: it needs Firefox and takes about a minute.

Invented titles in a temporary folder, and a temporary saved library. Uses
the Marionette helper from loading_screen_check.py; playing is faked. Steps:
first launch, where the result screen scans by itself with its progress line (the first scan screen), a rescan (from Home's
menu and with r; since the Home actions work its progress and result are in a toast), a
relaunch that shows the saved library without scanning, a folder taken away
("Folder not available"), a failed scan, and a deleted saved library.
Since the Home shell work the films and the shows are in two tabs: "rows" are the
Movies tab's, and the Movies tab has the focus at launch and after a scan.

Screenshots at each window width go to the folder given as the first argument.

Run from the repo root:  python3 tests/saved_library_check.py [screenshot-dir]
"""

import base64
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
from tests.loading_screen_check import UI_DIR, Marionette, free_port  # noqa: E402
from tests.window_sizes import SIZES, WINDOW, set_window, FIREFOX_FLAG  # noqa: E402
from tests.test_parsed_library import MOVIE_FILES, TV_FILES  # noqa: E402

SOURCE_DELAY_S = 1.5  # each folder's scan is slowed down so progress shows
ENTER, DOWN = "", ""

STATE_JS = """
const visible = (el) => el && !el.hidden && getComputedStyle(el).display !== 'none';
const active = document.activeElement;
const shown = [...document.querySelectorAll('.file-row, .result-action')].filter(r => visible(r) && !r.closest('[hidden]'));
const section = (s) => document.querySelector(`.source[data-source="${s}"] [data-role="status"]`);
const ob = document.getElementById('onboarding');
const words = ob.querySelector('[data-role="scan-words"]');
return {
  loading: visible(document.getElementById('loading')),
  firstScan: visible(ob) && !!ob.dataset.result && ob.dataset.result !== 'reading',
  title: ob.querySelector('[data-role="title"]').textContent,
  progress: visible(words) ? words.textContent : null,
  library: visible(document.getElementById('library')),
  // Since the Home actions work a rescan shows in Enamel's toast: "Scanning…", then the result.
  toast: visible(document.getElementById('scan-toast')) ? document.getElementById('scan-toast').textContent.trim() : null,
  rescanning: visible(document.getElementById('scan-toast')) && document.getElementById('scan-toast').textContent.trim().startsWith('Scanning'),
  banner: visible(document.getElementById('error-banner')) ? document.getElementById('error-banner').textContent : null,
  rows: shown.map(r => (r.querySelector('.row-title') || r).textContent),
  kinds: shown.map(r => r.dataset.kind),
  subtitles: shown.map(r => (r.querySelector('.row-subtitle') || {}).textContent || ''),
  focusedIndex: shown.indexOf(active),
  // Focus shows on Enamel's rows (the third design system step) as the lift to the control
  // surface and, on the result screen's primary button (the first scan screen), as Enamel's
  // focus fill (cream since 0.11.0, the Enamel 0.11.0 upgrade).
  ringVisible: !!active && (() => { const colour = (token) => { const p = document.createElement('div'); p.style.background = `var(${token})`; document.body.appendChild(p); const c = getComputedStyle(p).backgroundColor; p.remove(); return c; };
    const bg = getComputedStyle(active).backgroundColor;
    return (active.classList.contains('en-row') && bg === colour('--en-surface-control'))
      || (active.classList.contains('en-button--primary') && bg === colour('--en-focus-fill')); })(),
  movieStatus: visible(section('movies')) ? section('movies').textContent : null,
  movieStatusIsError: section('movies').dataset.state === 'error',
  tvStatus: visible(section('tv')) ? section('tv').textContent : null,
  overflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth,
  focusedTab: active && active.dataset ? active.dataset.tab || null : null,
};
"""


class App:
    """One server run, like one launch of the app."""

    def __init__(self, settings, logs_dir, played, scans):
        httpd_ref = {}
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        self.port = self.httpd.server_address[1]
        base = make_handler(UI_DIR, logs_dir, settings, httpd_ref, self.port)

        class Handler(base):
            def log_message(self, format, *args):
                pass

            def _handle_mpv_status(self):
                self._send_json(HTTPStatus.OK, {"available": True})

            def _handle_play(self):
                root = settings["movies_path"]
                if not os.path.isdir(root):
                    return super()._handle_play()  # the real "Folder not available" answer
                played.append(self._read_json_body())
                self._send_json(HTTPStatus.OK, {"started": True})

        self.httpd.RequestHandlerClass = Handler
        httpd_ref["server"] = self.httpd
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def wait_state(m, predicate, timeout):
    end = time.time() + timeout
    while time.time() < end:
        state = m.js(STATE_JS)
        if predicate(state):
            return state
        time.sleep(0.2)
    return m.js(STATE_JS)


def rescan_done(s):
    """The scan is over and the new library is on screen: the toast shows
    the result, which comes once the lists are redrawn (the Home actions work)."""
    return bool(s["toast"]) and not s["rescanning"]


def shot(m, shots_dir, name):
    for size, (w, h) in SIZES.items():
        set_window(m, w, h)
        time.sleep(0.4)
        overflow = m.js(STATE_JS)["overflowX"]
        (shots_dir / f"{name}-{size}.png").write_bytes(
            base64.b64decode(m.send("WebDriver:TakeScreenshot", {})["value"]))
        yield size, overflow
    set_window(m, *WINDOW)


def run(m, tmp, shots_dir, check):
    movies, tv, data = tmp / "Movies", tmp / "TV Shows", tmp / "data"
    for base, files in ((movies, MOVIE_FILES), (tv, TV_FILES)):
        for rel in files:
            (base / rel).parent.mkdir(parents=True, exist_ok=True)
            (base / rel).write_bytes(b"")
    settings = {"movies_path": str(movies), "tv_path": str(tv), "mpv_command": "mpv", "mpv_args": [],
                "resume": True, "keep_awake": False, "data_dir": str(data)}
    played, scans = [], []

    real_scan_source = library_index.scan_source
    real_full_scan = library_index.full_scan

    def slow_scan_source(*args):
        time.sleep(SOURCE_DELAY_S)
        return real_scan_source(*args)

    def counted_full_scan(*args):
        scans.append(time.time())
        return real_full_scan(*args)

    library_index.scan_source = slow_scan_source
    library_index.full_scan = counted_full_scan

    def launch():
        app = App(settings, tmp, played, scans)
        m.send("WebDriver:Navigate", {"url": f"http://127.0.0.1:{app.port}/"})
        return app

    # 1. First launch, folders set and no saved library: the scan starts by
    # itself, on the result screen (the first scan screen).
    app = launch()
    s = wait_state(m, lambda s: s["progress"] and " of " in s["progress"], 30)
    check(f"scan: progress line, with nothing to press: {s['progress']!r}",
          s["progress"] == f"Scanning… 0 of {len(MOVIE_FILES) + len(TV_FILES)}" and s["rows"] == [], s)
    for size, overflow in shot(m, shots_dir, "first-scan-progress"):
        check(f"scan: progress fits at {size}", not overflow)
    s = wait_state(m, lambda s: s["progress"] != f"Scanning… 0 of {len(MOVIE_FILES) + len(TV_FILES)}", 5)
    check(f"scan: progress moves on: {s['progress']!r}", s["progress"] in (
        f"Scanning… {len(MOVIE_FILES)} of {len(MOVIE_FILES) + len(TV_FILES)}", None), s["progress"])
    s = wait_state(m, lambda s: s["firstScan"], 15)
    check("first launch: then the result, with Open my library focused and showing it",
          s["title"] == "Your library is ready" and s["rows"] == ["Open my library", "Change folders"]
          and s["focusedIndex"] == 0 and s["ringVisible"], s)
    for size, overflow in shot(m, shots_dir, "first-launch"):
        check(f"first launch: fits at {size}", not overflow)

    # 2. Open my library.
    m.press(ENTER)
    s = wait_state(m, lambda s: s["library"], 15)
    check("scan: then the library (no Rescan row since the Home actions work)", s["rows"] == ["Example Film", "Other Movie"], s)
    check("scan: the Movies tab has the focus", s["focusedTab"] == "movies", s)
    check("scan: saved to the data folder", (data / "library.json").is_file())
    for size, overflow in shot(m, shots_dir, "library"):
        check(f"library: fits at {size}", not overflow)

    # 3. Rescan from Home's menu (Start, then A on Rescan library): the list
    # stays, the toast shows the progress, the focus stays on the tab.
    m.press("m")
    time.sleep(0.3)
    m.press(ENTER)
    s = wait_state(m, lambda s: s["rescanning"], 3)
    check(f"rescan (menu): the toast shows {s['toast']!r} and the list stays on screen",
          s["rescanning"] and len(s["rows"]) == 2 and s["library"], s)
    for size, overflow in shot(m, shots_dir, "rescan-progress"):
        check(f"rescan: fits at {size}", not overflow)
    s = wait_state(m, rescan_done, 15)
    check(f"rescan (menu): then {s['toast']!r}, the focus still on the Movies tab",
          s["toast"] == "No changes" and s["focusedTab"] == "movies", s)

    # 4. r from a film row does the same, and keeps the focus on that film.
    m.press(DOWN)
    m.press(DOWN)
    m.press("r")
    s = wait_state(m, lambda s: s["rescanning"], 6)
    check("rescan (r): the toast says Scanning…, list stays", s["rescanning"] and len(s["rows"]) == 2, s)
    s = wait_state(m, rescan_done, 15)
    check("rescan (r): afterwards the focus is still on the same film", s["focusedIndex"] == 1, s)
    count = len(scans)

    # 5. Relaunch: the library appears at once, no scan.
    app.stop()
    app = launch()
    start = time.time()
    s = wait_state(m, lambda s: s["library"] and not s["loading"], 30)
    check(f"relaunch: the saved library shows without a scan ({time.time() - start:.1f} s, "
          "including the 2 s loading screen)", len(scans) == count and len(s["rows"]) == 2, s)

    # 6. A folder taken away (like the card out).
    shutil.move(str(movies), str(tmp / "Movies-away"))
    app.stop()
    app = launch()
    s = wait_state(m, lambda s: s["library"] and not s["loading"], 30)
    check(f"card out: muted {s['movieStatus']!r} under Movies, items still listed",
          s["movieStatus"] == "Folder not available" and not s["movieStatusIsError"]
          and s["rows"] == ["Example Film", "Other Movie"], s)
    for size, overflow in shot(m, shots_dir, "folder-not-available"):
        check(f"card out: fits at {size}", not overflow)
    m.press(DOWN)
    m.press(ENTER)  # on the first film
    s = wait_state(m, lambda s: s["banner"], 3)
    check(f"card out: playing shows {s['banner']!r}", s["banner"] == "Folder not available" and played == [], s)
    m.press("r")
    s = wait_state(m, lambda s: s["toast"] == "Movies folder not available", 15)
    check(f"card out: a rescan removes nothing, the toast says {s['toast']!r}",
          s["rows"] == ["Example Film", "Other Movie"] and s["toast"] == "Movies folder not available", s)
    shutil.move(str(tmp / "Movies-away"), str(movies))

    # 7. A failed scan keeps the saved library.
    def failing_full_scan(*args):
        raise OSError("invented failure")

    library_index.full_scan = failing_full_scan
    m.press("r")
    s = wait_state(m, lambda s: s["toast"] and s["toast"].startswith("Couldn't scan"), 8)
    check(f"failed scan: the toast says {s['toast']!r}, library still there",
          s["toast"] == "Couldn't scan the library. The saved library is unchanged." and len(s["rows"]) == 2, s)
    library_index.full_scan = counted_full_scan

    # 8. Deleting the saved library brings the first launch back.
    app.stop()
    (data / "library.json").unlink()
    app = launch()
    s = wait_state(m, lambda s: s["firstScan"] and not s["loading"], 30)
    check("deleted saved library: the scan and the result again", s["rows"][:1] == ["Open my library"], s)
    app.stop()
    library_index.scan_source = real_scan_source
    library_index.full_scan = real_full_scan


def main(steps=run, prefix="saved-library-"):
    """Start a headless Firefox and drive `steps` in it. missing_items_check.py
    (the quick rescan and Remove work) reuses this with its own steps."""
    shots_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix=prefix))
    shots_dir.mkdir(parents=True, exist_ok=True)
    results = []

    def check(text, ok, detail=None):
        results.append((text if ok or detail is None else f"{text}: {json.dumps(detail, default=str)}", ok))

    # Firefox can still be writing its profile as it exits; don't fail on that.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        tmp = Path(tmp)
        home = tmp / "home"
        profile = home / ".var/app/org.mozilla.firefox/data/check-profile"
        profile.mkdir(parents=True)
        env = dict(os.environ, HOME=str(home), MOZ_HEADLESS="1")
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
            work = tmp / "work"
            work.mkdir()
            steps(m, work, shots_dir, check)
        except Exception as exc:
            results.append((f"could not finish ({exc!r})", False))
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
    for text, ok in results:
        print(f"{'ok  ' if ok else 'FAIL'} {text}")
    print(f"screenshots: {shots_dir}")
    failures = sum(not ok for _, ok in results)
    print("all good" if not failures else f"{failures} problem(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
