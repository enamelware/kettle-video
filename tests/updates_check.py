# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Check for updates in Settings › About, and What's new (the never-online work), in a
real, headless Firefox, with the controller's keys only. Not part of the
unit tests: it needs Firefox and takes about a minute.

GitHub is a stand-in inside the app's server (an invented release 1.1.0
with invented notes); Firefox uses the kiosk profile's own settings from
launch.sh, so nothing goes online. Invented folders only. Checks:

  - at every window width, from Enamel's smallest supported box to very
    wide: Check for updates is the row under the version, with "Last
    checked: never" under its label, focused wholly in view and clear of
    the hint bar, nothing cut off sideways;
  - A on it: the row reads Checking…, and Down and Up still move while it
    runs; then "Version 1.1.0 is available", Last checked: today, and one
    What's new row under it showing the version (no Update and restart
    row: this copy isn't an installed one, and the invented release has no
    files to download; that row is tests/app_update_check.py, the Update and restart work);
  - What's new at every width: its title, the notes as paragraphs (a list
    item each), Down scrolls to the last one above the hint bar, B goes
    back to its row;
  - checking again with no connection: "Couldn't check: no connection",
    What's new gone, Last checked still today; then up to date:
    "Up to date (v<this version>)".

Screenshots go to the folder given as the first argument.

Run from the repo root:  python3 tests/updates_check.py [screenshot-dir]
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
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from backend import library_index, settings_screen, update_check  # noqa: E402
from backend.server import make_handler  # noqa: E402
from tests.kiosk_profile_check import launch_user_js  # noqa: E402
from tests.loading_screen_check import UI_DIR, Marionette, free_port  # noqa: E402
from tests.window_sizes import FIREFOX_FLAG, SIZES, WINDOW, set_window  # noqa: E402

UP, DOWN = "", ""
SPACE, B, START = " ", "q", "m"
VERSION = settings_screen.version(REPO)
NOTES = "\n".join(["## What changed", ""] + [
    f"- Invented change number {n}, described in a sentence long enough to wrap on a narrow screen."
    for n in range(1, 31)] + ["", "Thanks to the invented testers."])
RELEASE = {"tag_name": "v1.1.0", "body": NOTES,
           "assets": [{"name": "kettle-video-1.1.0.tar.gz", "size": 41_943_040}]}

STATE_JS = """
const visible = (el) => el && !el.hidden && !el.closest('[hidden]') && el.getClientRects().length > 0;
const box = (el) => { const r = el.getBoundingClientRect(); return {top: r.top, bottom: r.bottom, left: r.left, right: r.right}; };
const text = (el) => el ? el.textContent.replace(/\\s+/g, ' ').trim() : '';
const settings = document.getElementById('settings');
const reader = document.getElementById('licence');
const menu = document.getElementById('home-menu');
const hint = document.getElementById('hint-bar');
const active = document.activeElement;
const rows = [...settings.querySelectorAll('.settings-row')];
const updates = [...settings.querySelectorAll('[data-role="updates"] .settings-row')];
const paragraphs = [...reader.querySelectorAll('[data-role="text"] p')];
const cutOff = [...document.querySelectorAll('#settings *, #licence *')].filter(e => visible(e))
  .filter(e => { const r = e.getBoundingClientRect(); return r.right > document.documentElement.clientWidth + 1 || r.left < -1; })
  .map(e => e.className || e.tagName).slice(0, 5);
const focused = new Set([...document.querySelectorAll('[data-focused="true"]')].filter(e => e.getClientRects().length));
if (active && active !== document.body) focused.add(active);
return {
  settings: visible(settings), reader: visible(reader), library: visible(document.getElementById('library')),
  menuOpen: menu.open && !menu.dataset.closing,
  menuFocused: (menu.querySelector('.en-picker__row[data-focused="true"]') || {textContent: ''}).textContent.trim(),
  notes: [...settings.querySelectorAll('[data-role="about"] .en-note')].map(text),
  updates: updates.map(r => ({title: text(r.querySelector('.row-title')),
    lines: [...r.querySelectorAll('.en-row__meta')].filter(visible).map(text)})),
  aboveUpdates: (() => { const n = settings.querySelector('[data-role="about"]'); const u = settings.querySelector('[data-role="updates"]');
    return n && u && n.getBoundingClientRect().bottom <= u.getBoundingClientRect().top + 0.5; })(),
  activeKind: active && active.dataset ? active.dataset.kind || null : null,
  activeIndex: rows.indexOf(active),
  activeBox: active && active !== document.body ? box(active) : null,
  hintTop: box(hint).top,
  hint: hint.innerText.replace(/\\s+/g, ' ').trim(),
  readerTitle: text(reader.querySelector('[data-role="title"]')),
  readerNotes: [...reader.querySelectorAll('.en-note')].map(text),
  paragraphs: paragraphs.map(text),
  lastParagraph: paragraphs.length ? box(paragraphs[paragraphs.length - 1]) : null,
  scrollY: window.scrollY,
  overflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth,
  cutOff, focusedCount: focused.size,
};
"""


def wait_state(m, predicate, timeout=5):
    end = time.time() + timeout
    s = m.js(STATE_JS)
    while not predicate(s) and time.time() < end:
        time.sleep(0.1)
        s = m.js(STATE_JS)
    return s


def press(m, key, predicate=None, timeout=5):
    m.press(key)
    if predicate is None:
        time.sleep(0.3)
        return m.js(STATE_JS)
    return wait_state(m, predicate, timeout)


def shoot(m, shots_dir, name):
    m.settle()
    (shots_dir / f"{name}.png").write_bytes(base64.b64decode(m.send("WebDriver:TakeScreenshot", {})["value"]))


def in_view(s):
    b = s["activeBox"]
    return b is not None and b["top"] >= -0.5 and b["bottom"] <= s["hintTop"] + 0.5 \
        and not s["overflowX"] and not s["cutOff"] and s["focusedCount"] == 1


def to_kind(m, kind):
    """Up to the first row, then Down to the first row of this kind."""
    s = m.js(STATE_JS)
    for _ in range(30):
        if s["activeIndex"] == 0:
            break
        s = press(m, UP)
    for _ in range(30):
        if s["activeKind"] == kind:
            break
        s = press(m, DOWN)
    return s


def run(env, profile, shots_dir, check):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        media = tmp / "media"
        for rel in ("Films/Invented Alpha (2001)/Invented Alpha (2001).mkv",
                    "Shows/Invented Show/Season 1/Invented Show S01E01.mkv"):
            (media / rel).parent.mkdir(parents=True, exist_ok=True)
            (media / rel).write_bytes(b"\0")
        app_dir = tmp / "app"
        (app_dir / "data").mkdir(parents=True)
        settings = {"movies_path": str(media / "Films"), "tv_path": str(media / "Shows"),
                    "mpv_command": "mpv", "mpv_args": [], "resume": False, "keep_awake": False,
                    "data_dir": str(app_dir / "data")}
        settings_file = app_dir / "settings.json"
        settings_file.write_text(json.dumps(settings))
        roots = {"movies": settings["movies_path"], "tv": settings["tv_path"]}
        library_index.save(app_dir / "data" / library_index.FILE_NAME,
                           library_index.full_scan(roots, None, lambda d, t: None))

        github = {"answer": RELEASE, "gate": threading.Event(), "asked": 0}
        github["gate"].set()

        def fetch(version):
            github["asked"] += 1
            github["gate"].wait(20)
            answer = github["answer"]
            if isinstance(answer, Exception):
                raise answer
            return answer

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        port = httpd.server_address[1]
        base = make_handler(UI_DIR, app_dir, dict(settings), {"server": httpd}, port, None, settings_file)

        class Handler(base):
            def log_message(self, format, *args):
                pass

            def _handle_mpv_status(self):
                self._send_json(HTTPStatus.OK, {"available": True})

        httpd.RequestHandlerClass = Handler
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        mport = free_port()
        # The kiosk profile's own settings: this Firefox can't go online either.
        (profile / "user.js").write_text(launch_user_js() + f'user_pref("marionette.port", {mport});\n')
        cmd = ["--headless", "--marionette", FIREFOX_FLAG, "--no-remote", "-profile", str(profile), "about:blank"]
        ff = subprocess.Popen(
            ["firefox", *cmd] if shutil.which("firefox") else ["flatpak", "run", "org.mozilla.firefox", *cmd],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        m = None
        try:
            with mock.patch.object(update_check, "is_development", return_value=False), \
                    mock.patch.object(update_check, "fetch_latest", fetch):
                m = Marionette(mport)
                m.send("WebDriver:Navigate", {"url": f"http://127.0.0.1:{port}/"})
                set_window(m, *WINDOW)
                wait_state(m, lambda s: s["library"] and s["activeKind"] == "movie", 30)
                press(m, START, lambda s: s["menuOpen"])
                press(m, DOWN, lambda s: s["menuFocused"] == "Settings")
                press(m, SPACE, lambda s: s["settings"] and s["activeIndex"] == 0, 10)
                check("Settings opens, nothing asked of GitHub yet", github["asked"] == 0, github["asked"])

                for size, (w, h) in SIZES.items():
                    set_window(m, w, h)
                    time.sleep(0.4)
                    press(m, UP)
                    s = to_kind(m, "update-check")
                    shoot(m, shots_dir, f"updates-row-{size}")
                    check(f"{size}: Check for updates under the version notes, Last checked: never, in view",
                          s["activeKind"] == "update-check" and s["aboveUpdates"]
                          and s["updates"] == [{"title": "Check for updates", "lines": ["Last checked: never"]}]
                          and s["notes"][0] == f"Version {VERSION}" and in_view(s), s)
                check("still nothing asked of GitHub", github["asked"] == 0, github["asked"])

                set_window(m, *WINDOW)
                time.sleep(0.4)
                github["gate"].clear()
                s = press(m, SPACE, lambda s: s["updates"][0]["lines"][-1:] == ["Checking…"])
                shoot(m, shots_dir, "updates-checking")
                check("A: the row reads Checking…", s["updates"][0]["lines"] == ["Last checked: never", "Checking…"], s["updates"])
                s = press(m, DOWN, lambda s: s["activeKind"] == "credit")
                check("while it runs, Down still moves", s["activeKind"] == "credit", s["activeKind"])
                s = press(m, UP, lambda s: s["activeKind"] == "update-check")
                github["gate"].set()
                s = wait_state(m, lambda s: len(s["updates"]) == 2, 10)
                shoot(m, shots_dir, "updates-newer")
                check("then Version 1.1.0 is available, Last checked: today, and What's new under it",
                      s["updates"] == [{"title": "Check for updates",
                                        "lines": ["Last checked: today", "Version 1.1.0 is available"]},
                                       {"title": "What's new", "lines": ["Version 1.1.0"]}], s["updates"])
                check("the focus stayed on Check for updates, one focus",
                      s["activeKind"] == "update-check" and s["focusedCount"] == 1, s)
                check("one request, from the Settings action", github["asked"] == 1, github["asked"])

                s = press(m, DOWN, lambda s: s["activeKind"] == "whats-new")
                for size, (w, h) in SIZES.items():
                    set_window(m, w, h)
                    time.sleep(0.4)
                    s = to_kind(m, "whats-new")
                    check(f"{size}: What's new focused, in view", in_view(s), s)
                    s = press(m, SPACE, lambda s: s["reader"] and s["paragraphs"])
                    shoot(m, shots_dir, f"updates-whats-new-{size}")
                    check(f"{size}: What's new shows its title and the notes, a list item each, B Back in the hint bar",
                          s["readerTitle"] == "What's new in 1.1.0" and s["paragraphs"][0] == "What changed"
                          and s["paragraphs"][1].startswith("• Invented change number 1,")
                          and s["paragraphs"][-1] == "Thanks to the invented testers." and len(s["paragraphs"]) == 32
                          and "B BACK" in s["hint"] and "SELECT" not in s["hint"], {k: s[k] for k in ("readerTitle", "hint")})
                    last = -1
                    for _ in range(40):
                        for _ in range(20):
                            m.press(DOWN)
                        s = m.js(STATE_JS)
                        if s["scrollY"] == last:
                            break
                        last = s["scrollY"]
                    shoot(m, shots_dir, f"updates-whats-new-end-{size}")
                    check(f"{size}: Down scrolls the notes to the end, the last one above the hint bar",
                          s["scrollY"] > 0 and 0 < s["lastParagraph"]["bottom"] <= s["hintTop"] + 0.5
                          and not s["overflowX"] and not s["cutOff"], s)
                    s = press(m, B, lambda s: s["settings"])
                    check(f"{size}: B goes back to What's new", s["activeKind"] == "whats-new" and in_view(s), s)

                set_window(m, *WINDOW)
                time.sleep(0.4)
                github["answer"] = update_check.CheckFailed("stand-in", offline=True)
                s = to_kind(m, "update-check")
                s = press(m, SPACE, lambda s: "Couldn't" in " ".join(s["updates"][0]["lines"]), 10)
                shoot(m, shots_dir, "updates-no-connection")
                check("no connection: the plain words, What's new gone, Last checked still today",
                      s["updates"] == [{"title": "Check for updates",
                                        "lines": ["Last checked: today", "Couldn't check: no connection"]}], s["updates"])
                github["answer"] = {"tag_name": f"v{VERSION}", "body": "", "assets": []}
                s = press(m, SPACE, lambda s: "Up to date" in " ".join(s["updates"][0]["lines"]), 10)
                check(f"then up to date: Up to date (v{VERSION})",
                      s["updates"][0]["lines"] == ["Last checked: today", f"Up to date (v{VERSION})"], s["updates"])
                s = press(m, B, lambda s: s["library"], 10)
                s = press(m, START, lambda s: s["menuOpen"])
                press(m, DOWN, lambda s: s["menuFocused"] == "Settings")
                s = press(m, SPACE, lambda s: s["settings"], 10)
                check("Settings opened again keeps the last result", s["updates"][0]["lines"] ==
                      ["Last checked: today", f"Up to date (v{VERSION})"], s["updates"])
                check("three checks, each from A on the row", github["asked"] == 3, github["asked"])
        finally:
            github["gate"].set()
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
    shots_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="updates-"))
    shots_dir.mkdir(parents=True, exist_ok=True)
    results = []

    def check(text, ok, detail=None):
        results.append((text if ok or detail is None else f"{text}: {json.dumps(detail, default=str)}", bool(ok)))

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        home = Path(tmp) / "home"
        env = dict(os.environ, HOME=str(home), MOZ_HEADLESS="1")
        profile = home / ".var/app/org.mozilla.firefox/data/check-profile"
        if shutil.which("firefox"):
            profile = home / ".mozilla/check-profile"
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
