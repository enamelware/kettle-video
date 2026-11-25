# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The backend stops answering, or answers with something unexpected, while
a film is starting or playing, in a real headless Firefox (the stuck Playing fix). Not
part of the unit tests: it needs Firefox and takes about a minute.

Uses the Marionette helper from loading_screen_check.py and the invented
library from test_parsed_library.py, in a temporary data folder. Playing is
faked: mpv never starts. For each way of failing, checks that "Playing..."
goes away, a plain error message shows, and the arrow keys and Enter work
again:

  - the status answer is not JSON (a broken backend)
  - the status request gets no answer at all (connection dropped)
  - the status request hangs (the backend froze)
  - the play request itself gets no answer
  - the play is refused because mpv is missing: the install message shows
  - mpv could not be started: the error and its hint show
  - one missed answer during a film does not end the wait
  - after all that, a normal play still works

Since the Home actions work it also checks that Start doesn't open Home's menu during a
film (no rescans while playing; the Rescan row of the quick rescan and Remove work is gone), and opens it
again after each of these errors.

Run from the repo root:  python3 tests/play_failure_check.py
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

from backend import mpv  # noqa: E402
from backend.server import make_handler  # noqa: E402
from tests.click_focus_check import DOWN, ENTER, PLAYING_JS, UP  # noqa: E402
from tests.loading_screen_check import UI_DIR, Marionette, free_port  # noqa: E402
from tests.window_sizes import WINDOW, set_window, FIREFOX_FLAG  # noqa: E402
from tests.test_parsed_library import MOVIE_FILES, TV_FILES  # noqa: E402

# How long "Playing..." shows before the backend goes wrong.
PLAYING_S = 1.5
# The page waits 10 s per request and allows 3 misses in a row.
HANG_WAIT_S = 45
# What the backend reports when mpv could not be started at all.
START_FAILED = {"ok": False, "error": mpv.START_FAILED,
                "hint": mpv.START_FAILED_HINT}


def start_server(settings, logs_dir, played, mode):
    """mode[0] says how the backend behaves: "ok", "garbage", "drop",
    "hang" (for status) or "drop-play" (for play)."""
    httpd_ref = {}
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
    port = httpd.server_address[1]
    base = make_handler(UI_DIR, logs_dir, settings, httpd_ref, port)
    playing_until = [0.0]
    missed = [False]

    class Handler(base):
        def log_message(self, format, *args):
            pass

        def _handle_mpv_status(self):
            self._send_json(HTTPStatus.OK, {"available": True})

        def _drop(self):
            self.close_connection = True

        def _handle_play(self):
            body = self._read_json_body()
            if mode[0] == "drop-play":
                return self._drop()
            if mode[0] == "refuse":
                # What the real backend answers when mpv is missing.
                return self._send_json(HTTPStatus.SERVICE_UNAVAILABLE,
                                       {"error": "mpv is not available", "hint": mpv.INSTALL_HINT})
            played.append(body)
            playing_until[0] = time.time() + PLAYING_S
            missed[0] = False
            self._send_json(HTTPStatus.OK, {"started": True})

        def _handle_status(self):
            if mode[0] == "one-miss" and not missed[0] and time.time() < playing_until[0]:
                # One broken answer in the middle of a film, then all is well.
                missed[0] = True
                return self._drop()
            if mode[0] == "start-failed":
                # mpv could not be started: the backend is idle again at once.
                return self._send_json(HTTPStatus.OK, {"state": "idle", "last_result": START_FAILED})
            if time.time() < playing_until[0] or mode[0] in ("ok", "one-miss"):
                state = "playing" if time.time() < playing_until[0] else "idle"
                return self._send_json(HTTPStatus.OK, {"state": state, "last_result": {"ok": True}})
            if mode[0] == "garbage":
                body = b"<html>Internal error</html>"
                self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if mode[0] == "hang":
                time.sleep(HANG_WAIT_S)
            return self._drop()

    httpd.RequestHandlerClass = Handler
    httpd_ref["server"] = httpd
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port


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


def check_failure(m, played, mode, how, timeout, check):
    """Starts a film with the focus on the first one, lets the backend fail
    in the given way, then checks the page recovers."""
    mode[0] = how
    before = len(played)
    m.press(ENTER)
    if how != "drop-play":
        s = wait(m, lambda s: s["playing"], 3)
        check(f"{how}: Playing... shows", s["playing"] and len(played) == before + 1, s)
        m.press("m")
        time.sleep(0.3)
        check(f"{how}: while playing Start doesn't open the menu", not menu_open(m))
    s = wait(m, lambda s: not s["playing"] and s["banner"], timeout)
    check(f"{how}: Playing... goes away and an error shows",
          not s["playing"] and bool(s["banner"]), s)
    check(f"{how}: the message is plain",
          s["banner"] in ("The app lost contact with its backend during playback.",
                          "Playback couldn't start: the app lost contact with its backend."), s["banner"])
    check(f"{how}: the focus is back on the film", s["focusedIndex"] == 0, s)
    # The Home actions work: once the film is over, Start opens the menu again.
    m.press("m")
    time.sleep(0.3)
    opened = menu_open(m)
    m.press("q")
    time.sleep(0.5)
    check(f"{how}: afterwards Start opens the menu again (B closes it)", opened and not menu_open(m))
    mode[0] = "ok"
    m.press(DOWN)
    s = state(m)
    check(f"{how}: Down works again", s["focusedIndex"] == 1, s)
    m.press(UP)
    s = state(m)
    check(f"{how}: Up works again", s["focusedIndex"] == 0, s)


def menu_open(m):
    return m.js("const d = document.getElementById('home-menu'); return d.open && !d.dataset.closing;")


def check_reported_error(m, played, mode, how, hint, check):
    """The backend answers properly but reports a problem (mpv missing, or
    mpv could not be started): the message and its hint both show."""
    mode[0] = how
    m.press(ENTER)
    s = wait(m, lambda s: not s["playing"] and s["banner"], 10)
    check(f"{how}: no Playing..., an error shows", not s["playing"] and bool(s["banner"]), s)
    check(f"{how}: the error comes with its hint", hint in (s["banner"] or ""), s["banner"])
    check(f"{how}: the focus is back on the film", s["focusedIndex"] == 0, s)
    mode[0] = "ok"
    m.press(DOWN)
    s = state(m)
    check(f"{how}: Down works again", s["focusedIndex"] == 1, s)
    m.press(UP)
    s = state(m)
    check(f"{how}: Up works again", s["focusedIndex"] == 0, s)


def check_all(m, played, mode, check):
    s = wait(m, lambda s: s["rows"][:1] == ["Open my library"] and not s["loading"], 30)
    check("first launch scans, then offers Open my library", s["rows"][:1] == ["Open my library"], s["rows"])
    m.press(ENTER)
    s = wait(m, lambda s: s["library"] and not s["loading"] and len(s["rows"]) == 2, 30)
    check("library shows", s["rows"] == ["Example Film 2001 2 parts", "Other Movie 1999"], s)
    m.press(DOWN)  # the first film (no Rescan row since the Home actions work)
    check("focus on the first film", state(m)["focusedIndex"] == 0)

    check_failure(m, played, mode, "garbage", 10, check)
    check_failure(m, played, mode, "drop", 10, check)
    check_failure(m, played, mode, "drop-play", 10, check)
    check_failure(m, played, mode, "hang", HANG_WAIT_S, check)
    check_reported_error(m, played, mode, "refuse", mpv.INSTALL_HINT, check)
    check_reported_error(m, played, mode, "start-failed", mpv.START_FAILED_HINT, check)

    # One missed answer in the middle of a film does not end the wait.
    mode[0] = "one-miss"
    before = len(played)
    m.press(ENTER)
    s = wait(m, lambda s: s["playing"], 3)
    check("one miss: Playing... shows", s["playing"] and len(played) == before + 1, s)
    time.sleep(PLAYING_S / 2)
    s = state(m)
    check("one miss: still Playing..., no error", s["playing"] and not s["banner"], s)
    s = wait(m, lambda s: not s["playing"], PLAYING_S + 5)
    check("one miss: the film ends normally, no error",
          not s["playing"] and not s["banner"] and s["focusedIndex"] == 0, s)
    mode[0] = "ok"

    # Normal playback still works, with no error left on screen.
    before = len(played)
    m.press(ENTER)
    s = wait(m, lambda s: s["playing"], 3)
    check("normal play: Playing... shows, the old error is gone",
          s["playing"] and not s["banner"] and len(played) == before + 1, s)
    s = wait(m, lambda s: not s["playing"], PLAYING_S + 5)
    check("normal play: back on the same film, no error",
          not s["playing"] and not s["banner"] and s["focusedIndex"] == 0, s)


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
        mode = ["ok"]
        httpd, port = start_server(settings, tmp, played, mode)
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
            check_all(m, played, mode, check)
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
        profile = home / ".var/app/org.mozilla.firefox/data/check-profile-play-failure"
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
