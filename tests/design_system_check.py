# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Design system 2/4 (the second design system step) in a real, headless Firefox. Not part of the
unit tests: it needs Firefox and takes about a minute.

Opens each screen this issue restyles, with invented films and shows: the
loading screen, "mpv not found", the first scan's result screen, the error banner,
"folder not found" (both over the plain-list fallback), Home on the Movies and TV Shows tabs, a show's episodes,
"Playing…" and a rescan (since the Home actions work in Enamel's toast); since the Enamel 0.11.0 upgrade also Home's
menu, and onboarding's two folder screens and a message in a folder row. At every window width in tests/window_sizes.py (the responsive layout work) it
checks: both Enamel stylesheets load before the app's own and every file
comes from the app's own server; exactly one element shows focus (none on
the loading and "mpv not found" screens, which have nothing to focus); no
sideways scrolling; nothing in the bars, tabs or messages is cut off; the
focused tab's ring stays inside the tab strip and clear of the other tab;
the hint bar says the same words as before (uppercase now) and still
changes as the focus moves. Since the Enamel 0.11.0 upgrade: 1rem is the text size the run asks
for (so tests/text_size_check.py really checks 200%), no row, button or
menu row cuts its text at its bottom, and a row's message stays inside it.

Screenshots, one per screen and size, go to the folder given as the first
argument (default: a temporary folder; pass docs/screenshots/design-system/
to refresh the committed ones).

Run from the repo root:  python3 tests/design_system_check.py [screenshot-dir]
"""

import base64
import contextlib
import io
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
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from backend import folder_finder, library_index  # noqa: E402
from backend.server import make_handler  # noqa: E402
from tests.home_shell_check import FILMS  # noqa: E402
from tests.test_folder_finder import make  # noqa: E402
from tests.loading_screen_check import UI_DIR, Marionette, free_port  # noqa: E402
from tests.window_sizes import SIZES, WINDOW, set_window, FIREFOX_FLAG  # noqa: E402
from tests.test_parsed_library import TV_FILES  # noqa: E402

ENTER, UP, DOWN, RIGHT = "", "", "", ""
VENDORED = ["vendor/enamel/tokens/enamel.css", "vendor/enamel/components/enamel-components.css"]

STATE_JS = """
const shown = (el) => !!el && el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden';
const byId = (id) => { const el = document.getElementById(id); return shown(el) && !el.hidden ? el : null; };
const W = document.documentElement.clientWidth, H = window.innerHeight;
const rect = (el) => { const r = el.getBoundingClientRect(); return {left: r.left, right: r.right, top: r.top, bottom: r.bottom}; };
// An element shows focus when it has it (or data-focused) and isn't covered.
// Its middle, or (for a row taller than the room above the hint bar, such as
// an onboarding row with its message in the smallest box) near its top.
const uncovered = (el) => { const r = el.getBoundingClientRect();
  return [r.height / 2, Math.min(r.height / 2, 12)].some(dy => {
    const hit = document.elementFromPoint(Math.min(Math.max(r.left + r.width / 2, 0), W - 1), Math.min(Math.max(r.top + dy, 0), H - 1));
    return !!hit && (hit === el || el.contains(hit)); }); };
const focusers = [...new Set([...document.querySelectorAll(':focus, [data-focused="true"]')])]
  .filter(el => el !== document.body && shown(el) && uncovered(el));
// Bits of the frame and messages that must never be cut off.
const parts = [...document.querySelectorAll('#action-bar, #action-bar .en-button, #tab-strip .tab, #hint-bar .hint, #hint-bar .en-glyph, '
  + '#mpv-missing, #error-banner, #playing-status, #scan-toast, '
  + '.status[data-state="error"], #loading p, '
  // Home's menu, and onboarding's titles, bands, rows and their messages (the Enamel 0.11.0 upgrade).
  + '.en-picker__row, #onboarding h1, #onboarding .onboarding-intro, #onboarding .en-band, .folder-row, '
  + '#onboarding .en-row__message')].filter(el => shown(el) && !el.closest('[hidden]'));
// Rows grow taller rather than cut their text (the Enamel 0.11.0 upgrade): nothing that holds text
// in a row, a button or a menu row runs out of its bottom.
const clipped = [...document.querySelectorAll('.file-row, .folder-row, .en-row, .en-picker__row, .en-button, .continue-tile')]
  .filter(el => shown(el) && !el.closest('[hidden]') && el.scrollHeight > el.clientHeight + 1)
  .map(el => `${el.className}: ${el.scrollHeight} > ${el.clientHeight}`);
// A row's message (onboarding) sits wholly inside its row.
const outOfRow = [...document.querySelectorAll('#onboarding .folder-row')].filter(r => shown(r) && !r.closest('[hidden]'))
  .flatMap(r => [...r.querySelectorAll('.en-row__message')].filter(x => x.textContent && shown(x)).map(x => [r, x]))
  .filter(([r, x]) => { const a = x.getBoundingClientRect(), b = r.getBoundingClientRect();
    return a.top < b.top - 0.5 || a.bottom > b.bottom + 0.5 || a.left < b.left - 0.5 || a.right > b.right + 0.5; })
  .map(([r, x]) => x.textContent.slice(0, 30));
const onboarding = document.getElementById('onboarding');
const messages = [...document.querySelectorAll('#onboarding .en-row__message')].filter(x => x.textContent && shown(x) && !x.closest('[hidden]'));
// Where the page is taller than the window it scrolls (Enamel's rule
// below its smallest box, the responsive layout work): a part counts as cut off only when it
// runs off the side, or off the page itself where no scrolling reaches it.
const pageH = document.documentElement.scrollHeight;
const cut = parts.filter(el => { const r = rect(el); return r.left < -0.5 || r.right > W + 0.5
  || r.top + scrollY < -0.5 || r.bottom + scrollY > Math.max(H, pageH) + 0.5
  || (pageH <= H + 0.5 && (r.top < -0.5 || r.bottom > H + 0.5))
  || el.scrollWidth > el.clientWidth + 1; }).map(el => el.id || el.className || el.textContent.slice(0, 30));
const active = document.activeElement;
let ring = null;
if (active && active.classList.contains('tab')) {
  const cs = getComputedStyle(active);
  const out = parseFloat(cs.outlineWidth) + parseFloat(cs.outlineOffset);
  const r = rect(active), strip = rect(document.getElementById('tab-strip'));
  const other = [...document.querySelectorAll('#tab-strip .tab')].find(t => t !== active);
  const o = rect(other);
  const ringBox = {left: r.left - out, right: r.right + out, top: r.top - out, bottom: r.bottom + out};
  ring = {style: cs.outlineStyle, colour: cs.outlineColor, inStrip: ringBox.top >= strip.top && ringBox.bottom <= strip.bottom
      && ringBox.left >= 0 && ringBox.right <= W,
    // Beside the other tab, or above or below it when the tabs wrap (the responsive layout work).
    clearOfOther: ringBox.right <= o.left || ringBox.left >= o.right || ringBox.bottom <= o.top || ringBox.top >= o.bottom};
}
const loading = document.getElementById('loading');
// Open my library (the first scan screen): Enamel's primary button, wholly on screen,
// and since Enamel 0.11.0 (the Enamel 0.11.0 upgrade) cream with dark text while it has the focus,
// like every focused button.
const scanButton = (() => { const b = document.querySelector('[data-kind="open-library"]');
  if (!b || !shown(b) || b.closest('[hidden]')) return null;
  const colour = (prop, token) => { const p = document.createElement('div'); p.style[prop] = `var(${token})`; document.body.appendChild(p);
    const c = getComputedStyle(p)[prop]; p.remove(); return c; };
  const cs = getComputedStyle(b), r = rect(b);
  return {tag: b.tagName, classes: b.className, focused: b === document.activeElement,
    creamFill: cs.backgroundColor === colour('backgroundColor', '--en-focus-fill'),
    inkText: cs.color === colour('color', '--en-focus-fill-ink'),
    onScreen: r.left >= 0 && r.right <= W && r.top >= 0 && r.bottom <= H}; })();
return {
  scanButton,
  W, H,
  loading: !!loading && shown(loading) && !loading.hidden,
  library: !!byId('library'), episodes: !!byId('episodes'), firstScan: !!document.querySelector('#onboarding[data-result]:not([data-result="reading"])'),
  mpvMissing: !!byId('mpv-missing'), errorBanner: !!byId('error-banner'),
  playing: !!byId('playing-status'), rescanning: !!byId('scan-toast'),
  folderError: [...document.querySelectorAll('.status[data-state="error"]')].some(el => shown(el) && !el.closest('[hidden]')),
  focusers: focusers.map(el => el.dataset.tab || el.dataset.kind || el.id || el.tagName),
  overflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth,
  cut, ring, clipped, outOfRow,
  // 1rem: the viewer's own text size, which Enamel never sets (the Enamel 0.11.0 upgrade).
  rootFont: getComputedStyle(document.documentElement).fontSize,
  onboardingStep: shown(onboarding) && !onboarding.hidden && onboarding.querySelector('.folder-row:focus') ? onboarding.dataset.step || null : null,
  rowMessages: messages.length,
  menuOpen: !!(window.EnamelUI && window.EnamelUI.picker.isOpen()),
  hint: document.getElementById('hint-bar').innerText.replace(/\\s+/g, ' ').trim(),
  sheets: [...document.styleSheets].map(s => { let rules = -1; try { rules = s.cssRules.length; } catch (e) {} return {href: s.href, rules}; }),
  resources: performance.getEntriesByType('resource').map(e => e.name),
  origin: location.origin,
};
"""


def start_server(case, settings, logs_dir, hold):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
    port = httpd.server_address[1]
    with contextlib.redirect_stdout(io.StringIO()):
        base = make_handler(UI_DIR, logs_dir, settings, {}, port)

    class Handler(base):
        def log_message(self, format, *args):
            pass

        def _handle_mpv_status(self):
            if case == "mpv":
                return self._send_json(HTTPStatus.OK, {
                    "available": False, "install_hint": "flatpak install flathub io.mpv.Mpv"})
            self._send_json(HTTPStatus.OK, {"available": True})

        def _handle_parsed_library(self, fixture=None):
            if case == "slow":
                hold.wait(20)
            # The saved library fails, so the page falls back to the plain
            # list, which is where a folder that can't be read shows its error.
            if case in ("fail", "nofolder"):
                return self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "test"})
            return super()._handle_parsed_library(fixture)

        # "Playing…" and "Rescanning…" stay while the check holds them.
        def _handle_play(self):
            self._read_json_body()
            self._send_json(HTTPStatus.OK, {"started": True})

        def _handle_status(self):
            self._send_json(HTTPStatus.OK, {"state": "idle" if hold.is_set() else "playing",
                                            "last_result": {"ok": True}})

        def _handle_scan(self):
            if case == "first":  # the result screen needs the real scan (the first scan screen)
                return super()._handle_scan()
            self._send_json(HTTPStatus.OK, {"started": True, "state": "scanning", "files_done": 1, "files_total": 4})

        def _handle_scan_status(self):
            if hold.is_set() or case == "first":
                return super()._handle_scan_status()
            self._send_json(HTTPStatus.OK, {"state": "scanning", "files_done": 1, "files_total": 4})

    httpd.RequestHandlerClass = Handler
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port


def wait_state(m, predicate, timeout):
    end = time.time() + timeout
    while True:
        state = m.js(STATE_JS)
        if predicate(state) or time.time() > end:
            return state
        time.sleep(0.2)


# Firefox's default text size, in CSS pixels, at 100% (Settings, Fonts, Size).
NORMAL_TEXT_PX = 16
# Enamel's smallest supported box, 20rem by 15rem: at the normal text size
# 320 by 240, and as large again at 200%, since it is set in the viewer's own
# text size. Below it Enamel only asks that the page scrolls, so the checks
# run at the window sizes that hold it (the Enamel 0.11.0 upgrade).
SMALLEST_BOX_REM = (20, 15)
text_size = 100  # set by main()


def sizes_held():
    """The window sizes that hold Enamel's smallest box at this text size."""
    px = NORMAL_TEXT_PX * text_size / 100
    return {name: (w, h) for name, (w, h) in SIZES.items()
            if w >= SMALLEST_BOX_REM[0] * px and h >= SMALLEST_BOX_REM[1] * px}


def look(m, shots_dir, screen, check, focused, hint=None):
    """Every size: a screenshot and every check for this screen."""
    for size, (w, h) in sizes_held().items():
        set_window(m, w, h)
        # Each screen is drawn once and the window then resized, which a
        # device never does; the app keeps the focus in view whenever it
        # moves or a message appears, so do the same here (the responsive layout work).
        m.js("const f = document.activeElement; if (f && f !== document.body) "
             "f.scrollIntoView({block: 'nearest', inline: 'nearest'}); return true;")
        time.sleep(0.2)
        inner = m.js("return [window.innerWidth, window.innerHeight];")
        check(f"{screen} {size}: the page is {w}x{h}", inner == [w, h], inner)
        # One screenful, what a viewer sees at this size, not the whole scrolling page.
        png = base64.b64decode(m.send("WebDriver:TakeScreenshot", {"full": False})["value"])
        (shots_dir / f"{screen}-{size}.png").write_bytes(png)
        # PNG header: width and height are the two big-endian numbers at bytes 16-24.
        shot = [int.from_bytes(png[16:20], "big"), int.from_bytes(png[20:24], "big")]
        # Zoomed in below Firefox's narrowest window, a CSS pixel is more than one screen pixel.
        ratio = m.js("return window.devicePixelRatio;")
        check(f"{screen} {size}: the screenshot is one screenful, {w}x{h}",
              shot == [w, h] or all(abs(got - want * ratio) <= ratio + 1 for got, want in zip(shot, (w, h))),
              [shot, ratio])
        s = m.js(STATE_JS)
        where = f"{screen} {size}"
        expected = [f"{s['origin']}/{path}" for path in VENDORED + ["css/tokens.css", "css/defaults.css"]]
        check(f"{where}: both Enamel stylesheets load, before the app's own",
              [x["href"] for x in s["sheets"]] == expected and all(x["rules"] > 0 for x in s["sheets"][:2]), s["sheets"])
        outside = [name for name in s["resources"] if not name.startswith(s["origin"] + "/")]
        check(f"{where}: nothing fetched from the network", not outside, outside)
        want = 1 if focused else 0
        check(f"{where}: {want} element(s) show focus: {s['focusers']}", len(s["focusers"]) == want, s["focusers"])
        check(f"{where}: no sideways scrolling", not s["overflowX"], s)
        cut = s["cut"]
        if screen.startswith("onboarding") and w == min(width for width, _ in sizes_held().values()):
            # Enamel's hints never wrap inside themselves, so in its smallest
            # box onboarding's long A hint is wider than the bar: a gap
            # recorded for Enamel (the folder choice screens), as tests/onboarding_check.py notes.
            hints = [c for c in cut if "hint" in c or "glyph" in c]
            if hints:
                print(f"note {where}: hints wider than the bar (Enamel gap, the folder choice screens): {hints}")
            cut = [c for c in cut if c not in hints]
        check(f"{where}: nothing in the bars, tabs or messages is cut off", not cut, cut)
        # The text size really is what this run asks for, or a 200% run would
        # quietly check the normal size again (the Enamel 0.11.0 upgrade).
        want_root = f"{NORMAL_TEXT_PX * text_size / 100:g}px"
        check(f"{where}: 1rem is {want_root}, the viewer's text size", s["rootFont"] == want_root, s["rootFont"])
        check(f"{where}: rows, buttons and menu rows grow with their text, none cut at its bottom",
              not s["clipped"], s["clipped"])
        check(f"{where}: a row's message stays wholly inside its row", not s["outOfRow"], s["outOfRow"])
        if s["ring"] is not None:
            r = s["ring"]
            check(f"{where}: the focused tab's accent ring is inside the strip and clear of the other tab",
                  r["style"] == "solid" and r["colour"] == "rgb(238, 138, 114)" and r["inStrip"] and r["clearOfOther"], r)
        if hint is not None:
            check(f"{where}: the hint bar says {s['hint']!r}", s["hint"] == hint, s["hint"])
        if screen == "first-launch":
            b = s["scanButton"]
            check(f"{where}: Open my library is Enamel's primary button, focused, cream fill with dark text, on screen",
                  b is not None and b["tag"] == "BUTTON" and "en-button--primary" in b["classes"]
                  and b["focused"] and b["creamFill"] and b["inkText"] and b["onScreen"], b)
    set_window(m, *WINDOW)


def run_case(m, case, port, hold, shots_dir, check):
    set_window(m, *WINDOW)
    m.send("WebDriver:Navigate", {"url": f"http://127.0.0.1:{port}/"})
    ready = lambda s: (s["library"] or s["firstScan"] or s["mpvMissing"] or s["errorBanner"]) and not s["loading"]  # noqa: E731
    if case == "onboarding":
        # Choosing the folders (the folder choice screens), with no folders set (the Enamel 0.11.0 upgrade: every screen
        # at 200% text too).
        s = wait_state(m, lambda s: s["onboardingStep"] == "1", 30)
        check("onboarding: screen 1 shows, a folder focused", s["onboardingStep"] == "1", s)
        look(m, shots_dir, "onboarding-1", check, focused=True)
        m.press(ENTER)
        s = wait_state(m, lambda s: s["onboardingStep"] == "2", 10)
        check("onboarding: screen 2 shows, a folder focused", s["onboardingStep"] == "2", s)
        look(m, shots_dir, "onboarding-2", check, focused=True)
        m.press(ENTER)  # the folder chosen for movies again: a message in its row
        s = wait_state(m, lambda s: s["rowMessages"] == 1, 10)
        check("onboarding: the movies folder chosen again says so in its row",
              s["onboardingStep"] == "2" and s["rowMessages"] == 1, s)
        look(m, shots_dir, "onboarding-message", check, focused=True)
        return
    if case == "slow":
        s = wait_state(m, lambda s: s["loading"], 10)
        check("loading: the loading screen shows", s["loading"], s)
        look(m, shots_dir, "loading", check, focused=False)
        hold.set()
        return
    s = wait_state(m, ready, 30)
    if case == "mpv":
        check("mpv: the mpv message shows", s["mpvMissing"], s)
        look(m, shots_dir, "mpv-missing", check, focused=False, hint="A SELECT B QUIT")
    elif case == "first":
        check("first: the result screen shows", s["firstScan"], s)
        look(m, shots_dir, "first-launch", check, focused=True, hint="A OPEN MY LIBRARY B BACK")
    elif case == "fail":
        check("fail: the error banner shows", s["errorBanner"], s)
        look(m, shots_dir, "error-banner", check, focused=True, hint="A SELECT B QUIT")
    elif case == "nofolder":
        check("nofolder: the folder-not-found message shows", s["folderError"], s)
        look(m, shots_dir, "folder-not-found", check, focused=True, hint="A SELECT B QUIT")
    else:
        check("home: the library shows, focus on the Movies tab", s["library"] and s["focusers"] == ["movies"], s)
        look(m, shots_dir, "home-movies", check, focused=True, hint="A SELECT B QUIT")
        m.press(RIGHT)
        time.sleep(0.3)
        look(m, shots_dir, "home-tv", check, focused=True, hint="A SELECT B QUIT")
        for key in (DOWN, ENTER):  # the first show
            m.press(key)
            time.sleep(0.3)
        s = wait_state(m, lambda s: s["episodes"], 5)
        check("home: a show's episodes open", s["episodes"], s)
        look(m, shots_dir, "episodes", check, focused=True, hint="A SELECT B BACK")
        m.press(UP)
        time.sleep(0.3)
        s = m.js(STATE_JS)
        check("home: Up from the first episode goes to the tabs; the hint goes on saying Back",
              s["focusers"] == ["tv"] and s["hint"] == "A SELECT B BACK", s)

        m.send("WebDriver:Navigate", {"url": f"http://127.0.0.1:{port}/"})
        wait_state(m, ready, 30)
        for key in (DOWN, ENTER):  # the first film, play
            m.press(key)
            time.sleep(0.3)
        s = wait_state(m, lambda s: s["playing"], 5)
        check("home: Playing… shows while a film plays", s["playing"], s)
        look(m, shots_dir, "playing", check, focused=True)
        hold.set()
        wait_state(m, lambda s: not s["playing"], 5)
        hold.clear()

        m.send("WebDriver:Navigate", {"url": f"http://127.0.0.1:{port}/"})
        wait_state(m, ready, 30)
        m.press("m")  # Home's menu (the Home actions work), an Enamel picker
        s = wait_state(m, lambda s: s["menuOpen"], 5)
        m.settle()  # it fades in
        check("home: Start opens the menu", s["menuOpen"], s)
        look(m, shots_dir, "menu", check, focused=True)
        m.press(ENTER)  # Rescan library
        time.sleep(0.3)
        s = wait_state(m, lambda s: s["rescanning"], 5)
        m.settle()  # the toast slides in
        s = m.js(STATE_JS)
        check("home: the scan toast shows during a rescan", s["rescanning"], s)
        look(m, shots_dir, "rescanning", check, focused=True)
        hold.set()


def main(size=100):
    """size: Firefox's default text size, as a percentage of normal, as a
    viewer sets it in Firefox's settings (tests/text_size_check.py, the Enamel 0.11.0 upgrade)."""
    global text_size
    text_size = size
    # Run without an argument (as scripts/test.sh does), the screenshots go to
    # a temporary folder, so a routine run never rewrites the committed ones.
    # Pass docs/screenshots/design-system/ to refresh the saved ones.
    shots_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="design-system-"))
    shots_dir.mkdir(parents=True, exist_ok=True)
    results = []

    def check(text, ok, detail=None):
        results.append((text if ok or detail is None else f"{text}: {json.dumps(detail, default=str)[:1500]}", ok))

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
        library_index.save(tmp / "data" / library_index.FILE_NAME, index)
        first = dict(settings, data_dir=str(tmp / "empty-data"))
        nofolder = dict(settings, movies_path=str(tmp / "Not There"))
        # No folders set: onboarding, its folder search pointed at invented
        # folders only.
        choose = dict(settings, movies_path="", tv_path="", data_dir=str(tmp / "onboarding-data"))
        places = tmp / "places"
        make(str(places / "internal"), ["Videos/Films/Alpha/a.mkv", "Videos/Films/Beta/b.mkv",
                                        "Videos/Shows/Show/Season 1/s01e01.mkv"])
        make(str(places / "sd"), ["Films/Gamma/g.mkv"])
        found = [folder_finder.Place("internal", "Internal storage", str(places / "internal")),
                 folder_finder.Place("sd", "SD card", str(places / "sd"))]
        search = mock.patch.object(folder_finder, "list_places", lambda: list(found))
        search.start()

        home = tmp / "home"
        env = dict(os.environ, HOME=str(home), MOZ_HEADLESS="1")
        profile = home / ".var/app/org.mozilla.firefox/data/check-profile-design-system"
        profile.mkdir(parents=True)
        mport = free_port()
        (profile / "user.js").write_text(
            f'user_pref("marionette.port", {mport});\n'
            'user_pref("browser.shell.checkDefaultBrowser", false);\n'
            'user_pref("browser.aboutwelcome.enabled", false);\n'
            f'user_pref("font.size.variable.x-western", {round(NORMAL_TEXT_PX * text_size / 100)});\n'
        )
        cmd = ["--headless", "--marionette", FIREFOX_FLAG, "--no-remote", "-profile", str(profile), "about:blank"]
        ff = subprocess.Popen(
            ["firefox", *cmd] if shutil.which("firefox") else ["flatpak", "run", "org.mozilla.firefox", *cmd],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        m = None
        try:
            m = Marionette(mport)
            for case, case_settings in (("slow", settings), ("mpv", settings), ("first", first),
                                        ("fail", settings), ("nofolder", nofolder), ("home", settings),
                                        ("onboarding", choose)):
                hold = threading.Event()
                httpd, port = start_server(case, case_settings, tmp, hold)
                try:
                    run_case(m, case, port, hold, shots_dir, check)
                except Exception as exc:  # report and carry on with the next case
                    results.append((f"{case}: could not run ({exc!r})", False))
                finally:
                    hold.set()
                    httpd.shutdown()
                    httpd.server_close()
        finally:
            search.stop()
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
