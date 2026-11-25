# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Look again on the first launch's "mpv not found" screen (the mpv missing screen) in a real,
headless Firefox. Not part of the unit tests: it needs Firefox and takes about
two minutes.

Drives the screen with the real backend check and a temporary PATH: stand-ins
for mpv and flatpak appear in it as if installed, and are never played. Invented
folders in a temporary folder and temporary settings files; the app's own
settings.json is never read or written.

At every window width in tests/window_sizes.py, from Enamel's smallest supported
box to very wide, for each of the three messages (mpv missing, a broken
mpv_command, a failed check): the words, the primary button focused and in view,
the hint bar saying A Look again and B Quit; Up and Down reach every word; nothing
cut off, no sideways scroll. Look again with the same answer stays, keeps the
focus and says so; with a different answer the message follows it; with mpv found,
screen 1 opens on its first folder.

Once: a Flatpak found; Space and a tap each checking once; the button showing
the press while A is held, in Enamel's pressed cream, dropped when A comes up
or the window loses focus (Enamel 0.11.0, the Enamel 0.11.0 upgrade); a setting changed to
another program that can't be found, never told nothing changed, then to one that
can; A pressed again during a check and just after mpv is found, also with a failed
folder search, never choosing anything; A with the button
scrolled away; a check that stalls (A off, Up and Down scrolling, B quitting, and
the page giving up after 30 seconds with the button still focused); r and Home's
other keys doing nothing; a later launch keeping the message on its own, with no
button; the address ending in #onboarding; a stalled onboarding question not
leaving the loading screen up; a normal first launch never showing the screen;
this device's real mpv, when it has one, found by the real check (only looked for,
never started); and, started as launch.sh starts it, fresh start with pretend mpv
is missing, where Look again stays, and fresh start reading a fixed setting from
the pretend app folder's settings.json, which stays unchanged.

Run from the repo root:  python3 tests/mpv_look_again_check.py [screenshot-dir]
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

from backend import folder_finder, mpv  # noqa: E402
from backend.launch_options import FRESH_START, PRETEND_NO_MPV  # noqa: E402
from backend.server import make_handler  # noqa: E402
from tests.click_focus_check import tap  # noqa: E402
from tests.fresh_start_check import Session  # noqa: E402
from tests.home_shell_check import DOWN, ENTER, RIGHT, UP  # noqa: E402
from tests.loading_screen_check import UI_DIR, Marionette, free_port  # noqa: E402
from tests.test_folder_finder import make  # noqa: E402
from tests.window_sizes import FIREFOX_FLAG, SIZES, WINDOW, set_window  # noqa: E402

CHECK_FAILED = "The app couldn't check whether mpv is ready to play."
BROKEN = 'mpv "--fs'
QUOTE = "settings.json's 'mpv_command' has a quote that isn't closed."
MISSING_PROGRAM = "settings.json's 'mpv_command' names a program that can't be found."
EXIT = "Press q to exit."
SAME_ANSWER = "Tried again. Same answer."
CHECKING = "Checking again…"
MISSING_LINES = [mpv.INSTALL_HINT, EXIT]
QUOTE_LINES = [QUOTE, mpv.SETTING_HINT, EXIT]
FAILED_LINES = [CHECK_FAILED, EXIT]
A_LOOK_AGAIN = ["A Look again", "B Quit"]

STATE_JS = """
const visible = (el) => !!el && !el.hidden && getComputedStyle(el).display !== 'none' && !el.closest('[hidden]');
const box = document.getElementById('mpv-missing');
const button = box.querySelector('.mpv-look-again');
const note = box.querySelector('[data-role="note"]');
const hintTop = document.getElementById('hint-bar').getBoundingClientRect().top;
const inRoom = (r) => r.top >= -0.5 && r.bottom <= hintTop + 0.5 && r.left >= -0.5 && r.right <= innerWidth + 0.5;
const parts = [...box.querySelectorAll('p'), ...(button ? [button] : [])].filter(visible);
const onboarding = document.getElementById('onboarding');
const f = document.activeElement;
return {
  loading: visible(document.getElementById('loading')),
  slow: visible(document.querySelector('#loading [data-role="slow"]')),
  shown: visible(box),
  lines: [...box.querySelectorAll('p:not([data-role])')].map((p) => p.textContent),
  note: visible(note) ? note.textContent : null,
  button: visible(button),
  words: button ? button.textContent : null,
  primary: !!button && button.classList.contains('en-button') && button.classList.contains('en-button--primary'),
  focused: !!button && f === button,
  marked: !!button && button.dataset.focused === 'true',
  buttonInView: !!button && inRoom(button.getBoundingClientRect()),
  hints: [...document.querySelectorAll('#hint-bar .en-hint')].filter(visible)
    .filter((h) => h.dataset.role !== 'fresh-start').map((h) => h.textContent.replace(/\\s+/g, ' ').trim()),
  overflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth,
  cutOff: parts.filter((el) => { const r = el.getBoundingClientRect();
    return r.left < -0.5 || r.right > innerWidth + 0.5 || el.scrollWidth > el.clientWidth + 1; }).map((el) => el.textContent),
  parts: parts.map((el) => { const r = el.getBoundingClientRect();
    return {text: el.textContent, top: r.top + scrollY, bottom: r.bottom + scrollY}; }),
  scrollY: window.scrollY,
  hintTop,
  fresh: [...document.querySelectorAll('.fresh-start')].filter(visible).map((m) => m.innerText.trim()),
  step: visible(onboarding) ? onboarding.dataset.step || '' : null,
  listShown: visible(onboarding.querySelector('[data-role="groups"]')),
  focusedKind: f && f.dataset ? f.dataset.kind || null : null,
  firstFolder: !!f && f === onboarding.querySelector('.folder-row'),
  firstScan: visible(document.querySelector('#onboarding[data-result]:not([data-result="reading"])')),
  library: visible(document.getElementById('library')),
};
"""

# Enamel's focused button is filled with cream (0.11.0, the Enamel 0.11.0 upgrade; the accent
# until then).
FOCUS_FILL_JS = """
const probe = document.createElement('div');
probe.style.color = 'var(--en-focus-fill)';
document.body.append(probe);
const accent = getComputedStyle(probe).color;
probe.remove();
return getComputedStyle(document.querySelector('.mpv-look-again')).backgroundColor === accent;
"""

PRESSED_JS = "return document.querySelector('.mpv-look-again').dataset.pressed === 'true';"

# The button's fill, and Enamel's pressed and focus creams.
PRESS_LOOK_JS = """
const colour = (token) => { const p = document.createElement('div'); p.style.backgroundColor = `var(${token})`;
  document.body.append(p); const c = getComputedStyle(p).backgroundColor; p.remove(); return c; };
return {fill: getComputedStyle(document.querySelector('.mpv-look-again')).backgroundColor,
        pressed: colour('--en-cream-pressed'), focus: colour('--en-focus-fill')};
"""

CENTRE_JS = """
const r = document.querySelector('.mpv-look-again').getBoundingClientRect();
return [Math.round(r.left + r.width / 2), Math.round(r.top + r.height / 2)];
"""


def stand_in(path, body="exit 0"):
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(0o755)


class Scenario:
    """One app, on its own port so that a page address is always a new page."""

    def __init__(self, world, mpv_command="auto", folders=False, fail=False):
        self.world = world
        self.file = world.tmp / f"settings-{len(world.servers)}.json"
        self.fail = fail  # the check answers with an error page
        self.hold = None  # a Look again waits on this event
        self.gave_up = False
        self.hold_onboarding = None
        self.fail_search = False  # the folder search answers with an error page
        self.look_agains = 0
        self.scans = 0
        self.quits = 0
        media = str(world.tmp) if folders else ""
        self.write(mpv_command)
        settings = {"movies_path": media, "tv_path": media, "mpv_command": mpv_command, "mpv_args": [],
                    "resume": True, "keep_awake": False,
                    "data_dir": str(world.tmp / f"data-{len(world.servers)}")}
        ref = {}
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        self.port = httpd.server_address[1]
        base = make_handler(UI_DIR, world.tmp, settings, ref, self.port, None, None, self.file)
        scenario = self

        class Handler(base):
            def log_message(self, format, *args):
                pass

            def do_GET(self):
                if self.path == "/api/onboarding" and scenario.hold_onboarding:
                    scenario.hold_onboarding.wait(40)
                    self.close_connection = True
                    return None
                return super().do_GET()

            def _error_page(self):
                body = b"<html>Internal error</html>"
                self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _handle_mpv_status(self):
                if scenario.fail:
                    return self._error_page()
                return super()._handle_mpv_status()

            def _handle_find_folders(self):
                if scenario.fail_search:
                    return self._error_page()
                return super()._handle_find_folders()

            def _handle_mpv_look_again(self):
                scenario.look_agains += 1
                if scenario.hold:
                    scenario.hold.wait(40)
                    if scenario.gave_up:  # the page has stopped waiting: no one to answer
                        self.close_connection = True
                        return None
                return super()._handle_mpv_look_again()

            def _handle_scan(self):
                scenario.scans += 1
                return super()._handle_scan()

            def _handle_shutdown(self):
                scenario.quits += 1
                self._send_json(HTTPStatus.OK, {"ok": True})

        httpd.RequestHandlerClass = Handler
        ref["server"] = httpd
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        world.servers.append(httpd)

    def write(self, command):
        self.file.write_text(json.dumps({"movies_path": "", "tv_path": "", "mpv_command": command}), encoding="utf-8")

    def url(self, ending=""):
        return f"http://127.0.0.1:{self.port}/{ending}"


class World:
    def __init__(self, m, tmp, bin_dir, shots_dir, check):
        self.m, self.tmp, self.bin, self.shots_dir, self.check = m, tmp, bin_dir, shots_dir, check
        self.servers = []

    def state(self):
        return self.m.js(STATE_JS)

    def wait(self, predicate, timeout=10):
        end = time.time() + timeout
        s = self.state()
        while not predicate(s) and time.time() < end:
            time.sleep(0.05)
            s = self.state()
        return s

    def open(self, url, size="w1280"):
        set_window(self.m, *WINDOW)
        self.m.send("WebDriver:Navigate", {"url": url})
        set_window(self.m, *SIZES[size])

    def on_screen(self, timeout=10):
        return self.wait(lambda s: not s["loading"] and s["button"] and s["focused"], timeout)

    def on_folders(self, timeout=10):
        return self.wait(lambda s: s["step"] == "1" and s["listShown"] and s["firstFolder"], timeout)

    def screen(self, where, s, lines):
        """The message, its button and the hint bar are right."""
        check = self.check
        check(f"{where}: the loading screen has gone and the words show", not s["loading"] and s["lines"] == lines, s["lines"])
        check(f"{where}: one primary button, Look again", s["button"] and s["primary"] and s["words"] == "Look again", s)
        check(f"{where}: it has the focus, marked for Enamel's focus style", s["focused"] and s["marked"], s)
        self.m.settle()
        check(f"{where}: it shows Enamel's focus, the cream fill", self.m.js(FOCUS_FILL_JS))
        check(f"{where}: it is in view, clear of the hint bar", s["buttonInView"], s)
        check(f"{where}: the hint bar says A Look again, B Quit", s["hints"] == A_LOOK_AGAIN, s["hints"])
        check(f"{where}: nothing cut off, no sideways scroll", not s["cutOff"] and not s["overflowX"], s)

    def every_word_reachable(self, where):
        """Up to the top, then Down to the end, as a controller would: every
        part of the message and the button is seen, with nothing skipped."""
        check, m = self.check, self.m
        s = self.state()
        for _ in range(20):
            if s["scrollY"] < 1:
                break
            m.press(UP)
            s = self.state()
        check(f"{where}: Up reaches the top", s["scrollY"] < 1, s["scrollY"])
        seen = []
        for _ in range(20):
            seen.append((s["scrollY"], s["scrollY"] + s["hintTop"]))
            before = s["scrollY"]
            m.press(DOWN)
            s = self.state()
            if abs(s["scrollY"] - before) < 1:
                break
        reach = 0
        for top, bottom in seen:
            if top > reach + 0.5:
                break  # a gap: words were skipped between two views
            reach = max(reach, bottom)
        last = max(part["bottom"] for part in s["parts"])
        check(f"{where}: Down shows everything to the end, button included", reach >= last - 0.5, [seen, last])
        check(f"{where}: the focus stayed on the button, in view at the end", s["focused"] and s["buttonInView"], s)

    def shot(self, name):
        self.m.settle()
        (self.shots_dir / f"{name}.png").write_bytes(base64.b64decode(self.m.send("WebDriver:TakeScreenshot", {})["value"]))

    def stays(self, where, app, lines, press=ENTER):
        """A press changes nothing: one check, same words, the focus kept."""
        check, m = self.check, self.m
        before = app.look_agains
        m.press(press)
        s = self.wait(lambda s: s["note"] == SAME_ANSWER, 5)
        time.sleep(0.2)
        check(f"{where}: stays on this screen and says it got the same answer",
              s["shown"] and s["step"] is None and s["note"] == SAME_ANSWER and s["lines"] == lines, s)
        check(f"{where}: the button keeps the focus, in view", s["focused"] and s["marked"] and s["buttonInView"], s)
        check(f"{where}: one press, one check", app.look_agains == before + 1, app.look_agains - before)
        check(f"{where}: nothing cut off, no sideways scroll", not s["cutOff"] and not s["overflowX"], s)

    def continues(self, where, app, press=ENTER):
        check = self.check
        self.m.press(press)
        s = self.on_folders()
        check(f"{where}: on to screen 1, focused on its first folder", s["step"] == "1" and s["firstFolder"], s)
        check(f"{where}: the mpv screen has gone", not s["shown"], s)
        check(f"{where}: the hint bar is onboarding's", s["hints"][0] == "A This is my movies folder" and "B Quit" in s["hints"], s["hints"])
        check(f"{where}: nothing was saved", json.loads(app.file.read_text())["movies_path"] == "", app.file.read_text())

    def mpv_installed(self, on):
        (self.bin / "mpv").unlink(missing_ok=True)
        if on:
            stand_in(self.bin / "mpv")


def every_width(w):
    for size in SIZES:
        # mpv missing, then found.
        w.mpv_installed(False)
        app = Scenario(w)
        w.open(app.url(), size)
        s = w.on_screen()
        where = f"missing at {size}"
        w.screen(where, s, MISSING_LINES)
        w.shot(f"mpv-look-again-missing-{size}")
        w.every_word_reachable(where)
        w.stays(where, app, MISSING_LINES)
        w.shot(f"mpv-look-again-missing-tried-{size}")
        w.mpv_installed(True)
        w.continues(where, app)
        w.shot(f"mpv-look-again-found-{size}")

        # A broken setting, then fixed in the file: mpv still missing, then there.
        w.mpv_installed(False)
        app = Scenario(w, BROKEN)
        w.open(app.url(), size)
        s = w.on_screen()
        where = f"broken setting at {size}"
        w.screen(where, s, QUOTE_LINES)
        w.shot(f"mpv-look-again-setting-{size}")
        w.every_word_reachable(where)
        w.stays(where, app, QUOTE_LINES)
        app.write("auto")
        w.m.press(ENTER)
        s = w.wait(lambda s: s["lines"] == MISSING_LINES, 5)
        w.check(f"{where}: fixed to auto, the message follows; no 'same answer'",
                s["lines"] == MISSING_LINES and s["note"] is None, s)
        w.check(f"{where}: the button keeps the focus, in view", s["focused"] and s["buttonInView"], s)
        w.mpv_installed(True)
        w.continues(where, app)

        # The check fails, works again and finds nothing, then finds mpv.
        w.mpv_installed(False)
        app = Scenario(w, fail=True)
        w.open(app.url(), size)
        s = w.on_screen()
        where = f"failed check at {size}"
        w.screen(where, s, FAILED_LINES)
        w.shot(f"mpv-look-again-failed-{size}")
        w.every_word_reachable(where)
        w.stays(where, app, FAILED_LINES)
        app.fail = False
        w.m.press(ENTER)
        s = w.wait(lambda s: s["lines"] == MISSING_LINES, 5)
        w.check(f"{where}: the check works again, the message follows", s["lines"] == MISSING_LINES and s["note"] is None, s)
        w.check(f"{where}: the button keeps the focus, in view", s["focused"] and s["buttonInView"], s)
        w.mpv_installed(True)
        w.continues(where, app)


def presses(w):
    check, m = w.check, w.m
    # A Flatpak appearing, with its real command line.
    w.mpv_installed(False)
    app = Scenario(w)
    w.open(app.url())
    w.on_screen()
    stand_in(w.bin / "flatpak", "exit 1")
    w.stays("flatpak there without mpv", app, MISSING_LINES)
    stand_in(w.bin / "flatpak", f'[ "$1 $2" = "info {mpv.FLATPAK_APP_ID}" ]')
    w.continues("the Flatpak found", app)
    (w.bin / "flatpak").unlink()

    # Space, and a tap, which also finds mpv.
    app = Scenario(w)
    w.open(app.url())
    w.on_screen()
    w.stays("Space", app, MISSING_LINES, " ")
    # A held (Enamel 0.11.0, the Enamel 0.11.0 upgrade): the button shows the press while Space is
    # down, and springs back when it comes up.
    m.send("WebDriver:PerformActions", {"actions": [{"type": "key", "id": "kb", "actions": [{"type": "keyDown", "value": " "}]}]})
    pressed = m.js(PRESSED_JS)
    look = m.js(PRESS_LOOK_JS)
    m.send("WebDriver:PerformActions", {"actions": [{"type": "key", "id": "kb", "actions": [{"type": "keyUp", "value": " "}]}]})
    check("A held: the button shows the press, and drops it when A comes up", pressed and not m.js(PRESSED_JS), pressed)
    # The attribute is the one Enamel's stylesheet answers: the face darkens
    # to Enamel's pressed cream, not the focus cream.
    check("A held: the button takes Enamel's pressed cream", look["fill"] == look["pressed"] != look["focus"], look)
    time.sleep(0.5)
    # The window losing focus while A is down (the Steam overlay, say) drops it.
    m.send("WebDriver:PerformActions", {"actions": [{"type": "key", "id": "kb", "actions": [{"type": "keyDown", "value": " "}]}]})
    pressed = m.js(PRESSED_JS)
    m.js("window.dispatchEvent(new Event('blur')); return true;")
    after_blur = m.js(PRESSED_JS)
    m.send("WebDriver:PerformActions", {"actions": [{"type": "key", "id": "kb", "actions": [{"type": "keyUp", "value": " "}]}]})
    check("A held, then the window loses focus: the press is dropped", pressed and not after_blur, [pressed, after_blur])
    time.sleep(0.5)
    x, y = m.js(CENTRE_JS)
    before = app.look_agains
    tap(m, x, y)
    time.sleep(0.5)
    s = w.state()
    check("a tap checks once and keeps the focus", app.look_agains == before + 1 and s["focused"] and s["shown"], s)
    w.mpv_installed(True)
    x, y = m.js(CENTRE_JS)
    tap(m, x, y)
    s = w.on_folders()
    check("a tap goes on to screen 1 when mpv is found", s["step"] == "1" and s["firstFolder"], s)
    w.mpv_installed(False)

    # A again while a check runs: one check, and nothing chosen.
    app = Scenario(w)
    w.open(app.url())
    w.on_screen()
    app.hold = threading.Event()
    w.mpv_installed(True)
    m.press(ENTER)
    m.press(ENTER)
    m.press(" ")
    time.sleep(0.2)
    check("A during a check doesn't start another", app.look_agains == 1, app.look_agains)
    app.hold.set()
    w.on_folders()
    time.sleep(0.3)
    s = w.state()
    check("it then opens screen 1, still on the first folder", s["step"] == "1" and s["firstFolder"], s)

    # A again just after mpv is found: the button has gone and no folder is chosen.
    w.mpv_installed(False)
    app = Scenario(w)
    w.open(app.url())
    s = w.on_screen()
    check("double press: starts on the mpv screen", s["button"], s)
    w.mpv_installed(True)
    # One action, so the timing is exact: the check answers in a few
    # milliseconds, and the second A comes a double press's gap after the first.
    m.send("WebDriver:PerformActions", {"actions": [{"type": "key", "id": "kb", "actions": [
        {"type": "keyDown", "value": ENTER}, {"type": "keyUp", "value": ENTER},
        {"type": "pause", "duration": 300},
        {"type": "keyDown", "value": ENTER}, {"type": "keyUp", "value": ENTER},
    ]}]})
    w.on_folders()
    time.sleep(0.5)
    s = w.state()
    check("a second press just after mpv is found chooses nothing", s["step"] == "1" and s["firstFolder"], s)
    check("nothing was saved by it", json.loads(app.file.read_text())["movies_path"] == "", app.file.read_text())
    # The keys work again on screen 1, so the guard isn't a dead end.
    m.press(ENTER)
    s = w.wait(lambda s: s["step"] == "2", 5)
    check("the keys then work on screen 1", s["step"] == "2", s)
    w.mpv_installed(False)

    # The same double press with the folder search failing: screen 1 then has
    # only "I don't have movies", and the second press must not choose it.
    app = Scenario(w)
    w.open(app.url())
    s = w.on_screen()
    check("failed search: starts on the mpv screen", s["button"], s)
    app.fail_search = True
    w.mpv_installed(True)
    m.send("WebDriver:PerformActions", {"actions": [{"type": "key", "id": "kb", "actions": [
        {"type": "keyDown", "value": ENTER}, {"type": "keyUp", "value": ENTER},
        {"type": "pause", "duration": 300},
        {"type": "keyDown", "value": ENTER}, {"type": "keyUp", "value": ENTER},
    ]}]})
    w.on_folders()
    time.sleep(0.5)
    s = w.state()
    check("failed search: the second press doesn't skip movies", s["step"] == "1" and s["focusedKind"] == "skip", s)
    m.press(ENTER)
    s = w.wait(lambda s: s["step"] == "2", 5)
    check("failed search: the keys then work on screen 1", s["step"] == "2", s)
    w.mpv_installed(False)

    # A setting changed to another program that can't be found gives the same
    # sentence: the words must stay true, and the new setting has really been read.
    app = Scenario(w, "/nonexistent/one")
    w.open(app.url())
    s = w.on_screen()
    missing_program = [MISSING_PROGRAM, mpv.SETTING_HINT, EXIT]
    w.screen("another program", s, missing_program)
    app.write("/nonexistent/two")
    w.stays("another program", app, missing_program)
    stand_in(w.bin / "my-mpv")
    app.write("my-mpv --fs")
    w.continues("another program, then one that is there", app)
    (w.bin / "my-mpv").unlink()

    # A with the button scrolled away (the smallest box) brings it back.
    app = Scenario(w, BROKEN)
    w.open(app.url(), "w320")
    w.on_screen()
    for _ in range(6):
        m.press(UP)
    s = w.state()
    check("smallest box: Up scrolls away from the button, the focus staying", s["scrollY"] < 1 and s["focused"], s)
    check("smallest box: and the button is out of view", not s["buttonInView"], s)
    w.stays("smallest box, button scrolled away", app, QUOTE_LINES)
    # A smaller window doesn't leave it out of view either.
    w.open(app.url(), "w1280")
    w.on_screen()
    set_window(m, *SIZES["w320"])
    s = w.wait(lambda s: s["buttonInView"], 3)
    check("a window made smaller keeps the focused button in view", s["buttonInView"] and s["focused"], s)

    # Home's other keys do nothing on this screen.
    set_window(m, *WINDOW)
    app = Scenario(w)
    w.open(app.url())
    before = w.on_screen()
    for key in ("r", "m", "a", "", RIGHT):  #  is Backspace
        m.press(key)
    time.sleep(0.5)
    s = w.state()
    check("r, Start, Y, X and Right do nothing here", app.scans == 0 and app.look_agains == 0 and s["shown"]
          and s["focused"] and s["lines"] == before["lines"] and s["note"] is None and not s["library"], s)
    m.press("q")
    time.sleep(0.3)
    check("B quits", app.quits == 1, app.quits)


def stalled(w):
    """A check that never answers: the page gives up after 30 seconds."""
    check, m = w.check, w.m
    w.mpv_installed(False)
    app = Scenario(w, BROKEN)
    w.open(app.url(), "w320")
    w.on_screen()
    app.hold = threading.Event()
    started = time.time()
    m.press(ENTER)
    s = w.wait(lambda s: s["note"] == CHECKING, 3)
    check("a slow check says it is checking", s["note"] == CHECKING, s)
    check("the button keeps the focus, in view", s["focused"] and s["buttonInView"], s)
    w.shot("mpv-look-again-checking-w320")
    m.press(ENTER)
    time.sleep(0.2)
    check("A does nothing while it waits", app.look_agains == 1, app.look_agains)
    before = w.state()["scrollY"]
    m.press(UP)
    s = w.state()
    check("Up still scrolls while it waits", s["scrollY"] < before, [before, s["scrollY"]])
    m.press(DOWN)
    m.press("q")
    time.sleep(0.3)
    check("B still quits while it waits", app.quits == 1, app.quits)
    s = w.wait(lambda s: s["lines"] == FAILED_LINES, 35)
    check("after about 30 seconds the screen says it couldn't check",
          s["lines"] == FAILED_LINES and 28 < time.time() - started < 40, [s["lines"], time.time() - started])
    check("no 'checking' line is left, and no 'same answer'", s["note"] is None, s["note"])
    check("the button still has the focus, in view", s["focused"] and s["buttonInView"], s)
    app.gave_up = True
    app.hold.set()
    app.hold = None
    m.press(ENTER)
    w.wait(lambda s: s["lines"] != FAILED_LINES, 5)
    check("A works again afterwards", app.look_agains == 2, app.look_agains)


def other_launches(w):
    check, m = w.check, w.m
    w.mpv_installed(False)

    # A later launch: the message on its own, as before.
    app = Scenario(w, folders=True)
    w.open(app.url(), "w320")
    s = w.wait(lambda s: not s["loading"] and s["shown"])
    check("later launch: the message shows with no button", s["lines"] == MISSING_LINES and not s["button"], s)
    check("later launch: the hint bar is as before", s["hints"] == ["A Select", "B Quit"], s["hints"])
    m.press(ENTER)
    time.sleep(0.3)
    check("later launch: A does nothing", app.look_agains == 0 and w.state()["shown"], app.look_agains)
    m.press("q")
    time.sleep(0.3)
    check("later launch: B quits", app.quits == 1, app.quits)

    # The address ending in #onboarding with a folder set: the flow comes first.
    app = Scenario(w, folders=True)
    w.open(app.url("#onboarding"))
    s = w.on_screen()
    w.screen("#onboarding", s, MISSING_LINES)
    w.mpv_installed(True)
    w.continues("#onboarding", app)
    w.mpv_installed(False)

    # The question "is it a first launch?" stalling can't leave the loading
    # screen up: the message shows on its own, as on any launch.
    app = Scenario(w)
    app.hold_onboarding = threading.Event()
    w.open(app.url())
    s = w.wait(lambda s: not s["loading"], 15)
    app.hold_onboarding.set()
    check("a stalled onboarding question: the loading screen gives way to the message",
          not s["loading"] and s["lines"] == MISSING_LINES and not s["button"], s)

    # With mpv there, this screen never shows, not even for a moment.
    w.mpv_installed(True)
    app = Scenario(w)
    w.open(app.url())
    shown = False
    end = time.time() + 10
    s = w.state()
    while not (s["step"] == "1" and s["firstFolder"]) and time.time() < end:
        shown = shown or s["shown"]
        s = w.state()
    check("mpv there: screen 1 opens", s["step"] == "1" and s["firstFolder"], s)
    check("mpv there: the mpv screen never showed", not shown and not s["shown"] and app.look_agains == 0, s)
    w.mpv_installed(False)


def real_mpv(w, real_path):
    """This device's real mpv, if it has one: the real check finds it, as after
    installing it. Only looked for; it is never started."""
    with mock.patch.dict(os.environ, {"PATH": real_path}):
        found = mpv.detect("auto")
    if not found["available"]:
        print("skipped: this device has no mpv for the real check")
        return
    app = Scenario(w)
    w.open(app.url())
    w.on_screen()
    with mock.patch.dict(os.environ, {"PATH": real_path}):
        w.continues(f"this device's real mpv ({found['via']})", app)


def real_start(w):
    """Started as launch.sh starts it, from a pretend app folder that has both
    folders set: fresh start opens the first-launch flow."""
    check = w.check
    w.mpv_installed(False)
    app = w.tmp / "app"
    app.mkdir()
    (app / "ui").symlink_to(UI_DIR)
    (app / "vendor").symlink_to(REPO / "vendor")
    settings_file = app / "settings.json"
    settings = {"movies_path": str(w.tmp), "tv_path": str(w.tmp), "mpv_command": "auto", "keep_awake": False}
    settings_file.write_text(json.dumps(settings), encoding="utf-8")
    before = settings_file.read_bytes()
    parent = w.tmp / "fresh-parent"
    parent.mkdir()

    # The issue's eye check. Even with an mpv there, it still counts as missing.
    w.mpv_installed(True)
    session = Session(app, {FRESH_START: "1", PRETEND_NO_MPV: "1"}, parent)
    for size in SIZES:
        w.open(f"http://127.0.0.1:{session.port}/", size)
        s = w.on_screen()
        where = f"fresh start, pretending, at {size}"
        w.screen(where, s, MISSING_LINES)
        check(f"{where}: the marker shows", s["fresh"] == ["FRESH START"], s["fresh"])
        w.shot(f"mpv-look-again-fresh-{size}")
        w.m.press(ENTER)
        s = w.wait(lambda s: s["note"] == SAME_ANSWER, 5)
        check(f"{where}: Look again stays, as mpv still counts as missing",
              s["note"] == SAME_ANSWER and s["step"] is None and s["focused"] and s["buttonInView"], s)
    check("fresh start, pretending: quits", session.quit())
    check("fresh start, pretending: settings.json unchanged", settings_file.read_bytes() == before)
    w.mpv_installed(False)

    # Fresh start, not pretending: the broken setting is fixed in the real file.
    settings_file.write_text(json.dumps({**settings, "mpv_command": BROKEN}), encoding="utf-8")
    session = Session(app, {FRESH_START: "1"}, parent)
    w.open(f"http://127.0.0.1:{session.port}/")
    s = w.on_screen()
    w.screen("fresh start, broken setting", s, QUOTE_LINES)
    settings_file.write_text(json.dumps(settings), encoding="utf-8")
    w.mpv_installed(True)
    w.m.press(ENTER)
    s = w.on_folders()
    check("fresh start: the setting fixed in settings.json counts, on to screen 1", s["step"] == "1" and s["firstFolder"], s)
    check("fresh start: settings.json is only read", settings_file.read_bytes() == before)
    check("fresh start: quits", session.quit())
    check("fresh start: its folder is gone", list(parent.iterdir()) == [])
    w.mpv_installed(False)


def run(env, profile, shots_dir, check):
    real_path = os.environ["PATH"]
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        found = tmp / "found"
        make(str(found), ["Films/Alpha/a.mkv", "Films/Beta/b.mkv", "Shows/Gamma/g.mkv", "Shows/Delta/d.mkv"])
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
        patches = [
            mock.patch.object(folder_finder, "list_places",
                              lambda: [folder_finder.Place("internal", "Internal storage", str(found))]),
            # From here on, mpv and flatpak are only what this check puts there.
            mock.patch.dict(os.environ, {"PATH": str(bin_dir)}),
        ]
        for patch in patches:
            patch.start()
        m = None
        world = None
        try:
            m = Marionette(mport)
            world = World(m, tmp, bin_dir, shots_dir, check)
            every_width(world)
            presses(world)
            other_launches(world)
            real_mpv(world, real_path)
            real_start(world)
            stalled(world)
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
            for httpd in world.servers if world else []:
                httpd.shutdown()
                httpd.server_close()


def main():
    shots_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="mpv-look-again-"))
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
        profile = home / ".var/app/org.mozilla.firefox/data/check-profile-mpv-look-again"
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
