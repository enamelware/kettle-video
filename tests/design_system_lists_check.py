# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Design system 3/4 (the third design system step) in a real, headless Firefox: Continue
watching, the Movies and TV Shows lists and a show's episodes in Enamel.
Not part of the unit tests: it needs Firefox (and ffmpeg, to make a test
picture).

Invented films and shows, with a very long film title, a missing film and a
missing episode, and six Continue watching tiles (a long name, a missing
one, one with no picture). At every window width in tests/window_sizes.py
(the responsive layout work) it moves
the focus over the tiles, the tabs and the rows, and at each stop checks:
exactly one element shows focus (the tile's accent ring, the tab's ring or
the row's lift, and no other element with any of them); no sideways
scrolling; the focused tile's ring is inside the row (not clipped); the
focused row is wholly on screen, between the tab strip and the hint bar;
the long title and the "Missing" rows fit the row's width. Also: the
focused row lifts to the control surface with its muted lines soft, the
progress bars are Enamel's thin accent bars, and `d` still shows the
paths. Since the last design system step it also opens the remove question (since the Home actions work from
Home's menu, after checking the action bar's Menu button and the menu
itself): Cancel has the focus and is the only element showing it, and B
goes back to where the menu was opened. Since the picker confirm work the question is an Enamel picker:
Cancel fills white with dark text, the panel fits on screen above the hint
bar, and the hint bar stays visible. Since the Enamel 0.8.0 upgrade (Enamel 0.8.0's taller
rows) Home's menu fits above the hint bar too wherever the question does,
and the focused row of the menu and of the question is wholly in the window
at every width, Enamel's smallest box included.

Screenshots, one per screen and size, go to the folder given as the first
argument (default: a temporary folder; pass docs/screenshots/design-system/
to refresh the committed ones).

Run from the repo root:  python3 tests/design_system_lists_check.py [screenshot-dir]
"""

import base64
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from tests import continue_row_layout_check as layout  # noqa: E402
from tests.home_shell_check import FILMS  # noqa: E402
from tests.window_sizes import SIZES, WINDOW, set_window  # noqa: E402
from tests.saved_library_check import ENTER, main, wait_state  # noqa: E402
from tests.test_parsed_library import TV_FILES  # noqa: E402

UP, DOWN, RIGHT = "", "", ""
LONG = "An Extremely Long Invented Film Title That Goes On And On Until It Has To Wrap Onto A Second Line And Beyond"
GONE_FILM = "Gone Away Film (1995)/Gone.Away.Film.1995.mkv"
MOVIES = [*FILMS, f"{LONG} (2004)/{LONG}.2004.mkv", GONE_FILM]
# The first episode of the show with seasons goes missing.
GONE_EPISODE = "Test Show/Season 1/Test.Show.S01E01.Pilot.mkv"

# Sizes where Enamel's picker can't fit above the hint bar (an Enamel
# gap, raised on the responsive layout work): Enamel's smallest box.
ENAMEL_PICKER_GAP = {"w320"}

ACCENT = "rgb(238, 138, 114)"  # --en-focus-ring and the progress fill (default accent)
CONTROL = "rgb(61, 68, 80)"  # --en-surface-control
SOFT = "rgb(184, 188, 191)"  # --en-text-soft
STRONG = "rgb(255, 255, 255)"  # --en-text-strong
FILL = "rgb(242, 235, 218)"  # --en-focus-fill: Enamel's cream since 0.11.0 (the Enamel 0.11.0 upgrade), white until then
FILL_INK = "rgb(14, 20, 27)"  # --en-focus-fill-ink
THIN_BAR = 8  # --en-c-progress-thin, px: Enamel 0.11.0's thin bar (the Enamel 0.11.0 upgrade; 4 until then)

STATE_JS = """
const shown = (el) => !!el && el.getClientRects().length > 0 && !el.closest('[hidden]') && getComputedStyle(el).display !== 'none';
const W = document.documentElement.clientWidth, H = window.innerHeight;
const box = (el) => { const r = el.getBoundingClientRect(); return {left: r.left, right: r.right, top: r.top, bottom: r.bottom}; };
const active = document.activeElement;
// Every way an element can look focused here. Since Enamel 0.5.0 (issue
// The Enamel 0.5.0 upgrade) every tile carries a transparent ring that only takes the accent on
// focus, so a ring counts only when it has a colour.
const ringOn = (cs) => cs.outlineStyle === 'solid' && parseFloat(cs.outlineWidth) > 0 && cs.outlineColor !== 'rgba(0, 0, 0, 0)';
const looks = [];
for (const t of document.querySelectorAll('.continue-tile')) if (shown(t) && ringOn(getComputedStyle(t, '::after'))) looks.push(t);
for (const t of document.querySelectorAll('.tab')) if (shown(t) && ringOn(getComputedStyle(t))) looks.push(t);
// Since Enamel 0.11.0 (the Enamel 0.11.0 upgrade) every row has the same satin rim and soft
// shadow at rest, so a shadow counts only when it differs from the rows'
// usual one.
const fileRows = [...document.querySelectorAll('.file-row')].filter(shown);
const shadowCount = {};
for (const r of fileRows) { const sh = getComputedStyle(r).boxShadow; shadowCount[sh] = (shadowCount[sh] || 0) + 1; }
const restingShadow = Object.keys(shadowCount).sort((a, b) => shadowCount[b] - shadowCount[a])[0];
for (const r of fileRows) {
  const cs = getComputedStyle(r);
  if (cs.backgroundColor === '""" + CONTROL + """' || (fileRows.length > 1 && cs.boxShadow !== restingShadow) || ringOn(cs)) looks.push(r);
}
// Enamel's Menu button (the Home actions work; no bar behind it since the Home polish) fills white when focused.
for (const b of document.querySelectorAll('#action-bar .en-button')) {
  if (shown(b) && getComputedStyle(b).backgroundColor === '""" + FILL + """') looks.push(b);
}
// Inside an Enamel picker (the remove question, the picker confirm work; Home's menu,
// The Home actions work) the focused row fills white.
for (const r of document.querySelectorAll('.en-picker__row')) {
  if (shown(r) && getComputedStyle(r).backgroundColor === '""" + FILL + """') looks.push(r);
}
const tiles = [...document.querySelectorAll('.continue-tile')].filter(shown);
const row = document.querySelector('.continue-row');
let tileRing = null;
if (active && tiles.includes(active)) {
  const cs = getComputedStyle(active, '::after');
  // The focused tile is drawn grown (Enamel 0.5.0), its ring with it.
  const scale = new DOMMatrix(getComputedStyle(active).transform).a;
  const reach = (parseFloat(cs.outlineWidth) + parseFloat(cs.outlineOffset)) * scale;
  const f = box(active.querySelector('.continue-frame')), r = box(row);
  tileRing = {colour: cs.outlineColor, inside: f.top - reach >= r.top - 0.5 && f.bottom + reach <= r.bottom + 0.5
    && f.left - reach >= r.left - 0.5 && f.right + reach <= r.right + 0.5 && f.left - reach >= -0.5 && f.right + reach <= W + 0.5};
}
const strip = document.getElementById('tab-strip'), hint = document.getElementById('hint-bar');
const isRow = active && active.classList.contains('file-row');
const rows = [...document.querySelectorAll('.file-row')].filter(shown);
const panel = document.querySelector('dialog[open] .en-picker');
const inPicker = active && active.classList.contains('en-picker__row');
const hintBox = box(hint);
const muted = isRow ? [...active.querySelectorAll('.row-label, .row-year, .row-subtitle, .row-note, .row-path')].filter(shown) : [];
return {
  // The loading screen covers the page until the library arrives.
  loading: shown(document.getElementById('loading')),
  ready: shown(document.getElementById('library')) || shown(document.getElementById('episodes')),
  episodes: shown(document.getElementById('episodes')),
  looks: looks.map(el => el.dataset.tab || el.dataset.id || el.dataset.kind || el.className),
  activeIsOnlyLook: looks.length === 1 && looks[0] === active,
  activeKind: active ? (active.dataset.tab ? 'tab' : active.classList.contains('continue-tile') ? 'tile' : active.dataset.kind || active.tagName) : null,
  activeTitle: isRow && active.querySelector('.row-title') ? active.querySelector('.row-title').textContent : null,
  activeStatus: active && active.dataset ? active.dataset.status || '' : '',
  overflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth,
  tileRing,
  // A row taller than the room between the bars (a long title, focused, in
  // a short window: the responsive layout work) can't be wholly on screen; its top must be.
  rowOnScreen: isRow ? (() => { const r = box(active), top = Math.max(0, box(strip).bottom), bottom = box(hint).top;
    const sides = r.left >= -0.5 && r.right <= W + 0.5;
    return sides && (r.bottom - r.top > bottom - top ? r.top >= top - 0.5 && r.top <= top + 8
      : r.top >= top - 0.5 && r.bottom <= bottom + 0.5); })() : null,
  rowLift: isRow ? getComputedStyle(active).backgroundColor : null,
  // Enamel's satin light stays on the focused row (the Enamel 0.11.0 upgrade): the app sets only its colour.
  rowSatin: isRow ? getComputedStyle(active).backgroundImage : null,
  rowTitleColour: isRow && active.querySelector('.row-title') ? getComputedStyle(active.querySelector('.row-title')).color : null,
  rowMutedColours: muted.map(e => getComputedStyle(e).color),
  // No row's text runs out of its row.
  rowsCut: rows.filter(r => r.scrollWidth > r.clientWidth + 1 || box(r).right > W + 0.5).map(r => r.textContent.slice(0, 40)),
  rowCount: rows.length,
  missingRows: rows.filter(r => r.dataset.status === 'missing').map(r => r.querySelector('.row-title').textContent),
  pathsShown: rows.some(r => [...r.querySelectorAll('.row-path')].some(shown)),
  progressColours: tiles.map(t => getComputedStyle(t.querySelector('.continue-progress-fill')).backgroundColor),
  // The remove question (the picker confirm work): the panel is wholly on screen above
  // the hint bar and nothing in it is cut off.
  pickerFits: panel ? (() => { const p = box(panel); return p.left >= -0.5 && p.right <= W + 0.5 && p.top >= -0.5
    && p.bottom <= hintBox.top + 0.5 && [panel, ...panel.querySelectorAll('.en-picker__title, .en-picker__row')]
    .every(e => e.scrollWidth <= e.clientWidth + 1); })() : null,
  // Nothing behind the question draws above its darkened layer: the middle
  // of every Continue watching picture on screen hits the dialog (the
  // pictures are darkened like the rest of the page).
  layerOver: panel ? (() => { const seen = tiles.map(t => box(t.querySelector('.continue-frame')))
    .map(r => [(r.left + r.right) / 2, (r.top + r.bottom) / 2]).filter(([x, y]) => x >= 0 && x < W && y >= 0 && y < H);
    return seen.length > 0 && seen.every(([x, y]) => panel.closest('dialog').contains(document.elementFromPoint(x, y))); })() : null,
  // The focused picker row (Home's menu or the remove question) is wholly
  // in the window, so it can be seen even where the panel can't fit
  // (the Enamel 0.8.0 upgrade: Enamel 0.8.0's rows are taller).
  pickerRowOnScreen: inPicker ? (() => { const r = box(active);
    return r.left >= -0.5 && r.right <= W + 0.5 && r.top >= -0.5 && r.bottom <= H + 0.5; })() : null,
  pickerFill: inPicker ? [getComputedStyle(active).backgroundColor,
    ...[...active.querySelectorAll('span')].map(e => getComputedStyle(e).color)] : null,
  // The darkened layer stops where the hint bar starts (its backdrop is
  // transparent), so the hint bar is not covered.
  hintOnTop: panel ? Math.abs(box(panel.closest('dialog')).bottom - hintBox.top) <= 0.5 : null,
  progressHeights: tiles.map(t => t.querySelector('.continue-progress').getBoundingClientRect().height),
};
"""


def state(m):
    m.settle()  # measure once the focus has finished moving (the Enamel 0.5.0 upgrade)
    return m.js(STATE_JS)


def wait(m, predicate, timeout=3):
    end = time.time() + timeout
    while True:
        s = state(m)
        if predicate(s) or time.time() > end:
            return s
        time.sleep(0.15)


def shot(m, shots_dir, name):
    png = base64.b64decode(m.send("WebDriver:TakeScreenshot", {"full": False})["value"])
    (shots_dir / f"{name}.png").write_bytes(png)


def press(m, key, predicate=lambda s: True):
    m.press(key)
    return wait(m, predicate)


def look(check, where, s, row_place=True):
    """The checks made at every stop. Showing the paths (d) makes the
    focused row taller where it stands, so its place isn't checked then."""
    check(f"{where}: exactly one element shows focus, the focused one ({s['looks']})", s["activeIsOnlyLook"], s)
    check(f"{where}: no sideways scrolling, no row's text cut off", not s["overflowX"] and not s["rowsCut"], s["rowsCut"])
    if s["tileRing"] is not None:
        check(f"{where}: the tile's accent ring is whole, inside the row",
              s["tileRing"]["colour"] == ACCENT and s["tileRing"]["inside"], s["tileRing"])
    if s["rowOnScreen"] is not None and row_place:
        check(f"{where}: the focused row is wholly on screen, lifted, title strong, muted lines soft",
              s["rowOnScreen"] and s["rowLift"] == CONTROL and s["rowTitleColour"] in (STRONG, SOFT)
              and all(c == SOFT for c in s["rowMutedColours"]), s)
        check(f"{where}: the focused row keeps Enamel's satin finish (the Enamel 0.11.0 upgrade)",
              s["rowSatin"] not in (None, "none"), s["rowSatin"])


def walk(m, check, shots_dir, size):
    where = f"home {size}"
    s = wait(m, lambda s: not s["loading"] and s["activeKind"] == "tile", 20)
    check(f"{where}: the loading screen has gone, the large tile has the focus",
          not s["loading"] and s["activeKind"] == "tile" and s["looks"] == ["m1"], s)
    look(check, f"{where}, large tile", s)
    # The action bar (the Home actions work): Up from the tile reaches Menu, filled
    # white, the only thing showing focus; Down goes back to the tile.
    s = press(m, UP, lambda s: s["activeKind"] == "menu")
    check(f"{where}: Up from the tile reaches the bar's Menu button", s["activeKind"] == "menu", s)
    look(check, f"{where}, Menu button", s, row_place=False)
    shot(m, shots_dir, f"lists-home-menu-button-{size}")
    s = press(m, DOWN, lambda s: s["looks"] == ["m1"])
    check(f"{where}: Down goes back to the large tile", s["looks"] == ["m1"], s)
    check(f"{where}: thin accent progress bars on every tile",
          s["progressColours"] and all(c == ACCENT for c in s["progressColours"])
          and all(abs(h - THIN_BAR) < 0.6 for h in s["progressHeights"]), [s["progressColours"], s["progressHeights"]])
    shot(m, shots_dir, f"lists-home-tile-{size}")
    for _ in range(2):  # the first key after a page opens can go astray in headless Firefox
        s = press(m, RIGHT, lambda s: s["looks"] == ["m2"])
        if s["looks"] == ["m2"]:
            break
    look(check, f"{where}, small tile", s)
    for _ in range(6):
        s = press(m, RIGHT)
    look(check, f"{where}, last tile", s)
    shot(m, shots_dir, f"lists-home-last-tile-{size}")
    s = press(m, DOWN, lambda s: s["activeKind"] == "tab")
    check(f"{where}: Down from the tiles reaches the tabs", s["activeKind"] == "tab", s)
    look(check, f"{where}, tab", s)
    # Home's menu (the Home actions work), opened with Start: its first row filled white,
    # the only thing showing focus.
    s = press(m, "m", lambda s: s["activeKind"] == "menu-rescan")
    check(f"menu {size}: Start opens the menu on Rescan library", s["activeKind"] == "menu-rescan", s)
    look(check, f"menu {size}, Rescan library", s, row_place=False)
    shot(m, shots_dir, f"lists-home-menu-{size}")
    check(f"menu {size}: Rescan library, focused, is wholly in the window", s["pickerRowOnScreen"] is True, s)
    if size not in ENAMEL_PICKER_GAP:
        # The Enamel 0.8.0 upgrade: with Enamel 0.8.0's taller rows the menu (five rows
        # here since Settings, the Settings screen work) still fits above the hint bar
        # wherever the remove question does.
        check(f"menu {size}: the menu is wholly on screen above the hint bar, nothing cut off",
              s["pickerFits"] is True and s["hintOnTop"] is True, s)
    s = press(m, DOWN, lambda s: s["activeKind"] == "menu-remove-missing")
    look(check, f"menu {size}, Remove 2 missing items", s, row_place=False)
    check(f"menu {size}: Remove 2 missing items, focused, is wholly in the window", s["pickerRowOnScreen"] is True, s)
    # The remove question (the last design system step's screenshot pass; an Enamel picker
    # since the picker confirm work): Cancel has the focus, filled white with dark text, and is
    # the only element showing it; the panel fits above the hint bar, which
    # stays visible; B goes back where the menu was opened.
    s = press(m, ENTER, lambda s: s["activeKind"] == "confirm-cancel")
    check(f"remove question {size}: the question opens with Cancel focused", s["activeKind"] == "confirm-cancel", s)
    look(check, f"remove question {size}, Cancel", s, row_place=False)
    check(f"remove question {size}: Cancel fills with Enamel's focus fill (cream since 0.11.0) with dark text",
          s["pickerFill"] is not None and s["pickerFill"][0] == FILL and all(c == FILL_INK for c in s["pickerFill"][1:]), s)
    check(f"remove question {size}: Cancel, focused, is wholly in the window (the Enamel 0.8.0 upgrade)", s["pickerRowOnScreen"] is True, s)
    if size in ENAMEL_PICKER_GAP:
        # Enamel's picker doesn't fit this short a window; raised on
        # The responsive layout work for Enamel (needs enamel), never styled here.
        print(f"note remove question {size}: Enamel's picker is taller than the room above the hint bar "
              f"(an Enamel gap, the responsive layout work); fits: {s['pickerFits']}")
    else:
        check(f"remove question {size}: the picker is wholly on screen, nothing cut off, the layer meets the hint bar",
              s["pickerFits"] is True and s["hintOnTop"] is True, s)
        check(f"remove question {size}: nothing behind draws above the darkened layer, pictures included",
              s["layerOver"] is True, s)
    shot(m, shots_dir, f"lists-remove-question-{size}")
    s = press(m, "q", lambda s: s["activeKind"] == "tab")
    check(f"remove question {size}: B goes back to the tab the menu was opened from", s["activeKind"] == "tab", s)
    s = press(m, DOWN, lambda s: s["activeKind"] == "movie")
    look(check, f"{where}, first film", s)
    shot(m, shots_dir, f"lists-movies-{size}")
    # Down through the list: the long title, the missing film, the last row.
    # (The long title sorts first, by "Extremely": a leading An is ignored.)
    seen = set()
    for step in range(s["rowCount"]):
        if step:
            s = press(m, DOWN)
        if (s["activeTitle"] or "").startswith("An Extremely Long") and "long" not in seen:
            seen.add("long")
            look(check, f"{where}, the long title (shown in full while focused)", s)
            shot(m, shots_dir, f"lists-movies-long-title-{size}")
        if s["activeStatus"] == "missing" and "missing" not in seen:
            seen.add("missing")
            look(check, f"{where}, the missing film", s)
            shot(m, shots_dir, f"lists-movies-missing-{size}")
    check(f"{where}: the long title and the missing film were both reached", seen == {"long", "missing"}, seen)
    look(check, f"{where}, last row", s)
    # d shows the paths, and nothing is cut off with them on.
    s = press(m, "d", lambda s: s["pathsShown"])
    check(f"{where}: d shows the paths", s["pathsShown"], s)
    look(check, f"{where}, paths shown", s, row_place=False)
    s = press(m, "d", lambda s: not s["pathsShown"])
    check(f"{where}: d hides them again", not s["pathsShown"], s)

    # TV Shows: back up to the tabs, Right, then into the list and a show.
    for _ in range(s["rowCount"] + 1):
        s = press(m, UP)
        if s["activeKind"] == "tab":
            break
    s = press(m, RIGHT, lambda s: s["looks"] == ["tv"])
    look(check, f"tv {size}, tab", s)
    s = press(m, DOWN, lambda s: s["activeKind"] == "show")
    s = press(m, DOWN, lambda s: s["activeTitle"] == "Test Show")
    look(check, f"tv {size}, a show", s)
    shot(m, shots_dir, f"lists-tv-{size}")
    s = press(m, ENTER, lambda s: s["episodes"] and s["activeKind"] == "episode")
    check(f"episodes {size}: a show's episodes open", s["episodes"], s)
    look(check, f"episodes {size}, first episode (missing)", s)
    check(f"episodes {size}: the missing episode is marked", s["activeStatus"] == "missing" and s["missingRows"], s)
    shot(m, shots_dir, f"lists-episodes-{size}")
    for _ in range(s["rowCount"]):
        s = press(m, DOWN)
    look(check, f"episodes {size}, last episode", s)


def run(m, tmp, shots_dir, check):
    movies, tv, data = tmp / "Movies", tmp / "TV Shows", tmp / "data"
    for base, files in ((movies, MOVIES), (tv, TV_FILES)):
        for rel in files:
            (base / rel).parent.mkdir(parents=True, exist_ok=True)
            (base / rel).write_bytes(b"")
    frame = tmp / "frame.jpg"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=960x540",
                    "-frames:v", "1", str(frame)], check=True)
    layout.FRAME_JPG = frame.read_bytes()
    settings = {"movies_path": str(movies), "tv_path": str(tv), "mpv_command": "mpv", "mpv_args": [],
                "resume": True, "keep_awake": False, "data_dir": str(data)}
    app = layout.App(settings, tmp)
    try:
        m.send("WebDriver:Navigate", {"url": f"http://127.0.0.1:{app.port}/"})
        wait_state(m, lambda s: not s["loading"] and (s["library"] or s["firstScan"]), 30)
        m.press(ENTER)  # Open my library
        wait_state(m, lambda s: s["library"], 30)
        # A film and an episode go missing; a rescan marks them.
        (movies / GONE_FILM).unlink()
        (tv / GONE_EPISODE).unlink()
        m.press("r")
        wait_state(m, lambda s: s["library"] and s["toast"] == "2 missing", 20)
        app.items = layout.SIX
        for size, (w, h) in SIZES.items():
            m.send("WebDriver:Navigate", {"url": f"http://127.0.0.1:{app.port}/"})
            set_window(m, w, h)  # after the page opens: opening a page resets the zoom
            wait(m, lambda s: s["ready"] and not s["loading"] and s["activeKind"] == "tile", 20)
            inner = m.js("return [window.innerWidth, window.innerHeight];")
            check(f"{size}: the page is {w}x{h}", inner == [w, h], inner)
            walk(m, check, shots_dir, size)
    finally:
        app.stop()
        set_window(m, *WINDOW)


if __name__ == "__main__":
    sys.exit(main(run, prefix="design-system-lists-"))
