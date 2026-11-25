# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Drive the Home shell in a real, headless Firefox (the Home shell work). Not part of
the unit tests: it needs Firefox and takes about a minute.

Uses the Marionette helper from loading_screen_check.py; playing is faked.
Each case except "first" saves its library to a temporary data folder
first, so the shell shows at once. Takes about a minute and a half. Cases:

  long   40 invented films and the invented shows: the Menu button at the
         top (the Home actions work; since the Home polish with no bar behind it, scrolling with the
         page), the black hint bar, the tabs and
         their counts, the pinned tab strip while a long list scrolls (with
         room for several rows), the colours on the selected pill and on a
         focused row, and the hint bar; the empty Continue watching area,
         hidden list headings, A and Left on the Movies tab doing nothing,
         Down from the TV Shows tab landing on the first show, and Left
         from a show's episodes
  real   the real folders from settings.json (read-only): counts and
         screenshots of both tabs and one show's episodes
  mpv    mpv missing: the message, no tabs, the hint bar there, no action bar
  first  no saved library: the first-launch screen, no tabs, the hint bar
         there, no action bar (Home's actions are in the Home actions work's menu)

Screenshots at each window width go to the folder given as the first argument.

Run from the repo root:  python3 tests/home_shell_check.py [screenshot-dir]
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
from tests.test_parsed_library import TV_FILES  # noqa: E402

LEFT = ""

FILMS = [f"Invented Film {n:02d} ({1980 + n})/Invented.Film.{n:02d}.{1980 + n}.mkv" for n in range(1, 41)]
ENTER, UP, DOWN, RIGHT = "", "", "", ""

BLACK = "rgb(0, 0, 0)"
WHITE = "rgb(255, 255, 255)"
# Enamel's white since 0.11.0 (the Enamel 0.11.0 upgrade): the hint bar's button glyphs.
CREAM = "rgb(242, 235, 218)"  # --en-cream
# Since the second design system step the page, the tabs and the hint bar are Enamel's.
CONTROL = "rgb(61, 68, 80)"  # --en-surface-control: the selected tab
KT_PAGE = "rgb(14, 20, 27)"  # --en-surface-page
CORAL = "rgb(238, 138, 114)"  # --en-focus-ring (the default accent)
# Since the third design system step the rows are Enamel's too: a focused row lifts to the
# control surface, its title strong, its muted lines soft.
KT_SOFT = "rgb(184, 188, 191)"  # --en-text-soft
KT_MUTED = "rgb(139, 146, 154)"  # --en-text-muted

STATE_JS = """
const visible = (el) => el && !el.hidden && getComputedStyle(el).display !== 'none' && !el.closest('[hidden]');
const box = (el) => { const r = el.getBoundingClientRect(); return {top: r.top, bottom: r.bottom, left: r.left, width: r.width, height: r.height}; };
const top = document.getElementById('action-bar');
const strip = document.getElementById('tab-strip');
const hint = document.getElementById('hint-bar');
const active = document.activeElement;
const rows = [...document.querySelectorAll('.file-row, .result-action')].filter(visible);
const isRow = active && active.matches('.file-row, .result-action');
const stripBox = box(strip);
const hintBox = box(hint);
return {
  loading: visible(document.getElementById('loading')),
  library: visible(document.getElementById('library')),
  episodes: visible(document.getElementById('episodes')),
  mpvMissing: visible(document.getElementById('mpv-missing')),
  firstScan: visible(document.querySelector('#onboarding[data-result]:not([data-result="reading"])')),
  continueWatching: (() => { const c = document.getElementById('continue-watching');
    return c ? {exists: true, tiles: c.querySelectorAll('.continue-tile').length, height: c.getBoundingClientRect().height} : {exists: false}; })(),
  // The lists' own headings: kept in the page, not shown (1px or less).
  headingSizes: [...document.querySelectorAll('#library .source > h2')].map(h => { const r = h.getBoundingClientRect(); return [r.width, r.height]; }),
  viewportW: document.documentElement.clientWidth,
  viewportH: window.innerHeight,
  scrollY: window.scrollY,
  top: box(top),
  topShown: visible(top),
  topBg: getComputedStyle(top).backgroundColor,
  topButtons: [...top.querySelectorAll('button')].filter(visible).map(b => b.textContent.trim()),
  buttonRight: box(top.querySelector('button')).left + box(top.querySelector('button')).width,
  // The page's side gutter, Enamel's, which grows a little on very wide pages.
  bodyPadRight: parseFloat(getComputedStyle(document.body).paddingRight),
  topPosition: getComputedStyle(top).position,
  stripShown: visible(strip),
  strip: stripBox,
  tabs: [...strip.querySelectorAll('.tab')].map(t => t.innerText.replace(/\\s+/g, ' ').trim()),
  selected: (strip.querySelector('.tab[aria-selected="true"]') || {dataset: {}}).dataset.tab || null,
  pillBg: getComputedStyle(strip.querySelector('.tab[aria-selected="true"]')).backgroundColor,
  pillText: getComputedStyle(strip.querySelector('.tab[aria-selected="true"]')).color,
  otherBg: getComputedStyle(strip.querySelector('.tab[aria-selected="false"]')).backgroundColor,
  focusedTab: active && active.dataset ? active.dataset.tab || null : null,
  focusShadow: active ? getComputedStyle(active).boxShadow : '',
  focusOutline: active ? [getComputedStyle(active).outlineStyle, getComputedStyle(active).outlineColor] : null,
  hint: hint.innerText.replace(/\\s+/g, ' ').trim(),
  hintShown: visible(hint),
  hintBg: getComputedStyle(hint).backgroundColor,
  hintBox: hintBox,
  // Only the glyphs on screen: X Remove shows only on a Continue watching tile (the Continue watching work).
  glyphs: [...hint.querySelectorAll('.button-glyph')].filter(g => g.getClientRects().length > 0).map(g => [getComputedStyle(g).borderRadius, getComputedStyle(g).backgroundColor]),
  focusedKind: isRow ? active.dataset.kind : null,
  focusedBox: isRow ? box(active) : null,
  focusedBg: isRow ? getComputedStyle(active).backgroundColor : null,
  // Every bit of text on the focused row, with its colour.
  focusedTextColours: isRow ? [...active.querySelectorAll('span')].filter(visible).filter(e => e.children.length === 0 && e.textContent.trim()).map(e => getComputedStyle(e).color) : [],
  unfocusedSubtitleColours: rows.filter(r => r !== active).flatMap(r => [...r.querySelectorAll('.row-subtitle')]).filter(visible).map(e => getComputedStyle(e).color),
  // Rows wholly on screen between the tab strip (or top bar) and the hint bar.
  // Never counting rows above the window, where the bars have scrolled away (the responsive layout work).
  rowsInView: rows.filter(r => { const b = r.getBoundingClientRect(); return b.top >= Math.max(0, visible(strip) ? stripBox.bottom : box(top).bottom) - 1 && b.bottom <= hintBox.top + 1; }).length,
  bodyBg: getComputedStyle(document.body).backgroundColor,
  overflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth,
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
            if case == "mpv":
                return self._send_json(HTTPStatus.OK, {
                    "available": False, "install_hint": "flatpak install flathub io.mpv.Mpv"})
            self._send_json(HTTPStatus.OK, {"available": True})

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


def sizes(m, shots_dir, name):
    """Each window size in turn, with a screenshot; yields the size and state."""
    for size, (w, h) in SIZES.items():
        set_window(m, w, h)
        time.sleep(0.5)
        (shots_dir / f"shell-{name}-{size}.png").write_bytes(
            base64.b64decode(m.send("WebDriver:TakeScreenshot", {})["value"]))
        yield size, m.js(STATE_JS)


def short_window(s):
    """Too short to keep two lines of tabs and the hint bar pinned with two
    rows between them (20rem since the Home polish, which took the docked action bar
    out of the sum; 24.25rem from the Enamel 0.8.0 upgrade): they scroll with the page there
    (the responsive layout work)."""
    return s["viewportH"] < 20 * 16


def check_bars(s, size, check, back="Quit", home=True, select="Select"):
    if home:
        # Since the Home polish no bar: the Menu button sits on the page with no fill
        # behind it and scrolls with it (never docked). Its row keeps the
        # action bar's height on one line: a button plus the tight space
        # above and below, 68 px at the browser's normal font size.
        check(f"{size}: no bar at the top: Menu's row has no fill, {s['top']['height']:.0f} px high (68 px), "
              "and scrolls with the page",
              s["topShown"] and s["topBg"] in ("transparent", "rgba(0, 0, 0, 0)") and s["topPosition"] == "static"
              and abs(s["top"]["height"] - 68) < 1.5 and abs(s["top"]["top"] + s["scrollY"]) < 1, s)
        check(f"{size}: one button, Menu, on the right at the page's gutter",
              s["topButtons"] == ["Menu"] and abs(s["viewportW"] - s["buttonRight"] - s["bodyPadRight"]) <= 4, s)
    else:
        check(f"{size}: no action bar on this screen", not s["topShown"], s)
    # Since the Enamel 0.6.0 upgrade (Enamel 0.6.0) the hint bar is Enamel's own height,
    # --en-size-bar: 3.75rem, 60 px at the browser's normal font size. Longer
    # words than Select (the result screen, the first scan screen) may take a second line in a
    # narrow window: the bar grows rather than cutting them off.
    fits = select != "Select" and s["hintBox"]["height"] >= 60
    check(f"{size}: black hint bar at the bottom, Enamel's 60 px: {s['hint']!r}",
          s["hintShown"] and s["hintBg"] == BLACK and s["hint"] == f"A {select.upper()} B {back.upper()}"
          and abs(s["hintBox"]["bottom"] - s["viewportH"]) < 1 and (fits or abs(s["hintBox"]["height"] - 60) < 1.5), s)
    check(f"{size}: the button glyphs are Enamel's round cream glyphs",
          len(s["glyphs"]) == 2 and all(r == "999px" and bg == CREAM for r, bg in s["glyphs"]), s["glyphs"])
    check(f"{size}: no sideways scroll", not s["overflowX"], s)


def check_long(m, shots_dir, check, played):
    s = wait_state(m, lambda s: s["library"] and not s["loading"], 30)
    check("long: Movies tab focused at launch, counts MOVIES 40 and TV SHOWS (BETA) 2",
          s["focusedTab"] == "movies" and s["tabs"] == ["MOVIES 40", "TV SHOWS (BETA) 2"], s)
    cw = s["continueWatching"]
    check("long: the Continue watching area is there, with no tiles, and takes no space",
          cw["exists"] and cw.get("tiles") == 0 and cw.get("height") == 0, cw)
    check("long: the lists' own headings are kept but not shown",
          len(s["headingSizes"]) == 2 and all(w <= 1 and h <= 1 for w, h in s["headingSizes"]), s["headingSizes"])
    m.press(ENTER)
    time.sleep(0.5)
    s = m.js(STATE_JS)
    check("long: A on a tab does nothing (nothing plays, focus stays on the Movies tab)",
          played == [] and s["focusedTab"] == "movies" and s["selected"] == "movies" and s["library"], s)
    m.press(LEFT)
    s = m.js(STATE_JS)
    check("long: Left on the Movies tab does nothing (no wrap-around)",
          s["focusedTab"] == "movies" and s["selected"] == "movies", s)
    check("long: selected tab is Enamel's control-coloured pill with white text, the other plain text",
          s["pillBg"] == CONTROL and s["pillText"] == WHITE and s["otherBg"] == "rgba(0, 0, 0, 0)", s)
    check("long: Enamel's accent ring on the focused tab",
          s["focusOutline"] == ["solid", CORAL], s["focusOutline"])
    check("long: flat Enamel page colour", s["bodyBg"] == KT_PAGE, s["bodyBg"])
    for size, s in sizes(m, shots_dir, "home"):
        check_bars(s, size, check)

    for _ in range(25):
        m.press(DOWN)
    for size, s in sizes(m, shots_dir, "scrolled"):
        m.press(DOWN)
        m.press(UP)  # scroll the focused row into view at this size
        s = m.js(STATE_JS)
        if short_window(s):
            check(f"long: {size}: the page has scrolled, and in this short window the bars scrolled with it",
                  s["scrollY"] > 0 and s["strip"]["bottom"] <= 0.5, s)
        else:
            check(f"long: {size}: the page has scrolled, the Menu button with it, and the tab strip is "
                  "pinned at the top of the window",
                  s["scrollY"] > 0 and abs(s["strip"]["top"]) < 1 and s["top"]["bottom"] <= 0.5, s)
        fb = s["focusedBox"]
        # In a short window the strip has scrolled off the top: the row must
        # then be on screen, not merely below the strip (the responsive layout work).
        check(f"long: {size}: the focused row is clear of the tab strip and the hint bar",
              fb is not None and fb["top"] >= max(s["strip"]["bottom"], 0) - 0.5
              and fb["bottom"] <= s["hintBox"]["top"], s)
        # A short window keeps room for two rows at least (the responsive layout work), where
        # two of them fit at all: since Enamel 0.8.0 (the Enamel 0.8.0 upgrade) a row with a title
        # wrapped onto two lines is taller than half of the smallest
        # supported box's room, so there Enamel's own rule holds: one whole
        # row with its title fits.
        room = s["hintBox"]["top"] - max(s["strip"]["bottom"], 0)
        two_fit = fb is not None and room >= 2 * fb["height"] + 12
        need = (2 if two_fit else 1) if short_window(s) else 4
        check(f"long: {size}: {s['rowsInView']} rows fit between the tab strip and the hint bar (at least {need})",
              s["rowsInView"] >= need, s)
        check_bars(s, size, check)
        (shots_dir / f"shell-scrolled-{size}.png").write_bytes(
            base64.b64decode(m.send("WebDriver:TakeScreenshot", {})["value"]))

    for _ in range(30):
        m.press(UP)
    s = m.js(STATE_JS)
    menu_focused = m.js("return document.activeElement.dataset.kind === 'menu';")
    check("long: Up past the first row and the tabs reaches the Menu button (the Home actions work), page at the top",
          menu_focused and s["scrollY"] == 0, s)
    m.press(DOWN)
    s = m.js(STATE_JS)
    check("long: Down from the bar goes back to the tabs, page at the top",
          s["focusedTab"] == "movies" and s["scrollY"] == 0, s)
    m.press(RIGHT)
    m.press(DOWN)
    m.settle()  # the lift fades in (Enamel 0.5.0, the Enamel 0.5.0 upgrade)
    s = m.js(STATE_JS)
    check("long: a focused show row lifts to the control surface, title strong, second line soft",
          s["focusedKind"] == "show" and len(s["focusedTextColours"]) >= 2
          and set(s["focusedTextColours"]) == {WHITE, KT_SOFT} and s["focusedBg"] == CONTROL, s)
    check("long: unfocused rows keep Enamel's muted text for their second line",
          s["unfocusedSubtitleColours"] and set(s["unfocusedSubtitleColours"]) == {KT_MUTED}, s)
    m.press(DOWN)
    m.press(ENTER)  # Test Show
    s = wait_state(m, lambda s: s["episodes"], 3)
    for size, s in sizes(m, shots_dir, "episodes"):
        check_bars(s, size, check, back="Back")
    m.press(UP)  # from the first episode to the tabs
    m.press(LEFT)
    s = m.js(STATE_JS)
    check("long: Left on the tabs from a show's episodes shows the Movies list, focus on the tab",
          not s["episodes"] and s["library"] and s["selected"] == "movies" and s["focusedTab"] == "movies"
          and s["hint"] == "A SELECT B QUIT", s)


def check_real(m, shots_dir, check, index):
    s = wait_state(m, lambda s: s["library"] and not s["loading"], 60)
    counts = {source: len(index["sources"][source]["items"]) for source in ("movies", "tv")}
    expected = [f"MOVIES {counts['movies']}", f"TV SHOWS (BETA) {counts['tv']}"]
    check(f"real: counts {s['tabs']} match the saved library", s["tabs"] == expected, s)
    for size, s in sizes(m, shots_dir, "real-movies"):
        check_bars(s, size, check)
    m.press(RIGHT)
    for size, s in sizes(m, shots_dir, "real-tv"):
        check(f"real: {size}: TV Shows tab selected, its list showing", s["selected"] == "tv", s)
        check_bars(s, size, check)
    m.press(DOWN)
    m.press(ENTER)
    s = wait_state(m, lambda s: s["episodes"], 3)
    if s["episodes"]:
        for size, s in sizes(m, shots_dir, "real-episodes"):
            check_bars(s, size, check, back="Back")


def check_mpv(m, shots_dir, check):
    s = wait_state(m, lambda s: s["mpvMissing"] and not s["loading"], 15)
    check("mpv: the mpv message shows, with no tabs", s["mpvMissing"] and not s["stripShown"], s)
    for size, s in sizes(m, shots_dir, "mpv-missing"):
        check_bars(s, size, check, home=False)


def check_first(m, shots_dir, check):
    s = wait_state(m, lambda s: s["firstScan"] and not s["loading"], 15)
    check("first: the first-launch screen shows, with no tabs", s["firstScan"] and not s["stripShown"], s)
    for size, s in sizes(m, shots_dir, "first-launch"):
        check_bars(s, size, check, back="Back", home=False, select="Open my library")


def run_case(case, env, profile, shots_dir, check):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        if case == "real":
            settings = load_settings(REPO)
        else:
            for base, files in ((tmp / "Movies", FILMS), (tmp / "TV Shows", TV_FILES)):
                for rel in files:
                    (base / rel).parent.mkdir(parents=True, exist_ok=True)
                    (base / rel).write_bytes(b"")
            settings = {"movies_path": str(tmp / "Movies"), "tv_path": str(tmp / "TV Shows"),
                        "mpv_command": "mpv", "mpv_args": []}
        settings["data_dir"] = str(tmp / "data")  # never the app's own saved library
        index = None
        if case != "first":  # the first-launch case starts with no saved library
            roots = {"movies": settings["movies_path"], "tv": settings["tv_path"]}
            index = library_index.full_scan(roots, None, lambda done, total: None)
            library_index.save(Path(settings["data_dir"]) / library_index.FILE_NAME, index)
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
            if case == "long":
                check_long(m, shots_dir, check, played)
            elif case == "real":
                check_real(m, shots_dir, check, index)
            elif case == "first":
                check_first(m, shots_dir, check)
            else:
                check_mpv(m, shots_dir, check)
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
    shots_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="home-shell-"))
    shots_dir.mkdir(parents=True, exist_ok=True)
    results = []

    def check(text, ok, detail=None):
        results.append((text if ok or detail is None else f"{text}: {json.dumps(detail, default=str)}", ok))

    # Firefox can still be writing its profile as it exits; don't fail on that.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        home = Path(tmp) / "home"
        env = dict(os.environ, HOME=str(home), MOZ_HEADLESS="1")
        for case in ("long", "real", "mpv", "first"):
            profile = home / f".var/app/org.mozilla.firefox/data/check-profile-{case}"
            profile.mkdir(parents=True)
            try:
                run_case(case, env, profile, shots_dir, check)
            except Exception as exc:  # report and carry on with the next case
                results.append((f"{case}: could not run ({exc!r})", False))
    for text, ok in results:
        print(f"{'ok  ' if ok else 'FAIL'} {text}")
    print(f"screenshots: {shots_dir}")
    failures = sum(not ok for _, ok in results)
    print("all good" if not failures else f"{failures} problem(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
