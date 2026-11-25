# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The page keeps the screen on while a film plays (the screen wake lock fix), in a real
headless Firefox. Not part of the unit tests: it needs Firefox and takes
about half a minute.

Firefox's Screen Wake Lock is replaced by a stand-in that counts requests
and releases (headless Firefox has no screen to keep on). Playing is faked:
mpv never starts. Checks:

  - keep_awake on: one "screen" lock is held while the film plays and
    released when it ends; the launch log gets "held" then "released"
  - Firefox lets go in the middle of a film (as when the page is hidden):
    "lost", and the page asks again once it shows; released at the end
  - the backend is lost during the film: the lock is still released
  - mpv exits with an error: the error shows and the lock is released
  - keep_awake off: the page never asks
  - Firefox refuses the lock: "refused", and the film plays and ends as usual
  - a Firefox without the Screen Wake Lock: "unsupported", same

Uses the Marionette helper from loading_screen_check.py, the helpers from
play_failure_check.py and the invented library from test_parsed_library.py.

Run from the repo root:  python3 tests/screen_awake_check.py
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
from tests.click_focus_check import DOWN, ENTER  # noqa: E402
from tests.loading_screen_check import UI_DIR, Marionette, free_port  # noqa: E402
from tests.window_sizes import WINDOW, set_window, FIREFOX_FLAG  # noqa: E402
from tests.play_failure_check import state, wait  # noqa: E402
from tests.test_parsed_library import MOVIE_FILES, TV_FILES  # noqa: E402

# How long each faked film plays.
PLAYING_S = 2.0

# A stand-in Screen Wake Lock that counts what the page does with it.
STUB_JS = """
window.__wake = {requests: 0, releases: 0, held: 0, types: [], refuse: false, last: null};
const makeSentinel = () => {
  const s = new EventTarget();
  s.released = false;
  s.release = async () => {
    if (s.released) return;
    s.released = true;
    window.__wake.releases += 1;
    window.__wake.held -= 1;
    s.dispatchEvent(new Event("release"));
  };
  return s;
};
Object.defineProperty(navigator, "wakeLock", {configurable: true, value: {
  request: async (type) => {
    window.__wake.requests += 1;
    window.__wake.types.push(type);
    if (window.__wake.refuse) throw new DOMException("refused", "NotAllowedError");
    const s = makeSentinel();
    window.__wake.held += 1;
    window.__wake.last = s;
    return s;
  },
}});
"""
WAKE_JS = ("const w = window.__wake; return {requests: w.requests, releases: w.releases,"
           " held: w.held, types: w.types};")


def start_server(settings, logs_dir, mode, reports):
    """mode: keep_awake (bool) and status ("ok", or "drop" to lose the
    backend while playing). reports: the wake-lock words the page sent."""
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
            self._read_json_body()
            playing_until[0] = time.time() + PLAYING_S
            self._send_json(HTTPStatus.OK, {"started": True, "keep_awake": mode["keep_awake"]})

        def _handle_status(self):
            playing = time.time() < playing_until[0]
            if mode["status"] == "drop" and playing:
                self.close_connection = True
                return
            self._send_json(HTTPStatus.OK, {"state": "playing" if playing else "idle",
                                            "last_result": mode.get("result", {"ok": True})})

        def _handle_wake_lock(self):
            reports.append(self._read_json_body().get("state"))
            self._send_json(HTTPStatus.OK, {"ok": True})

    httpd.RequestHandlerClass = Handler
    httpd_ref["server"] = httpd
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port


def wake(m):
    return m.js(WAKE_JS)


def play_one(m, timeout=PLAYING_S + 10):
    """Plays the focused film and waits for the page to be back."""
    m.press(ENTER)
    s = wait(m, lambda s: s["playing"], 3)
    during = wake(m)
    s = wait(m, lambda s: not s["playing"], timeout)
    time.sleep(0.3)  # the last report reaches the server
    return during, s


def check_all(m, mode, reports, check):
    s = wait(m, lambda s: s["rows"][:1] == ["Open my library"] and not s["loading"], 30)
    check("first launch scans, then offers Open my library", s["rows"][:1] == ["Open my library"], s["rows"])
    m.press(ENTER)
    s = wait(m, lambda s: s["library"] and not s["loading"] and len(s["rows"]) == 2, 30)
    check("library shows", len(s["rows"]) == 2, s)
    m.press(DOWN)  # the first film (no Rescan row since the Home actions work)
    check("focus on the first film", state(m)["focusedIndex"] == 0)
    m.js(STUB_JS)

    # 1. keep_awake on, a normal film.
    reports.clear()
    during, s = play_one(m)
    check("on: one screen lock held while the film plays",
          during["held"] == 1 and during["requests"] == 1 and during["types"] == ["screen"], during)
    after = wake(m)
    check("on: released when the film ends", after["held"] == 0 and after["releases"] == 1, after)
    check("on: the launch log gets held, then released", reports == ["held", "released"], reports)
    check("on: the film ended normally", not s["playing"] and not s["banner"], s)

    # 2. Firefox lets go in the middle of the film; the page asks again.
    reports.clear()
    before = wake(m)
    m.press(ENTER)
    wait(m, lambda s: s["playing"], 3)
    time.sleep(0.3)
    m.js("window.__wake.last.release(); document.dispatchEvent(new Event('visibilitychange'));")
    time.sleep(0.3)
    middle = wake(m)
    check("lost: asked again once the page shows",
          middle["requests"] == before["requests"] + 2 and middle["held"] == 1, middle)
    wait(m, lambda s: not s["playing"], PLAYING_S + 10)
    time.sleep(0.3)
    after = wake(m)
    check("lost: nothing held after the film", after["held"] == 0, after)
    check("lost: the launch log says held, lost, held, released",
          reports == ["held", "lost", "held", "released"], reports)

    # 3. The backend is lost during the film.
    reports.clear()
    mode["status"] = "drop"
    m.press(ENTER)
    wait(m, lambda s: s["playing"], 3)
    s = wait(m, lambda s: not s["playing"] and s["banner"], 30)
    mode["status"] = "ok"
    time.sleep(0.3)
    after = wake(m)
    check("backend lost: the error shows", bool(s["banner"]), s)
    check("backend lost: the lock is released anyway", after["held"] == 0, after)
    check("backend lost: the launch log gets held, then released", reports == ["held", "released"], reports)
    time.sleep(PLAYING_S)  # let the faked film end before the next one

    # 3b. mpv exits with an error: the lock is released all the same.
    reports.clear()
    mode["result"] = {"ok": False, "error": "mpv stopped with an error"}
    during, s = play_one(m)
    del mode["result"]
    after = wake(m)
    check("mpv error: a lock was held during the film", during["held"] == 1, during)
    check("mpv error: the error shows", bool(s["banner"]), s)
    check("mpv error: the lock is released", after["held"] == 0, after)
    check("mpv error: the launch log gets held, then released", reports == ["held", "released"], reports)

    # 4. keep_awake off: the page never asks.
    reports.clear()
    mode["keep_awake"] = False
    before = wake(m)
    during, s = play_one(m)
    check("off: no lock asked for", during["requests"] == before["requests"] and during["held"] == 0, during)
    check("off: nothing reported", reports == [], reports)
    mode["keep_awake"] = True

    # 5. Firefox refuses the lock.
    reports.clear()
    m.js("window.__wake.refuse = true;")
    during, s = play_one(m)
    m.js("window.__wake.refuse = false;")
    check("refused: nothing held", during["held"] == 0, during)
    check("refused: the film plays and ends as usual", not s["playing"] and not s["banner"], s)
    check("refused: the launch log says refused, then released", reports == ["refused", "released"], reports)

    # 6. A Firefox without the Screen Wake Lock.
    reports.clear()
    m.js("Object.defineProperty(navigator, 'wakeLock', {configurable: true, value: undefined});")
    during, s = play_one(m)
    check("unsupported: the film plays and ends as usual", not s["playing"] and not s["banner"], s)
    check("unsupported: the launch log says unsupported", reports == ["unsupported"], reports)


def run(env, profile, check):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for base, files in ((tmp / "Movies", MOVIE_FILES), (tmp / "TV Shows", TV_FILES)):
            for rel in files:
                (base / rel).parent.mkdir(parents=True, exist_ok=True)
                (base / rel).write_bytes(b"")
        settings = {"movies_path": str(tmp / "Movies"), "tv_path": str(tmp / "TV Shows"),
                    "mpv_command": "mpv", "mpv_args": [], "data_dir": str(tmp / "data")}
        mode = {"keep_awake": True, "status": "ok"}
        reports = []
        httpd, port = start_server(settings, tmp, mode, reports)
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
            check_all(m, mode, reports, check)
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
        profile = home / ".var/app/org.mozilla.firefox/data/check-profile-screen-awake"
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
