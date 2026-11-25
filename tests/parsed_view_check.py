# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Drive the parsed library view in a real, headless Firefox (the parsed library view).
Not part of the unit tests: it needs Firefox and takes about half a minute.

Since the Home shell work (Home shell) the films and the shows are in two tabs: the
Movies tab has the focus at launch, Down goes into its list, and Right on
the tabs shows the TV Shows tab. "rows" below are the
rows of the tab on screen.

Uses the Marionette helper from loading_screen_check.py. Playing is faked
(the request is recorded, mpv never starts). Since the saved library work each case
starts with no saved library (a temporary data folder), so the view case
first presses Open my library. Since the Home actions work a rescan shows in a toast
(tests/home_actions_check.py and tests/saved_library_check.py cover it). Cases:

  view      invented titles: rows, focus, keys, episode list, d, r, back
  fallback  the parsed answer says ok false: the sentence and the plain list
  real      the real folders from settings.json (read-only)

Screenshots at each window width go to the folder given as the first argument.

Run from the repo root:  python3 tests/parsed_view_check.py [screenshot-dir]
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
from backend.settings import load_settings  # noqa: E402
from tests.loading_screen_check import UI_DIR, Marionette, free_port  # noqa: E402
from tests.window_sizes import SIZES, WINDOW, set_window, FIREFOX_FLAG  # noqa: E402
from tests.test_parsed_library import MOVIE_FILES, TV_FILES  # noqa: E402

RESCAN_DELAY_S = 3

STATE_JS = """
const visible = (el) => el && !el.hidden && getComputedStyle(el).display !== 'none';
const active = document.activeElement;
const shown = [...document.querySelectorAll('.file-row, .result-action')].filter(r => visible(r) && !r.closest('[hidden]'));
const focusable = [...document.querySelectorAll('*')].filter(el => el.tabIndex >= 0);
return {
  loading: visible(document.getElementById('loading')),
  library: visible(document.getElementById('library')),
  episodes: visible(document.getElementById('episodes')),
  // Since the Home actions work a rescan shows in Enamel's toast.
  toast: visible(document.getElementById('scan-toast')) ? document.getElementById('scan-toast').textContent.trim() : null,
  rescanning: visible(document.getElementById('scan-toast')) && document.getElementById('scan-toast').textContent.trim().startsWith('Scanning'),
  banner: visible(document.getElementById('error-banner')) ? document.getElementById('error-banner').textContent : null,
  rows: shown.map(r => r.querySelector('.row-line') ? r.querySelector('.row-line').innerText.replace(/\\s+/g, ' ') : r.textContent),
  subtitles: shown.map(r => (r.querySelector('.row-subtitle') || {}).textContent || ''),
  focusedIndex: shown.indexOf(active),
  focusedKind: active && active.dataset ? active.dataset.kind || null : null,
  // Tabs (Enamel's, the second design system step) draw their ring with an outline; Enamel's
  // rows (the third design system step) show focus by lifting to the control surface; rows that
  // keep the app's look draw a ring with a shadow.
  ringVisible: active && (getComputedStyle(active).boxShadow !== 'none' || getComputedStyle(active).outlineStyle !== 'none'
    || (active.classList.contains('en-row') && getComputedStyle(active).backgroundColor === (() => { const p = document.createElement('div'); p.style.background = 'var(--en-surface-control)'; document.body.appendChild(p); const c = getComputedStyle(p).backgroundColor; p.remove(); return c; })())),
  focusableOutsideRows: focusable.length,
  headings: [...document.querySelectorAll('#episodes h3')].map(h => h.textContent),
  showTitle: document.querySelector('[data-role="show-title"]').textContent,
  pathsShown: [...document.querySelectorAll('.row-path')].filter(p => visible(p) && !p.closest('[hidden]')).map(p => p.textContent),
  overflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth,
  focusedTab: active && active.dataset ? active.dataset.tab || null : null,
  tabs: [...document.querySelectorAll('#tab-strip .tab')].map(t => t.innerText.replace(/\\s+/g, ' ').trim()),
  selectedTab: (document.querySelector('#tab-strip .tab[aria-selected="true"]') || {dataset: {}}).dataset.tab || null,
  backHint: document.querySelector('#hint-bar [data-role="back"]').textContent,
};
"""


def start_server(case, settings, logs_dir, played):
    httpd_ref = {}
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
    port = httpd.server_address[1]
    base = make_handler(UI_DIR, logs_dir, settings, httpd_ref, port)

    class Handler(base):
        def log_message(self, format, *args):
            pass

        def _handle_mpv_status(self):
            self._send_json(HTTPStatus.OK, {"available": True})

        def _handle_parsed_library(self):
            if case == "fallback":
                return self._send_json(HTTPStatus.OK, {"ok": False, "error": "SENTENCE"})
            return super()._handle_parsed_library()

        def _handle_play(self):
            played.append(self._read_json_body())
            self._send_json(HTTPStatus.OK, {"started": True})

    httpd.RequestHandlerClass = Handler
    httpd_ref["server"] = httpd
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port


def wait_state(m, predicate, timeout):
    end = time.time() + timeout
    while time.time() < end:
        state = m.js(STATE_JS)
        if predicate(state):
            return state
        time.sleep(0.2)
    return m.js(STATE_JS)


def shot(m, shots_dir, name):
    for size, (w, h) in SIZES.items():
        set_window(m, w, h)
        time.sleep(0.4)
        overflow = m.js(STATE_JS)["overflowX"]
        (shots_dir / f"{name}-{size}.png").write_bytes(
            base64.b64decode(m.send("WebDriver:TakeScreenshot", {})["value"]))
        yield size, overflow


def check_view(m, played, shots_dir, check):
    s = wait_state(m, lambda s: s["rows"][:1] == ["Open my library"] and not s["loading"], 30)
    check("view: first launch offers Scan my folders", s["rows"][:1] == ["Open my library"], s["rows"])
    m.press("\ue007")
    s = wait_state(m, lambda s: s["library"] and not s["loading"], 30)
    # Later scans are slowed down, so the toast's "Scanning…" can be seen.
    real_scan = library_index.full_scan
    library_index.full_scan = lambda *a: (time.sleep(RESCAN_DELAY_S), real_scan(*a))[1]
    check("view: the Movies tab has the focus, with both counts",
          s["focusedTab"] == "movies" and s["tabs"] == ["MOVIES 2", "TV SHOWS (BETA) 2"] and s["ringVisible"], s)
    # Since the Movies list work: the title, the year and "2 parts" on one line.
    check("view: the Movies tab lists the films", s["rows"] == ["Example Film 2001 2 parts", "Other Movie 1999"], s["rows"])
    check("view: films have no second line", s["subtitles"] == ["", ""], s["subtitles"])
    check("view: B says Quit on Home", s["backHint"] == "Quit", s["backHint"])
    m.press("\ue014")
    s = m.js(STATE_JS)
    check("view: Right shows the TV Shows tab, focus stays on the tabs",
          s["focusedTab"] == "tv" and s["selectedTab"] == "tv" and s["rows"] == ["Kiri Anime", "Test Show"], s)
    check("view: show subtitles", s["subtitles"] == ["flat, 3 episodes", "2 seasons, 3 episodes, 1 special"],
          s["subtitles"])
    m.press("\ue014")
    check("view: Right on the last tab changes nothing", m.js(STATE_JS)["focusedTab"] == "tv")
    m.press("\ue012")
    s = m.js(STATE_JS)
    check("view: Left goes back to the Movies tab", s["focusedTab"] == "movies" and s["rows"][0] == "Example Film 2001 2 parts", s)
    m.press("\ue015")  # into the list (no Rescan row since the Home actions work)
    m.settle()  # the row's lift fades in (Enamel 0.5.0, the Enamel 0.5.0 upgrade)
    s = m.js(STATE_JS)
    check("view: first film focused, ring drawn, nothing else focusable",
          s["focusedIndex"] == 0 and s["ringVisible"] and s["focusableOutsideRows"] == 0, s)
    for size, overflow in shot(m, shots_dir, "library"):
        check(f"view: library fits at {size} (no sideways scroll)", not overflow)

    m.press("\ue015")  # ArrowDown
    m.press("\ue013")  # ArrowUp
    m.press("\ue015")
    check("view: Down, Up, Down lands on the second row", m.js(STATE_JS)["focusedIndex"] == 1)

    m.press("\ue013")
    film_id = m.js("return document.activeElement.dataset.id;")
    m.press("\ue007")  # Enter on the two-part film
    time.sleep(1)
    # Since the Movies list work a film is asked for by its ID; the back end picks the
    # part (tests/test_library_order.py).
    check("view: A on a two-part film asks for it by its ID",
          played[-1:] == [{"source": "movies", "id": film_id}] and film_id, played)
    s = m.js(STATE_JS)
    check("view: after playing, focus is back on the same row, same tab",
          s["focusedIndex"] == 0 and s["library"] and s["selectedTab"] == "movies", s)

    m.press("d")
    s = m.js(STATE_JS)
    check("view: d shows the original paths", MOVIE_FILES[0] in s["pathsShown"], s["pathsShown"])
    m.press("d")
    check("view: d again hides them", m.js(STATE_JS)["pathsShown"] == [])

    m.press("\ue013")
    s = m.js(STATE_JS)
    check("view: Up from the first row goes back to the tabs", s["focusedTab"] == "movies", s)
    m.press("\ue014")
    for _ in range(2):
        m.press("\ue015")
    m.press(" ")  # Space on "Test Show"
    s = wait_state(m, lambda s: s["episodes"], 3)
    check("view: A on a show opens its episodes in place of the library",
          s["episodes"] and not s["library"] and s["showTitle"] == "Test Show", s)
    check("view: season headings", s["headings"] == ["Season 1", "Season 2", "Specials"], s["headings"])
    check("view: episode labels and the unnumbered note",
          s["rows"][:3] == ["S01E01 Pilot", "S01E02 Test.Show.S01E02.mkv", "S02E05 Test.Show.S02E05.mkv"]
          and s["rows"][3].startswith("Special ") and s["rows"][3].endswith("unnumbered"), s["rows"])
    check("view: first episode focused", s["focusedIndex"] == 0 and s["focusedKind"] == "episode")
    check("view: B says Back inside a show, TV Shows tab selected",
          s["backHint"] == "Back" and s["selectedTab"] == "tv", s)
    for size, overflow in shot(m, shots_dir, "episodes"):
        check(f"view: episode list fits at {size}", not overflow)
    m.press("\ue013")
    s = m.js(STATE_JS)
    check("view: Up from the first episode goes to the tabs", s["focusedTab"] == "tv" and s["episodes"], s)
    m.press("r")  # a rescan with the focus on the tab, inside a show
    wait_state(m, lambda s: s["rescanning"], 2)
    # The toast shows the result once the lists are redrawn, so a focus moved
    # by the redraw can't be missed.
    s = wait_state(m, lambda s: s["toast"] and not s["rescanning"], RESCAN_DELAY_S + 5)
    time.sleep(0.3)
    s = m.js(STATE_JS)
    check("view: r with the focus on the tab inside a show: afterwards the focus is still on the tab",
          s["episodes"] and s["showTitle"] == "Test Show" and s["focusedTab"] == "tv" and s["focusedIndex"] == -1, s)
    m.press("\ue015")
    check("view: Down goes back to the first episode", m.js(STATE_JS)["focusedIndex"] == 0)

    m.press("\ue015")
    m.press("\ue007")
    time.sleep(1)
    check("view: A on an episode plays it", played[-1:] == [{"source": "tv", "path": TV_FILES[4]}], played)

    m.press("r")
    s = wait_state(m, lambda s: s["rescanning"], 2)
    check("view: r shows Scanning… in the toast and keeps the list",
          s["rescanning"] and s["episodes"] and len(s["rows"]) == 4, s)
    s = wait_state(m, lambda s: s["toast"] and not s["rescanning"], RESCAN_DELAY_S + 5)
    check("view: after the rescan, same show and same episode focused",
          s["episodes"] and s["showTitle"] == "Test Show" and s["focusedIndex"] == 1, s)

    m.press("q")
    s = wait_state(m, lambda s: s["library"], 2)
    check("view: B goes back to the library, focus on the show in the TV Shows tab",
          s["library"] and s["focusedIndex"] == 1 and s["selectedTab"] == "tv" and s["backHint"] == "Quit", s)
    m.press("\ue00c")  # Escape: from the library it opens the menu on Quit (the Home actions work)
    time.sleep(0.5)
    m.press("\ue007")  # Quit


def check_fallback(m, played, shots_dir, check):
    s = wait_state(m, lambda s: s["library"] and not s["loading"], 30)
    check("fallback: the sentence shows", s["banner"] == "SENTENCE", s["banner"])
    check("fallback: the plain file list shows in the Movies tab, the tab focused",
          len(s["rows"]) == len(MOVIE_FILES) and s["focusedTab"] == "movies"
          and s["tabs"] == [f"MOVIES {len(MOVIE_FILES)}", f"TV SHOWS (BETA) {len(TV_FILES)}"], s)
    m.press("\ue015")
    m.press("\ue007")
    time.sleep(1)
    check("fallback: A plays the file as before", played[-1:] == [{"source": "movies", "path": MOVIE_FILES[0]}], played)
    # The second file, so landing on the first row by chance can't pass.
    m.press("\ue015")
    m.press("\ue007")
    time.sleep(1)
    check("fallback: A on the second file plays it", played[-1:] == [{"source": "movies", "path": MOVIE_FILES[1]}],
          played)
    s = m.js(STATE_JS)
    check("fallback: after playing, focus is back on the same file, Movies tab still selected",
          s["focusedIndex"] == 1 and s["selectedTab"] == "movies", s)
    # The TV Shows tab (the Home shell work): after playing, the same file in the same
    # tab, not the default Movies tab.
    m.press("")
    m.press("")  # Up from the first file: the tabs
    m.press("")  # Right: TV Shows
    s = m.js(STATE_JS)
    check("fallback: Up from the first file, then Right: the TV Shows tab, its files",
          s["focusedTab"] == "tv" and s["selectedTab"] == "tv" and len(s["rows"]) == len(TV_FILES), s)
    m.press("")
    m.press("")
    m.press("")  # A on the second TV file
    time.sleep(1)
    check("fallback: A on a TV file plays it",
          played[-1:] and played[-1]["source"] == "tv" and played[-1]["path"] in TV_FILES, played)
    s = m.js(STATE_JS)
    check("fallback: after playing a TV file, focus is back on it, TV Shows tab still selected",
          s["focusedIndex"] == 1 and s["selectedTab"] == "tv" and s["focusedTab"] is None, s)


def check_real(m, played, shots_dir, check):
    wait_state(m, lambda s: s["rows"][:1] == ["Open my library"] and not s["loading"], 30)
    start = time.time()
    m.press("\ue007")
    s = wait_state(m, lambda s: s["library"] and not s["loading"], 60)
    check(f"real: SD card library shows in {time.time() - start:.1f} s: {len(s['rows'])} rows", bool(s["rows"]), s)
    for row, sub in zip(s["rows"], s["subtitles"]):
        check(f"real:   {row}{' / ' + sub if sub else ''}", True)
    for size, overflow in shot(m, shots_dir, "real"):
        check(f"real: fits at {size}", not overflow)


def run_case(case, env, profile, shots_dir, check):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        if case == "real":
            settings = load_settings(REPO)
        else:
            for base, files in ((tmp / "Movies", MOVIE_FILES), (tmp / "TV Shows", TV_FILES)):
                for rel in files:
                    (base / rel).parent.mkdir(parents=True, exist_ok=True)
                    (base / rel).write_bytes(b"")
            settings = {"movies_path": str(tmp / "Movies"), "tv_path": str(tmp / "TV Shows"),
                        "mpv_command": "mpv", "mpv_args": []}
        settings["data_dir"] = str(tmp / "data")  # never the app's own saved library
        played = []
        httpd, port = start_server(case, settings, tmp, played)
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
            {"view": check_view, "fallback": check_fallback, "real": check_real}[case](m, played, shots_dir, check)
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
    shots_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="parsed-view-"))
    shots_dir.mkdir(parents=True, exist_ok=True)
    results = []

    def check(text, ok, detail=None):
        results.append((text if ok or detail is None else f"{text}: {json.dumps(detail, default=str)}", ok))

    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp) / "home"
        env = dict(os.environ, HOME=str(home), MOZ_HEADLESS="1")
        for case in ("view", "fallback", "real"):
            profile = home / f".var/app/org.mozilla.firefox/data/check-profile-{case}"
            profile.mkdir(parents=True)
            try:
                run_case(case, env, profile, shots_dir, check)
            except Exception as exc:
                results.append((f"{case}: could not run ({exc!r})", False))
    for text, ok in results:
        print(f"{'ok  ' if ok else 'FAIL'} {text}")
    print(f"screenshots: {shots_dir}")
    failures = sum(not ok for _, ok in results)
    print("all good" if not failures else f"{failures} problem(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
