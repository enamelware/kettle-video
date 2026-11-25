# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Drive the Movies list in a real, headless Firefox (the Movies list work). Not part
of the unit tests: it needs Firefox and takes about a minute.

Uses the Marionette helper from loading_screen_check.py; playing is faked
(the request is recorded and mpv never starts). Cases:

  fixture  ?fixture=2000 (2,000 invented films), at the narrowest and the
           widest window in tests/window_sizes.py (the responsive layout work): draw and
           letter-jump times (under 300 ms), every row drawn, long titles on
           two lines with "…" and in full when focused, the list not jumping
           as the focus moves, Left and Right by letter (empty letters
           skipped, nothing at either end), Left and Right still switching
           tabs on the tab strip, Up from the first row to the tabs, the
           letter strip (only letters with films, the current one marked,
           never focused, a tap jumps, ending where the hint bar starts:
           The Enamel 0.6.0 upgrade), a tap on a film playing it by ID and
           the focus coming back to it, no sideways scroll, the year apart
           from the title, Enamel's row colours (the third design system step: text titles,
           muted years; on the focused film a strong title, soft year and
           the lift to the control surface), Left and Right
           doing nothing inside the TV Shows list; screenshots
  real     the real folders from settings.json (read-only): the films in the
           back end's order with the right groups, alphabetical inside each
           group, a leading The, A or An ignored (the title sorting work); the TV shows
           in the same order rule; screenshots

Screenshots go to the folder given as the first argument.

Run from the repo root:  python3 tests/movies_list_check.py [screenshot-dir]
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
import re
import unicodedata
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from backend import library_index, library_order  # noqa: E402
from backend.server import make_handler  # noqa: E402
from backend.settings import load_settings  # noqa: E402

# Enamel's row colours (the third design system step): --en-text, --en-text-muted, and on the
# focused row --en-text-strong, --en-text-soft and --en-surface-control.
KT_TEXT = "rgb(220, 222, 223)"
KT_MUTED = "rgb(139, 146, 154)"
KT_STRONG = "rgb(255, 255, 255)"
KT_SOFT = "rgb(184, 188, 191)"
KT_CONTROL = "rgb(61, 68, 80)"
from tests.loading_screen_check import UI_DIR, Marionette, free_port  # noqa: E402
from tests.window_sizes import SIZES, set_window, FIREFOX_FLAG  # noqa: E402
from tests.test_parsed_library import TV_FILES  # noqa: E402

# WebDriver key codes.
ENTER, UP, DOWN, LEFT, RIGHT = "\ue007", "\ue013", "\ue015", "\ue012", "\ue014"
DRAW_LIMIT_MS = 300
FILMS = [f"Invented Film {n:02d} ({1980 + n})/Invented.Film.{n:02d}.{1980 + n}.mkv" for n in range(1, 6)]

STATE_JS = """
const visible = (el) => el && !el.hidden && getComputedStyle(el).display !== 'none' && !el.closest('[hidden]');
const active = document.activeElement;
const isRow = active && active.classList.contains('file-row');
const strip = document.querySelector('.letter-strip');
const stripBox = strip.getBoundingClientRect();
const rows = [...document.querySelectorAll('#library .file-row')].filter(visible);
const movieRows = rows.filter(r => r.dataset.kind === 'movie');
const measures = (name) => performance.getEntriesByName(name).map(e => e.duration);
return {
  loading: visible(document.getElementById('loading')),
  library: visible(document.getElementById('library')),
  selectedTab: (document.querySelector('.tab[aria-selected="true"]') || {dataset: {}}).dataset.tab,
  focusedTab: active && active.dataset ? active.dataset.tab || null : null,
  focusedKind: isRow ? active.dataset.kind : null,
  focusedIndex: rows.indexOf(active),
  focusedLetter: isRow ? active.dataset.letter || null : null,
  focusedId: isRow ? active.dataset.id || null : null,
  focusedTop: isRow ? active.getBoundingClientRect().top : null,
  focusedBottom: isRow ? active.getBoundingClientRect().bottom : null,
  rows: rows.length,
  movieRows: movieRows.length,
  rowLetters: movieRows.map(r => r.dataset.letter),
  rowTitles: movieRows.map(r => r.querySelector('.row-title').textContent),
  rowYears: movieRows.map(r => (r.querySelector('.row-year') || {textContent: ''}).textContent),
  // The Home shell look on film rows (a sample, to stay quick at 2,000).
  focusedTextColours: isRow ? [...active.querySelectorAll('span')].filter(visible).filter(e => e.children.length === 0 && e.textContent.trim()).map(e => getComputedStyle(e).color) : [],
  focusShadow: active ? getComputedStyle(active).boxShadow : '',
  focusBg: active ? getComputedStyle(active).backgroundColor : '',
  focusedTitleColour: isRow && active.querySelector('.row-title') ? getComputedStyle(active.querySelector('.row-title')).color : '',
  unfocusedYearColours: movieRows.filter(r => r !== active).slice(0, 40).map(r => r.querySelector('.row-year')).filter(Boolean).map(e => getComputedStyle(e).color),
  unfocusedTitleColours: movieRows.filter(r => r !== active).slice(0, 40).map(r => getComputedStyle(r.querySelector('.row-title')).color),
  stripShown: visible(strip),
  stripLetters: [...strip.children].map(c => c.dataset.letter),
  stripText: [...strip.children].map(c => c.textContent),
  stripCurrent: [...strip.querySelectorAll('[aria-current="true"]')].map(c => [c.dataset.letter, getComputedStyle(c).fontWeight]),
  stripFocusable: [...strip.querySelectorAll('*')].some(c => c.tabIndex >= 0) || strip.tabIndex >= 0,
  stripLeft: stripBox.left,
  stripRight: stripBox.right,
  stripBottom: stripBox.bottom,
  // The Enamel 0.6.0 upgrade: the strip stops where Enamel's hint bar (now its own,
  // taller height) starts, neither under it nor short of it.
  hintTop: document.getElementById('hint-bar').getBoundingClientRect().top,
  // Right edge of the widest visible row: the strip must not cover rows.
  rowsRight: Math.max(0, ...rows.filter(r => { const b = r.getBoundingClientRect(); return b.bottom > 0 && b.top < innerHeight; }).map(r => r.getBoundingClientRect().right)),
  viewportW: document.documentElement.clientWidth,
  viewportH: innerHeight,
  overflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth,
  draw: measures('Movies list: draw'),
  drawFrame: measures('Movies list: draw to next frame'),
  jump: measures('Movies list: jump'),
  jumpFrame: measures('Movies list: jump to next frame'),
  banner: visible(document.getElementById('error-banner')) ? document.getElementById('error-banner').textContent : null,
  playing: visible(document.getElementById('playing-status')),
};
"""

# The title of row i (a movie row index): lines shown, and whether it is cut.
TITLE_JS = """
const row = [...document.querySelectorAll('#library .file-row[data-kind="movie"]')][arguments[0]];
const t = row.querySelector('.row-title');
const lh = parseFloat(getComputedStyle(t).lineHeight) || parseFloat(getComputedStyle(t).fontSize) * 1.2;
return {lines: Math.round(t.getBoundingClientRect().height / lh), cut: t.scrollHeight > t.clientHeight + 1,
        overflow: getComputedStyle(t).textOverflow, clamp: getComputedStyle(t).webkitLineClamp,
        text: t.textContent, focused: document.activeElement === row};
"""

LONG_INDEX_JS = """
const rows = [...document.querySelectorAll('#library .file-row[data-kind="movie"]')];
return rows.findIndex((r, i) => { const t = r.querySelector('.row-title');
  return i > 3 && r !== document.activeElement && t.scrollHeight > t.clientHeight + 1; });
"""

CENTRE_JS = """
const el = document.querySelector(arguments[0]);
el.scrollIntoView({block: 'nearest'});
const r = el.getBoundingClientRect();
return [Math.round(r.left + r.width / 2), Math.round(r.top + r.height / 2)];
"""


def start_server(settings, logs_dir, played):
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


def press(m, key, times=1):
    for _ in range(times):
        m.press(key)
    time.sleep(0.15)
    return m.js(STATE_JS)


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
    time.sleep(0.4)


def shot(m, shots_dir, name):
    (shots_dir / f"movies-{name}.png").write_bytes(
        base64.b64decode(m.send("WebDriver:TakeScreenshot", {"full": False})["value"]))


def first_index_of(letters, letter):
    return letters.index(letter)


def check_fixture(m, shots_dir, check, played, size, timings):
    s = wait_state(m, lambda s: s["library"] and not s["loading"] and s["draw"], 60)
    check(f"{size}: 2,000 invented films, every row drawn", s["movieRows"] == 2000, s["movieRows"])
    draw = s["draw"][-1] if s["draw"] else None
    timings.append(f"{size}: draw {draw:.0f} ms, {s['drawFrame'][-1]:.0f} ms to the next frame"
                   if draw is not None else f"{size}: no draw time")
    check(f"{size}: 2,000 rows drawn in {draw and round(draw)} ms (limit {DRAW_LIMIT_MS})",
          draw is not None and draw < DRAW_LIMIT_MS, s["draw"])
    groups = list(dict.fromkeys(s["rowLetters"]))
    check(f"{size}: groups in order #, A to Z, other",
          [library_order.GROUPS.index(g) for g in groups] == sorted(library_order.GROUPS.index(g) for g in groups)
          and groups[0] == "#" and groups[-1] == "other", groups)
    check(f"{size}: the letter strip lists only letters with films, other shown as …",
          s["stripShown"] and s["stripLetters"] == groups and s["stripText"][-1] == "…", s["stripLetters"])
    check(f"{size}: the strip is never focusable", not s["stripFocusable"])
    check(f"{size}: the strip sits on the right edge and covers no row",
          abs(s["stripRight"] - s["viewportW"]) < 2 and s["rowsRight"] <= s["stripLeft"] + 1,
          [s["stripLeft"], s["stripRight"], s["rowsRight"], s["viewportW"]])
    check(f"{size}: the strip ends where the hint bar starts (the Enamel 0.6.0 upgrade)",
          abs(s["stripBottom"] - s["hintTop"]) < 1, [s["stripBottom"], s["hintTop"]])
    check(f"{size}: no sideways scroll", not s["overflowX"])
    check(f"{size}: the year sits apart from the title, never inside it",
          any(s["rowYears"]) and not any(t.rstrip().endswith(")") and t.rstrip()[-5:-1].isdigit()
                                         for t in s["rowTitles"]),
          [t for t in s["rowTitles"] if t.rstrip().endswith(")")][:5])
    check(f"{size}: on rows not focused the title is Enamel's text and the year muted",
          s["unfocusedTitleColours"] and set(s["unfocusedTitleColours"]) == {KT_TEXT}
          and s["unfocusedYearColours"] and set(s["unfocusedYearColours"]) == {KT_MUTED},
          [sorted(set(s["unfocusedTitleColours"])), sorted(set(s["unfocusedYearColours"]))])

    # Down into the list (its first film since the Home actions work: no Rescan row), Up back to the tabs.
    s = press(m, DOWN)
    check(f"{size}: Down from the tabs goes to the first film",
          s["focusedKind"] == "movie" and s["focusedIndex"] == 0, s["focusedKind"])
    s = press(m, UP)
    check(f"{size}: Up from the first row goes back to the tabs", s["focusedTab"] == "movies", s["focusedTab"])
    s = press(m, RIGHT)
    check(f"{size}: Right on the tab strip still switches to TV Shows", s["selectedTab"] == "tv", s["selectedTab"])
    # The TV Shows list keeps Left and Right as they were: no letter jumps.
    s = press(m, DOWN, 2)
    on_show = (s["focusedKind"], s["focusedIndex"])
    s = press(m, RIGHT)
    check(f"{size}: Right inside the TV Shows list does nothing",
          on_show[0] == "show" and (s["focusedKind"], s["focusedIndex"]) == on_show and s["selectedTab"] == "tv",
          [on_show, s["focusedKind"], s["focusedIndex"], s["selectedTab"]])
    s = press(m, LEFT)
    check(f"{size}: Left inside the TV Shows list does nothing",
          (s["focusedKind"], s["focusedIndex"]) == on_show and s["selectedTab"] == "tv",
          [on_show, s["focusedKind"], s["focusedIndex"], s["selectedTab"]])
    s = press(m, UP, 2)
    check(f"{size}: Up from the TV Shows list goes back to the tabs", s["focusedTab"] == "tv", s["focusedTab"])
    s = press(m, LEFT)
    check(f"{size}: Left on the tab strip switches back to Movies", s["selectedTab"] == "movies", s["selectedTab"])

    # Letter jumps.
    s = press(m, DOWN)
    s = press(m, LEFT)
    check(f"{size}: Left on the first film (first group) does nothing",
          s["focusedKind"] == "movie" and s["focusedIndex"] == 0, s["focusedKind"])
    seen = [(s["focusedLetter"], s["focusedIndex"])]
    for _ in range(len(groups) - 1):
        s = press(m, RIGHT)
        seen.append((s["focusedLetter"], s["focusedIndex"]))
    letters = s["rowLetters"]
    offset = s["rows"] - s["movieRows"]
    expected = [(g, first_index_of(letters, g) + offset) for g in groups]
    check(f"{size}: Right goes through every letter with films, onto each first film", seen == expected,
          {"seen": seen[:5], "expected": expected[:5]})
    s = press(m, RIGHT)
    check(f"{size}: Right in the last group does nothing", s["focusedLetter"] == groups[-1]
          and s["focusedIndex"] == expected[-1][1], s["focusedIndex"])
    check(f"{size}: the strip marks the current letter in bold",
          s["stripCurrent"] and s["stripCurrent"][0][0] == groups[-1] and int(s["stripCurrent"][0][1]) >= 600,
          s["stripCurrent"])
    s = press(m, DOWN, 3)
    s = press(m, LEFT)
    check(f"{size}: Left goes to the first film of the previous letter",
          (s["focusedLetter"], s["focusedIndex"]) == expected[-2], (s["focusedLetter"], s["focusedIndex"]))
    s = press(m, LEFT, len(groups))
    check(f"{size}: Left in the first group does nothing",
          (s["focusedLetter"], s["focusedIndex"]) == expected[0], (s["focusedLetter"], s["focusedIndex"]))
    jumps = s["jump"]
    timings.append(f"{size}: letter jump median {sorted(jumps)[len(jumps) // 2]:.1f} ms, slowest {max(jumps):.1f} ms, "
                   f"slowest to next frame {max(s['jumpFrame']):.1f} ms")
    check(f"{size}: letter jumps under {DRAW_LIMIT_MS} ms (slowest {max(jumps):.1f} ms)", max(jumps) < DRAW_LIMIT_MS)

    # Long titles: two lines with "…" until focused, in full when focused.
    long_index = m.js(LONG_INDEX_JS)
    if long_index < 0:
        # On a page this wide no invented title needs a third line.
        print(f"  {size}: no title is cut at two lines at this width, so the long-title steps are skipped")
    else:
        t = m.send("WebDriver:ExecuteScript", {"script": TITLE_JS, "args": [long_index]})["value"]
        check(f"{size}: an unfocused long title shows two lines, cut with …",
              t["lines"] == 2 and t["cut"] and not t["focused"], t)
        # Focus the row just above it, then move Down onto it.
        target = long_index + offset
        s = press(m, UP, s["focusedIndex"])  # onto the first film (row 0)
        s = press(m, DOWN, target - 1)  # onto the row just above the long one
        before_top = m.js(f"return document.querySelectorAll('#library .file-row')[{target}].getBoundingClientRect().top;")
        s = press(m, DOWN)
        t = m.send("WebDriver:ExecuteScript", {"script": TITLE_JS, "args": [long_index]})["value"]
        check(f"{size}: the focused long title shows in full", t["focused"] and not t["cut"] and t["lines"] >= 2, t)
        # A focused title taller than a short window can't stay in place and
        # wholly on screen; its top is shown instead (the responsive layout work).
        check(f"{size}: moving onto it keeps it in place (no jump)", abs(s["focusedTop"] - before_top) < 1.5
              or s["focusedBottom"] <= s["viewportH"] or (-0.5 <= s["focusedTop"] <= 8 and s["focusedBottom"] > s["viewportH"]),
              [before_top, s["focusedTop"]])
        shot(m, shots_dir, f"long-title-focused-{size}")
        top_on_long = s["focusedTop"]
        s = press(m, DOWN)
        t = m.send("WebDriver:ExecuteScript", {"script": TITLE_JS, "args": [long_index]})["value"]
        check(f"{size}: leaving it, the title is two lines with … again", t["lines"] == 2 and t["cut"], t)
        shot(m, shots_dir, f"long-title-unfocused-{size}")
        check(f"{size}: moving down past it, the list doesn't jump back (focused row below where it was)",
              s["focusedTop"] >= top_on_long, [top_on_long, s["focusedTop"]])

    # A tap on the strip jumps; the strip never takes the focus.
    letter = "M" if "M" in groups else groups[len(groups) // 2]
    x, y = m.send("WebDriver:ExecuteScript", {"script": CENTRE_JS,
                                               "args": [f'.letter-strip-letter[data-letter="{letter}"]']})["value"]
    tap(m, x, y)
    s = m.js(STATE_JS)
    check(f"{size}: tapping {letter} on the strip jumps to its first film",
          (s["focusedLetter"], s["focusedIndex"]) == dict((g, (g, i)) for g, i in expected)[letter],
          (s["focusedLetter"], s["focusedIndex"]))
    check(f"{size}: the focused film lifts to the control surface, title strong, year and labels soft",
          s["focusedKind"] == "movie" and len(s["focusedTextColours"]) >= 2
          and s["focusedTitleColour"] == KT_STRONG
          and set(s["focusedTextColours"]) == {KT_STRONG, KT_SOFT} and s["focusBg"] == KT_CONTROL,
          [s["focusedTextColours"], s["focusedTitleColour"], s["focusBg"]])
    shot(m, shots_dir, f"list-{size}")

    # A on a film plays it by ID; a tap on another film plays it too; the
    # focus comes back to the same row.
    played.clear()
    focused_id, focused_index = s["focusedId"], s["focusedIndex"]
    s = press(m, ENTER)
    s = wait_state(m, lambda s: not s["playing"], 10)
    check(f"{size}: A plays the focused film by its ID, not its location",
          played and played[-1] == {"source": "movies", "id": focused_id}, played)
    check(f"{size}: after the film, the focus is back on the same row", s["focusedIndex"] == focused_index, s)
    played.clear()
    x, y = m.send("WebDriver:ExecuteScript", {"script": CENTRE_JS,
                                               "args": [f'#library .file-row[data-kind="movie"]:nth-child({focused_index - offset + 3})']})["value"]
    tap(m, x, y)
    s = wait_state(m, lambda s: not s["playing"], 10)
    check(f"{size}: tapping a film plays it, and the focus stays on it",
          played and played[-1].get("id") == s["focusedId"] and s["focusedIndex"] == focused_index + 2, [played, s["focusedIndex"]])


def check_real(m, shots_dir, check, index, roots):
    s = wait_state(m, lambda s: s["library"] and not s["loading"], 30)
    shown = library_index.render(index, roots)["movies"]["items"]
    from_titles = [library_order.letter_group(i["display_title"]) for i in shown]
    check(f"real: {len(shown)} films listed in the back end's order",
          s["movieRows"] == len(shown) and s["rowLetters"] == [i["letter"] for i in shown], s["movieRows"])
    groups = [i["letter"] for i in shown]
    ranks = [library_order.GROUPS.index(g) for g in groups]
    check("real: groups in order", ranks == sorted(ranks), list(dict.fromkeys(groups)))
    check("real: every film's group matches its title", from_titles == groups,
          [(i["display_title"], i["letter"]) for i, g in zip(shown, from_titles) if g != i["letter"]])
    # Inside each group, titles run alphabetically ignoring capitals,
    # accents and a leading The, A or An (checked here with a plain key of its own, on the saved titles).
    saved = {i["id"]: i for i in index["sources"]["movies"]["items"]}

    # Ø, Ł, Æ, Đ, Ð, ß, Œ, Þ count as their nearest plain letter (the designer's
    # decision on the Movies list work), so "Ørsted" sorts among the O titles.
    nearest = str.maketrans({"ø": "o", "ł": "l", "æ": "a", "đ": "d", "ð": "d", "ß": "s", "œ": "o", "þ": "t"})

    def plain(title):
        swapped = title.lower().translate(nearest)  # before casefold, which turns ß into ss
        folded = "".join(c for c in unicodedata.normalize("NFKD", swapped) if not unicodedata.combining(c)).casefold()
        # A leading The, A or An is ignored (the title sorting work), once, when a letter or digit follows.
        return re.sub(r"^(the|an|a) +(?=.*[^\W_])", "", folded.strip())

    out_of_order = [(a["display_title"], b["display_title"]) for a, b in zip(shown, shown[1:])
                    if a["letter"] == b["letter"] and plain(saved[a["id"]]["title"]) > plain(saved[b["id"]]["title"])]
    check("real: inside each group, alphabetical ignoring capitals and accents", not out_of_order, out_of_order[:5])

    # TV Shows tab (the title sorting work): shows follow the same rule, so "The Oakhollow"
    # sits with the O titles. Shows have no letter groups and no nearest-letter
    # swap, so the plain key here only folds capitals and accents and drops
    # a leading The, A or An.
    def plain_show(title):
        folded = "".join(c for c in unicodedata.normalize("NFKD", title) if not unicodedata.combining(c)).casefold()
        return re.sub(r"^(the|an|a) +(?=.*[^\W_])", "", folded.strip())

    saved_shows = {i["id"]: i for i in index["sources"].get("tv", {}).get("items", [])}
    shows = library_index.render(index, roots)["tv"]["items"]
    shows_out_of_order = [(a["display_title"], b["display_title"]) for a, b in zip(shows, shows[1:])
                          if plain_show(saved_shows[a["id"]]["title"]) > plain_show(saved_shows[b["id"]]["title"])]
    check(f"real: {len(shows)} TV shows in order, ignoring capitals, accents and a leading The, A or An",
          not shows_out_of_order, shows_out_of_order[:5])
    articled = [s["display_title"] for s in shows if re.match(r"(?i)(the|an|a) +\w", s["display_title"])]
    print(f"  (real TV shows starting with The, A or An: {len(articled)})")
    for size, (w, h) in SIZES.items():
        set_window(m, w, h)
        time.sleep(0.5)
        m.press(DOWN)
        m.press(DOWN)
        time.sleep(0.2)
        shot(m, shots_dir, f"real-{size}")
        s = m.js(STATE_JS)
        check(f"real {size}: no sideways scroll, strip covers no row",
              not s["overflowX"] and s["rowsRight"] <= s["stripLeft"] + 1, [s["rowsRight"], s["stripLeft"]])
        m.press(UP)
        m.press(UP)


def run_case(case, size, env, profile, shots_dir, check, timings):
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
        roots = {"movies": settings["movies_path"], "tv": settings["tv_path"]}
        index = library_index.full_scan(roots, None, lambda done, total: None)
        library_index.save(Path(settings["data_dir"]) / library_index.FILE_NAME, index)
        played = []
        httpd, port = start_server(settings, tmp, played)
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
            set_window(m, *SIZES[size])
            query = "?fixture=2000" if case == "fixture" else ""
            m.send("WebDriver:Navigate", {"url": f"http://127.0.0.1:{port}/{query}"})
            set_window(m, *SIZES[size])  # again: opening a page resets the zoom
            if case == "fixture":
                check_fixture(m, shots_dir, check, played, size, timings)
            else:
                check_real(m, shots_dir, check, index, roots)
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
    shots_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="movies-list-"))
    shots_dir.mkdir(parents=True, exist_ok=True)
    results, timings = [], []

    def check(text, ok, detail=None):
        results.append((text if ok or detail is None else f"{text}: {json.dumps(detail, default=str)}", ok))

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        home = Path(tmp) / "home"
        env = dict(os.environ, HOME=str(home), MOZ_HEADLESS="1")
        for case, size in (("fixture", "w320"), ("fixture", "w2560"), ("real", "w1280")):
            profile = home / f".var/app/org.mozilla.firefox/data/check-profile-{case}-{size}"
            profile.mkdir(parents=True)
            try:
                run_case(case, size, env, profile, shots_dir, check, timings)
            except Exception as exc:  # report and carry on with the next case
                results.append((f"{case} {size}: could not run ({exc!r})", False))
    for text, ok in results:
        print(f"{'ok  ' if ok else 'FAIL'} {text}")
    for line in timings:
        print(f"timing {line}")
    print(f"screenshots: {shots_dir}")
    failures = sum(not ok for _, ok in results)
    print("all good" if not failures else f"{failures} problem(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
