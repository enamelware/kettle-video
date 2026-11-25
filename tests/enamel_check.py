# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The vendored design system in a real, headless Firefox (the first design system step). Not
part of the unit tests: it needs Firefox and takes about half a minute.

Opens the page with invented films and shows. Checks that both stylesheets
load (their rules are readable) before the app's own, and that every file
the page fetched came from the app's own server, on the Movies tab, the TV
Shows tab and one show's episodes, at every window width in
tests/window_sizes.py (the responsive layout work).

Until the second design system step it also checked that the page looked exactly the same with
the two stylesheets taken out; since the second design system step the app uses Enamel on purpose,
so that comparison is gone (tests/design_system_check.py checks the look).

Screenshots go to the folder given as the first argument.

Run from the repo root:  python3 tests/enamel_check.py [screenshot-dir]
"""

import base64
import contextlib
import io
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

from backend import library_index  # noqa: E402
from backend.server import make_handler  # noqa: E402
from tests.home_shell_check import FILMS  # noqa: E402
from tests.loading_screen_check import UI_DIR, Marionette, free_port  # noqa: E402
from tests.window_sizes import SIZES, WINDOW, set_window, FIREFOX_FLAG  # noqa: E402
from tests.test_parsed_library import TV_FILES  # noqa: E402

ENTER, DOWN, RIGHT = "", "", ""
VENDORED = ["vendor/enamel/tokens/enamel.css", "vendor/enamel/components/enamel-components.css"]

READY_JS = """
const shown = (id) => { const el = document.getElementById(id); return el && !el.hidden; };
const loading = document.querySelector('.loading-screen');
return shown('library') && (!loading || loading.hidden || getComputedStyle(loading).display === 'none');
"""
EPISODES_JS = "const el = document.getElementById('episodes'); return !!el && !el.hidden;"

SHEETS_JS = """
return {
  sheets: [...document.styleSheets].map(s => {
    let rules = -1;
    try { rules = s.cssRules.length; } catch (e) {}
    return {href: s.href, rules};
  }),
  resources: performance.getEntriesByType('resource').map(e => e.name),
  page: location.origin,
};
"""


def start_server(ui_dir, settings, logs_dir):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
    port = httpd.server_address[1]
    with contextlib.redirect_stdout(io.StringIO()):
        base = make_handler(ui_dir, logs_dir, settings, {}, port)

    class Handler(base):
        def log_message(self, format, *args):
            pass

        def _handle_mpv_status(self):
            self._send_json(HTTPStatus.OK, {"available": True})

    httpd.RequestHandlerClass = Handler
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port


def wait_for(m, script, timeout):
    end = time.time() + timeout
    while time.time() < end:
        if m.js(script):
            return True
        time.sleep(0.2)
    return False


def capture(m, port, shots_dir, label):
    """The stylesheets and fetched files at each size, in three places; None
    where a place didn't show."""
    set_window(m, *WINDOW)
    m.send("WebDriver:Navigate", {"url": f"http://127.0.0.1:{port}/"})
    dumps = {}
    if not wait_for(m, READY_JS, 30):
        return dumps, m.js(SHEETS_JS)
    for place, keys, ready in (("movies", [], READY_JS), ("tv", [RIGHT], READY_JS),
                               ("episodes", [DOWN, DOWN, ENTER], EPISODES_JS)):
        for key in keys:
            m.press(key)
            time.sleep(0.3)
        if not wait_for(m, ready, 5):
            dumps[place] = None
            continue
        for size, (w, h) in SIZES.items():
            set_window(m, w, h)
            time.sleep(0.5)
            (shots_dir / f"enamel-{place}-{size}-{label}.png").write_bytes(
                base64.b64decode(m.send("WebDriver:TakeScreenshot", {})["value"]))
            dumps[f"{place} {size}"] = m.js(SHEETS_JS)
    return dumps, m.js(SHEETS_JS)


def main():
    shots_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="enamel-"))
    shots_dir.mkdir(parents=True, exist_ok=True)
    results = []

    def check(text, ok, detail=None):
        results.append((text if ok or detail is None else f"{text}: {json.dumps(detail, default=str)[:2000]}", ok))

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        tmp = Path(tmp)
        for base, files in ((tmp / "Movies", FILMS), (tmp / "TV Shows", TV_FILES)):
            for rel in files:
                (base / rel).parent.mkdir(parents=True, exist_ok=True)
                (base / rel).write_bytes(b"")
        settings = {"movies_path": str(tmp / "Movies"), "tv_path": str(tmp / "TV Shows"),
                    "mpv_command": "mpv", "mpv_args": [], "data_dir": str(tmp / "data")}
        roots = {"movies": settings["movies_path"], "tv": settings["tv_path"]}
        index = library_index.full_scan(roots, None, lambda done, total: None)
        library_index.save(tmp / "data" / library_index.FILE_NAME, index)

        home = tmp / "home"
        env = dict(os.environ, HOME=str(home), MOZ_HEADLESS="1")
        profile = home / ".var/app/org.mozilla.firefox/data/check-profile-enamel"
        profile.mkdir(parents=True)
        mport = free_port()
        (profile / "user.js").write_text(
            f'user_pref("marionette.port", {mport});\n'
            'user_pref("browser.shell.checkDefaultBrowser", false);\n'
            'user_pref("browser.aboutwelcome.enabled", false);\n'
        )
        servers = [start_server(UI_DIR, settings, tmp)]
        cmd = ["--headless", "--marionette", FIREFOX_FLAG, "--no-remote", "-profile", str(profile), "about:blank"]
        ff = subprocess.Popen(
            ["firefox", *cmd] if shutil.which("firefox") else ["flatpak", "run", "org.mozilla.firefox", *cmd],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        m = None
        try:
            m = Marionette(mport)
            built, sheets = capture(m, servers[0][1], shots_dir, "with")
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
            for httpd, _ in servers:
                httpd.shutdown()
                httpd.server_close()

    origin = sheets["page"]
    hrefs = [s["href"] for s in sheets["sheets"]]
    expected = [f"{origin}/{path}" for path in VENDORED + ["css/tokens.css", "css/defaults.css"]]
    check("the page loads both Enamel stylesheets, before its own", hrefs == expected, hrefs)
    check("both Enamel stylesheets arrived (their rules are readable)",
          all(s["rules"] > 0 for s in sheets["sheets"][:2]), sheets["sheets"])
    outside = [name for name in sheets["resources"] if not name.startswith(origin + "/")]
    check(f"every file fetched came from the app's own server ({len(sheets['resources'])} files)",
          not outside and sheets["resources"], outside)
    for place in ("movies", "tv", "episodes"):
        for size in SIZES:
            key = f"{place} {size}"
            got = built.get(key)
            check(f"{key}: shows, with both Enamel stylesheets loaded",
                  bool(got) and [x["href"] for x in got["sheets"][:2]] == expected[:2]
                  and all(x["rules"] > 0 for x in got["sheets"][:2]), got)

    for text, ok in results:
        print(f"{'ok  ' if ok else 'FAIL'} {text}")
    print(f"screenshots: {shots_dir}")
    failures = sum(not ok for _, ok in results)
    print("all good" if not failures else f"{failures} problem(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
