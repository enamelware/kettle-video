# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Clicking or tapping a row, then pressing Enter, in a real headless Firefox
(the click-then-Enter fix). Not part of the unit tests: it needs Firefox and takes about
half a minute.

Uses the Marionette helper from loading_screen_check.py and the invented
library from test_parsed_library.py, in a temporary data folder. Playing is
faked: the request is recorded, mpv never starts, and the app is told it is
"playing" for a moment so "Playing..." shows. Checks:

  - a click on a show or an episode only selects it (nothing plays, a show
    doesn't open); a click or tap on a film plays it (the Movies list work)
  - a click while "Playing..." is up changes nothing
  - click a show, Enter: its episodes open; click an episode, Enter: it plays
  - after a click, Down and Up move on from the clicked row
  - a tap (touch) on a film plays it
  - a click while the loading screen is up changes nothing

Since the Home shell work the films and the shows are in two tabs, the Movies tab
has the focus at launch, and a tap on a tab selects it.

Run from the repo root:  python3 tests/click_focus_check.py
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

from backend.server import make_handler  # noqa: E402
from tests.loading_screen_check import UI_DIR, Marionette, free_port  # noqa: E402
from tests.window_sizes import WINDOW, set_window, FIREFOX_FLAG  # noqa: E402
from tests.parsed_view_check import STATE_JS  # noqa: E402
from tests.test_parsed_library import MOVIE_FILES, TV_FILES  # noqa: E402

# How long the faked playback says "playing".
PLAYING_S = 2.5

ENTER = ""
DOWN = ""
UP = ""

# Centre of the n-th visible row (as in STATE_JS), in
# viewport pixels, after scrolling it into view.
ROW_CENTRE_JS = """
const visible = (el) => el && !el.hidden && getComputedStyle(el).display !== 'none';
const shown = [...document.querySelectorAll('.file-row, .result-action')].filter(r => visible(r) && !r.closest('[hidden]'));
const row = shown[arguments[0]];
row.scrollIntoView({ block: 'center' });
const r = row.getBoundingClientRect();
return [Math.round(r.left + r.width / 2), Math.round(r.top + r.height / 2)];
"""


def start_server(settings, logs_dir, played):
    httpd_ref = {}
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
    port = httpd.server_address[1]
    base = make_handler(UI_DIR, logs_dir, settings, httpd_ref, port)
    playing_until = [0.0]

    class Handler(base):
        def log_message(self, format, *args):
            pass

        def _handle_mpv_status(self):
            self._send_json(HTTPStatus.OK, {"available": True})

        def _handle_play(self):
            played.append(self._read_json_body())
            playing_until[0] = time.time() + PLAYING_S
            self._send_json(HTTPStatus.OK, {"started": True})

        def _handle_status(self):
            state = "playing" if time.time() < playing_until[0] else "idle"
            self._send_json(HTTPStatus.OK, {"state": state, "last_result": {"ok": True}})

    httpd.RequestHandlerClass = Handler
    httpd_ref["server"] = httpd
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port


def tap(m, x, y, pointer="mouse"):
    m.send("WebDriver:PerformActions", {"actions": [{
        "type": "pointer", "id": pointer, "parameters": {"pointerType": pointer},
        "actions": [
            {"type": "pointerMove", "x": x, "y": y, "origin": "viewport", "duration": 0},
            {"type": "pointerDown", "button": 0},
            {"type": "pointerUp", "button": 0},
        ],
    }]})
    m.send("WebDriver:ReleaseActions", {})


TAB_CENTRE_JS = """
const r = document.querySelector(`#tab-strip .tab[data-tab="${arguments[0]}"]`).getBoundingClientRect();
return [Math.round(r.left + r.width / 2), Math.round(r.top + r.height / 2)];
"""


def click_tab(m, name, pointer="mouse"):
    x, y = m.send("WebDriver:ExecuteScript", {"script": TAB_CENTRE_JS, "args": [name]})["value"]
    tap(m, x, y, pointer)
    time.sleep(0.3)


def click_row(m, index, pointer="mouse"):
    x, y = m.send("WebDriver:ExecuteScript", {"script": ROW_CENTRE_JS, "args": [index]})["value"]
    tap(m, x, y, pointer)
    time.sleep(0.3)


# The films' IDs, in list order (the Movies list work: films play by ID).
FILM_IDS_JS = "return [...document.querySelectorAll('.file-row[data-kind=\"movie\"]')].map(r => r.dataset.id);"

PLAYING_JS = STATE_JS.replace(
    "return {",
    "return { playing: visible(document.getElementById('playing-status')),", 1)


def state(m):
    return m.js(PLAYING_JS)


def wait(m, predicate, timeout):
    end = time.time() + timeout
    while time.time() < end:
        s = state(m)
        if predicate(s):
            return s
        time.sleep(0.2)
    return state(m)


def check_clicks(m, played, check):
    s = wait(m, lambda s: s["rows"][:1] == ["Open my library"] and not s["loading"], 30)
    check("first launch scans, then offers Open my library", s["rows"][:1] == ["Open my library"], s["rows"])
    m.press(ENTER)
    s = wait(m, lambda s: s["library"] and not s["loading"] and len(s["rows"]) == 2, 30)
    check("library shows, Movies tab focused",
          s["rows"] == ["Example Film 2001 2 parts", "Other Movie 1999"] and s["focusedTab"] == "movies", s)
    film_ids = m.js(FILM_IDS_JS)

    # Since the Movies list work a click on a film plays it, asked for by its ID.
    click_row(m, 1)
    s = wait(m, lambda s: s["playing"], 3)
    check("click a film: it looks selected and plays", s["focusedIndex"] == 1 and s["playing"], s)
    check("click a film: the clicked film is asked for",
          played[-1:] == [{"source": "movies", "id": film_ids[1]}] and len(played) == 1, played)

    # A click while "Playing..." is up changes nothing.
    check("Playing... shows", s["playing"], s)
    click_row(m, 0)
    s = state(m)
    check("click while Playing...: focus stays on the film playing", s["focusedIndex"] == 1, s)
    s = wait(m, lambda s: not s["playing"], PLAYING_S + 5)
    check("after Playing..., focus is still on the film played", s["focusedIndex"] == 1, s)
    m.press(ENTER)
    wait(m, lambda s: s["playing"], 3)
    check("click while Playing... did not change what plays next",
          played[-1:] == [{"source": "movies", "id": film_ids[1]}] and len(played) == 2, played)
    wait(m, lambda s: not s["playing"], PLAYING_S + 5)

    # After a click (which plays the film), Down and Up carry on from it.
    click_row(m, 0)
    wait(m, lambda s: not s["playing"], PLAYING_S + 5)
    m.press(DOWN)
    check("click, then Down: the row below the clicked one", state(m)["focusedIndex"] == 1)
    click_row(m, 1)
    wait(m, lambda s: not s["playing"], PLAYING_S + 5)
    m.press(UP)
    check("click, then Up: the row above the clicked one", state(m)["focusedIndex"] == 0)

    # A click on a tab selects it and shows its list (the Home shell work).
    click_tab(m, "tv")
    s = state(m)
    check("click the TV Shows tab: it is selected and focused, the shows show",
          s["selectedTab"] == "tv" and s["focusedTab"] == "tv" and s["rows"] == ["Kiri Anime", "Test Show"], s)

    # A show: its episodes open; then an episode plays.
    click_row(m, 1)
    time.sleep(0.5)
    s = state(m)
    check("click a show alone only selects it: episodes not opened",
          not s["episodes"] and s["library"] and s["focusedIndex"] == 1, s)
    m.press(ENTER)
    s = wait(m, lambda s: s["episodes"], 3)
    check("click a show, Enter: its episodes open",
          s["episodes"] and s["showTitle"] == "Test Show" and s["focusedIndex"] == 0, s)
    count = len(played)
    click_row(m, 2)
    time.sleep(0.5)
    check("click an episode alone plays nothing", len(played) == count, played)
    m.press(ENTER)
    wait(m, lambda s: s["playing"], 3)
    check("click an episode, Enter: the clicked episode is asked for",
          played[-1:] == [{"source": "tv", "path": TV_FILES[5]}], played)
    s = wait(m, lambda s: not s["playing"], PLAYING_S + 5)
    click_row(m, 1)
    m.press(DOWN)
    check("episodes: click, then Down: the row below", state(m)["focusedIndex"] == 2)
    click_row(m, 1)
    m.press(UP)
    check("episodes: click, then Up: the row above", state(m)["focusedIndex"] == 0)

    m.press("q")
    s = wait(m, lambda s: s["library"], 3)
    check("B from the episodes: back on the show, as before", s["library"] and s["focusedIndex"] == 1, s)

    # A tap (touch) works like a click, on a tab and on a row.
    click_tab(m, "movies", pointer="touch")
    s = state(m)
    check("tap the Movies tab: it is selected, the films show",
          s["selectedTab"] == "movies" and s["rows"][0] == "Example Film 2001 2 parts", s)
    count = len(played)
    click_row(m, 0, pointer="touch")
    wait(m, lambda s: s["playing"], 3)
    check("tap a film: the tapped film plays",
          played[-1:] == [{"source": "movies", "id": film_ids[0]}] and len(played) == count + 1, played)
    wait(m, lambda s: not s["playing"], PLAYING_S + 5)


def check_loading(m, played, port, check):
    # The library is saved now, so a reload shows it under the loading screen.
    m.send("WebDriver:Navigate", {"url": f"http://127.0.0.1:{port}/"})
    before = len(played)
    s = wait(m, lambda s: s["loading"] and len(s["rows"]) == 2, 5)
    check("reload: loading screen up, list underneath", s["loading"] and len(s["rows"]) == 2, s)
    click_row(m, 1)
    s = state(m)
    check("click while loading: still loading, focus not moved from the Movies tab",
          s["loading"] and s["focusedTab"] == "movies", s)
    click_tab(m, "tv")
    s = state(m)
    check("click a tab while loading: nothing changes", s["loading"] and s["selectedTab"] == "movies", s)
    s = wait(m, lambda s: not s["loading"], 10)
    check("after loading: the Movies tab is still focused", s["focusedTab"] == "movies", s)
    m.press(DOWN)  # the first film (no Rescan row since the Home actions work)
    m.press(ENTER)
    wait(m, lambda s: s["playing"], 3)
    check("after loading, Enter plays the first film, not the clicked row",
          played[before:] == [{"source": "movies", "id": m.js(FILM_IDS_JS)[0]}], played[before:])


def run(env, profile, check):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for base, files in ((tmp / "Movies", MOVIE_FILES), (tmp / "TV Shows", TV_FILES)):
            for rel in files:
                (base / rel).parent.mkdir(parents=True, exist_ok=True)
                (base / rel).write_bytes(b"")
        settings = {"movies_path": str(tmp / "Movies"), "tv_path": str(tmp / "TV Shows"),
                    "mpv_command": "mpv", "mpv_args": [], "data_dir": str(tmp / "data")}
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
            set_window(m, *WINDOW)
            m.send("WebDriver:Navigate", {"url": f"http://127.0.0.1:{port}/"})
            check_clicks(m, played, check)
            check_loading(m, played, port, check)
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
    results = []

    def check(text, ok, detail=None):
        results.append((text if ok or detail is None else f"{text}: {json.dumps(detail, default=str)}", ok))

    # Firefox can still be writing its profile as it quits.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        home = Path(tmp) / "home"
        env = dict(os.environ, HOME=str(home), MOZ_HEADLESS="1")
        profile = home / ".var/app/org.mozilla.firefox/data/check-profile-click"
        profile.mkdir(parents=True)
        try:
            run(env, profile, check)
        except Exception as exc:
            results.append((f"could not run ({exc!r})", False))
    for text, ok in results:
        print(f"{'ok  ' if ok else 'FAIL'} {text}")
    failures = sum(not ok for _, ok in results)
    print("all good" if not failures else f"{failures} problem(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
