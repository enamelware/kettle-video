# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Drive the letter strip on Home in a real, headless Firefox (the letter strip fix). Not
part of the unit tests: it needs Firefox and takes about a minute.

Invented titles in temporary folders and a temporary saved library; playing
and Continue watching are faked, so mpv never starts and nothing real
is read or written. The strip must show exactly the list's own letter
groups, in order, each one drawn and not covered by anything, before any
scrolling. Moments, each checked the same way:

  first load with Continue watching showing, and with it empty; after
  switching tabs and back; after a rescan that finds new letters; coming back
  from a film (which brings Continue watching in); and after the last tile is
  removed (which takes it away).

Then, with every group in use, at every width in tests/window_sizes.py and in
narrow and short windows: the strip stays on screen; where every letter fits
all are in view, and where they can't, each is still readable and can be
brought into view and tapped, and Right keeps the current letter in view, as do
a trip to TV Shows and back and a shorter window. Left, Right and a tap land on
each group's first film; no tab or button sits under a letter. The strip is
moved by script here: a real swipe isn't exercised.

Screenshots go to the folder given as the first argument.

Run from the repo root:  python3 tests/letter_strip_check.py [screenshot-dir]
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
from tests.window_sizes import FIREFOX_FLAG, SIZES, WINDOW, set_window  # noqa: E402

ENTER, DOWN, UP, LEFT, RIGHT, BACKSPACE = "\ue007", "\ue015", "\ue013", "\ue012", "\ue014", "\ue003"

# A few letters with gaps between them, and films enough that the page scrolls.
SOME_LETTERS = "ABGLRUW"
# Every group the list can have: #, A to Z, and other.
EVERY_GROUP = ["#", *"ABCDEFGHIJKLMNOPQRSTUVWXYZ", "other"]
# The windows beyond tests/window_sizes.py: narrow but tall, just wide enough
# for the tabs to share a line, bars docked but too short for every letter both
# before and after the resize step (it catches a letter lost by a resize), just
# tall enough to keep the bars docked, and wide but short.
MORE_SIZES = {"narrow-tall": (320, 700), "tabs-share-a-line": (560, 700),
              "bars-docked-letters-scroll": (640, 600), "just-docked": (640, 400), "wide-short": (1280, 240)}
# How much shorter the window gets in the resize step; not below Enamel's
# smallest supported box.
RESIZE_STEP = 80
SMALLEST_HEIGHT = 240

CONTINUE_ITEM = {"id": "invented-tile", "kind": "movie", "name": "Invented Tile",
                 "caption": "Invented Tile · Resume at 30:00 · 90 min left", "picture": None,
                 "position": 1800, "duration": 7200, "missing": False}

STRIP_JS = """
const visible = (el) => el && !el.hidden && getComputedStyle(el).display !== 'none' && !el.closest('[hidden]');
const strip = document.querySelector('.letter-strip');
const stripBox = strip.getBoundingClientRect();
const letters = [...strip.children];
const uncovered = (el) => {
  const b = el.getBoundingClientRect();
  const hit = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2);
  return hit === el;
};
const rows = [...document.querySelectorAll('.source[data-source="movies"] .file-row')];
const active = document.activeElement;
const textBoxes = (el) => { const words = document.createRange(); words.selectNodeContents(el); return [...words.getClientRects()]; };
const lettersDrawn = visible(strip) ? letters.flatMap(textBoxes) : [];
const clash = (a, b) => a.right > b.left + 1 && a.left < b.right - 1 && a.bottom > b.top + 1 && a.top < b.bottom - 1;
return {
  loading: visible(document.getElementById('loading')),
  library: visible(document.getElementById('library')),
  continueShown: visible(document.getElementById('continue-watching')),
  selectedTab: (document.querySelector('.tab[aria-selected="true"]') || {dataset: {}}).dataset.tab,
  focusedLetter: active && active.dataset ? active.dataset.letter || null : null,
  focusedId: active && active.dataset ? active.dataset.id || null : null,
  shown: visible(strip),
  strip: strip.getAttribute('hidden') === null ? letters.map(l => l.dataset.letter) : [],
  rowGroups: [...new Set(rows.map(r => r.dataset.letter))],
  firstIds: Object.fromEntries([...rows].reverse().map(r => [r.dataset.letter, r.dataset.id])),
  notDrawn: visible(strip) ? letters.filter(l => !uncovered(l)).map(l => l.dataset.letter) : [],
  current: [...strip.querySelectorAll('[aria-current="true"]')].map(l => l.dataset.letter),
  currentInView: [...strip.querySelectorAll('[aria-current="true"]')].every(uncovered),
  fits: strip.scrollHeight <= strip.clientHeight + 1,
  stripBox: [stripBox.left, stripBox.top, stripBox.right, stripBox.bottom],
  hintTop: document.getElementById('hint-bar').getBoundingClientRect().top,
  viewport: [document.documentElement.clientWidth, innerHeight],
  fontPx: parseFloat(getComputedStyle(strip).fontSize),
  // Enamel's small text, measured on a tab, which is set in it.
  smallPx: parseFloat(getComputedStyle(document.querySelector('.tab')).fontSize),
  // A letter over a tab's words, or anywhere on a button. A tab with no pill
  // behind it (the unselected one) has nothing to cover but its words.
  overlapping: [
    ...[...document.querySelectorAll('#tab-strip .tab')].filter(visible)
      .filter(el => textBoxes(el).some(w => lettersDrawn.some(l => clash(w, l)))),
    ...[...document.querySelectorAll('#action-bar .en-button')].filter(visible)
      .filter(el => lettersDrawn.some(l => clash(el.getBoundingClientRect(), l))),
  ].map(el => el.dataset.tab || el.dataset.kind || el.textContent.trim()),
  // How many lines of text each tab has: the distinct heights its words sit at.
  tabLines: [...document.querySelectorAll('#tab-strip .tab')].map(t => { const size = parseFloat(getComputedStyle(t).fontSize);
    return textBoxes(t).map(r => r.top).sort((a, b) => a - b).filter((top, i, all) => i === 0 || top - all[i - 1] > size / 2).length; }),
  tabTops: [...document.querySelectorAll('#tab-strip .tab')].map(t => Math.round(t.getBoundingClientRect().top)),
  scrollY: window.scrollY,
  overflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth,
};
"""

# Brings one letter into the strip's view, without the page moving, and says
# whether it can then be seen and where to tap it.
BRING_JS = """
const strip = document.querySelector('.letter-strip');
const el = strip.querySelector(`[data-letter="${arguments[0]}"]`);
strip.scrollTop = el.offsetTop - strip.clientHeight / 2 + el.offsetHeight / 2;
const b = el.getBoundingClientRect();
const x = b.left + b.width / 2, y = b.top + b.height / 2;
return {ok: document.elementFromPoint(x, y) === el, x: Math.round(x), y: Math.round(y)};
"""


def film(title, n):
    return f"{title} ({1990 + n})/{title.replace(' ', '.')}.{1990 + n}.mkv"


def films_for(groups, each=3):
    out = []
    for group in groups:
        word = {"#": "1999 Invented", "other": "Город"}.get(group, f"{group}invented")
        out.extend(film(word, n) for n in range(1, each + 1))
    return out


def write_films(base, files):
    for rel in files:
        (base / rel).parent.mkdir(parents=True, exist_ok=True)
        (base / rel).write_bytes(b"")


def start_server(settings, logs_dir, shared):
    httpd_ref = {}
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
    port = httpd.server_address[1]
    base = make_handler(UI_DIR, logs_dir, settings, httpd_ref, port)

    class Handler(base):
        def log_message(self, format, *args):
            pass

        def _handle_mpv_status(self):
            self._send_json(HTTPStatus.OK, {"available": True})

        def _handle_play(self):
            self._read_json_body()
            shared["continue"] = [CONTINUE_ITEM]
            self._send_json(HTTPStatus.OK, {"started": True})

        def _handle_continue(self):
            self._send_json(HTTPStatus.OK, {"items": shared["continue"]})

        def _handle_continue_remove(self):
            self._read_json_body()
            shared["continue"] = []
            self._send_json(HTTPStatus.OK, {"ok": True})

    httpd.RequestHandlerClass = Handler
    httpd_ref["server"] = httpd
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port


def state(m):
    return m.js(STRIP_JS)


def wait(m, predicate, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        s = state(m)
        if predicate(s):
            return s
        time.sleep(0.2)
    return state(m)


def settled(m, predicate, timeout=30):
    """Waits for predicate, then lets the page's measured sizes catch up."""
    wait(m, predicate, timeout)
    time.sleep(0.4)
    return state(m)


def press(m, key, times=1):
    for _ in range(times):
        m.press(key)
    time.sleep(0.2)
    return state(m)


def tap(m, x, y):
    m.send("WebDriver:PerformActions", {"actions": [{
        "type": "pointer", "id": "touch", "parameters": {"pointerType": "touch"},
        "actions": [
            {"type": "pointerMove", "x": x, "y": y, "origin": "viewport", "duration": 0},
            {"type": "pointerDown", "button": 0},
            {"type": "pointerUp", "button": 0},
        ],
    }]})
    m.send("WebDriver:ReleaseActions", {})
    time.sleep(0.3)


def shot(m, shots_dir, name):
    (shots_dir / f"letter-strip-{name}.png").write_bytes(
        base64.b64decode(m.send("WebDriver:TakeScreenshot", {"full": False})["value"]))


def check_all_drawn(check, moment, s, groups=None):
    """The one test every moment takes: the strip is the list's own groups, in
    order, and every letter is drawn and not covered, with no scrolling."""
    want = groups if groups is not None else s["rowGroups"]
    check(f"{moment}: the strip shows the list's own groups, in order",
          s["shown"] and s["strip"] == want and s["rowGroups"] == want,
          {"strip": s["strip"], "rows": s["rowGroups"], "want": want})
    check(f"{moment}: every letter is drawn, none covered, before any scrolling",
          s["shown"] and not s["notDrawn"] and s["fits"], {"covered": s["notDrawn"], "fits": s["fits"]})


def check_moments(m, tmp, shared, shots_dir, check):
    """The five moments, with a few letters, at the everyday window."""
    groups = list(SOME_LETTERS)

    # First load, with Continue watching showing.
    s = settled(m, lambda s: s["library"] and not s["loading"] and s["continueShown"])
    check("first load: Continue watching is showing", s["continueShown"], s)
    check("first load: the page hasn't scrolled", s["scrollY"] == 0, s["scrollY"])
    check_all_drawn(check, "first load, Continue watching showing", s, groups)
    shot(m, shots_dir, "first-load-continue")

    # After switching tabs: TV Shows has no letter groups, so no strip.
    s = press(m, UP, 3)  # from the tile or row up to the bar, whichever
    m.js("document.querySelector('.tab[data-tab=\"movies\"]').focus(); return true;")
    s = press(m, RIGHT)
    check("tab switch: TV Shows, which has no letter groups, shows no strip",
          s["selectedTab"] == "tv" and not s["shown"], [s["selectedTab"], s["shown"]])
    s = press(m, LEFT)
    time.sleep(0.3)
    s = state(m)
    check("tab switch: back on Movies", s["selectedTab"] == "movies", s["selectedTab"])
    check_all_drawn(check, "after switching tabs and back", s, groups)

    # After a rescan that finds new letters.
    write_films(tmp / "Movies", films_for(["D", "Z"]))
    m.press("r")
    with_new = sorted(groups + ["D", "Z"])
    s = settled(m, lambda s: s["strip"] == with_new)
    check_all_drawn(check, "after a rescan that finds new letters", s, with_new)

    # Coming back from a film, which brings Continue watching back in. Remove
    # the tile first, so the film is what brings it in.
    m.js("document.querySelector('.tab[data-tab=\"movies\"]').focus(); return true;")
    m.js("const t = document.querySelector('.continue-tile'); if (t) t.focus(); return true;")
    m.press(UP)
    m.js("const t = document.querySelector('.continue-tile'); if (t) t.focus(); return true;")
    s = press(m, BACKSPACE)
    s = settled(m, lambda s: not s["continueShown"], 10)
    check("removing the last tile hides Continue watching", not s["continueShown"], s)
    check_all_drawn(check, "Continue watching hidden", s, with_new)
    shot(m, shots_dir, "continue-hidden")

    m.js("document.querySelector('.tab[data-tab=\"movies\"]').focus(); return true;")
    s = press(m, DOWN)
    s = press(m, ENTER)
    s = settled(m, lambda s: s["continueShown"], 15)
    check("back from a film: Continue watching is showing", s["continueShown"], s)
    check_all_drawn(check, "coming back from a film", s, with_new)
    shot(m, shots_dir, "back-from-film")


def check_empty_continue(m, check):
    s = settled(m, lambda s: s["library"] and not s["loading"])
    check("first load, Continue watching empty: it is hidden", not s["continueShown"], s)
    check_all_drawn(check, "first load, Continue watching empty", s, list(SOME_LETTERS))


def check_size(m, shots_dir, check, size):
    """Every group in use, in one window, Continue watching showing."""
    s = settled(m, lambda s: s["library"] and not s["loading"] and s["continueShown"])
    check(f"{size}: the strip shows every group, in order",
          s["shown"] and s["strip"] == EVERY_GROUP and s["rowGroups"] == EVERY_GROUP, s["strip"])
    left, top, right, bottom = s["stripBox"]
    width, height = s["viewport"]
    check(f"{size}: the strip is on screen, down the right edge, ending where the hint bar starts",
          abs(right - width) < 2 and left > 0 and top >= 0 and top < bottom and abs(bottom - s["hintTop"]) < 1
          and bottom <= height, [s["stripBox"], s["viewport"], s["hintTop"]])
    check(f"{size}: no sideways scroll", not s["overflowX"])
    # At the top of the page, and with the tabs in view wherever they sit.
    m.js("window.scrollTo(0, 0); return true;")
    top_of_page = state(m)["overlapping"]
    m.js("document.getElementById('tab-strip').scrollIntoView({block: 'center'}); return true;")
    time.sleep(0.2)
    with_tabs = state(m)
    check(f"{size}: no tab or button is under a letter", not top_of_page and not with_tabs["overlapping"],
          [top_of_page, with_tabs["overlapping"]])
    check(f"{size}: each tab's name stays on one line",
          with_tabs["tabLines"] == [1, 1], with_tabs["tabLines"])
    if size == "tabs-share-a-line":
        check(f"{size}: the two tabs do share a line", len(set(with_tabs["tabTops"])) == 1, with_tabs["tabTops"])
    # Readable: never under seven tenths of Enamel's small text.
    check(f"{size}: letters are readable ({s['fontPx']:.1f}px)", s["fontPx"] >= 0.7 * s["smallPx"] - 0.1,
          [s["fontPx"], s["smallPx"]])
    if s["fits"]:
        check(f"{size}: everything fits, so every letter is in view", not s["notDrawn"], s["notDrawn"])
    else:
        print(f"  {size}: {len(s['strip'])} letters don't all fit at a readable size; the strip scrolls")
    shot(m, shots_dir, size)

    # Every letter can be brought into view, without the page moving.
    start_y = state(m)["scrollY"]
    bad = []
    for letter in EVERY_GROUP:
        got = m.send("WebDriver:ExecuteScript", {"script": BRING_JS, "args": [letter]})["value"]
        if not got["ok"]:
            bad.append(letter)
    check(f"{size}: every letter can be brought into view", not bad, bad)
    check(f"{size}: bringing letters into view doesn't move the page", state(m)["scrollY"] == start_y)

    # A tap on a far letter lands on its first film.
    for letter in ("Z", "other", "#"):
        got = m.send("WebDriver:ExecuteScript", {"script": BRING_JS, "args": [letter]})["value"]
        tap(m, got["x"], got["y"])
        s = state(m)
        check(f"{size}: tapping {letter} lands on its first film",
              s["focusedLetter"] == letter and s["focusedId"] == s["firstIds"][letter],
              [s["focusedLetter"], s["focusedId"]])
        check(f"{size}: the tapped letter is marked and in view",
              s["current"] == [letter] and s["currentInView"], [s["current"], s["currentInView"]])

    # Right goes through every group onto each first film, keeping the current
    # letter in view; nothing at the end. Left comes back the same way.
    seen, out_of_view = [], []
    for _ in range(len(EVERY_GROUP) - 1):
        s = press(m, RIGHT)
        seen.append(s["focusedId"])
        if not s["currentInView"] or s["current"] != [s["focusedLetter"]]:
            out_of_view.append(s["focusedLetter"])
    want = [s["firstIds"][g] for g in EVERY_GROUP[1:]]
    check(f"{size}: Right lands on each group's first film", seen == want, {"seen": seen[:4], "want": want[:4]})
    check(f"{size}: the current letter stays marked and in view while jumping", not out_of_view, out_of_view)
    s = press(m, RIGHT)
    check(f"{size}: Right at the last group does nothing", s["focusedId"] == want[-1], s["focusedId"])
    s = press(m, LEFT)
    check(f"{size}: Left lands on the previous group's first film", s["focusedId"] == want[-2], s["focusedId"])
    check(f"{size}: and its letter stays in view", s["currentInView"], s["current"])

    # Where the strip scrolls, a late letter stays in view through a trip to
    # TV Shows and back, and when the window gets shorter. Firefox keeps the
    # strip's place across the trip by itself, so that step guards the promise,
    # whatever provides it; the shorter window is the step that fails without
    # the app's resize watcher.
    if not s["fits"]:
        late = s["current"]
        m.js("document.querySelector('.tab[data-tab=\"movies\"]').focus(); return true;")
        s = press(m, RIGHT)
        check(f"{size}: on TV Shows the strip is gone", s["selectedTab"] == "tv" and not s["shown"], s["selectedTab"])
        press(m, LEFT)
        time.sleep(0.3)
        s = state(m)
        check(f"{size}: back on Movies, the late letter is still marked and in view",
              s["selectedTab"] == "movies" and s["current"] == late and s["currentInView"],
              [s["selectedTab"], s["current"], s["currentInView"]])
        window_w, window_h = {**SIZES, **MORE_SIZES}[size]
        if window_h - RESIZE_STEP >= SMALLEST_HEIGHT:
            set_window(m, window_w, window_h - RESIZE_STEP)
            time.sleep(0.4)
            s = state(m)
            check(f"{size}: in a shorter window, the late letter is still in view",
                  s["current"] == late and s["currentInView"], [s["current"], s["currentInView"]])


def run_app(case, size, env, profile, shots_dir, check):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        groups = EVERY_GROUP if case == "size" else list(SOME_LETTERS)
        write_films(tmp / "Movies", films_for(groups))
        write_films(tmp / "TV Shows", ["Invented Show/Season 1/Invented.Show.S01E01.mkv"])
        settings = {"movies_path": str(tmp / "Movies"), "tv_path": str(tmp / "TV Shows"), "mpv_command": "mpv",
                    "mpv_args": [], "data_dir": str(tmp / "data")}
        roots = {"movies": settings["movies_path"], "tv": settings["tv_path"]}
        index = library_index.full_scan(roots, None, lambda done, total: None)
        library_index.save(Path(settings["data_dir"]) / library_index.FILE_NAME, index)
        shared = {"continue": [] if case == "empty" else [CONTINUE_ITEM]}
        httpd, port = start_server(settings, tmp, shared)
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
            window = {**SIZES, **MORE_SIZES}.get(size, WINDOW)
            set_window(m, *window)
            m.send("WebDriver:Navigate", {"url": f"http://127.0.0.1:{port}/"})
            set_window(m, *window)  # again: opening a page resets the zoom
            if case == "moments":
                check_moments(m, tmp, shared, shots_dir, check)
            elif case == "empty":
                check_empty_continue(m, check)
            else:
                check_size(m, shots_dir, check, size)
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
    shots_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="letter-strip-"))
    shots_dir.mkdir(parents=True, exist_ok=True)
    results = []

    def check(text, ok, detail=None):
        results.append((text if ok or detail is None else f"{text}: {json.dumps(detail, default=str, ensure_ascii=False)}", ok))

    runs = [("moments", "w1280"), ("empty", "w1280")]
    runs += [("size", size) for size in ("w320", "w640", "w1280", "w2560", *MORE_SIZES)]
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        home = Path(tmp) / "home"
        env = dict(os.environ, HOME=str(home), MOZ_HEADLESS="1")
        for case, size in runs:
            profile = home / f".var/app/org.mozilla.firefox/data/check-profile-{case}-{size}"
            profile.mkdir(parents=True)
            try:
                run_app(case, size, env, profile, shots_dir, check)
            except Exception as exc:  # report and carry on with the next case
                results.append((f"{case} {size}: could not run ({exc!r})", False))
    for text, ok in results:
        print(f"{'ok  ' if ok else 'FAIL'} {text}")
    print(f"screenshots: {shots_dir}")
    failures = sum(not ok for _, ok in results)
    print("all good" if not failures else f"{failures} problem(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
