# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The start-up problem page (the start-up problem screen) in a real, headless Firefox. Not
part of the unit tests: it needs Firefox and takes under a minute.

The page is served by the real message server (backend/startup_error.py), as
launch.sh starts it, with a broken settings file in a temporary folder; the
app's own settings.json is never read or written.

At every window width in tests/window_sizes.py, from Enamel's smallest
supported box to very wide: every line of the message shown, starting with
"Kettle couldn't start." and ending with the log's name; Close focused (in
Enamel's focus) and in view, above the hint bar; the hint bar saying A Close
and B Close; nothing cut off and no sideways scroll; Up reaching the first
line and Down the last. Then, at every width, a development copy on a
branch that couldn't start (the "Try a branch" work, its git a stand-in): the
line naming the branch, Close focused first, Right to Back to main (in view,
the hint saying A Back to main), A going back once and saying so with Close
focused again, B closing. Then once: Space (A), q (B), Escape, Enter and a
tap on Close each close it, which ends the message server.

Run from the repo root:  python3 tests/startup_error_check.py [screenshot-dir]
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
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from unittest import mock  # noqa: E402

from backend import startup_error, try_branch  # noqa: E402
from tests.click_focus_check import tap  # noqa: E402
from tests.loading_screen_check import Marionette, free_port  # noqa: E402
from tests.window_sizes import SIZES, WINDOW, FIREFOX_FLAG, set_window  # noqa: E402

RIGHT = ""  # WebDriver's Right arrow
KEYS = {"Space (A)": " ", "q (B)": "q", "Escape": "", "Enter": ""}

STATE_JS = """
const main = document.getElementById('startup-error');
const lines = [...main.querySelectorAll('[data-role="lines"] p')];
const button = main.querySelector('[data-kind="close"]');
const back = main.querySelector('[data-kind="back-to-main"]');
const status = main.querySelector('[data-role="status"]');
const bar = document.querySelector('.en-hintbar');
const r = (el) => { const b = el.getBoundingClientRect(); return [b.left, b.top, b.right, b.bottom]; };
return {
  lines: lines.map((p) => p.textContent),
  lineRects: lines.map(r),
  focused: document.activeElement === button && button.dataset.focused === 'true',
  backShown: !back.hidden, back: r(back),
  backFocused: document.activeElement === back && back.dataset.focused === 'true',
  status: status.hidden ? null : status.textContent,
  focusedCount: main.querySelectorAll('[data-focused="true"]').length,
  button: r(button), bar: r(bar), hints: bar.textContent.replace(/\\s+/g, ' ').trim(),
  w: window.innerWidth, h: window.innerHeight,
  scrollW: document.documentElement.scrollWidth,
  scrollY: window.scrollY, maxY: document.documentElement.scrollHeight - window.innerHeight,
};
"""


class MessageServer:
    """The real message server in a thread, on a broken settings file."""

    def __init__(self, root):
        self.port = free_port()
        self.quiet = StringIO()

        def run():
            with redirect_stdout(self.quiet), redirect_stderr(self.quiet):
                startup_error.serve(startup_error.BACKEND_STOPPED, "logs/launch-20260101-120000.log",
                                    self.port, root)

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        time.sleep(0.3)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}/"

    def closed(self, timeout=5):
        self.thread.join(timeout)
        return not self.thread.is_alive()


def wait(m, predicate, timeout=10):
    end = time.time() + timeout
    while True:
        state = m.js(STATE_JS)
        if predicate(state) or time.time() > end:
            return state
        time.sleep(0.1)


def app_root(tmp):
    """A pretend app folder: the real page and styles, a broken settings file."""
    root = tmp / "app"
    for name in ("ui", "vendor/enamel"):
        shutil.copytree(REPO / name, root / name, ignore=shutil.ignore_patterns("__pycache__"))
    (root / "settings.json").write_text('{"movies_path": "/films", "tv_path": "/shows",}')
    return root


def check_size(m, root, label, size, check, shots):
    server = MessageServer(root)
    m.send("WebDriver:Navigate", {"url": server.url})
    set_window(m, *size)
    s = wait(m, lambda s: len(s["lines"]) >= 4 and s["focused"])
    m.settle()
    s = m.js(STATE_JS)
    if shots:
        shot = m.send("WebDriver:TakeScreenshot", {"full": False})["value"]
        (shots / f"startup-error-{label}.png").write_bytes(base64.b64decode(shot))
    check(f"{label}: the whole message", s["lines"][:1] == ["Kettle couldn't start."]
          and s["lines"][1].startswith("Your settings have a mistake: settings.json is not valid JSON")
          and s["lines"][2] == startup_error.SETTINGS_FIX
          and "launch-20260101-120000.log" in s["lines"][-1], s["lines"])
    check(f"{label}: Close focused", s["focused"])
    b, bar = s["button"], s["bar"]
    check(f"{label}: Close in view, above the hint bar",
          b[0] >= 0 and b[2] <= s["w"] and b[1] >= 0 and b[3] <= bar[1] + 0.5, {"button": b, "bar": bar})
    check(f"{label}: hint bar says A Close and B Close", s["hints"] == "A Close B Close", s["hints"])
    check(f"{label}: hint bar on screen", bar[3] <= s["h"] + 0.5 and bar[0] >= 0 and bar[2] <= s["w"] + 0.5, bar)
    check(f"{label}: no sideways scroll", s["scrollW"] <= s["w"], [s["scrollW"], s["w"]])
    check(f"{label}: no line cut off at the sides",
          all(r[0] >= 0 and r[2] <= s["w"] + 0.5 for r in s["lineRects"]), s["lineRects"])
    if s["maxY"] > 0:
        for _ in range(40):
            m.press("")  # Up
        top = wait(m, lambda s: s["scrollY"] == 0, 3)
        check(f"{label}: Up reaches the first line", top["scrollY"] == 0 and top["lineRects"][0][1] >= 0,
              [top["scrollY"], top["lineRects"][0]])
        for _ in range(40):
            m.press("")  # Down
        end = wait(m, lambda s: s["scrollY"] >= s["maxY"] - 1, 3)
        last = end["lineRects"][-1]
        check(f"{label}: Down reaches the last line", end["scrollY"] >= end["maxY"] - 1 and last[3] <= end["bar"][1] + 0.5,
              [end["scrollY"], end["maxY"], last, end["bar"]])
        check(f"{label}: scrolling leaves Close focused", end["focused"])
    m.press(" ")
    check(f"{label}: A closes it", server.closed())


def check_branch(m, root, label, size, check, shots):
    """A development copy on a branch that couldn't start: Back to main
    beside Close (the "Try a branch" work). The git side is a stand-in here; the
    unit tests (tests/test_try_branch.py) run the real one."""
    asked = []

    def back_to_main(*args, **kwargs):
        asked.append(True)
        return {"ok": True, "text": try_branch.BACK_ON_MAIN_AT_START}

    with mock.patch.object(startup_error, "back_to_main_offer", return_value="issue-40"), \
            mock.patch.object(startup_error, "back_to_main", back_to_main):
        server = MessageServer(root)
        m.send("WebDriver:Navigate", {"url": server.url})
        set_window(m, *size)
        s = wait(m, lambda s: s["backShown"] and s["focused"])
        m.settle()
        s = m.js(STATE_JS)
        check(f"{label} on a branch: says which branch, Close focused first, Back to main shown",
              "This copy is on issue-40." in s["lines"] and s["focused"] and s["backShown"]
              and s["focusedCount"] == 1, s)
        m.press(RIGHT)
        s = wait(m, lambda s: s["backFocused"], 3)
        b, bar = s["back"], s["bar"]
        if shots:
            shot = m.send("WebDriver:TakeScreenshot", {"full": False})["value"]
            (shots / f"startup-error-branch-{label}.png").write_bytes(base64.b64decode(shot))
        check(f"{label} on a branch: Right focuses Back to main, in view, the hint says so",
              s["backFocused"] and s["focusedCount"] == 1 and b[0] >= 0 and b[2] <= s["w"] + 0.5
              and b[1] >= 0 and b[3] <= bar[1] + 0.5 and s["hints"] == "A Back to main B Close",
              {"back": b, "bar": bar, "hints": s["hints"], "focused": s["backFocused"]})
        check(f"{label} on a branch: no sideways scroll", s["scrollW"] <= s["w"], [s["scrollW"], s["w"]])
        m.press(" ")
        s = wait(m, lambda s: s["status"] and not s["backShown"], 5)
        check(f"{label} on a branch: A goes back to main once, says so, Close focused again",
              asked == [True] and s["status"] == try_branch.BACK_ON_MAIN_AT_START and not s["backShown"]
              and s["focused"] and s["hints"] == "A Close B Close", s)
        check(f"{label} on a branch: still open after going back", not server.closed(0.3))
        m.press("q")
        check(f"{label} on a branch: B closes it", server.closed())


def check_presses(m, root, check):
    for name, key in KEYS.items():
        server = MessageServer(root)
        m.send("WebDriver:Navigate", {"url": server.url})
        set_window(m, *WINDOW)
        wait(m, lambda s: s["focused"])
        m.press(key)
        check(f"{name} closes it", server.closed())
    server = MessageServer(root)
    m.send("WebDriver:Navigate", {"url": server.url})
    set_window(m, *WINDOW)
    s = wait(m, lambda s: s["focused"])
    b = s["button"]
    tap(m, (b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
    check("a tap on Close closes it", server.closed())


def run(env, profile, check, shots):
    with tempfile.TemporaryDirectory() as tmp:
        root = app_root(Path(tmp))
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
            for label, size in SIZES.items():
                check_size(m, root, label, size, check, shots)
            for label, size in SIZES.items():
                check_branch(m, root, label, size, check, shots)
            check_presses(m, root, check)
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


def main():
    results = []

    def check(text, ok, detail=None):
        results.append((text if ok or detail is None else f"{text}: {json.dumps(detail, default=str)}", ok))

    shots = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if shots:
        shots.mkdir(parents=True, exist_ok=True)
    # Firefox can still be writing its profile as it quits.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        home = Path(tmp) / "home"
        env = dict(os.environ, HOME=str(home), MOZ_HEADLESS="1")
        profile = home / ".var/app/org.mozilla.firefox/data/check-profile-startup-error"
        profile.mkdir(parents=True)
        try:
            run(env, profile, check, shots)
        except Exception as exc:
            results.append((f"could not run ({exc!r})", False))
    for text, ok in results:
        print(f"{'ok  ' if ok else 'FAIL'} {text}")
    failures = sum(not ok for _, ok in results)
    print("all good" if not failures else f"{failures} problem(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
