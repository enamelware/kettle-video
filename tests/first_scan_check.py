# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Onboarding's screen 3, the first scan and its result (the first scan screen), in a real,
headless Firefox, with invented folders in a temporary folder (the folder search
is pointed at them) and temporary settings files; the app's own settings.json is
never read or written. Not part of the unit tests: it needs Firefox.

At every window width in tests/window_sizes.py: after a good choice on screen 2,
"Reading your folders" with the step label and Enamel's progress, with no hints
for A and B, and neither doing anything; then "Your library is ready", its line,
Enamel's two panels side by side only when both fit at their minimum width,
stacked otherwise, the two notes, Open my library focused, nothing cut off and no
sideways scroll; Down reaches Change folders; B goes back to screen 2 on the
choice made; A scans again; Change folders goes back to screen 1 on the choice
made; Open my library opens Home.

Once each: a kind skipped says "Not set" and which kind; nothing found, with
Change folders alone, focused; folders already set go straight to the scan, where
B and Change folders go to screen 1; a failed scan and a card that came out show
the message with Change folders; one folder out, a note; a tap on each button;
a second A just after the save; "Still working…" on a long scan; a real empty
library, launching again and after Remove empties one, goes to the scan. The invented folders are byte-for-byte unchanged.

Screenshots go to the folder given as the first argument.

Run from the repo root:  python3 tests/first_scan_check.py [screenshot-dir]
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
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from backend import folder_dialog, folder_finder as ff, library_index, server  # noqa: E402
from backend.server import make_handler  # noqa: E402
from tests.click_focus_check import tap  # noqa: E402
from tests.home_shell_check import DOWN, ENTER, UP  # noqa: E402
from tests.loading_screen_check import UI_DIR, Marionette, free_port  # noqa: E402
from tests.test_folder_finder import make, snapshot  # noqa: E402
from tests.window_sizes import FIREFOX_FLAG, SIZES, WINDOW, set_window  # noqa: E402

FAKE_MPV = "#!/usr/bin/env python3\n"
CARD_FILES = ["Films/Alpha (2001)/Alpha.2001.mkv", "Films/Beta (2002)/Beta.2002.mkv", "Films/Some.Show.S01E05.mkv"]
HOME_FILES = ["Shows/Gamma/Season 1/Gamma.S01E01.mkv", "Shows/Gamma/Season 1/Gamma.S01E02.mkv",
              "Shows/Delta/Delta.S01E01.mkv", "Shows/Loose Film (1999).mkv"]
SCAN_FAILED = "Couldn't scan the library. The saved library is unchanged."

STATE_JS = """
const visible = (el) => !!el && !el.hidden && getComputedStyle(el).display !== 'none' && !el.closest('[hidden]');
const el = document.getElementById('onboarding');
const f = document.activeElement;
const buttons = [...el.querySelectorAll('.result-action')];
const panels = [...el.querySelectorAll('.en-statpanel')];
const pair = el.querySelector('.en-statpair');
const looking = el.querySelector('[data-role="looking"]');
const rows = [...el.querySelectorAll('.folder-row')];
const hintTop = document.getElementById('hint-bar').getBoundingClientRect().top;
const minWidth = pair ? parseFloat(getComputedStyle(pair).getPropertyValue('--en-c-statpanel-min')) * parseFloat(getComputedStyle(document.documentElement).fontSize) : 0;
const gap = pair ? parseFloat(getComputedStyle(pair).columnGap) : 0;
const boxes = [...el.querySelectorAll('h1, .onboarding-intro, .en-statpanel, .en-statpanel *, .en-note, .result-action, .en-progress, .en-progress__head')];
const progress = el.querySelector('.en-progress');
return {
  open: visible(el),
  step: el.dataset.step || null,
  result: el.dataset.result || null,
  stepLabel: el.querySelector('.en-steplabel').textContent,
  title: el.querySelector('[data-role="title"]').textContent,
  intro: visible(el.querySelector('.onboarding-intro')) ? el.querySelector('.onboarding-intro').textContent : null,
  looking: visible(looking) ? looking.textContent : null,
  lookingError: looking.dataset.state === 'error',
  words: visible(el.querySelector('[data-role="scan-words"]')) ? el.querySelector('[data-role="scan-words"]').textContent : null,
  slow: visible(el.querySelector('[data-role="scan-slow"]')) ? el.querySelector('[data-role="scan-slow"]').textContent : null,
  progress: visible(progress) ? { role: progress.getAttribute('role'), label: progress.getAttribute('aria-label') } : null,
  buttons: buttons.map((b) => b.textContent),
  primary: buttons.filter((b) => b.classList.contains('en-button--primary')).map((b) => b.textContent),
  focused: buttons.includes(f) ? f.textContent : null,
  marked: buttons.filter((b) => b.dataset.focused === 'true').map((b) => b.textContent),
  focusedInView: buttons.includes(f) && (() => { const r = f.getBoundingClientRect();
    return r.top >= -0.5 && r.bottom <= hintTop + 0.5 && r.left >= -0.5 && r.right <= innerWidth + 0.5; })(),
  focusable: panels.filter((p) => p.tabIndex >= 0).length,
  panels: panels.map((p) => ({ label: p.getAttribute('aria-label'), role: p.getAttribute('role'),
    numbers: [...p.querySelectorAll('.en-statpanel__number')].map((n) => n.textContent),
    counts: [...p.querySelectorAll('.en-statpanel__count')].map((c) => c.textContent),
    path: p.querySelector('.en-statpanel__path').textContent,
    notSet: p.querySelector('.en-statpanel__notset') ? p.querySelector('.en-statpanel__notset').textContent : null })),
  sideBySide: panels.length === 2 && Math.abs(panels[0].getBoundingClientRect().top - panels[1].getBoundingClientRect().top) < 1,
  bothFit: !!pair && pair.clientWidth >= 2 * minWidth + gap,
  notes: [...el.querySelectorAll('.en-note')].map((n) => n.textContent),
  rowAt: rows.indexOf(f),
  rowKind: rows.includes(f) ? f.dataset.kind : null,
  rowId: rows.includes(f) ? f.dataset.id || null : null,
  names: rows.map((r) => r.querySelector('.row-line').innerText),
  hints: [...document.querySelectorAll('#hint-bar .en-hint')].filter(visible).map((h) => h.textContent.replace(/\\s+/g, ' ').trim()),
  overflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth,
  cutOff: boxes.filter(visible).filter((b) => { const r = b.getBoundingClientRect();
    return r.left < -0.5 || r.right > innerWidth + 0.5 || (b.clientWidth > 0 && b.scrollWidth > b.clientWidth + 1); }).map((b) => b.className || b.tagName),
  library: visible(document.getElementById('library')),
  loading: visible(document.getElementById('loading')),
  errorBanner: visible(document.getElementById('error-banner')) ? document.getElementById('error-banner').textContent : null,
};
"""

BUTTON_AT_JS = """
const b = document.querySelector(`.result-action[data-kind="${arguments[0]}"]`);
b.scrollIntoView({block: 'center'});
const r = b.getBoundingClientRect();
return [Math.round(r.left + r.width / 2), Math.round(r.top + r.height / 2)];
"""


def wait(m, predicate, timeout=20):
    end = time.time() + timeout
    s = m.js(STATE_JS)
    while not predicate(s) and time.time() < end:
        time.sleep(0.1)
        s = m.js(STATE_JS)
    return s


def done(s):
    return s["result"] in ("ready", "nothing", "failed")


class Run:
    def __init__(self, tmp, m, shots_dir, check, hold):
        self.tmp, self.m, self.shots_dir, self.check, self.hold = tmp, m, shots_dir, check, hold
        self.count = 0
        self.quits = 0
        self.servers = []

    def server(self, **paths):
        self.count += 1
        folder = self.tmp / f"app-{self.count}"
        (folder / "data").mkdir(parents=True)
        settings_file = folder / "settings.json"
        settings = {"movies_path": "", "tv_path": "", "mpv_command": str(self.tmp / "fake-mpv"), "mpv_args": [],
                    "resume": False, "keep_awake": False, "data_dir": str(folder / "data"), **paths}
        settings_file.write_text(json.dumps(settings))
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        port = httpd.server_address[1]
        base = make_handler(UI_DIR, folder, dict(settings), {}, port, None, settings_file)
        run = self

        class Handler(base):
            def log_message(self, format, *args):
                pass

            def _handle_shutdown(self):
                run.quits += 1
                self._send_json(200, {"ok": True})

        httpd.RequestHandlerClass = Handler
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.servers.append(httpd)
        return port

    def open(self, port, size="w1280"):
        set_window(self.m, *WINDOW)
        self.m.send("WebDriver:Navigate", {"url": f"http://127.0.0.1:{port}/"})
        set_window(self.m, *SIZES[size])

    def shot(self, name, size):
        self.m.settle()
        (self.shots_dir / f"first-scan-{name}-{size}.png").write_bytes(
            base64.b64decode(self.m.send("WebDriver:TakeScreenshot", {})["value"]))

    def layout(self, s, where):
        self.check(f"{where}: nothing cut off, no sideways scroll", not s["overflowX"] and not s["cutOff"], s["cutOff"])

    def press_until(self, key, predicate, tries=12):
        s = self.m.js(STATE_JS)
        while not predicate(s) and tries > 0:
            self.m.press(key)
            time.sleep(0.1)
            s = self.m.js(STATE_JS)
            tries -= 1
        return s

    def to_screen_2(self, port, size="w1280"):
        """Screen 1's list, Films chosen, on screen 2's Shows."""
        self.open(port, size)
        s = wait(self.m, lambda s: s["step"] == "1" and s["rowAt"] == 0)
        s = self.press_until(DOWN, lambda s: s["names"][s["rowAt"]] == "SD card › Films")
        self.m.press(ENTER)
        return wait(self.m, lambda s: s["step"] == "2" and s["rowAt"] == 0)

    def full_flow(self, size):
        check, m = self.check, self.m
        where = f"at {size}"
        port = self.server()
        s = self.to_screen_2(port, size)
        tv_id = s["rowId"]
        self.hold.clear()
        try:
            m.press(ENTER)
            s = wait(m, lambda s: s["result"] == "reading", 10)
            check(f"{where}: the scan starts at once, titled, with its step and Enamel's progress",
                  s["step"] == "3" and s["stepLabel"] == "Step 3 of 3" and s["title"] == "Reading your folders"
                  and s["progress"] == {"role": "progressbar", "label": "Reading your folders"} and s["words"], s)
            check(f"{where}: during the scan, no hints for A and B", s["hints"] == [], s["hints"])
            self.layout(s, f"{where}: reading")
            self.shot("reading", size)
            quits = self.quits
            m.press("q")
            m.press(ENTER)
            m.press("a")
            time.sleep(0.3)
            s = m.js(STATE_JS)
            check(f"{where}: B, A and Y do nothing during the scan",
                  s["result"] == "reading" and self.quits == quits and s["title"] == "Reading your folders", s)
        finally:
            self.hold.set()
        s = wait(m, done)
        check(f"{where}: the result: title and its line",
              s["result"] == "ready" and s["title"] == "Your library is ready" and s["stepLabel"] == "Step 3 of 3"
              and s["intro"] == "Titles come from your file and folder names. Nothing was changed in your folders.", s)
        check(f"{where}: both panels with their counts and folders", [p["label"] for p in s["panels"]]
              == ["3 movies, SD card › Films", "3 TV shows, 4 episodes, Internal storage › Shows"]
              and s["panels"][0]["numbers"] == ["3"] and s["panels"][1]["numbers"] == ["3", "4"]
              and s["panels"][0]["path"] == "SD card › Films" and s["focusable"] == 0, s["panels"])
        check(f"{where}: side by side only when both fit at their minimum width",
              s["sideBySide"] == s["bothFit"], (s["sideBySide"], s["bothFit"]))
        check(f"{where}: the two notes", s["notes"] == ["1 file in Films looks like an episode.",
                                                        "1 loose file in Shows looks like a film."], s["notes"])
        check(f"{where}: Open my library focused, marked and on screen, Change folders under it",
              s["buttons"] == ["Open my library", "Change folders"] and s["primary"] == ["Open my library"]
              and s["focused"] == "Open my library" and s["marked"] == ["Open my library"] and s["focusedInView"], s)
        check(f"{where}: the hint bar says what A and B do", s["hints"] == ["A Open my library", "B Back"], s["hints"])
        self.layout(s, f"{where}: result")
        self.shot("result", size)
        s = self.press_until(DOWN, lambda s: s["focused"] == "Change folders")
        check(f"{where}: Down reaches Change folders, and A's hint follows",
              s["focused"] == "Change folders" and s["focusedInView"] and s["hints"][0] == "A Change folders", s)
        s = self.press_until(UP, lambda s: s["focused"] == "Open my library")
        check(f"{where}: Up goes back to Open my library", s["focused"] == "Open my library", s)
        m.press("q")
        s = wait(m, lambda s: s["step"] == "2", 5)
        check(f"{where}: B on the result goes back to screen 2, on the choice made",
              s["step"] == "2" and s["rowId"] == tv_id and self.quits == quits, s)
        m.press(ENTER)
        s = wait(m, done)
        check(f"{where}: A there scans again", s["result"] == "ready", s)
        s = self.press_until(DOWN, lambda s: s["focused"] == "Change folders")
        m.press(ENTER)
        s = wait(m, lambda s: s["step"] == "1", 5)
        check(f"{where}: Change folders goes back to screen 1, on the choice made",
              s["names"][s["rowAt"]] == "SD card › Films", s)
        m.press(ENTER)
        s = wait(m, lambda s: s["step"] == "2", 5)
        check(f"{where}: and screen 2 keeps its choice too", s["rowId"] == tv_id, s)
        m.press(ENTER)
        s = wait(m, done)
        m.press(ENTER)
        s = wait(m, lambda s: s["library"] and not s["open"], 10)
        check(f"{where}: Open my library opens Home", s["library"] and not s["open"], s)

    def skipped_kind(self):
        check, m = self.check, self.m
        port = self.server()
        self.open(port)
        s = wait(m, lambda s: s["step"] == "1" and s["rowAt"] == 0)
        s = self.press_until(DOWN, lambda s: s["rowKind"] == "skip")
        m.press(ENTER)
        s = wait(m, lambda s: s["step"] == "2" and s["rowAt"] == 0)
        m.press(ENTER)
        s = wait(m, done)
        check("a skipped kind: Not set, with its second line saying which kind", s["panels"][0]["notSet"] == "Not set"
              and s["panels"][0]["path"] == "Movies" and s["panels"][0]["label"] == "Movies, not set"
              and s["panels"][0]["numbers"] == [], s["panels"])
        check("a skipped kind: the other still counts", s["result"] == "ready" and s["panels"][1]["numbers"] == ["3", "4"], s)
        self.shot("not-set", "w1280")

    def nothing_found(self, empty_movies, empty_tv):
        check, m = self.check, self.m
        port = self.server(movies_path=str(empty_movies), tv_path=str(empty_tv))
        quits = self.quits
        self.open(port)
        s = wait(m, done)
        check("nothing found: its title, and the same two panels at zero",
              s["result"] == "nothing" and s["title"] == "Nothing found in these folders"
              and [p["numbers"] for p in s["panels"]] == [["0"], ["0", "0"]], s)
        check("nothing found: Change folders alone, focused", s["buttons"] == ["Change folders"]
              and s["primary"] == ["Change folders"] and s["focused"] == "Change folders" and s["notes"] == [], s)
        self.shot("nothing", "w1280")
        set_window(m, *SIZES[min(SIZES, key=SIZES.get)])
        time.sleep(0.3)
        self.layout(m.js(STATE_JS), "nothing found, in the narrowest window")
        set_window(m, *SIZES["w1280"])
        m.press("q")
        s = wait(m, lambda s: s["step"] == "1" and s["rowAt"] == 0)
        check("folders already set: B on the result goes to screen 1, as there is no screen 2 choice to keep",
              s["step"] == "1" and self.quits == quits, s)

    def already_set(self, films, shows):
        check, m = self.check, self.m
        port = self.server(movies_path=str(films), tv_path=str(shows))
        self.open(port)
        s = wait(m, lambda s: s["result"] == "reading" or done(s))
        check("folders already set: straight to the scan, with no choice first", s["step"] == "3" and not s["library"], s)
        s = wait(m, done)
        check("folders already set: the result", s["result"] == "ready" and s["panels"][0]["numbers"] == ["3"], s)
        s = self.press_until(DOWN, lambda s: s["focused"] == "Change folders")
        m.press(ENTER)
        s = wait(m, lambda s: s["step"] == "1" and s["rowAt"] == 0)
        check("folders already set: Change folders searches, and lands on screen 1", s["step"] == "1" and s["rowAt"] == 0, s)

    def failures(self, films):
        check, m = self.check, self.m
        port = self.server(movies_path=str(films))
        with mock.patch.object(library_index, "full_scan", side_effect=OSError("invented")):
            self.open(port)
            s = wait(m, done)
        check("a failed scan: the existing message, with Change folders focused and no panels",
              s["result"] == "failed" and s["looking"] == SCAN_FAILED and s["lookingError"] and s["panels"] == []
              and s["buttons"] == ["Change folders"] and s["focused"] == "Change folders", s)
        self.shot("failed", "w1280")
        m.press("q")
        s = wait(m, lambda s: s["step"] == "1", 15)
        check("a failed scan: B is a way out", s["step"] == "1", s)
        gone = self.tmp / "gone-folder"
        port = self.server(movies_path=str(gone))
        self.open(port)
        s = wait(m, done)
        check("the card out: the same message, with a way out", s["result"] == "failed" and s["looking"] == SCAN_FAILED
              and s["focused"] == "Change folders", s)
        port = self.server(movies_path=str(gone), tv_path=str(films))
        self.open(port)
        s = wait(m, done)
        check("one folder out: a note, and the other still opens", s["result"] == "ready"
              and "Movies folder not available" in s["notes"] and s["focused"] == "Open my library", s)

    def taps(self):
        check, m = self.check, self.m
        port = self.server()
        s = self.to_screen_2(port)
        m.press(ENTER)
        s = wait(m, done)
        tap(m, *m.send("WebDriver:ExecuteScript", {"script": BUTTON_AT_JS, "args": ["change-folders"]})["value"])
        s = wait(m, lambda s: s["step"] == "1", 5)
        check("a tap on Change folders", s["step"] == "1", s)
        m.press(ENTER)
        s = wait(m, lambda s: s["step"] == "2", 5)
        m.press(ENTER)
        s = wait(m, done)
        tap(m, *m.send("WebDriver:ExecuteScript", {"script": BUTTON_AT_JS, "args": ["open-library"]})["value"])
        s = wait(m, lambda s: s["library"], 10)
        check("a tap on Open my library", s["library"], s)

    def second_press(self):
        check, m = self.check, self.m
        port = self.server()
        self.to_screen_2(port)
        quits = self.quits
        self.hold.clear()
        try:
            m.press(ENTER)
            m.press(ENTER)
            m.press("q")
            time.sleep(0.5)
            s = m.js(STATE_JS)
            check("A, A then B on the last step: the scan runs, with no error and no quit",
                  s["result"] == "reading" and s["errorBanner"] is None and self.quits == quits, s)
        finally:
            self.hold.set()
        s = wait(m, done)
        check("then the result", s["result"] == "ready", s)

    def still_working(self, films):
        check, m = self.check, self.m
        port = self.server(movies_path=str(films))
        self.hold.clear()
        try:
            self.open(port)
            s = wait(m, lambda s: s["result"] == "reading", 10)
            s = wait(m, lambda s: s["slow"] == "Still working…", 14)
            check("a long scan says it is still working", s["slow"] == "Still working…" and s["result"] == "reading", s)
            self.shot("still-working", "w1280")
        finally:
            self.hold.set()
        s = wait(m, done)
        check("and the result follows", s["result"] == "ready", s)

    def wait_for(self, script, timeout=15):
        """Until the script answers something true, or the time is up."""
        end = time.time() + timeout
        while not self.m.js(script) and time.time() < end:
            time.sleep(0.1)
        return self.m.js(script)

    def empty_after_launching_again(self, empty_movies, empty_tv):
        """A real scan of empty folders saves an empty library. The next launch,
        a new server on the same saved data, goes to screen 3, never empty Home."""
        check, m = self.check, self.m
        data = self.tmp / "data-empty-library"
        paths = {"movies_path": str(empty_movies), "tv_path": str(empty_tv), "data_dir": str(data)}
        self.open(self.server(**paths))
        s = wait(m, done)
        check("an empty library: the first launch finds nothing", s["result"] == "nothing", s)
        entry = library_index.entry_for(library_index.load(data / library_index.FILE_NAME, lambda line: None),
                                        "movies", str(empty_movies))
        check("an empty library: the scan did save one", entry is not None and entry["items"] == [], entry)
        self.open(self.server(**paths))
        s = wait(m, done)
        check("an empty library: launching again goes to screen 3, with Change folders, not an empty Home",
              s["open"] and s["step"] == "3" and s["result"] == "nothing" and not s["library"]
              and s["focused"] == "Change folders", s)

    def emptied_by_remove(self):
        """Remove empties the library on Home: screen 3, with its way out."""
        check, m = self.check, self.m
        film = self.tmp / "Only Film" / "Lone (2001)" / "Lone.2001.mkv"
        film.parent.mkdir(parents=True)
        film.write_bytes(b"")
        self.open(self.server(movies_path=str(self.tmp / "Only Film")))
        wait(m, done)
        m.press(ENTER)
        s = wait(m, lambda s: s["library"], 10)
        check("Remove: Home opens with the one film", s["library"], s)
        film.unlink()
        m.press("r")
        missing = self.wait_for("return !!document.querySelector('.file-row[data-status=\"missing\"]');")
        check("Remove: the film gone stays on Home, as missing, and isn't sent to the scan",
              missing and m.js(STATE_JS)["library"], m.js(STATE_JS))
        m.press("m")
        self.wait_for("return document.getElementById('home-menu').open;", 3)
        m.press(DOWN)
        m.press(ENTER)
        self.wait_for("return document.getElementById('confirm-remove').open;", 3)
        m.press(UP)
        m.press(ENTER)
        s = wait(m, lambda s: s["open"] and done(s), 15)
        check("Remove: emptying the library goes to screen 3, not an empty Home",
              s["step"] == "3" and s["result"] == "nothing" and not s["library"] and s["focused"] == "Change folders", s)


def run(env, profile, shots_dir, check):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        card, home = tmp / "CardLabel", tmp / "home-of-someone"
        make(str(card), CARD_FILES)
        make(str(home), HOME_FILES)
        empty_movies, empty_tv = tmp / "Empty Films", tmp / "Empty Shows"
        empty_movies.mkdir()
        empty_tv.mkdir()
        before = snapshot(str(card)), snapshot(str(home))
        fake = tmp / "fake-mpv"
        fake.write_text(FAKE_MPV)
        fake.chmod(0o755)
        hold = threading.Event()
        hold.set()
        real_scan = library_index.full_scan

        def held_scan(*args):
            hold.wait(30)
            return real_scan(*args)

        places = lambda: [ff.Place("internal", "Internal storage", str(home)), ff.Place("sd", "SD card", str(card))]
        patches = [mock.patch.object(ff, "list_places", places),
                   mock.patch.object(folder_dialog, "find", lambda: None),
                   mock.patch.object(library_index, "full_scan", held_scan),
                   mock.patch.object(server, "_log", lambda line: None)]
        for patch in patches:
            patch.start()
        mport = free_port()
        (profile / "user.js").write_text(
            f'user_pref("marionette.port", {mport});\n'
            'user_pref("browser.shell.checkDefaultBrowser", false);\n'
            'user_pref("browser.aboutwelcome.enabled", false);\n'
        )
        cmd = ["--headless", "--marionette", FIREFOX_FLAG, "--no-remote", "-profile", str(profile), "about:blank"]
        firefox = subprocess.Popen(
            ["firefox", *cmd] if shutil.which("firefox") else ["flatpak", "run", "org.mozilla.firefox", *cmd],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        m = None
        r = None
        try:
            m = Marionette(mport)
            r = Run(tmp, m, shots_dir, check, hold)
            for size in SIZES:
                r.full_flow(size)
            r.skipped_kind()
            r.nothing_found(empty_movies, empty_tv)
            r.already_set(card / "Films", home / "Shows")
            r.failures(card / "Films")
            r.taps()
            r.second_press()
            r.still_working(card / "Films")
            r.empty_after_launching_again(empty_movies, empty_tv)
            r.emptied_by_remove()
            check("the invented folders are byte-for-byte unchanged", (snapshot(str(card)), snapshot(str(home))) == before)
        finally:
            for patch in patches:
                patch.stop()
            if m is not None:
                try:
                    m.send("Marionette:Quit", {"flags": ["eForceQuit"]})
                except (OSError, RuntimeError, ValueError):
                    pass
            firefox.terminate()
            try:
                firefox.wait(10)
            except subprocess.TimeoutExpired:
                firefox.kill()
            if r is not None:
                for httpd in r.servers:
                    httpd.shutdown()
                    httpd.server_close()


def main():
    shots_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="first-scan-"))
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
        profile = home / ".var/app/org.mozilla.firefox/data/check-profile-first-scan"
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
