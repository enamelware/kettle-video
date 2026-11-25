# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Drive Home's actions in a real, headless Firefox (the Home actions work): the Menu
button at the top of Home (since the Home polish with no bar behind it: it scrolls
with the page), the menu (an Enamel picker), Start and
B, and scan progress in Enamel's toast. Not part of the unit tests: it
needs Firefox and takes about two minutes.

40 invented films and the invented shows, saved before the page opens.
Playing is faked; Quit is recorded instead of stopping the check's server
(tests/test_home_actions.py checks that it stops the real one). The scan
is slowed down so its progress can be seen. Cases:

  tiles    with two Continue watching tiles: Up from a tile reaches the
           bar and Down goes back to the same tile; at every window width
           (the Home polish) no black bar at the top, only the Menu button on the
           page, which scrolls away with the list while the tabs stay
           pinned to the top (in a short window they scroll away too, the responsive layout work),
           the focused row stays clear of the tabs, no sideways scrolling and
           one focused element, with screenshots of the bar, the scrolled
           list, the menu and the toast; Start from the middle of the list
           opens the menu on its first row, with Rescan library, Settings
           (the Settings screen work), Quit and Cancel, Quit drawn like the other rows
           while unfocused and in Enamel's red only with the focus (issue
           The Home polish, Enamel 0.13.1's destructive row); B and Escape in the menu
           close it without quitting and
           put the focus back; B on Home opens it on Quit; Rescan from the
           menu shows "Scanning…", counts files, then "No changes" and
           leaves after about three seconds, never taking the focus; the
           menu says "Scanning…" during a scan and doesn't start another;
           a scan that ends while the menu is open leaves the focus on the
           same film when the menu closes;
           a missing film: "1 missing", then "Remove 1 missing item" in
           the menu opens the remove question on Cancel; a failed scan
           says so; B then A quits
  notiles  no tiles: Up from the tabs reaches the bar, Down goes back to
           the tabs; Left and Right stay on Menu; A on Menu opens the
           menu; inside a show B goes back and Start still opens the menu.
           Enamel 0.11.0's press (the Enamel 0.11.0 upgrade): A held on a tab marks nothing; A
           held on Menu leaves neither Menu nor the menu's first row
           pressed once the menu opens, even as A repeats; A held on a
           menu row marks it, and nothing stays pressed once the focus is
           back on Menu or A comes up

Screenshots go to the folder given as the first argument.

Run from the repo root:  python3 tests/home_actions_check.py [screenshot-dir]
"""

import base64
import json
import os
import re
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

from backend import library_index  # noqa: E402
from backend.server import make_handler  # noqa: E402
from tests.home_shell_check import FILMS  # noqa: E402
from tests.loading_screen_check import UI_DIR, Marionette, free_port  # noqa: E402
from tests.test_parsed_library import TV_FILES  # noqa: E402
from tests.window_sizes import FIREFOX_FLAG, SIZES, WINDOW, set_window  # noqa: E402

ENTER, UP, DOWN, LEFT, RIGHT, ESCAPE = "", "", "", "", "", ""
SPACE, B, START = " ", "q", "m"

TILES = [
    {"id": "tile-one", "kind": "movie", "name": "Invented Film 01", "caption": "Invented Film 01 · Resume at 10:00",
     "position": 600, "duration": 5400, "missing": False},
    {"id": "tile-two", "kind": "movie", "name": "Invented Film 02", "caption": "Invented Film 02 · Resume at 20:00",
     "position": 1200, "duration": 5400, "missing": False},
]

STATE_JS = """
const visible = (el) => el && !el.hidden && getComputedStyle(el).display !== 'none' && !el.closest('[hidden]');
const box = (el) => { const r = el.getBoundingClientRect(); return {top: r.top, bottom: r.bottom, left: r.left, right: r.right, width: r.width, height: r.height}; };
const bar = document.getElementById('action-bar');
const strip = document.getElementById('tab-strip');
const hint = document.getElementById('hint-bar');
const menu = document.getElementById('home-menu');
const confirm = document.getElementById('confirm-remove');
const toast = document.getElementById('scan-toast');
const active = document.activeElement;
// Everything showing focus: the focused element, and anything marked
// data-focused (Enamel's own marker) that is on screen.
const focusedSet = new Set([...document.querySelectorAll('[data-focused="true"]')].filter(e => e.getClientRects().length));
if (active && active !== document.body) focusedSet.add(active);
const barBox = box(bar);
const button = bar.querySelector('[data-kind="menu"]');
const rows = [...document.querySelectorAll('.file-row')].filter(visible);
// Enamel's error red (--en-danger) and the page colour, read through a
// probe so no colour is written here (the Home polish: only a focused Quit is red;
// the Menu button has no bar of its own behind it).
const probe = document.createElement('div');
probe.style.backgroundColor = 'var(--en-danger)';
document.body.appendChild(probe);
const danger = getComputedStyle(probe).backgroundColor;
probe.style.backgroundColor = 'var(--en-surface-bar)';
const barColour = getComputedStyle(probe).backgroundColor;
probe.remove();
// Whose fill shows just left of the Menu button, at its middle: the first
// element there, or behind it, with a background of its own. The page
// itself (body or html), never a bar.
const beside = button && visible(bar) ? (() => {
  const b = box(button);
  let hit = document.elementFromPoint(Math.max(1, b.left - 8), b.top + b.height / 2);
  while (hit && hit !== document.documentElement && ['transparent', 'rgba(0, 0, 0, 0)'].includes(getComputedStyle(hit).backgroundColor)) hit = hit.parentElement;
  return hit ? hit.tagName : 'nothing';
})() : null;
return {
  library: visible(document.getElementById('library')),
  episodes: visible(document.getElementById('episodes')),
  loading: visible(document.getElementById('loading')),
  barShown: visible(bar),
  bar: barBox,
  barBg: getComputedStyle(bar).backgroundColor,
  barPosition: getComputedStyle(bar).position,
  barColour,
  beside,
  buttonBox: button ? box(button) : null,
  barButtons: [...bar.querySelectorAll('button')].map(b => b.textContent.trim()),
  buttonRight: button ? box(button).right : 0,
  strip: box(strip),
  hintTop: box(hint).top,
  hint: hint.innerText.replace(/\\s+/g, ' ').trim(),
  scrollY: window.scrollY,
  viewportW: document.documentElement.clientWidth,
  viewportH: window.innerHeight,
  overflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth,
  focusedCount: focusedSet.size,
  activeKind: active && active.dataset ? active.dataset.kind || null : null,
  activeTab: active && active.dataset ? active.dataset.tab || null : null,
  activeTile: active && active.classList.contains('continue-tile') ? active.dataset.id : null,
  activeKey: active && active.dataset ? active.dataset.key || null : null,
  activeBox: active && active !== document.body ? box(active) : null,
  menuOpen: menu.open && !menu.dataset.closing,
  menuRows: [...menu.querySelectorAll('.en-picker__row')].map(r => r.textContent.trim()),
  menuFocused: (menu.querySelector('.en-picker__row[data-focused="true"]') || {textContent: ''}).textContent.trim(),
  // The rows whose face is Enamel's red (the Home polish).
  danger,
  quitDestructive: [...menu.querySelectorAll('.en-picker__row--destructive')].map(r => r.textContent.trim()),
  menuRed: [...menu.querySelectorAll('.en-picker__row')].filter(r => getComputedStyle(r).backgroundColor === danger).map(r => r.textContent.trim()),
  // Each row's face colour, by its words, to compare Quit with the others.
  menuBg: Object.fromEntries([...menu.querySelectorAll('.en-picker__row')].map(r => [r.textContent.trim(), getComputedStyle(r).backgroundColor])),
  confirmOpen: confirm.open && !confirm.dataset.closing,
  confirmFocused: (confirm.querySelector('.en-picker__row[data-focused="true"]') || {dataset: {}}).dataset.kind || null,
  toastShown: visible(toast),
  toastText: toast.querySelector('.en-toast__text').textContent,
  toastBox: box(toast),
  toastHasFocus: toast.contains(active),
  toastPointer: getComputedStyle(toast).pointerEvents,
  rowCount: rows.length,
  missingRows: rows.filter(r => r.dataset.status === 'missing').length,
};
"""


TOAST_TIMES_JS = """
window.__toastTimes = {};
const toast = document.getElementById('scan-toast');
new MutationObserver(() => {
  const t = window.__toastTimes;
  if (!t.result && toast.textContent.trim() === 'No changes') t.result = performance.now();
  if (t.result && !t.hidden && toast.hidden) t.hidden = performance.now();
}).observe(toast, {attributes: true, childList: true, characterData: true, subtree: true});
return true;
"""


# Enamel 0.11.0's press (the Enamel 0.11.0 upgrade): what is marked data-pressed now.
PRESSED_JS = """
return [...document.querySelectorAll('[data-pressed]')].map(e => e.dataset.kind || e.textContent.trim());
"""
# A held key sends itself again (event.repeat), as Steam Input's A does.
REPEAT_JS = """
const t = document.activeElement || document.body;
t.dispatchEvent(new KeyboardEvent('keydown', {key: ' ', code: 'Space', repeat: true, bubbles: true, cancelable: true}));
return true;
"""
# Every menu row marked pressed from now on, even for a moment.
WATCH_ROWS_JS = """
window.__pressedRows = [];
// No old value: the attribute was added, not changed or removed.
new MutationObserver((records) => { for (const r of records) {
  if (r.oldValue === null) window.__pressedRows.push(r.target.textContent.trim()); } })
  .observe(document.getElementById('home-menu'), {attributes: true, attributeFilter: ['data-pressed'], attributeOldValue: true, subtree: true});
return true;
"""


def hold(m, key):
    """Key down, and kept down."""
    m.send("WebDriver:PerformActions", {"actions": [{"type": "key", "id": "kb", "actions": [{"type": "keyDown", "value": key}]}]})


def let_go(m, key):
    m.send("WebDriver:PerformActions", {"actions": [{"type": "key", "id": "kb", "actions": [{"type": "keyUp", "value": key}]}]})


def short_window(s):
    """Too short to keep two lines of tabs and the hint bar docked with two
    rows between them (20rem since the Home polish, without the docked bar): the tabs
    scroll with the page."""
    return s["viewportH"] < 20 * 16


def wait_state(m, predicate, timeout):
    end = time.time() + timeout
    while time.time() < end:
        state = m.js(STATE_JS)
        if predicate(state):
            return state
        time.sleep(0.1)
    return m.js(STATE_JS)


def shoot(m, shots_dir, name):
    (shots_dir / f"{name}.png").write_bytes(base64.b64decode(m.send("WebDriver:TakeScreenshot", {})["value"]))


def press(m, key, predicate=None, timeout=3):
    m.press(key)
    if predicate is None:
        time.sleep(0.3)
        return m.js(STATE_JS)
    return wait_state(m, predicate, timeout)


def one_focus(check, where, s):
    check(f"{where}: exactly one focused element", s["focusedCount"] == 1, s)


def check_tiles(m, shots_dir, check, app):
    s = wait_state(m, lambda s: s["library"] and not s["loading"] and s["activeTile"], 30)
    check("tiles: Home opens with the Menu button alone at the top right, focus on the first tile",
          s["barShown"] and s["barButtons"] == ["Menu"] and s["activeTile"] == "tile-one"
          and s["viewportW"] - s["buttonRight"] < 80 and s["bar"]["top"] == 0, s)
    check("tiles: no bar behind Menu (the Home polish): no fill of its own, not docked, the page beside it",
          s["barBg"] in ("transparent", "rgba(0, 0, 0, 0)") and s["barBg"] != s["barColour"]
          and s["barPosition"] == "static" and s["beside"] in ("BODY", "HTML"),
          [s["barBg"], s["barPosition"], s["beside"]])
    s = press(m, UP)
    check("tiles: Up from the first tile reaches the bar (Menu focused)", s["activeKind"] == "menu", s)
    one_focus(check, "tiles: on the bar", s)
    s = press(m, DOWN)
    check("tiles: Down from the bar goes back to the first tile", s["activeTile"] == "tile-one", s)
    s = press(m, RIGHT)
    s = press(m, UP)
    s = press(m, DOWN)
    check("tiles: from the second tile, Up then Down comes back to the second tile", s["activeTile"] == "tile-two", s)

    # Into the middle of the list.
    m.press(DOWN)  # the tabs
    for _ in range(18):
        m.press(DOWN)
    s = m.js(STATE_JS)
    key = s["activeKey"]
    check("tiles: the focus is on a film in the middle of the list", s["activeKind"] == "movie" and s["scrollY"] > 0, s)
    for size, (w, h) in SIZES.items():
        set_window(m, w, h)
        time.sleep(0.5)
        m.press(DOWN)
        m.press(UP)  # brings the focused row into view at this size
        time.sleep(0.3)
        s = m.js(STATE_JS)
        shoot(m, shots_dir, f"home-actions-scrolled-{size}")
        # The Home polish: the Menu button is not docked; it scrolled away with
        # the page, above the window.
        check(f"{size}: the Menu button scrolled away with the list, no bar left at the top",
              s["scrollY"] > 0 and s["barShown"] and s["bar"]["bottom"] <= 0.5, s)
        if short_window(s):
            check(f"{size}: in this short window the tabs scrolled away with the page too",
                  s["strip"]["bottom"] <= 0.5, s)
        else:
            check(f"{size}: the tab strip is pinned at the very top of the window",
                  abs(s["strip"]["top"]) < 1, s)
        fb = s["activeBox"]
        check(f"{size}: the focused row is clear of the bar, the tabs and the hint bar",
              fb is not None and fb["top"] >= max(s["strip"]["bottom"], 0) - 0.5 and fb["bottom"] <= s["hintTop"] + 0.5, s)
        check(f"{size}: no sideways scrolling", not s["overflowX"], s)
        one_focus(check, size, s)
        s = press(m, START, lambda s: s["menuOpen"])
        m.settle()
        shoot(m, shots_dir, f"home-actions-menu-{size}")
        check(f"{size}: Start from the middle of the list opens the menu on its first row",
              s["menuOpen"] and s["menuRows"] == ["Rescan library", "Settings", "Quit", "Cancel"]
              and s["menuFocused"] == "Rescan library", s)
        c = m.js(STATE_JS)  # the colours once the focus fade has ended
        check(f"{size}: Quit is Enamel's destructive row, the only one", c["quitDestructive"] == ["Quit"],
              c["quitDestructive"])
        check(f"{size}: Quit looks like the other rows while another row has the focus, nothing red",
              c["danger"] not in ("", "transparent", "rgba(0, 0, 0, 0)") and c["menuRed"] == []
              and c["menuBg"]["Quit"] == c["menuBg"]["Settings"], (c["danger"], c["menuRed"], c["menuBg"]))
        focused_bg = c["menuBg"]["Rescan library"]
        check(f"{size}: the menu fits without sideways scrolling", not s["overflowX"], s)
        one_focus(check, f"{size}: in the menu", s)
        s = press(m, B, lambda s: not s["menuOpen"])
        check(f"{size}: B in the menu closes it, focus back on the same film, nothing quits",
              not s["menuOpen"] and s["activeKey"] == key and not app["quit"], s)
    set_window(m, *WINDOW)
    time.sleep(0.5)

    s = press(m, B, lambda s: s["menuOpen"])
    check("B on Home opens the menu with Quit focused, and the hint bar says B Back",
          s["menuOpen"] and s["menuFocused"] == "Quit" and s["hint"].endswith("B BACK"), s)
    m.settle()
    c = m.js(STATE_JS)
    check("Quit with the focus on it is Enamel's red, the only red row (the Home polish)",
          c["menuRed"] == ["Quit"] and c["menuBg"]["Quit"] != focused_bg
          and c["menuBg"]["Settings"] != c["danger"], (c["menuRed"], c["menuBg"], focused_bg))
    for size, (w, h) in SIZES.items():
        set_window(m, w, h)
        time.sleep(0.4)
        c = m.js(STATE_JS)
        shoot(m, shots_dir, f"home-actions-quit-{size}")
        check(f"{size}: Quit focused is red, the only red row, the menu fits",
              c["menuOpen"] and c["menuFocused"] == "Quit" and c["menuRed"] == ["Quit"] and not c["overflowX"],
              (c["menuRed"], c["menuFocused"], c["overflowX"]))
    set_window(m, *WINDOW)
    time.sleep(0.4)
    s = press(m, B, lambda s: not s["menuOpen"])
    check("B again backs out: menu closed, nothing quits, the hint bar says B Quit again",
          not s["menuOpen"] and not app["quit"] and s["activeKey"] == key and s["hint"].endswith("B QUIT"), s)
    s = press(m, ESCAPE, lambda s: s["menuOpen"])
    check("Escape on Home opens the menu on Quit too", s["menuOpen"] and s["menuFocused"] == "Quit", s)
    s = press(m, ESCAPE, lambda s: not s["menuOpen"])
    check("Escape in the menu closes it without quitting", not s["menuOpen"] and not app["quit"], s)
    s = press(m, START, lambda s: s["menuOpen"])
    for _ in range(4):  # one more than the rows below Rescan library
        s = press(m, DOWN)
    check("Down in the menu stops at Cancel", s["menuFocused"] == "Cancel", s)
    s = press(m, ENTER, lambda s: not s["menuOpen"])
    check("Cancel closes the menu, focus back on the film", not s["menuOpen"] and s["activeKey"] == key, s)

    # Rescan from the menu: the toast counts, then says what changed. The
    # page notes when the result shows and when the toast is hidden.
    m.js(TOAST_TIMES_JS)
    scans_before = app["scans"]
    m.press(START)
    s = press(m, SPACE, lambda s: s["toastShown"])
    check("Rescan library closes the menu and starts the scan; the toast says Scanning…",
          not s["menuOpen"] and s["toastShown"] and s["toastText"].startswith("Scanning…"), s)
    check("the toast never takes the focus, and taps pass through it",
          not s["toastHasFocus"] and s["activeKey"] == key and s["toastPointer"] == "none", s)
    one_focus(check, "while the toast shows", s)
    m.settle()  # it slides in from the right edge
    s = m.js(STATE_JS)
    check("the toast sits at the bottom right, just above the hint bar",
          abs(s["toastBox"]["right"] - s["viewportW"]) < 1 and abs(s["toastBox"]["bottom"] - s["hintTop"]) < 1, s)
    s = press(m, START, lambda s: s["menuOpen"])
    check("while the scan runs the menu's first row reads Scanning…", s["menuRows"][0] == "Scanning…", s)
    s = press(m, SPACE, lambda s: not s["menuOpen"])
    s = wait_state(m, lambda s: re.fullmatch(r"Scanning… \d+ files", s["toastText"]), 10)
    check(f"the toast counts the files: {s['toastText']!r}", re.fullmatch(r"Scanning… \d+ files", s["toastText"]), s)
    for size, (w, h) in SIZES.items():
        set_window(m, w, h)
        time.sleep(0.2)
        s = m.js(STATE_JS)
        shoot(m, shots_dir, f"home-actions-toast-{size}")
        check(f"{size}: the toast fits, no sideways scrolling",
              not s["overflowX"] and s["toastBox"]["left"] >= 0 and s["toastBox"]["bottom"] <= s["hintTop"] + 1, s)
    set_window(m, *WINDOW)
    s = wait_state(m, lambda s: s["toastText"] == "No changes", 20)
    check("when the scan ends the toast says No changes", s["toastText"] == "No changes", s)
    check("choosing Scanning… started no second scan", app["scans"] == scans_before + 1, app["scans"])
    s = wait_state(m, lambda s: not s["toastShown"], 6)
    times = m.js("return window.__toastTimes;")
    gone = (times["hidden"] - times["result"]) / 1000 if times and times.get("hidden") and times.get("result") else -1
    check(f"then it leaves, about 3 seconds after the result showed ({gone:.1f} s)",
          not s["toastShown"] and 2.9 <= gone <= 4, [s, times])
    check("the focus stayed on the same film throughout", s["activeKey"] == key, s)

    # The menu open while a scan ends: the lists are drawn again behind it,
    # so the film it was opened from is a new copy; closing the menu still
    # puts the focus on that film (reviewer, round 1).
    m.press("r")
    wait_state(m, lambda s: s["toastShown"], 3)
    s = press(m, START, lambda s: s["menuOpen"])
    check("menu opened while a scan runs", s["menuOpen"] and s["menuRows"][0] == "Scanning…", s)
    s = wait_state(m, lambda s: s["toastText"] == "No changes", 20)
    check("the scan ends with the menu still open", s["menuOpen"] and s["toastText"] == "No changes", s)
    s = press(m, B, lambda s: not s["menuOpen"])
    check("B then closes the menu with the focus on the same film, shown",
          not s["menuOpen"] and s["activeKey"] == key and s["activeKind"] == "movie", s)
    one_focus(check, "after a scan ended under the menu", s)
    wait_state(m, lambda s: not s["toastShown"], 6)

    # A missing film: the result, then Remove in the menu.
    app["missing_file"].unlink()
    m.press("r")
    s = wait_state(m, lambda s: s["toastText"] == "1 missing", 20)
    check("r still rescans; a film gone missing: the toast says 1 missing", s["toastText"] == "1 missing", s)
    s = press(m, START, lambda s: s["menuOpen"])
    check("with something missing the menu has Remove 1 missing item, between Rescan and Quit",
          s["menuRows"] == ["Rescan library", "Remove 1 missing item", "Settings", "Quit", "Cancel"], s)
    m.press(DOWN)
    s = press(m, SPACE, lambda s: s["confirmOpen"])
    check("Remove 1 missing item opens the remove question, Cancel focused first",
          s["confirmOpen"] and not s["menuOpen"] and s["confirmFocused"] == "confirm-cancel", s)
    one_focus(check, "on the remove question", s)
    s = press(m, B, lambda s: not s["confirmOpen"])
    check("B on the question closes it, nothing removed, focus back on the film",
          not s["confirmOpen"] and s["missingRows"] == 1 and s["activeKey"] == key and not app["quit"], s)

    # A failed scan says so.
    app["fail"] = True
    m.press("r")
    s = wait_state(m, lambda s: s["toastText"].startswith("Couldn't"), 20)
    check(f"a failed scan says so: {s['toastText']!r}",
          s["toastText"] == "Couldn't scan the library. The saved library is unchanged.", s)
    app["fail"] = False

    # B then A quits.
    m.press(B)
    s = wait_state(m, lambda s: s["menuOpen"], 3)
    m.press(SPACE)
    end = time.time() + 5
    while not app["quit"] and time.time() < end:
        time.sleep(0.1)
    check("B then A quits: the page asks the server to stop", app["quit"] == 1, app["quit"])


def check_notiles(m, shots_dir, check, app):
    s = wait_state(m, lambda s: s["library"] and not s["loading"] and s["activeTab"], 30)
    check("notiles: Home opens on the Movies tab, the bar above", s["activeTab"] == "movies" and s["barShown"], s)
    for size, (w, h) in SIZES.items():
        set_window(m, w, h)
        time.sleep(0.4)
        s = m.js(STATE_JS)
        shoot(m, shots_dir, f"home-actions-home-{size}")
        check(f"notiles: {size}: Menu at the top right of the page, inside the window, no bar behind it",
              s["bar"]["top"] == 0 and s["buttonBox"]["top"] >= 0 and s["buttonRight"] <= s["viewportW"]
              and s["barBg"] in ("transparent", "rgba(0, 0, 0, 0)") and s["beside"] in ("BODY", "HTML"), s)
        check(f"notiles: {size}: no sideways scrolling", not s["overflowX"], s)
    set_window(m, *WINDOW)
    time.sleep(0.4)
    # A held on a tab (the Enamel 0.11.0 upgrade): only buttons and menu rows show Enamel's press.
    hold(m, SPACE)
    time.sleep(0.2)
    held = m.js(PRESSED_JS)
    let_go(m, SPACE)
    check("notiles: A held on the Movies tab marks nothing pressed", held == [], held)
    s = press(m, UP)
    check("notiles: Up from the tabs (no carousel) reaches the bar", s["activeKind"] == "menu", s)
    s = press(m, LEFT)
    s = press(m, RIGHT)
    check("notiles: Left and Right stay on Menu, its only button", s["activeKind"] == "menu", s)
    one_focus(check, "notiles: on the bar", s)
    # A held on Menu (Enamel 0.11.0's press, the Enamel 0.11.0 upgrade): the menu opens on the
    # press and the focus moves into it, so neither Menu nor the menu's first
    # row looks pressed while A is still down, even as the held key repeats.
    hold(m, SPACE)
    s = wait_state(m, lambda s: s["menuOpen"], 3)
    held = m.js(PRESSED_JS)
    m.js(REPEAT_JS)
    time.sleep(0.2)
    repeated = m.js(PRESSED_JS)
    s_repeat = m.js(STATE_JS)
    let_go(m, SPACE)
    time.sleep(0.2)
    s = m.js(STATE_JS)
    check("notiles: A on Menu opens the menu on its first row", s["menuOpen"] and s["menuFocused"] == "Rescan library", s)
    check("notiles: A held on Menu: once the menu opens nothing looks pressed, Menu or its first row",
          held == [], held)
    check("notiles: A held and repeating in the menu: still nothing pressed, nothing chosen",
          repeated == [] and s_repeat["menuOpen"] and s_repeat["menuFocused"] == "Rescan library", [repeated, s_repeat])
    check("notiles: A let go: nothing pressed", m.js(PRESSED_JS) == [], m.js(PRESSED_JS))
    s = press(m, B, lambda s: not s["menuOpen"])
    check("notiles: B closes it and the focus goes back to Menu", not s["menuOpen"] and s["activeKind"] == "menu", s)
    # A held on a menu row: the row is marked pressed (it is chosen on the
    # press, which closes the menu), and once the focus is back on Menu
    # nothing is left pressed, Menu included, while A is still down.
    s = press(m, SPACE, lambda s: s["menuOpen"])
    m.js(WATCH_ROWS_JS)
    press(m, DOWN)
    press(m, DOWN)
    s = press(m, DOWN)
    check("notiles: Down three times in the menu reaches Cancel (Settings since the Settings screen work)", s["menuFocused"] == "Cancel", s)
    hold(m, SPACE)
    s = wait_state(m, lambda s: not s["menuOpen"], 3)
    held = m.js(PRESSED_JS)
    let_go(m, SPACE)
    time.sleep(0.2)
    marked = m.js("return window.__pressedRows;")
    after = m.js(STATE_JS)
    check("notiles: A held on Cancel marks that row pressed (Enamel's press)", marked == ["Cancel"], marked)
    check("notiles: Cancel closes the menu, focus on Menu, which doesn't look pressed though A is still down",
          not s["menuOpen"] and s["activeKind"] == "menu" and held == [], [held, s])
    check("notiles: A coming up on Menu doesn't open the menu again",
          not after["menuOpen"] and after["activeKind"] == "menu", after)
    check("notiles: after A comes up nothing is pressed", m.js(PRESSED_JS) == [], m.js(PRESSED_JS))
    s = press(m, DOWN)
    check("notiles: Down from the bar goes back to the tabs", s["activeTab"] == "movies", s)
    # Inside a show: B goes back, Start opens the menu.
    m.press(RIGHT)
    m.press(DOWN)
    s = press(m, ENTER, lambda s: s["episodes"])
    check("notiles: a show's episodes keep the bar", s["episodes"] and s["barShown"], s)
    s = press(m, START, lambda s: s["menuOpen"])
    check("notiles: Start opens the menu inside a show", s["menuOpen"] and s["menuFocused"] == "Rescan library", s)
    s = press(m, B, lambda s: not s["menuOpen"])
    s = press(m, B, lambda s: not s["episodes"])
    check("notiles: B inside a show goes back to the list, no menu",
          not s["episodes"] and s["library"] and not s["menuOpen"] and not app["quit"], s)


def run_case(case, env, profile, shots_dir, check):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for base, files in ((tmp / "Movies", FILMS), (tmp / "TV Shows", TV_FILES)):
            for rel in files:
                (base / rel).parent.mkdir(parents=True, exist_ok=True)
                (base / rel).write_bytes(b"")
        settings = {"movies_path": str(tmp / "Movies"), "tv_path": str(tmp / "TV Shows"),
                    "mpv_command": "mpv", "mpv_args": [], "data_dir": str(tmp / "data")}
        roots = {"movies": settings["movies_path"], "tv": settings["tv_path"]}
        real_scan = library_index.full_scan
        index = real_scan(roots, None, lambda done, total: None)
        library_index.save(Path(settings["data_dir"]) / library_index.FILE_NAME, index)
        app = {"quit": 0, "scans": 0, "fail": False,
               "missing_file": tmp / "Movies" / FILMS[30]}

        # Slowed down, so the toast's progress can be seen: each progress
        # step stays a little over a second.
        def slow_scan(roots, previous, progress):
            app["scans"] += 1
            time.sleep(1.2)
            if app["fail"]:
                raise OSError("a failed scan, for the check")

            def slow_progress(done, total):
                progress(done, total)
                time.sleep(1.2)
            return real_scan(roots, previous, slow_progress)

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        port = httpd.server_address[1]
        base = make_handler(UI_DIR, tmp, settings, {"server": httpd}, port)

        class Handler(base):
            def log_message(self, format, *args):
                pass

            def _handle_mpv_status(self):
                self._send_json(HTTPStatus.OK, {"available": True})

            def _handle_continue(self):
                self._send_json(HTTPStatus.OK, {"items": TILES if case == "tiles" else []})

            def _handle_shutdown(self):
                app["quit"] += 1
                self._send_json(HTTPStatus.OK, {"ok": True})

        httpd.RequestHandlerClass = Handler
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
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
            with mock.patch.object(library_index, "full_scan", side_effect=slow_scan):
                m = Marionette(mport)
                m.send("WebDriver:Navigate", {"url": f"http://127.0.0.1:{port}/"})
                set_window(m, *WINDOW)
                if case == "tiles":
                    check_tiles(m, shots_dir, check, app)
                else:
                    check_notiles(m, shots_dir, check, app)
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
    shots_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="home-actions-"))
    shots_dir.mkdir(parents=True, exist_ok=True)
    results = []

    def check(text, ok, detail=None):
        results.append((text if ok or detail is None else f"{text}: {json.dumps(detail, default=str)}", bool(ok)))

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        home = Path(tmp) / "home"
        env = dict(os.environ, HOME=str(home), MOZ_HEADLESS="1")
        for case in ("tiles", "notiles"):
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
