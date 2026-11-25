# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Watch the loading screen in a real Firefox (the loading screen work). Not part of the
unit tests: it needs Firefox and takes about half a minute.

It drives a headless Firefox (no window) through Marionette, Firefox's
built-in remote control, with a throwaway profile and home folder. Cases:

  slow   the library takes 15 s: the screen shows, the wordmark uses the
         bundled font, and "Still working..." appears after 10 s
  quit   the library takes 15 s: pressing q on the screen quits the app
  fail   the library request fails: the error banner replaces the screen
  real   the real folders from settings.json (read-only), scanned first into
         a temporary saved library: the screen stays at least 2 s, ignores
         the arrow keys meanwhile, then the list shows, Movies tab focused
  first  no saved library: nothing waits behind the screen; the scan starts after it

In the real and first cases, the focused row waiting behind the screen must
be covered by it, ring included (the loading screen focus fix).

Screenshots of the slow case at each window width in tests/window_sizes.py
(the responsive layout work) are saved to the folder given
as the first argument (default: a temporary folder, printed at the end).

Run from the repo root:  python3 tests/loading_screen_check.py [screenshot-dir]
"""

import base64
import json
import os
import shutil
import socket
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
from backend.settings import load_settings  # noqa: E402

UI_DIR = REPO / "ui"
SLOW_LIBRARY_S = 15
from tests.window_sizes import SIZES, WINDOW, set_window, FIREFOX_FLAG  # noqa: E402


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server(case, settings, logs_dir):
    httpd_ref = {}
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
    port = httpd.server_address[1]
    base = make_handler(UI_DIR, logs_dir, settings, httpd_ref, port)

    class Handler(base):
        def log_message(self, format, *args):
            pass

        def _handle_mpv_status(self):
            if case == "real":
                return super()._handle_mpv_status()
            self._send_json(HTTPStatus.OK, {"available": True})

        def _handle_library(self):
            if case == "fail":
                return self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "test"})
            return super()._handle_library()

        # Since the parsed library view the page asks for the parsed library first.
        def _handle_parsed_library(self):
            if case in ("slow", "quit"):
                time.sleep(SLOW_LIBRARY_S)
            if case == "fail":
                return self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "test"})
            return super()._handle_parsed_library()

    httpd.RequestHandlerClass = Handler
    httpd_ref["server"] = httpd
    stopped = threading.Event()

    def serve():
        httpd.serve_forever()
        stopped.set()

    threading.Thread(target=serve, daemon=True).start()
    return httpd, port, stopped


class Marionette:
    """Just enough of Firefox's remote-control protocol for these checks."""

    def __init__(self, port, timeout=60):
        end = time.time() + timeout
        while True:
            try:
                self.sock = socket.create_connection(("127.0.0.1", port), timeout=30)
                break
            except OSError:
                if time.time() > end:
                    raise
                time.sleep(0.5)
        self.buf = b""
        self.msg_id = 0
        self._read()  # greeting
        self.send("WebDriver:NewSession", {"capabilities": {}})

    def _read(self):
        while b":" not in self.buf:
            self.buf += self.sock.recv(65536)
        length, _, rest = self.buf.partition(b":")
        length = int(length)
        while len(rest) < length:
            rest += self.sock.recv(65536)
        self.buf = rest[length:]
        return json.loads(rest[:length])

    def send(self, command, params=None):
        self.msg_id += 1
        data = json.dumps([0, self.msg_id, command, params or {}]).encode()
        self.sock.sendall(str(len(data)).encode() + b":" + data)
        _, _, error, result = self._read()
        if error:
            raise RuntimeError(f"{command}: {error}")
        return result

    def js(self, script):
        return self.send("WebDriver:ExecuteScript", {"script": script, "args": []})["value"]

    def press(self, key):
        self.send("WebDriver:PerformActions", {"actions": [{
            "type": "key", "id": "kb",
            "actions": [{"type": "keyDown", "value": key}, {"type": "keyUp", "value": key}],
        }]})

    # Since Enamel 0.5.0 (the Enamel 0.5.0 upgrade) things move: a focused tile grows and
    # its ring narrows, a focused row fades its lift in. Checks that measure
    # the look wait for that to finish first. The ring's slow breathing
    # afterwards (about five seconds, opacity only) changes nothing they
    # measure, so it isn't waited for.
    MOVING_JS = """
return document.getAnimations().some(a => a.playState === 'running' && a.animationName !== 'en-focus-pulse');
"""

    def settle(self, timeout=3):
        """Wait until nothing on the page is moving (at most `timeout` s)."""
        end = time.time() + timeout
        while self.js(self.MOVING_JS) and time.time() < end:
            time.sleep(0.05)


STATE_JS = """
const visible = (el) => el && !el.hidden && getComputedStyle(el).display !== 'none';
const loading = document.querySelector('.loading-screen');
const logo = document.querySelector('.kettle-logo');
// A focused row, or the focused tab (the Home shell work: the list starts on the tabs).
const row = document.activeElement && (document.activeElement.matches('.file-row, .result-action')
  || document.activeElement.classList.contains('tab')) ? document.activeElement : null;
// Is the focused row (or its ring, just outside it) drawn above the screen?
const showsThrough = row && visible(loading) && (() => {
  const r = row.getBoundingClientRect();
  const points = [[r.left + r.width / 2, r.top + r.height / 2], [r.left - 3, r.top + r.height / 2]];
  return points.some(([x, y]) => { const hit = document.elementFromPoint(x, y);
    return hit && !loading.contains(hit) && (row.contains(hit) || hit === row); });
})();
// The Home shell work: the screen covers the shell's black bars too (the top one Home's action bar since the Home actions work).
const barsCovered = visible(loading) && ['action-bar', 'hint-bar'].every(id => {
  const bar = document.getElementById(id);
  if (!bar) return true;
  const r = bar.getBoundingClientRect();
  const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
  return hit && loading.contains(hit);
});
return {
  barsCovered: !!barsCovered,
  rowBehind: !!row && visible(loading),
  showsThrough: !!showsThrough,
  loading: visible(loading),
  slow: visible(loading.querySelector('[data-role="slow"]')),
  library: visible(document.getElementById('library')),
  firstScan: visible(document.querySelector('#onboarding[data-result]:not([data-result="reading"])')),
  rows: document.querySelectorAll('.file-row, .result-action').length,
  focused: document.activeElement && document.activeElement.className,
  focusedIndex: [...document.querySelectorAll('.file-row, .result-action')].indexOf(document.activeElement),
  focusedTab: document.activeElement && document.activeElement.dataset ? document.activeElement.dataset.tab || null : null,
  banner: visible(document.getElementById('error-banner'))
    ? document.getElementById('error-banner').textContent : null,
  // Enamel's whole page speckle shows on the loading screen (the Enamel 0.11.0 upgrade): the same
  // picture as a bare .en-speckle, not one wiped by the app's background.
  speckleWhole: (() => { const bare = document.createElement('div'); bare.className = 'en-speckle';
    document.body.append(bare); const want = getComputedStyle(bare).backgroundImage; bare.remove();
    const got = getComputedStyle(loading).backgroundImage; return want !== 'none' && got === want; })(),
  logoText: logo.textContent,
  logoFontLoaded: document.fonts.check('1em "Rubik Mono One"'),
  logoFontStatus: [...document.fonts].filter(f => f.family.includes('Rubik')).map(f => f.status),
  logoFamily: getComputedStyle(logo).fontFamily,
  logoColour: getComputedStyle(logo).color,
  logoFits: logo.scrollWidth <= logo.parentElement.clientWidth,
  logoLines: Math.round(logo.getBoundingClientRect().height / parseFloat(getComputedStyle(logo).lineHeight)),
};
"""


def wait_state(m, predicate, timeout):
    end = time.time() + timeout
    while time.time() < end:
        state = m.js(STATE_JS)
        if predicate(state):
            return state
        time.sleep(0.25)
    return m.js(STATE_JS)


def run_case(case, firefox_env, profile, shots_dir, results):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        if case == "real":
            settings = load_settings(REPO)
        else:
            settings = {"movies_path": str(tmp), "tv_path": str(tmp), "mpv_command": "mpv", "mpv_args": []}
        settings["data_dir"] = str(tmp / "data")  # never the app's own saved library
        if case == "real":
            roots = {"movies": settings["movies_path"], "tv": settings["tv_path"]}
            index = library_index.full_scan(roots, None, lambda done, total: None)
            library_index.save(Path(settings["data_dir"]) / library_index.FILE_NAME, index)
        httpd, port, stopped = start_server(case, settings, tmp)
        mport = free_port()
        (profile / "user.js").write_text(
            f'user_pref("marionette.port", {mport});\n'
            'user_pref("browser.shell.checkDefaultBrowser", false);\n'
            'user_pref("browser.aboutwelcome.enabled", false);\n'
            'user_pref("datareporting.policy.firstRunURL", "");\n'
        )
        ff = subprocess.Popen(
            ["flatpak", "run", "org.mozilla.firefox", "--headless", "--marionette", FIREFOX_FLAG,
             "--no-remote", "-profile", str(profile), "about:blank"]
            if shutil.which("firefox") is None else
            ["firefox", "--headless", "--marionette", FIREFOX_FLAG, "--no-remote", "-profile", str(profile), "about:blank"],
            env=firefox_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        m = None
        try:
            m = Marionette(mport)
            w, h = WINDOW
            set_window(m, w, h)
            started = time.time()
            m.send("WebDriver:Navigate", {"url": f"http://127.0.0.1:{port}/"})

            if case == "slow":
                first = wait_state(m, lambda s: s["loading"] and s["logoFontLoaded"], 5)
                results.append(("slow: loading screen shows at launch", first["loading"] and not first["library"]))
                results.append((f"slow: wordmark text is \"{first['logoText']}\", font {first['logoFamily']}, "
                                 f"bundled font {first['logoFontStatus']}", first["logoFontLoaded"]))
                results.append((f"slow: wordmark colour {first['logoColour']} (Mustard is rgb(228, 168, 58))",
                                first["logoColour"] == "rgb(228, 168, 58)"))
                results.append(("slow: the loading screen shows Enamel's whole page speckle (the Enamel 0.11.0 upgrade)",
                                first["speckleWhole"]))
                for name, (w, h) in SIZES.items():
                    set_window(m, w, h)
                    time.sleep(0.5)
                    s = m.js(STATE_JS)
                    results.append((f"slow: at {name} the wordmark is on one line and fits the screen",
                                    s["logoFits"] and s["logoLines"] == 1))
                    results.append((f"slow: at {name} the screen covers the top bar and the hint bar (the Home shell work)",
                                    s["barsCovered"]))
                    png = base64.b64decode(m.send("WebDriver:TakeScreenshot", {})["value"])
                    (shots_dir / f"loading-{name}.png").write_bytes(png)
                early = m.js(STATE_JS)
                results.append(("slow: no \"Still working...\" before 10 s", not early["slow"]
                                 and time.time() - started < 10))
                s = wait_state(m, lambda s: s["slow"], 12)
                waited = time.time() - started
                results.append((f"slow: \"Still working...\" appears (after {waited:.1f} s) and the screen stays",
                                s["slow"] and s["loading"] and 9.5 <= waited <= 12))
                png = base64.b64decode(m.send("WebDriver:TakeScreenshot", {})["value"])
                (shots_dir / "still-working.png").write_bytes(png)
                # No saved library in this test setup: the scan and its result.
                s = wait_state(m, lambda s: s["firstScan"], SLOW_LIBRARY_S + 10)
                results.append(("slow: the scan's result replaces it when the library answer arrives",
                                 s["firstScan"] and not s["loading"]))

            elif case == "quit":
                wait_state(m, lambda s: s["loading"], 5)
                time.sleep(1)
                m.press("q")
                results.append(("quit: q on the loading screen quits the app (server shut down)",
                                 stopped.wait(5)))

            elif case == "fail":
                s = wait_state(m, lambda s: not s["loading"], 10)
                took = time.time() - started
                results.append((f"fail: the screen stays at least 2 s (gone after {took:.1f} s)", took >= 2))
                results.append((f"fail: error banner replaces the screen: {s['banner']!r}",
                                 s["banner"] == "Couldn't read the library." and not s["loading"]))

            elif case == "first":
                s = wait_state(m, lambda s: s["loading"], 10)
                results.append(("first: nothing to press waits behind the screen",
                                s["loading"] and not s["rowBehind"] and not s["showsThrough"]))
                # The screen stays only 2 s here, time for the narrowest and
                # the widest window (the responsive layout work).
                for name in (min(SIZES, key=SIZES.get), max(SIZES, key=SIZES.get)):
                    set_window(m, *SIZES[name])
                    time.sleep(0.3)
                    s = m.js(STATE_JS)
                    results.append((f"first: at {name}, nothing shows through the screen",
                                    s["loading"] and not s["showsThrough"]))
                    png = base64.b64decode(m.send("WebDriver:TakeScreenshot", {})["value"])
                    (shots_dir / f"first-behind-{name}.png").write_bytes(png)
                s = wait_state(m, lambda s: s["firstScan"], 20)
                results.append(("first: after the screen, the scan runs and its result's first button is focused",
                                 s["firstScan"] and s["focusedIndex"] == 0))

            elif case == "real":
                # Wait until the list is ready behind the screen, then press
                # ArrowDown while the screen still shows: it must be ignored.
                s = wait_state(m, lambda s: s["rows"] > 1 or not s["loading"], 60)
                pressed_under = s["loading"] and s["rows"] > 1
                results.append(("real: the focused Movies tab waiting behind the screen is covered by it",
                                 s["rowBehind"] and not s["showsThrough"]))
                png = base64.b64decode(m.send("WebDriver:TakeScreenshot", {})["value"])
                (shots_dir / "real-behind.png").write_bytes(png)
                m.press("\ue015")
                m.press("\ue015")
                s = wait_state(m, lambda s: not s["loading"], 60)
                took = time.time() - started
                results.append((f"real: the screen stays at least 2 s (gone after {took:.1f} s)", took >= 2))
                # The Home shell work: the Movies tab has the focus at launch.
                results.append(("real: arrow keys pressed while the list waits behind the screen "
                                "don't move the focus", pressed_under and s["focusedTab"] == "movies"))
                s = wait_state(m, lambda s: s["library"] or s["banner"], 60)
                results.append((f"real: the saved list shows without a scan in {took:.1f} s, "
                                f"{s['rows']} rows, Movies tab focused", s["library"] and not s["loading"]
                                and s["rows"] > 1 and s["focusedTab"] == "movies"))
        finally:
            # Stopping the `flatpak run` wrapper doesn't stop the Firefox
            # inside it, so ask Firefox itself to quit.
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
            if not stopped.is_set():
                httpd.shutdown()
            httpd.server_close()


def main():
    shots_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="loading-shots-"))
    shots_dir.mkdir(parents=True, exist_ok=True)
    results = []
    # Firefox can still be writing its profile as it exits; don't fail on that.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        home = Path(tmp) / "home"
        env = dict(os.environ, HOME=str(home), MOZ_HEADLESS="1")
        for case in ("slow", "quit", "fail", "real", "first"):
            profile = home / f".var/app/org.mozilla.firefox/data/check-profile-{case}"
            profile.mkdir(parents=True)
            try:
                run_case(case, env, profile, shots_dir, results)
            except Exception as exc:  # report and carry on with the next case
                results.append((f"{case}: could not run ({exc})", False))
    for text, ok in results:
        print(f"{'ok  ' if ok else 'FAIL'} {text}")
    print(f"screenshots: {shots_dir}")
    failures = sum(not ok for _, ok in results)
    print("all good" if not failures else f"{failures} problem(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
