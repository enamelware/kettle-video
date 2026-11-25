# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Drive the Home tab strip in a real, headless Firefox (the TV beta label): the
TV Shows tab marked as beta. Not part of the unit tests: it needs Firefox.

Uses the Marionette helper from loading_screen_check.py and the server
from home_shell_check.py, with invented films and shows (playing is
faked). At every window width, from Enamel's smallest supported box to
very wide: "(BETA)" sits on the same line as "SHOWS"; the TV Shows tab is
the same size whether it is neither selected nor focused, focused only,
or selected and focused, and selected with the focus on a show; both tabs
fit in the window, with no sideways scroll; the Movies tab reads "MOVIES"
and its count only. Screenshots of each state at each width go to the
folder given as the first argument.

Run from the repo root:  python3 tests/tv_beta_check.py [screenshot-dir]
"""

import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from backend import library_index  # noqa: E402
from tests.home_shell_check import DOWN, FILMS, LEFT, RIGHT, UP, start_server  # noqa: E402
from tests.loading_screen_check import Marionette, free_port  # noqa: E402
from tests.test_parsed_library import TV_FILES  # noqa: E402
from tests.window_sizes import FIREFOX_FLAG, SIZES, WINDOW, set_window  # noqa: E402

TAB_JS = """
const tv = document.querySelector('[data-tab="tv"]');
const movies = document.querySelector('[data-tab="movies"]');
const r = tv.getBoundingClientRect();
const text = [...tv.childNodes].find(n => n.nodeType === 3 && n.textContent.includes('(beta)'));
const lineOf = (from, to) => { const range = document.createRange(); range.setStart(text, from); range.setEnd(text, to);
  const rects = [...range.getClientRects()].filter(b => b.width > 0); return rects.map(b => Math.round(b.top)); };
const at = text ? text.textContent.indexOf('Shows') : -1;
const end = text ? text.textContent.indexOf(')') + 1 : -1;
const strip = document.getElementById('tab-strip').getBoundingClientRect();
const mr = movies.getBoundingClientRect();
return {
  ready: !!text && !document.getElementById('library').hidden && !!document.getElementById('loading')
         && (document.getElementById('loading').hidden || getComputedStyle(document.getElementById('loading')).display === 'none')
         && document.activeElement === movies,
  size: [r.width, r.height],
  // The top of each line "Shows (beta)" is drawn on: one line means one top.
  lines: text ? [...new Set(lineOf(at, end))] : [],
  selected: tv.getAttribute('aria-selected'),
  focused: document.activeElement === tv,
  activeTab: document.activeElement && document.activeElement.dataset ? document.activeElement.dataset.tab || null : null,
  name: tv.getAttribute('aria-label'),
  movies: movies.innerText.replace(/\\s+/g, ' ').trim(),
  moviesLabel: movies.getAttribute('aria-label'),
  fits: r.left >= 0 && r.right <= document.documentElement.clientWidth + 0.5 && mr.left >= 0
        && mr.right <= document.documentElement.clientWidth + 0.5,
  inStrip: r.top >= strip.top - 0.5 && r.bottom <= strip.bottom + 0.5,
  overflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth,
};
"""


def shot(m, shots_dir, name):
    (shots_dir / f"tv-beta-{name}.png").write_bytes(
        base64.b64decode(m.send("WebDriver:TakeScreenshot", {})["value"]))


def check_size(m, shots_dir, check, size):
    """At this window size, the TV Shows tab in each of its four states."""
    # Each size starts on the Movies tab, focused and selected: TV is neither.
    m.settle()
    states = {"neither": m.js(TAB_JS)}
    shot(m, shots_dir, f"{size}-neither")
    # Selected and focused: Right from the Movies tab, as on a controller.
    m.press(RIGHT)
    m.settle()
    states["both"] = m.js(TAB_JS)
    shot(m, shots_dir, f"{size}-selected-focused")
    # Selected only: Down onto the first show.
    m.press(DOWN)
    m.settle()
    states["selected"] = m.js(TAB_JS)
    shot(m, shots_dir, f"{size}-selected")
    # Back to the Movies tab with the controller's keys.
    m.press(UP)
    m.press(LEFT)
    m.settle()
    # Focused only: the focus put on TV (as a keyboard Tab would) while
    # Movies stays selected, then back on Movies for the next size.
    m.js("document.querySelector('[data-tab=\"tv\"]').focus(); return true;")
    m.settle()
    states["focused"] = m.js(TAB_JS)
    shot(m, shots_dir, f"{size}-focused")
    m.js("document.querySelector('[data-tab=\"movies\"]').focus(); return true;")

    want = {"neither": ("false", False), "focused": ("false", True),
            "both": ("true", True), "selected": ("true", False)}
    check(f"{size}: reached all four states",
          all((states[k]["selected"], states[k]["focused"]) == v for k, v in want.items()),
          {k: (v["selected"], v["focused"], v["activeTab"]) for k, v in states.items()})
    base = states["neither"]["size"]
    check(f"{size}: the TV Shows tab stays {base[0]:.1f} x {base[1]:.1f} in every state",
          all(abs(st["size"][0] - base[0]) < 0.5 and abs(st["size"][1] - base[1]) < 0.5
              for st in states.values()), {k: v["size"] for k, v in states.items()})
    for name, st in states.items():
        check(f"{size} {name}: \"(BETA)\" on the same line as \"SHOWS\"", len(st["lines"]) == 1, st["lines"])
        check(f"{size} {name}: both tabs fit, inside the strip, no sideways scroll",
              st["fits"] and st["inStrip"] and not st["overflowX"], st)


def run(env, profile, shots_dir, check):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for base, files in ((tmp / "Movies", FILMS), (tmp / "TV Shows", TV_FILES)):
            for rel in files:
                (base / rel).parent.mkdir(parents=True, exist_ok=True)
                (base / rel).write_bytes(b"")
        settings = {"movies_path": str(tmp / "Movies"), "tv_path": str(tmp / "TV Shows"),
                    "mpv_command": "mpv", "mpv_args": [], "data_dir": str(tmp / "data")}
        roots = {"movies": settings["movies_path"], "tv": settings["tv_path"]}
        index = library_index.full_scan(roots, None, lambda done, total: None)
        library_index.save(Path(settings["data_dir"]) / library_index.FILE_NAME, index)
        httpd, port = start_server("long", settings, tmp, [])
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
            end = time.time() + 30
            s = m.js(TAB_JS)
            while not s["ready"] and time.time() < end:
                time.sleep(0.2)
                s = m.js(TAB_JS)
            check("the library shows, with the TV Shows tab's text", s["ready"], s)
            check("the TV Shows tab's accessible name is \"TV shows, beta\"", s["name"] == "TV shows, beta", s["name"])
            check("the Movies tab reads MOVIES and its count only, with no label of its own",
                  s["movies"] == f"MOVIES {len(FILMS)}" and s["moviesLabel"] is None, s)
            for size, (w, h) in SIZES.items():
                set_window(m, w, h)
                time.sleep(0.5)
                check_size(m, shots_dir, check, size)
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
    shots_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="tv-beta-"))
    shots_dir.mkdir(parents=True, exist_ok=True)
    results = []

    def check(text, ok, detail=None):
        results.append((text if ok or detail is None else f"{text}: {json.dumps(detail, default=str)}", ok))

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        home = Path(tmp) / "home"
        env = dict(os.environ, HOME=str(home), MOZ_HEADLESS="1")
        profile = home / ".var/app/org.mozilla.firefox/data/check-profile-tv-beta"
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
