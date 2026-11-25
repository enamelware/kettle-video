# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Drive missing items, Remove and "no rescans while playing" in a real,
headless Firefox (the quick rescan and Remove work). Not part of the unit tests: it needs Firefox.

Invented titles in a temporary folder, and a temporary saved library;
mpv is faked. Steps: a film and a part go missing (dimmed rows with
"Missing" and "1 of 2 parts missing", the scan toast's "2 missing", and
since the Home actions work "Remove 2 missing items" in Home's menu), A on a missing
film, Remove (opened from the menu; an Enamel picker since the picker confirm work: Cancel
first, Up/Down stopping at the ends, Left/Right doing nothing, Cancel by
Enter, B, Escape (which never quits) and a tap, then Yes by A), a rescan
during playing
(also for a film the page didn't start, as after a reload),
a rescan with the Movies folder away, a split film missing its first part,
and one missing episode inside a show (marked on its own, A doesn't play).

Screenshots at each window width go to the folder given as the first argument.

Run from the repo root:  python3 tests/missing_items_check.py [screenshot-dir]
"""

import json
import shutil
import sys
import threading
import time
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from backend.server import make_handler  # noqa: E402
from tests.loading_screen_check import UI_DIR  # noqa: E402
from tests.saved_library_check import DOWN, ENTER, STATE_JS, main, rescan_done, shot, wait_state  # noqa: E402
from tests.test_parsed_library import MOVIE_FILES, TV_FILES  # noqa: E402

UP = "\ue013"  # WebDriver's ArrowUp
RIGHT = "\ue014"  # WebDriver's ArrowRight
LEFT = "\ue012"  # WebDriver's ArrowLeft
ESCAPE = "\ue00c"  # WebDriver's Escape
SPACE = " "  # the controller's A

MISSING_JS = """
const visible = (el) => el && !el.hidden && getComputedStyle(el).display !== 'none';
const shown = [...document.querySelectorAll('.file-row, .result-action')].filter(r => visible(r) && !r.closest('[hidden]'));
const confirm = document.getElementById('confirm-remove');
const title = (r) => r.querySelector('.row-title') || r;
return {
  statuses: shown.map(r => r.dataset.status || ''),
  missingNotes: shown.map(r => (r.querySelector('[data-role="missing"]') || {}).textContent || ''),
  // Dimmed: the title is not in the row's own text colour. (Since the second design system step
  // the page's text colour is Enamel's; the rows keep theirs until the third design system step.)
  dimmed: shown.map(r => getComputedStyle(title(r)).color !== getComputedStyle(r).color),
  // Home's menu (the Home actions work).
  menu: document.getElementById('home-menu').open && !document.getElementById('home-menu').dataset.closing,
  menuRows: [...document.querySelectorAll('#home-menu .en-picker__row')].map(r => r.textContent.trim()),
  playing: visible(document.getElementById('playing-status')),
  // The remove question is an Enamel picker (the picker confirm work).
  confirm: window.EnamelUI.picker.isOpen(),
  dialogShown: visible(confirm) && confirm.open,
  question: confirm.querySelector('[data-role="question"]').textContent,
  choices: [...confirm.querySelectorAll('.en-picker__row')].map(r => r.querySelector('span').textContent),
  choiceFocused: [...confirm.querySelectorAll('.en-picker__row')].findIndex(r => r === document.activeElement && r.dataset.focused === 'true'),
  cancelMarked: !!confirm.querySelector('.en-picker__row.en-picker__cancel:last-child[autofocus]'),
  back: document.querySelector('#hint-bar [data-role="back"]').textContent,
};
"""


class App:
    """One server run. mpv is "available"; playing waits for `release`."""

    def __init__(self, settings, logs_dir, release):
        httpd_ref = {}
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        self.port = self.httpd.server_address[1]
        base = make_handler(UI_DIR, logs_dir, settings, httpd_ref, self.port)

        class Handler(base):
            def log_message(self, format, *args):
                pass

            def _handle_mpv_status(self):
                self._send_json(HTTPStatus.OK, {"available": True})

        self.httpd.RequestHandlerClass = Handler
        httpd_ref["server"] = self.httpd
        self.patches = [
            mock.patch("backend.server.mpv.detect",
                       return_value={"available": True, "command": ["mpv"], "via": "configured"}),
            mock.patch("backend.server.mpv.play", side_effect=lambda *a, **k: release.wait(30) and {"ok": True}),
        ]
        self.mocks = [patch.start() for patch in self.patches]
        self.play = self.mocks[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        for patch in self.patches:
            patch.stop()


def state(m):
    return {**m.js(STATE_JS), **m.js(MISSING_JS)}


def wait(m, predicate, timeout):
    wait_state(m, lambda s: predicate({**s, **m.js(MISSING_JS)}), timeout)
    return state(m)


def open_remove(m):
    """The remove question, from Home's menu (the Home actions work): Start, then Down
    to "Remove N missing items" and A."""
    m.press("m")
    wait(m, lambda s: s["menu"], 3)
    m.press(DOWN)
    m.press(ENTER)
    return wait(m, lambda s: s["confirm"], 3)


def run(m, tmp, shots_dir, check):
    movies, tv, data = tmp / "Movies", tmp / "TV Shows", tmp / "data"
    for base, files in ((movies, MOVIE_FILES), (tv, TV_FILES)):
        for rel in files:
            (base / rel).parent.mkdir(parents=True, exist_ok=True)
            (base / rel).write_bytes(b"")
    settings = {"movies_path": str(movies), "tv_path": str(tv), "mpv_command": "mpv", "mpv_args": [],
                "resume": True, "keep_awake": False, "data_dir": str(data)}
    release = threading.Event()
    app = App(settings, tmp, release)
    m.send("WebDriver:Navigate", {"url": f"http://127.0.0.1:{app.port}/"})
    wait_state(m, lambda s: s["firstScan"] and not s["loading"], 30)
    m.press(ENTER)  # Open my library
    wait_state(m, lambda s: s["library"], 30)

    # 1. A film and one part of another go missing.
    (movies / MOVIE_FILES[2]).unlink()
    (movies / MOVIE_FILES[1]).unlink()
    m.press("r")
    wait_state(m, lambda s: s["rescanning"], 3)
    s = wait(m, lambda s: rescan_done(s) and "missing" in s["statuses"], 15)
    check("missing: both stay listed", s["rows"] == ["Example Film", "Other Movie"], s)
    check("missing: the gone film is dimmed and says \"Missing\"",
          s["statuses"][1] == "missing" and s["missingNotes"][1] == "Missing" and s["dimmed"][1], s)
    check("missing: the split film says \"1 of 2 parts missing\" and is not dimmed",
          s["missingNotes"][0] == "1 of 2 parts missing" and s["statuses"][0] == "" and not s["dimmed"][0], s)
    check(f"scan toast: {s['toast']!r}", s["toast"] == "2 missing", s)
    check("tabs: the Movies count is the films",
          m.js("return document.querySelector('[data-tab=\"movies\"] [data-role=\"count\"]').textContent") == "2")
    for size, overflow in shot(m, shots_dir, "missing"):
        check(f"missing: fits at {size}", not overflow)

    # 2. A on the missing film: the sentence, and no mpv.
    for _ in range(2):
        m.press(DOWN)
    s = wait(m, lambda s: s["focusedIndex"] == 1, 3)
    m.settle()  # the row's lift fades in (Enamel 0.5.0, the Enamel 0.5.0 upgrade)
    s = state(m)
    check("missing: the gone film still takes the focus, with a ring", s["focusedIndex"] == 1 and s["ringVisible"], s)
    m.press(ENTER)
    s = wait(m, lambda s: s["banner"], 3)
    status = m.js("return fetch('/api/status').then(r => r.json())")
    check(f"missing: A shows {s['banner']!r} and doesn't play",
          s["banner"] == "File not found. Rescan or remove it." and status["state"] == "idle", [s, status])
    for size, overflow in shot(m, shots_dir, "missing-file-not-found"):
        check(f"file not found: fits at {size}", not overflow)

    # 3. Remove: from Home's menu (the Home actions work), an Enamel picker over the
    # list (the picker confirm work). Rows: Yes, remove then Cancel; Cancel focused first.
    m.press("m")
    s = wait(m, lambda s: s["menu"], 3)
    check("remove: the menu has Remove 2 missing items, second",
          s["menuRows"] == ["Rescan library", "Remove 2 missing items", "Settings", "Quit", "Cancel"], s)
    m.press(DOWN)
    m.press(ENTER)
    s = wait(m, lambda s: s["confirm"], 3)
    check(f"remove: asks {s['question']!r} with Cancel focused first",
          s["question"] == "Remove 2 missing items?" and s["choices"] == ["Yes, remove", "Cancel"]
          and s["choiceFocused"] == 1 and s["cancelMarked"] and s["dialogShown"] and s["back"] == "Back", s)
    check("remove: the list stays behind the question, nothing in it focused",
          s["library"] and s["focusedIndex"] == -1, s)
    for size, overflow in shot(m, shots_dir, "remove-confirm"):
        check(f"remove question: fits at {size}", not overflow)
    # Left and Right (letter jumps in the Movies list) do nothing on the
    # question; Down on Cancel stays there. The app's other keys (r rescan,
    # X remove, d paths) are not acted on while the question is open either.
    for key, name in ((RIGHT, "Right"), (LEFT, "Left"), (DOWN, "Down"),
                      ("r", "r"), ("", "X (Backspace)"), ("d", "d")):
        m.press(key)
        time.sleep(0.2)
        s = state(m)
        paths = m.js("return document.body.hasAttribute('data-show-paths')")
        check(f"remove question: {name} on Cancel does nothing, focus stays on Cancel",
              s["confirm"] and s["choiceFocused"] == 1 and s["focusedIndex"] == -1
              and not s["rescanning"] and not paths and len(s["rows"]) == 2, [s, paths])
    m.press(UP)
    s = wait(m, lambda s: s["choiceFocused"] == 0, 3)
    check("remove question: Up goes to Yes, remove", s["confirm"] and s["choiceFocused"] == 0, s)
    m.press(UP)
    time.sleep(0.2)
    s = state(m)
    check("remove question: Up on Yes, remove stops there", s["confirm"] and s["choiceFocused"] == 0, s)
    m.press(DOWN)
    s = wait(m, lambda s: s["choiceFocused"] == 1, 3)
    check("remove question: Down goes back to Cancel", s["choiceFocused"] == 1, s)
    m.press(ENTER)  # Cancel
    s = wait(m, lambda s: not s["confirm"] and s["focusedIndex"] == 1, 3)
    check("remove: Cancel keeps everything, focus back where the menu was opened",
          len(s["rows"]) == 2 and s["focusedIndex"] == 1 and not s["confirm"] and s["back"] == "Quit", s)
    open_remove(m)
    m.press("q")  # B is Cancel too
    s = wait(m, lambda s: not s["confirm"] and s["focusedIndex"] == 1, 3)
    check("remove: B on the question is Cancel", len(s["rows"]) == 2 and not s["confirm"] and s["focusedIndex"] == 1, s)
    # Escape opens the menu on Quit elsewhere: on the question it only cancels.
    open_remove(m)
    m.press(ESCAPE)
    s = wait(m, lambda s: not s["confirm"] and s["focusedIndex"] == 1, 3)
    time.sleep(0.5)
    s = state(m)
    alive = m.js("return fetch('/api/status').then(r => r.ok, () => false)")
    check("remove: Escape on the question cancels and never quits or opens the menu",
          not s["confirm"] and not s["menu"] and s["focusedIndex"] == 1 and len(s["rows"]) == 2 and alive,
          [s, alive])
    # A tap on a row chooses it: Cancel.
    open_remove(m)
    m.js("document.querySelector('#confirm-remove .en-picker__cancel').click()")
    s = wait(m, lambda s: not s["confirm"], 3)
    check("remove: a tap on Cancel closes the question, nothing removed",
          not s["confirm"] and len(s["rows"]) == 2, s)
    # Yes, remove with A (Space), the controller's own key.
    open_remove(m)
    m.press(UP)
    wait(m, lambda s: s["choiceFocused"] == 0, 3)
    m.press(SPACE)  # A: Yes, remove
    s = wait(m, lambda s: s["library"] and len(s["rows"]) == 1, 5)
    check("remove: Yes removes only the missing entries",
          s["rows"] == ["Example Film"] and s["missingNotes"][0] == "" and not s["confirm"], s)
    check("remove: the film that had the focus is gone, so the focus is on the Movies tab",
          s["focusedTab"] == "movies", s)
    m.press("m")
    s = wait(m, lambda s: s["menu"], 3)
    check("remove: afterwards the menu has no Remove row", s["menuRows"] == ["Rescan library", "Settings", "Quit", "Cancel"], s)
    m.press("q")
    wait(m, lambda s: not s["menu"], 3)
    saved = json.loads((data / "library.json").read_text())
    check("remove: saved without them", [p["path"] for i in saved["sources"]["movies"]["items"]
                                         for p in i["parts"]] == [MOVIE_FILES[0]], saved["sources"]["movies"])

    # 4. No rescans while playing: Start and r do nothing in the list.
    # The removed film had the focus, so it went to the tabs: Down to the film.
    m.press(DOWN)
    wait(m, lambda s: s["focusedIndex"] == 0, 3)
    m.press(ENTER)  # plays Example Film
    s = wait(m, lambda s: s["playing"], 5)
    for key in ("m", "r"):
        m.press(key)
    time.sleep(0.5)
    s = state(m)
    busy = m.js("return fetch('/api/library/scan', {method: 'POST', headers: {'Content-Type': "
                "'application/json'}}).then(r => r.json().then(b => [r.status, b]))")
    check("playing: Start and r do nothing (no menu, no scan), and the scan request answers busy",
          s["playing"] and not s["menu"] and not s["toast"] and busy[0] == 409 and busy[1]["busy"], [s, busy])
    for size, overflow in shot(m, shots_dir, "rescan-unavailable"):
        check(f"playing: fits at {size}", not overflow)
    release.set()
    s = wait(m, lambda s: not s["playing"], 5)
    check("playing: when mpv closes, the list is back", not s["playing"] and s["focusedIndex"] == 0, s)

    # 4b. A film the page didn't start (as after a reload while playing):
    # r gets "busy" back, and the toast says so.
    release.clear()
    m.js("return fetch('/api/play', {method: 'POST', headers: {'Content-Type': 'application/json'}, "
         f"body: JSON.stringify({{source: 'movies', path: {json.dumps(MOVIE_FILES[0])}}})}}).then(r => r.status)")
    end = time.time() + 5
    while m.js("return fetch('/api/status').then(r => r.json())")["state"] != "playing" and time.time() < end:
        time.sleep(0.1)
    m.press("r")
    s = wait(m, lambda s: s["toast"] == "Rescan unavailable while playing", 5)
    check("playing (not started here): r makes the toast say \"Rescan unavailable while playing\"",
          s["toast"] == "Rescan unavailable while playing", s)
    release.set()

    # 5. The Movies folder away: nothing is marked missing.
    shutil.move(str(movies), str(tmp / "Movies-away"))
    m.press("r")
    s = wait(m, lambda s: rescan_done(s) and s["movieStatus"] == "Folder not available", 15)
    check("card out: \"Folder not available\", nothing missing, the toast names the folder",
          s["movieStatus"] == "Folder not available" and "missing" not in s["statuses"]
          and s["toast"] == "Movies folder not available" and s["rows"] == ["Example Film"], s)
    shutil.move(str(tmp / "Movies-away"), str(movies))

    # 6. The first part of a split film gone: A plays the part that is there.
    (movies / MOVIE_FILES[1]).write_bytes(b"")  # both parts back
    m.press("r")
    wait(m, lambda s: rescan_done(s) and s["movieStatus"] != "Folder not available"
         and s["toast"] == "1 added", 15)
    (movies / MOVIE_FILES[0]).unlink()
    m.press("r")
    s = wait(m, lambda s: rescan_done(s) and "1 of 2 parts missing" in s["missingNotes"], 15)
    film = s["missingNotes"].index("1 of 2 parts missing")
    focus = s["focusedIndex"]
    for _ in range(abs(film - focus)):
        m.press(DOWN if film > focus else UP)
    wait(m, lambda s: s["focusedIndex"] == film, 3)
    app.play.reset_mock()
    m.press(ENTER)
    end = time.time() + 5
    while not app.play.called and time.time() < end:
        time.sleep(0.05)
    played = Path(app.play.call_args.args[1]).as_posix() if app.play.called else None
    check("split film with its first part gone: A plays the second part",
          played is not None and played.endswith(MOVIE_FILES[1]), [played, state(m)])

    # 7. One episode gone: only that episode is marked, and A doesn't play it.
    wait(m, lambda s: not s["playing"], 5)
    (tv / TV_FILES[4]).unlink()  # Test Show, season 1, the second episode
    m.press("r")
    s = wait(m, lambda s: rescan_done(s) and s["toast"] == "1 missing", 15)
    for _ in range(s["focusedIndex"] + 1):
        m.press(UP)  # up to the tabs
    wait(m, lambda s: s["focusedTab"] == "movies", 3)
    m.press(RIGHT)
    s = wait(m, lambda s: s["focusedTab"] == "tv" and "Test Show" in s["rows"], 3)
    show = s["rows"].index("Test Show")
    check("missing episode: the show itself is not marked missing",
          s["statuses"][show] == "" and s["missingNotes"][show] == "", s)
    for _ in range(show + 1):
        m.press(DOWN)
    wait(m, lambda s: s["focusedIndex"] == show, 3)
    m.press(ENTER)
    s = wait(m, lambda s: s["back"] == "Back" and "missing" in s["statuses"], 3)
    gone = s["statuses"].index("missing") if "missing" in s["statuses"] else -1
    check("missing episode: only that episode is dimmed and says \"Missing\"",
          s["statuses"].count("missing") == 1 and s["missingNotes"][gone] == "Missing" and s["dimmed"][gone]
          and s["focusedIndex"] != gone, s)
    for size, overflow in shot(m, shots_dir, "missing-episode"):
        check(f"missing episode: fits at {size}", not overflow)
    for _ in range(gone - s["focusedIndex"]):
        m.press(DOWN)
    wait(m, lambda s: s["focusedIndex"] == gone, 3)
    app.play.reset_mock()
    m.press(ENTER)
    s = wait(m, lambda s: s["banner"], 3)
    time.sleep(0.5)
    check(f"missing episode: A shows {s['banner']!r} and doesn't play",
          s["banner"] == "File not found. Rescan or remove it." and not app.play.called, [s, app.play.call_args])
    app.stop()


if __name__ == "__main__":
    sys.exit(main(run, "missing-items-"))
