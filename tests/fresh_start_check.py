# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The FRESH START marker in a real, headless Firefox (the fresh start mode). Not
part of the unit tests: it needs Firefox and takes about two minutes.

Uses the Marionette helper from loading_screen_check.py, with invented
films and shows in temporary folders and a fake mpv that only waits a
moment. The servers run with the real launch options (fresh start, and
pretend mpv is missing); the data folders are temporary, so no real data
is read or written.

At every window width in tests/window_sizes.py, from Enamel's smallest
supported box to very wide, the marker reads FRESH START, is wholly on
screen and drawn on top, and covers nothing (nothing but its own bar or
screen is under it), on every screen: loading, first launch, Home on the
Movies and TV Shows tabs, Home's menu, a show's episodes, "Playing…",
and "mpv not found". Without fresh start there is no marker. Screenshots
of each screen at each width go to the folder given as the first argument.

Fresh start opens onboarding (the fresh start onboarding work), at every width, started the way
launch.sh starts it (server.serve) from a pretend app folder whose settings.json
has both folders set and which has a saved library: "No videos found yet" and
both onboarding screens show with the marker right and the focused row clear of
the hint bar; choosing folders reaches the result screen (the first scan screen); the pretend
settings.json and data folder are byte-for-byte unchanged and the session's
folder is gone after a quit. Once: the next fresh start asks again, and the same
app folder without fresh start doesn't ask. The folder search is pointed at
invented folders; the app's own settings.json is never read or written.
(The screens above come after the choice in a session, so those servers simply
start with the folders in hand.)

Run from the repo root:  python3 tests/fresh_start_check.py [screenshot-dir]
"""

import base64
import contextlib
import http.client
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from backend import folder_finder, library_index, server as backend_server  # noqa: E402
from backend.launch_options import FRESH_START, LaunchOptions  # noqa: E402
from backend.server import make_handler  # noqa: E402
from tests.home_shell_check import DOWN, ENTER, FILMS, RIGHT, UP  # noqa: E402
from tests.loading_screen_check import UI_DIR, Marionette, free_port  # noqa: E402
from tests.test_folder_finder import make  # noqa: E402
from tests.test_launch_options import snapshot  # noqa: E402
from tests.test_parsed_library import TV_FILES  # noqa: E402
from tests.window_sizes import FIREFOX_FLAG, SIZES, WINDOW, set_window  # noqa: E402

# Plays for a moment, so "Playing…" shows.
FAKE_MPV = "#!/usr/bin/env python3\nimport time\ntime.sleep(3)\n"

MARKER_JS = """
const visible = (el) => el && !el.hidden && getComputedStyle(el).display !== 'none' && !el.closest('[hidden]');
const shown = (id) => visible(document.getElementById(id));
// An open menu is a modal dialog: its see-through layer takes every tap,
// so there the marker counts as on top when the menu's panel doesn't reach
// it (the bar under the layer is laid out exactly as on Home, checked there).
const panel = document.querySelector('.en-dialog[open] .en-picker');
const meets = (a, b) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
const onTop = (el) => { const r = el.getBoundingClientRect();
  if (panel) return !meets(r, panel.getBoundingClientRect());
  const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
  return !!hit && (hit === el || el.contains(hit)); };
const markers = [...document.querySelectorAll('.fresh-start')].filter(visible);
// Home's menu is a dialog in front of everything: where its panel is taller
// than the space above the hint bar (the shortest windows) it may reach
// over the marker, which is right while the menu is open.
const panelOver = (el) => !!panel && meets(el.getBoundingClientRect(), panel.getBoundingClientRect());
const underPanel = !markers.some(onTop) && markers.some(panelOver);
const top = markers.find(onTop) || (underPanel ? markers.find(panelOver) : null);
let covers = null, box = null, text = null, container = null;
if (top) {
  const r = top.getBoundingClientRect();
  box = {left: r.left, top: r.top, right: r.right, bottom: r.bottom};
  text = top.innerText.trim();
  container = top.parentElement.id;
  // What would be seen there without the marker: only its own bar or screen.
  top.style.visibility = 'hidden';
  covers = [];
  if (!panel) for (const fx of [0.02, 0.25, 0.5, 0.75, 0.98]) for (const fy of [0.1, 0.5, 0.9]) {
    const hit = document.elementFromPoint(r.left + fx * r.width, r.top + fy * r.height);
    if (hit !== top.parentElement) covers.push(hit ? (hit.id || hit.className || hit.tagName) : 'nothing');
  }
  top.style.visibility = '';
}
const onboarding = document.getElementById('onboarding');
const focused = document.activeElement && document.activeElement.closest('.folder-row, .no-videos-action');
const hintTop = document.getElementById('hint-bar').getBoundingClientRect().top;
const focusBox = focused ? focused.getBoundingClientRect() : null;
return {
  loading: shown('loading'),
  onboarding: shown('onboarding') ? onboarding.dataset.step || null : null,
  listShown: visible(onboarding.querySelector('[data-role="groups"]')),
  focusedRow: focused ? focused.dataset.kind : null,
  // Above the hint bar, marker line included. A row taller than the room above
  // the bar (the smallest supported box) starts on screen and fills the room.
  focusClear: !!focusBox && focusBox.top >= -0.5 && (focusBox.bottom <= hintTop + 0.5
    || (focusBox.height > hintTop && focusBox.top < hintTop)),
  resultTitle: document.querySelector('#onboarding [data-role="title"]').textContent,
  firstScan: shown('onboarding') && ['ready', 'nothing', 'failed'].includes(document.getElementById('onboarding').dataset.result),
  library: shown('library'),
  episodes: shown('episodes'),
  mpvMissing: shown('mpv-missing'),
  playing: shown('playing-status'),
  menu: !!document.querySelector('#home-menu[open]'),
  tvSelected: document.querySelector('[data-tab="tv"]').getAttribute('aria-selected') === 'true',
  focusedKind: document.activeElement && document.activeElement.dataset ? document.activeElement.dataset.kind || null : null,
  freshRoot: document.documentElement.hasAttribute('data-fresh-start'),
  markers: markers.length,
  onTop: !!top && !underPanel,
  underPanel,
  container, text, box, covers,
  focusable: top ? top.tabIndex >= 0 : null,
  onScreen: !!box && box.left >= 0 && box.top >= 0 && box.right <= innerWidth + 0.5 && box.bottom <= innerHeight + 0.5,
  overflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth,
};
"""

SCREENS = {
    # screen: (what says it is showing, the marker's container)
    "loading": (lambda s: s["loading"], "loading"),
    "first-launch": (lambda s: not s["loading"] and s["firstScan"], "hint-bar"),
    "home-movies": (lambda s: not s["loading"] and s["library"] and not s["tvSelected"], "hint-bar"),
    "menu": (lambda s: s["menu"], "hint-bar"),
    "home-tv": (lambda s: s["library"] and s["tvSelected"] and not s["menu"], "hint-bar"),
    "episodes": (lambda s: s["episodes"], "hint-bar"),
    "playing": (lambda s: s["playing"], "hint-bar"),
    "mpv-missing": (lambda s: not s["loading"] and s["mpvMissing"], "hint-bar"),
    # Fresh start's way in (the fresh start onboarding work).
    "no-videos": (lambda s: not s["loading"] and s["onboarding"] == "no-videos" and s["focusedRow"], "hint-bar"),
    "step-1": (lambda s: not s["loading"] and s["onboarding"] == "1" and s["listShown"] and s["focusedRow"], "hint-bar"),
    "step-2": (lambda s: s["onboarding"] == "2" and s["listShown"] and s["focusedRow"], "hint-bar"),
    "result": (lambda s: not s["loading"] and s["firstScan"], "hint-bar"),
}


def start_server(settings, logs_dir, options):
    httpd_ref = {}
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
    port = httpd.server_address[1]
    base = make_handler(UI_DIR, logs_dir, settings, httpd_ref, port, options)

    class Handler(base):
        def log_message(self, format, *args):
            pass

        def _handle_shutdown(self):
            # q quits: the test server keeps running.
            self._send_json(200, {"ok": True})

    httpd.RequestHandlerClass = Handler
    httpd_ref["server"] = httpd
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port


def request(port, method, path):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        body = b"{}" if method == "POST" else None
        conn.request(method, path, body=body, headers={"Host": f"127.0.0.1:{port}",
                                                       "Content-Type": "application/json"})
        return json.loads(conn.getresponse().read())
    finally:
        conn.close()


def post(port, path):
    return request(port, "POST", path)


def wait(m, predicate, timeout=10):
    end = time.time() + timeout
    s = m.js(MARKER_JS)
    while not predicate(s) and time.time() < end:
        time.sleep(0.1)
        s = m.js(MARKER_JS)
    return s


class Session:
    """The app as launch.sh starts it, from a pretend app folder, until quit."""

    def __init__(self, folder, environ, fresh_parent):
        self.port = free_port()
        self.httpd_ref = {}

        def run_it():
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                backend_server.serve(folder, environ, self.port, self.httpd_ref, fresh_parent)

        self.thread = threading.Thread(target=run_it, daemon=True)
        self.thread.start()
        end = time.time() + 10
        while time.time() < end:
            try:
                request(self.port, "GET", "/api/status")
                return
            except OSError:
                time.sleep(0.05)
        raise RuntimeError("the app didn't start")

    def quit(self):
        post(self.port, "/api/shutdown")
        self.thread.join(10)
        return not self.thread.is_alive()


class Run:
    def __init__(self, m, shots_dir, check):
        self.m, self.shots_dir, self.check = m, shots_dir, check

    def open(self, port, size):
        set_window(self.m, *WINDOW)
        self.m.send("WebDriver:Navigate", {"url": f"http://127.0.0.1:{port}/"})
        set_window(self.m, *SIZES[size])

    def marker(self, screen, size):
        """The screen shows, then its marker is right: on top, on screen,
        covering nothing."""
        showing, container = SCREENS[screen]
        s = wait(self.m, lambda s: showing(s) and (s["onTop"] or s["underPanel"]), 15)
        where = f"{screen} at {size}"
        self.check(f"{where}: the screen shows", showing(s), s)
        if not showing(s):
            return
        self.m.settle()
        s = self.m.js(MARKER_JS)
        (self.shots_dir / f"fresh-start-{screen}-{size}.png").write_bytes(
            base64.b64decode(self.m.send("WebDriver:TakeScreenshot", {})["value"]))
        if s["underPanel"] and screen == "menu":
            self.check(f"{where}: FRESH START is there, behind the open menu's panel only",
                       s["text"] == "FRESH START", s)
        else:
            self.check(f"{where}: FRESH START is shown, drawn on top", s["onTop"] and s["text"] == "FRESH START", s)
            self.check(f"{where}: covers nothing", s["covers"] == [], s["covers"])
        self.check(f"{where}: in the {container}", s["container"] == container, s["container"])
        self.check(f"{where}: wholly on screen, no sideways scroll", s["onScreen"] and not s["overflowX"], s)
        self.check(f"{where}: never focusable", s["focusable"] is False, s)

    def onboarding(self, app, fresh_parent, nothing_found, size):
        """One whole fresh-start session at this size (the fresh start onboarding work)."""
        check, m = self.check, self.m
        where = f"onboarding at {size}"
        before = (app / "settings.json").read_bytes(), snapshot(app / "data")
        nothing_found.set()
        session = Session(app, {FRESH_START: "1"}, fresh_parent)
        self.open(session.port, size)
        self.marker("no-videos", size)
        nothing_found.clear()
        m.press(ENTER)  # Look again: the folders are there now
        self.marker("step-1", size)
        # Moving with the marker's line in the bar: each row stops above it.
        m.press(DOWN)
        s = wait(m, lambda s: s["focusClear"], 5)
        check(f"{where}: screen 1, the next row is clear of the hint bar", s["focusClear"], s)
        m.press(UP)
        s = wait(m, lambda s: s["focusClear"], 5)
        check(f"{where}: screen 1, and back on the first", s["focusClear"], s)
        m.press(ENTER)
        self.marker("step-2", size)
        m.press(DOWN)
        s = wait(m, lambda s: s["focusClear"], 5)
        check(f"{where}: screen 2, the next row is clear of the hint bar", s["focusClear"], s)
        m.press(ENTER)
        self.marker("result", size)
        s = m.js(MARKER_JS)
        check(f"{where}: choosing folders reaches the result screen", s["resultTitle"] == "Your library is ready", s)
        check(f"{where}: and the session has them", request(session.port, "GET", "/api/onboarding")["needed"] is False)
        check(f"{where}: the app folder's settings.json and data are unchanged",
              ((app / "settings.json").read_bytes(), snapshot(app / "data")) == before)
        check(f"{where}: quits", session.quit())
        check(f"{where}: the session's folder is gone, and nothing else changed", list(fresh_parent.iterdir()) == []
              and ((app / "settings.json").read_bytes(), snapshot(app / "data")) == before)

    def asks_again(self, app, fresh_parent):
        check, m = self.check, self.m
        session = Session(app, {FRESH_START: "1"}, fresh_parent)
        self.open(session.port, "w1280")
        s = wait(m, SCREENS["step-1"][0], 15)
        check("the next fresh start asks again", SCREENS["step-1"][0](s), s)
        check("and it quits", session.quit())
        session = Session(app, {}, fresh_parent)
        self.open(session.port, "w1280")
        s = wait(m, lambda s: not s["loading"] and s["library"], 15)
        check("the same app folder without fresh start opens its library and doesn't ask",
              s["library"] and s["onboarding"] is None and s["markers"] == 0, s)
        check("and it quits, too", session.quit())


def run(env, profile, shots_dir, check):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for base, files in ((tmp / "Movies", FILMS), (tmp / "TV Shows", TV_FILES)):
            for rel in files:
                (base / rel).parent.mkdir(parents=True, exist_ok=True)
                (base / rel).write_bytes(b"")
        fake = tmp / "fake-mpv"
        fake.write_text(FAKE_MPV)
        fake.chmod(0o755)
        settings = {"movies_path": str(tmp / "Movies"), "tv_path": str(tmp / "TV Shows"),
                    "mpv_command": str(fake), "mpv_args": [], "resume": True, "keep_awake": False}
        servers = []

        def server(name, fresh_start=True, pretend_no_mpv=False):
            folder = tmp / f"kettle-fresh-{name}"
            for sub in ("data", "watch_later"):
                (folder / sub).mkdir(parents=True)
            if fresh_start:
                options = LaunchOptions(data_dir=folder / "data", fresh_root=folder,
                                        watch_later_dir=folder / "watch_later", pretend_no_mpv=pretend_no_mpv)
            else:
                options = LaunchOptions(data_dir=folder / "data", pretend_no_mpv=pretend_no_mpv)
            httpd, port = start_server({**settings, "data_dir": str(options.data_dir)}, tmp, options)
            servers.append(httpd)
            return port

        fresh_port = server("fresh")
        missing_port = server("missing", pretend_no_mpv=True)
        # The pretend app folder for fresh start's way in (the fresh start onboarding work): both
        # folders set and a saved library, which must not show.
        app = tmp / "app"
        app.mkdir()
        (app / "ui").symlink_to(UI_DIR)
        (app / "vendor").symlink_to(REPO / "vendor")
        (app / "settings.json").write_text(json.dumps({
            "movies_path": settings["movies_path"], "tv_path": settings["tv_path"], "mpv_command": str(fake),
            "keep_awake": False}))
        index = library_index.full_scan({"movies": settings["movies_path"], "tv": settings["tv_path"]}, None, lambda *a: None)
        library_index.save(app / "data" / library_index.FILE_NAME, index)
        fresh_parent = tmp / "fresh-parent"
        fresh_parent.mkdir()
        found = tmp / "found"
        make(str(found), ["Films/Alpha/a.mkv", "Films/Beta/b.mkv", "Shows/Gamma/g.mkv", "Shows/Delta/d.mkv"])
        nothing_there = tmp / "nothing-there"
        nothing_there.mkdir()
        nothing_found = threading.Event()

        def list_places():
            root = nothing_there if nothing_found.is_set() else found
            return [folder_finder.Place("internal", "Internal storage", str(root))]

        logged = []
        patches = [mock.patch.object(folder_finder, "list_places", list_places),
                   mock.patch.object(backend_server, "_log", logged.append)]
        for patch in patches:
            patch.start()
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
            r = Run(m, shots_dir, check)
            # A brand-new user: the loading screen, then the scan's result. Each
            # has its own server, as the scan saves a library.
            for size in SIZES:
                r.open(server(f"first-{size}"), size)
                r.marker("loading", size)
                r.marker("first-launch", size)
            # The same scan into the fresh folder, for the screens below.
            post(fresh_port, "/api/library/scan")
            end = time.time() + 30
            while request(fresh_port, "GET", "/api/library/scan/status")["state"] == "scanning":
                if time.time() > end:
                    raise RuntimeError("the scan never finished")
                time.sleep(0.2)
            for size in SIZES:
                r.open(fresh_port, size)
                r.marker("home-movies", size)
                m.press("m")
                r.marker("menu", size)
                m.press("q")
                wait(m, lambda s: not s["menu"], 5)
                m.press(RIGHT)
                r.marker("home-tv", size)
                m.press(DOWN)
                wait(m, lambda s: s["focusedKind"] == "show", 5)
                m.press(ENTER)
                r.marker("episodes", size)
                wait(m, lambda s: s["focusedKind"] == "episode", 5)
                m.press(ENTER)
                r.marker("playing", size)
                wait(m, lambda s: not s["playing"], 10)
            for size in SIZES:
                r.open(missing_port, size)
                r.marker("mpv-missing", size)
            # Normal use: no marker anywhere.
            normal_port = server("normal", fresh_start=False)
            r.open(normal_port, "w1280")
            s = wait(m, lambda s: not s["loading"] and s["firstScan"], 15)
            time.sleep(0.5)
            s = m.js(MARKER_JS)
            check("without fresh start: no marker, and the page isn't marked", s["firstScan"]
                  and s["markers"] == 0 and not s["freshRoot"], s)
            for size in SIZES:
                r.onboarding(app, fresh_parent, nothing_found, size)
            r.asks_again(app, fresh_parent)
            check("no path in the log", not any(str(tmp) in line for line in logged), logged)
        finally:
            for patch in patches:
                patch.stop()
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
            for httpd in servers:
                httpd.shutdown()
                httpd.server_close()


def main():
    shots_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="fresh-start-"))
    shots_dir.mkdir(parents=True, exist_ok=True)
    results = []

    def check(text, ok, detail=None):
        results.append((text if ok or detail is None else f"{text}: {json.dumps(detail, default=str)}", ok))

    real = REPO / "settings.json"
    stamp = lambda st: (st.st_size, st.st_mtime_ns, st.st_ino)
    real_before = stamp(os.stat(real)) if real.exists() else None
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        home = Path(tmp) / "home"
        env = dict(os.environ, HOME=str(home), MOZ_HEADLESS="1")
        profile = home / ".var/app/org.mozilla.firefox/data/check-profile-fresh-start"
        profile.mkdir(parents=True)
        try:
            run(env, profile, shots_dir, check)
        except Exception as exc:
            results.append((f"could not run ({exc!r})", False))
    real_after = stamp(os.stat(real)) if real.exists() else None
    results.append(("the app's own settings.json was never written", real_after == real_before))
    for text, ok in results:
        print(f"{'ok  ' if ok else 'FAIL'} {text}")
    print(f"screenshots: {shots_dir}")
    failures = sum(not ok for _, ok in results)
    print("all good" if not failures else f"{failures} problem(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
