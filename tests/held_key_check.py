# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Holding a button down, in a real headless Firefox (the held button fix). Not part
of the unit tests: it needs Firefox and takes about half a minute.

A held key sends itself again and again, each repeat marked as such. The
check holds a key by pressing it down several times before letting go, and
first makes sure the page really sees those as repeats. Uses the Marionette
helper from loading_screen_check.py and the invented library from
test_parsed_library.py, in a temporary data folder. Playing and quitting
are faked: they are only recorded. Checks:

  - a held A on a show opens the show only: no episode is asked to play
  - a held B in the episode list goes back to the shows only: no quit
  - a held Down still moves several rows
  - the same for the other keys: a held Esc goes back only, a held Space
    opens a show only
  - a single A and a single B still work after that
  - since the Home actions work, a held B on Home opens the menu on Quit once and leaves
    it open; B then A quits

Run from the repo root:  python3 tests/held_key_check.py
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
from tests.click_focus_check import DOWN, ENTER, PLAYING_JS  # noqa: E402
from tests.loading_screen_check import UI_DIR, Marionette, free_port  # noqa: E402
from tests.window_sizes import WINDOW, set_window, FIREFOX_FLAG  # noqa: E402
from tests.test_parsed_library import MOVIE_FILES, TV_FILES  # noqa: E402

RIGHT = ""
# How many times a held key is sent: the first press, then the repeats.
HELD_PRESSES = 6

# Records every key the page receives, and whether it was a repeat.
RECORD_KEYS_JS = """
window.__keys = [];
window.addEventListener('keydown', (e) => window.__keys.push([e.key, e.repeat]), true);
"""


def start_server(settings, logs_dir, played, quits):
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

        def _handle_status(self):
            self._send_json(HTTPStatus.OK, {"state": "idle", "last_result": {"ok": True}})

        def _handle_shutdown(self):
            # Recorded only: the server keeps running.
            quits.append(True)
            self._send_json(HTTPStatus.OK, {"ok": True})

    httpd.RequestHandlerClass = Handler
    httpd_ref["server"] = httpd
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port


def hold(m, key, presses=HELD_PRESSES):
    """Presses the key down several times, a little apart, then lets go."""
    actions = []
    for _ in range(presses):
        actions += [{"type": "keyDown", "value": key}, {"type": "pause", "duration": 50}]
    actions.append({"type": "keyUp", "value": key})
    m.send("WebDriver:PerformActions", {"actions": [{"type": "key", "id": "kb", "actions": actions}]})
    m.send("WebDriver:ReleaseActions", {})
    time.sleep(0.5)


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


def recorded(m):
    return m.js("const k = window.__keys; window.__keys = []; return k;")


def check_held(m, played, quits, check):
    s = wait(m, lambda s: s["rows"][:1] == ["Open my library"] and not s["loading"], 30)
    check("first launch scans, then offers Open my library", s["rows"][:1] == ["Open my library"], s["rows"])
    m.press(ENTER)
    s = wait(m, lambda s: s["library"] and not s["loading"] and len(s["rows"]) == 2, 30)
    check("library shows, Movies tab focused", s["focusedTab"] == "movies", s)
    m.press(RIGHT)
    s = wait(m, lambda s: s["selectedTab"] == "tv", 3)
    check("TV Shows tab selected", s["rows"] == ["Kiri Anime", "Test Show"], s)
    m.press(DOWN)  # the first show (no Rescan row since the Home actions work)
    check("focus on the first show", state(m)["focusedIndex"] == 0)
    m.js(RECORD_KEYS_JS)

    # Held A on a show: the show opens, and nothing plays.
    hold(m, ENTER)
    keys = recorded(m)
    check("the page sees a held A as one press and its repeats",
          len(keys) == HELD_PRESSES and not keys[0][1] and all(r for _, r in keys[1:]), keys)
    time.sleep(0.5)
    s = state(m)
    check("held A on a show: its episodes open, focus on the first episode",
          s["episodes"] and s["showTitle"] == "Kiri Anime" and s["focusedIndex"] == 0, s)
    check("held A on a show: no episode is asked to play", played == [], played)

    # Held B in the episode list: back to the shows, and the app stays.
    hold(m, "q")
    keys = recorded(m)
    check("the page sees a held B as one press and its repeats",
          len(keys) == HELD_PRESSES and all(r for _, r in keys[1:]), keys)
    time.sleep(0.5)
    s = state(m)
    check("held B in the episodes: back on the show list, on that show",
          s["library"] and not s["episodes"] and s["focusedIndex"] == 0, s)
    check("held B in the episodes: the app is not asked to quit", quits == [], quits)

    # Held Down still moves several rows (the episode list has three).
    m.press(ENTER)
    s = wait(m, lambda s: s["episodes"], 3)
    check("single A on a show still opens it", s["episodes"] and played == [], s)
    hold(m, DOWN, presses=3)
    keys = recorded(m)
    s = state(m)
    check("held Down moves several rows: from the first episode to the third",
          s["focusedIndex"] == 2, {"state": s, "keys": keys})

    # The other B and A keys: a held Esc goes back only, a held Space opens only.
    hold(m, "")  # Escape
    keys = recorded(m)
    check("the page sees a held Esc as one press and its repeats",
          len(keys) == HELD_PRESSES and all(r for _, r in keys[1:]), keys)
    time.sleep(0.5)
    s = state(m)
    check("held Esc in the episodes: back on the show list, no quit",
          s["library"] and not s["episodes"] and quits == [], {"state": s, "quits": quits})
    hold(m, " ")
    keys = recorded(m)
    check("the page sees a held Space as one press and its repeats",
          len(keys) == HELD_PRESSES and all(r for _, r in keys[1:]), keys)
    time.sleep(0.5)
    s = state(m)
    check("held Space on a show: its episodes open, nothing plays",
          s["episodes"] and s["focusedIndex"] == 0 and played == [], {"state": s, "played": played})
    m.press(DOWN)
    m.press(DOWN)
    check("Down twice: on the third episode", state(m)["focusedIndex"] == 2)

    # Single presses still work.
    m.press(ENTER)
    time.sleep(0.5)
    check("single A on an episode plays it",
          played[-1:] == [{"source": "tv", "path": TV_FILES[2]}] and len(played) == 1, played)
    m.press("q")
    s = wait(m, lambda s: s["library"], 3)
    check("single B in the episodes goes back", s["library"] and quits == [], s)
    # Since the Home actions work B on Home opens the menu with Quit focused; A then quits.
    # Held, B opens it once and leaves it open: its repeats don't close it.
    menu_js = ("const d = document.getElementById('home-menu'); const f = d.querySelector('[data-focused=\"true\"]');"
               "return [d.open && !d.dataset.closing, f ? f.textContent.trim() : null];")
    m.js(RECORD_KEYS_JS)
    hold(m, "q")
    time.sleep(0.5)
    check("held B on the show list: the menu opens on Quit and stays open, no quit",
          m.js(menu_js) == [True, "Quit"] and quits == [], [m.js(menu_js), quits])
    m.press("q")
    time.sleep(0.5)
    check("B again closes the menu, no quit", m.js(menu_js)[0] is False and quits == [], quits)
    m.press("q")
    time.sleep(0.5)
    m.press(" ")
    time.sleep(0.5)
    check("B then A on the show list asks to quit", quits == [True], quits)


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
        quits = []
        httpd, port = start_server(settings, tmp, played, quits)
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
            check_held(m, played, quits, check)
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
        profile = home / ".var/app/org.mozilla.firefox/data/check-profile-held-key"
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
