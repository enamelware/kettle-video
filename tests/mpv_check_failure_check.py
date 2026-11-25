# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The mpv check at launch fails, or reports a broken mpv_command, in a real
headless Firefox (the settings mistakes work). Not part of the unit tests: it needs Firefox
and takes about a minute.

For each case the loading screen must give way to a plain message on the
"mpv not found" screen, instead of spinning on "Still working...":

  garbage   the check answers with a server error page
  drop      the check gets no answer at all (connection dropped)
  shape     the check answers with JSON that isn't an mpv status
  hang      the check never answers (the page gives up after 30 s)
  absent    mpv isn't installed: the install hint shows, as before
  quote     the real check, with an mpv_command whose quote isn't closed
  type      the real check, with an mpv_command that is a number
  missing   the real check, with an mpv_command naming a missing program

Each message must fit the screen at every window width in
tests/window_sizes.py (the responsive layout work), and q must still quit.
Screenshots of the quote case are saved to the folder given as the first
argument (default: a temporary folder, printed at the end). Settings are
temporary copies; the real settings.json is never read.

Run from the repo root:  python3 tests/mpv_check_failure_check.py [screenshot-dir]
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

from backend import mpv  # noqa: E402
from backend.server import make_handler  # noqa: E402
from tests.loading_screen_check import UI_DIR, Marionette, free_port  # noqa: E402
from tests.window_sizes import SIZES, WINDOW, set_window, FIREFOX_FLAG  # noqa: E402

CHECK_FAILED = "The app couldn't check whether mpv is ready to play."
# The page waits 30 s for the check, plus the loading screen's 2 s minimum.
HANG_S = 45
CASES = {
    # case: (mpv_command, the message's lines before "Press q to exit.")
    "garbage": ("auto", [CHECK_FAILED]),
    "drop": ("auto", [CHECK_FAILED]),
    "shape": ("auto", [CHECK_FAILED]),
    "hang": ("auto", [CHECK_FAILED]),
    # mpv not installed: the install hint alone, as before the settings mistakes work.
    "absent": ("auto", [mpv.INSTALL_HINT]),
    "quote": ('mpv "--fs', ["settings.json's 'mpv_command' has a quote that isn't closed.", mpv.SETTING_HINT]),
    "type": (7, ["settings.json's 'mpv_command' must be text in quotes, like \"auto\" or \"mpv\".",
                 mpv.SETTING_HINT]),
    "missing": ("/nonexistent/kettle-mpv",
                ["settings.json's 'mpv_command' names a program that can't be found.", mpv.SETTING_HINT]),
}

DOWN = "\ue015"

STATE_JS = """
const visible = (el) => el && !el.hidden && getComputedStyle(el).display !== 'none';
const box = document.getElementById('mpv-missing');
const r = box.getBoundingClientRect();
return {
  loading: visible(document.querySelector('.loading-screen')),
  slow: visible(document.querySelector('.loading-screen [data-role="slow"]')),
  message: visible(box) ? [...box.querySelectorAll('p')].map(p => p.textContent) : null,
  // Wholly on screen and clear of the hint bar, which must never cover it (the responsive layout work).
  fits: r.left >= 0 && r.right <= innerWidth && r.bottom <= Math.min(innerHeight, document.getElementById('hint-bar').getBoundingClientRect().top) + 0.5,
  overflowX: document.documentElement.scrollWidth > innerWidth,
  library: visible(document.getElementById('library')),
};
"""


def start_server(settings, logs_dir, case, quit_seen):
    httpd_ref = {}
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
    port = httpd.server_address[1]
    base = make_handler(UI_DIR, logs_dir, settings, httpd_ref, port)

    class Handler(base):
        def log_message(self, format, *args):
            pass

        def _handle_mpv_status(self):
            how = case[0]
            if how == "garbage":
                body = b"<html>Internal error</html>"
                self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if how == "drop":
                self.close_connection = True
                return
            if how == "shape":
                return self._send_json(HTTPStatus.OK, {"hello": "world"})
            if how == "absent":
                return self._send_json(HTTPStatus.OK, {"available": False, "install_hint": mpv.INSTALL_HINT})
            if how == "hang":
                time.sleep(HANG_S + 5)
                self.close_connection = True
                return
            return super()._handle_mpv_status()

        def _handle_shutdown(self):
            # q quits: noted, but the test server keeps running.
            quit_seen.append(case[0])
            self._send_json(HTTPStatus.OK, {"ok": True})

    httpd.RequestHandlerClass = Handler
    httpd_ref["server"] = httpd
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port


def wait(m, predicate, timeout):
    end = time.time() + timeout
    while time.time() < end:
        s = m.js(STATE_JS)
        if predicate(s):
            return s
        time.sleep(0.25)
    return m.js(STATE_JS)


def run(env, profile, shots_dir, check):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "Movies").mkdir()
        (tmp / "TV Shows").mkdir()
        settings = {"movies_path": str(tmp / "Movies"), "tv_path": str(tmp / "TV Shows"),
                    "mpv_command": "auto", "mpv_args": [], "resume": True, "keep_awake": False, "data_dir": str(tmp / "data")}
        case = ["garbage"]
        quit_seen = []
        httpd, port = start_server(settings, tmp, case, quit_seen)
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
            for name, (command, lines) in CASES.items():
                case[0] = name
                settings["mpv_command"] = command
                set_window(m, *WINDOW)
                m.send("WebDriver:Navigate", {"url": f"http://127.0.0.1:{port}/"})
                s = m.js(STATE_JS)
                check(f"{name}: the loading screen shows first", s["loading"], s)
                s = wait(m, lambda s: not s["loading"], HANG_S if name == "hang" else 10)
                check(f"{name}: the loading screen gives way", not s["loading"], s)
                check(f"{name}: a plain message shows", s["message"] == [*lines, "Press q to exit."], s)
                check(f"{name}: no library behind it", not s["library"], s)
                for size, (w, h) in SIZES.items():
                    set_window(m, w, h)
                    time.sleep(0.4)
                    s = m.js(STATE_JS)
                    if not s["fits"] and not s["overflowX"]:
                        # Taller than a short window (the responsive layout work): with nothing
                        # to focus, Down scrolls the page to the message's end.
                        for _ in range(6):
                            m.press(DOWN)
                        time.sleep(0.3)
                        s = m.js(STATE_JS)
                        check(f"{name}: at {size} Down scrolls the message to its end", s["fits"], s)
                        m.js("window.scrollTo(0, 0); return true;")
                    else:
                        check(f"{name}: the message fits at {size}", s["fits"] and not s["overflowX"], s)
                    if name == "quote":
                        (shots_dir / f"mpv-command-problem-{size}.png").write_bytes(
                            base64.b64decode(m.send("WebDriver:TakeScreenshot", {})["value"]))
                m.press("q")
                time.sleep(0.5)
                check(f"{name}: q quits", name in quit_seen, quit_seen)
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

    shots_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="mpv-check-shots-"))
    shots_dir.mkdir(parents=True, exist_ok=True)
    # Firefox can still be writing its profile as it quits.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        home = Path(tmp) / "home"
        env = dict(os.environ, HOME=str(home), MOZ_HEADLESS="1")
        profile = home / ".var/app/org.mozilla.firefox/data/check-profile-mpv-check"
        profile.mkdir(parents=True)
        try:
            run(env, profile, shots_dir, check)
        except Exception as exc:
            results.append((f"could not run ({exc!r})", False))
    for text, ok in results:
        print(f"{'ok  ' if ok else 'FAIL'} {text}")
    print(f"screenshots: {shots_dir}")
    failures = sum(not ok for _, ok in results)
    print("all good" if not failures else f"{failures} problem(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
