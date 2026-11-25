# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Onboarding's two screens (the folder choice screens) in a real, headless Firefox. Not
part of the unit tests: it needs Firefox and takes a few minutes.

Drives the onboarding screens. Uses the Marionette helper from
loading_screen_check.py, with invented folders in a temporary folder (the
folder search is pointed at them) and temporary settings files; the app's
own settings.json is never read or written.

At every window width in tests/window_sizes.py, from Enamel's smallest
supported box to very wide: screen 1 shows Enamel's step label, the title,
two group bands (filled with an icon for internal storage, outlined for the
card), and the focus on the first folder; Down scrolls the list with the
focused row always wholly on screen; A on a folder goes to screen 2 with
the focus on its first folder and the Movies badge on the folder chosen;
B goes back with the focus on that choice; A on the Movies folder shows the
message inside the focused row (Enamel's error mark, white text), which
goes when the focus moves; Y looks again keeping the focus; a tap chooses a
row (here one holding the Movies folder: its message); a good choice saves
both folders in the settings file and goes on to the scan and its result.
The hint bar's words follow each screen; nothing is cut off and nothing
scrolls sideways. Once: skipping both shows its message in the row; a slow
search shows "Looking for your videos"; with a folder set the flow stays
away at the plain address, and the page address ending in #onboarding opens
it anyway, saves and goes Home with that ending gone; a kind left empty says
"No folder chosen" on its tab after a scan. The invented folders are
byte-for-byte unchanged at the end. Screenshots go to the folder given as
the first argument.

"No videos found yet" (the No videos found screen), at every width: it shows in place of screen
1 with the sentence, Enamel's numbered steps and the Look again button
focused; Up and Down reach every word; Look again with still nothing keeps it,
and with folders now there shows screen 1 focused on the first folder; nothing
is cut off, and the settings and saved data are never written. Once: a card
not ready and a card found but empty, a tap on the button, Y still looking
again with its hint hidden, a slow first search and a slow Look again.

"Browse somewhere else" (the Browse somewhere else work), with a stand-in dialog program and never
a real dialog: at every width the row sits just above "I don't have ..." on
both screens and is the second button on "No videos found yet". At two widths:
a cancel returns the focus; a picked folder gets its row with its place, focused,
and can be chosen; the Movies folder picked again on screen 2 shows the same
message in its row; Y keeps the focus on the row; a dialog held open shows B
Cancel, and B closes it without leaving the screen; a dialog that fails says so.
On the no-videos screen, Down reaches the second button, a cancel returns to it,
a failure shows its line, and a picked folder opens screen 1 on its row. With no
dialog found, neither the row nor the button shows.

From the series review (the first onboarding review fixes), at every width: Y after a failed first search,
and Y on the Browse button of "No videos found yet", land on the first folder with
the page at its top; a card that isn't ready, with a folder found elsewhere, says so
above the list on both screens until Look again finds it, opening with the focused
row in view and the line on screen (in the smallest box, every word reachable with
Up), and A on a row scrolled away only bringing it back; a picked folder that can't
be read, or that holds Kettle's own files, says so in its row and A stays there;
videos only at the top of a home folder holding Kettle are refused until they are
moved into a folder, when Y finds it and it can be saved; a refused picked row's
words name Y and Browse, and both work. Once: the plain list says "No folder chosen" for a skipped kind.

From the second series review (the second onboarding review fixes), once, with Home held back after the save:
A again, and B, on the last step do nothing (no error on Home, no quit); once Home is
ready the keys work on it, on the library and the plain list;
after a failed save they work on the onboarding screen, and the save can be tried again.
With Home held back past 10 seconds, the loading screen says "Still working…", B quits
again, A stays off, and Home opens when it answers, with the loading screen gone.

Run from the repo root:  python3 tests/onboarding_check.py [screenshot-dir]
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
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from backend import folder_dialog  # noqa: E402
from backend import folder_finder as ff  # noqa: E402
from backend import onboarding, server  # noqa: E402
from backend.server import make_handler  # noqa: E402
from tests.click_focus_check import tap  # noqa: E402
from tests.home_shell_check import DOWN, ENTER, UP  # noqa: E402
from tests.loading_screen_check import UI_DIR, Marionette, free_port  # noqa: E402
from tests.test_folder_dialog import StandIn  # noqa: E402
from tests.test_folder_finder import make, snapshot  # noqa: E402
from tests.window_sizes import FIREFOX_FLAG, SIZES, WINDOW, set_window  # noqa: E402

FAKE_MPV = "#!/usr/bin/env python3\n"
WHITE = "rgb(255, 255, 255)"
# Ten collections at home, so the list is longer than a short window.
HOME_FILES = [f"Videos/Collection {n:02d}/{t}/{t}.mkv" for n in range(1, 11) for t in ("A", "B")]
CARD_FILES = ["loose-video.mkv", "Films/Alpha/a.mkv", "Films/Beta/b.mkv"]

STATE_JS = """
const visible = (el) => !!el && !el.hidden && getComputedStyle(el).display !== 'none' && !el.closest('[hidden]');
const el = document.getElementById('onboarding');
const rows = [...el.querySelectorAll('.folder-row')];
const f = document.activeElement;
const at = rows.indexOf(f);
const hintTop = document.getElementById('hint-bar').getBoundingClientRect().top;
const inView = (r) => r.top >= -0.5 && r.bottom <= hintTop + 0.5 && r.left >= -0.5 && r.right <= innerWidth + 0.5;
// A row taller than the room above the hint bar (the smallest supported
// box) is in view when it starts on screen and fills the room.
const rowInView = (r) => inView(r) || (r.height > hintTop && r.top >= -0.5 && r.top < hintTop
  && r.left >= -0.5 && r.right <= innerWidth + 0.5);
const looking = el.querySelector('[data-role="looking"]');
const boxes = [...el.querySelectorAll('h1, .onboarding-intro, .en-band, .folder-row, .en-badge, .en-row__message')];
return {
  open: visible(el),
  step: el.dataset.step || null,
  stepLabel: el.querySelector('.en-steplabel').textContent,
  title: el.querySelector('h1').innerText,
  looking: visible(looking) ? looking.textContent : null,
  lookingError: looking.dataset.state === 'error',
  lookingInView: visible(looking) && inView(looking.getBoundingClientRect()),
  lookingBox: (({top, bottom}) => [Math.round(top), Math.round(bottom), Math.round(hintTop)])(looking.getBoundingClientRect()),
  titleInView: inView(el.querySelector('h1').getBoundingClientRect()),
  scrollTop: Math.round(window.scrollY),
  // At the top of the page when the first row fits there with the title; a
  // short window scrolls only to bring that row into view.
  atTop: window.scrollY < 1 || (rows.length > 0 && rows[0].getBoundingClientRect().bottom + window.scrollY > hintTop),
  meta: rows.map((r) => { const m = r.querySelector('.en-row__meta'); return m ? m.textContent : ''; }).join(' | '),
  statusErrors: [...document.querySelectorAll('[data-role="status"][data-state="error"]')].map((e) => e.textContent),
  listShown: visible(el.querySelector('[data-role="groups"]')),
  rows: rows.length,
  at,
  kind: at >= 0 ? f.dataset.kind : null,
  id: at >= 0 ? f.dataset.id || null : null,
  text: at >= 0 ? f.querySelector('.row-line').innerText : null,
  marked: rows.filter((r) => r.dataset.focused === 'true').map((r) => rows.indexOf(r)),
  focusedInView: at >= 0 && rowInView(f.getBoundingClientRect()),
  ids: rows.map((r) => r.dataset.id || null),
  names: rows.map((r) => r.querySelector('.row-line').innerText),
  badges: [...el.querySelectorAll('.en-badge')].map((b) => [rows.indexOf(b.closest('.folder-row')), b.textContent]),
  messages: rows.map((r, i) => { const m = r.querySelector('.en-row__message');
    if (!m.textContent) return null;
    const box = m.getBoundingClientRect(), row = r.getBoundingClientRect();
    return {i, text: m.textContent, icon: !!m.querySelector('.en-icon'), colour: getComputedStyle(m).color,
            rowFill: getComputedStyle(r).backgroundColor, inRow: box.top >= row.top && box.bottom <= row.bottom
            && box.left >= row.left && box.right <= row.right, inView: rowInView(box), height: box.height}; }).filter(Boolean),
  bands: [...el.querySelectorAll('.en-band')].map((b) => ({text: b.innerText.replace(/\\s+/g, ' ').trim(),
    outline: b.classList.contains('en-band--outline'), icon: !!b.querySelector('.en-band__name .en-icon'),
    fill: getComputedStyle(b).backgroundColor})),
  hints: [...document.querySelectorAll('#hint-bar .en-hint')].filter(visible).map((h) => h.textContent.replace(/\\s+/g, ' ').trim()),
  overflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth,
  hintsCut: [...document.querySelectorAll('#hint-bar .en-hint')].filter(visible).filter((h) => { const r = h.getBoundingClientRect();
    return r.left < -0.5 || r.right > innerWidth + 0.5; }).map((h) => h.textContent.replace(/\\s+/g, ' ').trim()),
  cutOff: boxes.filter(visible).filter((b) => { const r = b.getBoundingClientRect();
    return r.left < -0.5 || r.right > innerWidth + 0.5 || b.scrollWidth > b.clientWidth + 1; }).map((b) => b.className || b.tagName),
  hash: location.hash,
  statuses: [...document.querySelectorAll('[data-role="status"]')].map((e) => e.textContent),
  firstScan: visible(document.querySelector('#onboarding[data-result]:not([data-result="reading"])')),
  library: visible(document.getElementById('library')),
};
"""

TAP_JS = """
const row = document.querySelectorAll('#onboarding .folder-row')[arguments[0]];
row.scrollIntoView({block: 'center'});
const r = row.getBoundingClientRect();
return [Math.round(r.left + r.width / 2), Math.round(r.top + Math.min(r.height / 2, 12))];
"""


# The "No videos found yet" screen (the No videos found screen).
NO_VIDEOS_JS = """
const visible = (el) => !!el && !el.hidden && getComputedStyle(el).display !== 'none' && !el.closest('[hidden]');
const el = document.getElementById('onboarding');
const b = el.querySelector('.no-videos-action');
const h1 = el.querySelector('h1');
const hintTop = document.getElementById('hint-bar').getBoundingClientRect().top;
const inView = (e) => { const r = e.getBoundingClientRect();
  return r.top >= -0.5 && r.bottom <= hintTop + 0.5 && r.left >= -0.5 && r.right <= innerWidth + 0.5; };
const browse = el.querySelector('.no-videos-action[data-kind="browse"]');
const boxes = [h1, el.querySelector('.onboarding-intro'), el.querySelector('.en-steps'),
  ...el.querySelectorAll('.en-steps > li'), b, browse].filter(Boolean);
const box = b ? b.getBoundingClientRect() : {left: 0, top: 0, width: 0, height: 0};
return {
  screen: el.dataset.step || null,
  title: visible(h1) ? h1.innerText : null,
  stepLabel: visible(el.querySelector('.en-steplabel')),
  intro: el.querySelector('.onboarding-intro').textContent,
  steps: visible(el.querySelector('.en-steps')) ? [...el.querySelectorAll('.en-steps > li')].map((li) => li.textContent) : [],
  looking: visible(el.querySelector('[data-role="looking"]')) ? el.querySelector('[data-role="looking"]').textContent : null,
  rows: el.querySelectorAll('.folder-row').length,
  button: visible(b) ? b.textContent : null,
  browse: visible(browse) ? browse.textContent : null,
  browsePrimary: !!browse && browse.classList.contains('en-button--primary'),
  browseFocused: !!browse && document.activeElement === browse,
  browseMarked: !!browse && browse.dataset.focused === 'true',
  browseInView: !!browse && inView(browse),
  primary: !!b && b.classList.contains('en-button') && b.classList.contains('en-button--primary'),
  focused: !!b && document.activeElement === b,
  marked: !!b && b.dataset.focused === 'true',
  buttonInView: !!b && inView(b),
  titleInView: inView(h1),
  buttonAt: [Math.round(box.left + box.width / 2), Math.round(box.top + box.height / 2)],
  hints: [...document.querySelectorAll('#hint-bar .en-hint')].filter(visible).map((h) => h.textContent.replace(/\\s+/g, ' ').trim()),
  overflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth,
  cutOff: boxes.filter(visible).filter((e) => { const r = e.getBoundingClientRect();
    return r.left < -0.5 || r.right > innerWidth + 0.5 || e.scrollWidth > e.clientWidth + 1; }).map((e) => e.className || e.tagName),
};
"""

# Home, in the moment after the save (the second onboarding review fixes).
HOME_JS = """
const f = document.activeElement;
const banner = document.getElementById('error-banner');
return {
  error: banner.hidden ? null : banner.textContent,
  focus: f === document.body ? null : f.dataset.key || f.className,
  picker: !!(window.EnamelUI && window.EnamelUI.picker.isOpen()),
  loading: !document.getElementById('loading').hidden,
  slow: !document.querySelector('#loading [data-role="slow"]').hidden,
};
"""

NO_VIDEOS_STEPS = [
    "Make one folder for movies and one for TV shows, on this device or on an SD card.",
    "Copy your videos in. Give each TV show its own folder.",
    "If they are on a card, put it in. Then choose Look again.",
]
PLAYS_WHAT = "It plays videos you already have and doesn't create folders for you."


def wait(m, predicate, timeout=10, js=STATE_JS):
    end = time.time() + timeout
    s = m.js(js)
    while not predicate(s) and time.time() < end:
        time.sleep(0.1)
        s = m.js(js)
    return s


class Run:
    def __init__(self, tmp, places, m, shots_dir, check, nowhere, broken, home_open):
        self.tmp, self.places, self.m, self.shots_dir, self.check = tmp, places, m, shots_dir, check
        self.nowhere = nowhere  # while it holds places, the search looks only there
        self.broken = broken  # while set, a search fails
        self.home_open = home_open  # while clear, the library's answer is held back
        self.servers = []
        self.count = 0
        self.quits = 0

    def server(self, parent=None, **paths):
        """A server saving into its own temporary settings file, with
        neither folder set unless paths says otherwise. parent: the folder
        the app sits in."""
        self.count += 1
        folder = (parent or self.tmp) / f"app-{self.count}"
        (folder / "data").mkdir(parents=True)
        settings_file = folder / "settings.json"
        fake = self.tmp / "fake-mpv"
        settings = {"movies_path": "", "tv_path": "", "mpv_command": str(fake), "mpv_args": [],
                    "resume": False, "keep_awake": False, "data_dir": str(folder / "data"), **paths}
        settings_file.write_text(json.dumps({**settings, "a_later_setting": [1, 2]}, indent=2))
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        port = httpd.server_address[1]
        base = make_handler(UI_DIR, folder, dict(settings), {}, port, None, settings_file)
        run = self

        class Handler(base):
            def log_message(self, format, *args):
                pass

            def _handle_shutdown(self):
                run.quits += 1
                self._send_json(200, {"ok": True})  # q quits: the test server keeps running

        httpd.RequestHandlerClass = Handler
        httpd.handle_error = lambda *args: None  # the invented failed search prints nothing
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.servers.append(httpd)
        return port, settings_file

    def open(self, port, size):
        set_window(self.m, *WINDOW)
        self.m.send("WebDriver:Navigate", {"url": f"http://127.0.0.1:{port}/"})
        set_window(self.m, *SIZES[size])
        return wait(self.m, lambda s: s["open"] and s["at"] == 0 and s["listShown"], 20)

    def shot(self, name, size):
        self.m.settle()
        (self.shots_dir / f"onboarding-{name}-{size}.png").write_bytes(
            base64.b64decode(self.m.send("WebDriver:TakeScreenshot", {})["value"]))

    def layout(self, s, where):
        self.check(f"{where}: nothing cut off, no sideways scroll", not s["overflowX"] and not s["cutOff"], s["cutOff"])
        # Enamel's hints never wrap inside themselves, so in its smallest
        # supported box the long A hint is wider than the bar: a gap
        # recorded for Enamel (the folder choice screens). Wider than that, every hint fits.
        if not where.endswith("w320"):
            self.check(f"{where}: every hint wholly on screen", not s["hintsCut"], s["hintsCut"])
        else:
            print(f"note {where}: hints wider than the bar (Enamel gap): {s['hintsCut']}")
        self.check(f"{where}: one row marked focused, the focused one", s["marked"] == [s["at"]], s["marked"])

    def press_until(self, key, predicate, limit=30):
        s = self.m.js(STATE_JS)
        for _ in range(limit):
            if predicate(s):
                break
            self.m.press(key)
            time.sleep(0.05)
            s = self.m.js(STATE_JS)
        return s

    def flow(self, size):
        check, m = self.check, self.m
        port, settings_file = self.server()
        s = self.open(port, size)
        where = f"screen 1 at {size}"
        check(f"{where}: shows, focus on the first folder", s["open"] and s["step"] == "1" and s["at"] == 0
              and s["kind"] == "folder", s)
        if not s["open"]:
            return
        check(f"{where}: step label and title", s["stepLabel"] == "Step 1 of 3"
              and s["title"].endswith("Which folder has your movies?"), s["title"])
        bands = s["bands"]
        check(f"{where}: a filled band with an icon for internal storage, an outlined one for the card",
              len(bands) == 2 and not bands[0]["outline"] and bands[1]["outline"] and all(b["icon"] for b in bands)
              and bands[0]["text"].endswith("10 folders") and bands[1]["text"].endswith("2 folders")
              and bands[0]["fill"] != bands[1]["fill"], bands)
        check(f"{where}: rows as paths with counts, the last one to skip",
              s["names"][0] == "Internal storage › Videos › Collection 01"
              and s["names"][-1] == "I don't have movies" and s["rows"] == 14, s["names"])
        check(f"{where}: Browse somewhere else just above the last row",
              s["names"][-2] == "Browse somewhere else", s["names"])
        check(f"{where}: hints", s["hints"] == ["A This is my movies folder", "B Quit", "Y Look again"], s["hints"])
        self.layout(s, where)
        self.shot("step1", size)
        # Down to the end: the list scrolls, the focused row always in view.
        in_view = []
        for _ in range(s["rows"] - 1):
            m.press(DOWN)
            time.sleep(0.05)
            in_view.append(m.js(STATE_JS)["focusedInView"])
        s = m.js(STATE_JS)
        check(f"{where}: Down reaches the last row, always wholly on screen",
              s["kind"] == "skip" and all(in_view), in_view)
        films = s["names"].index("SD card › Films")
        whole = s["names"].index("SD card")
        films_id = s["ids"][films]
        s = self.press_until(UP, lambda s: s["at"] == films)
        check(f"{where}: Up back to the card's Films, in view", s["id"] == films_id and s["focusedInView"], s)
        m.press(ENTER)
        s = wait(m, lambda s: s["step"] == "2" and s["at"] == 0)
        where = f"screen 2 at {size}"
        check(f"{where}: shows, focus on the first folder", s["step"] == "2" and s["at"] == 0, s)
        check(f"{where}: step label and title", s["stepLabel"] == "Step 2 of 3"
              and s["title"].endswith("Which folder has your TV shows?"), s["title"])
        check(f"{where}: the Movies badge on the folder chosen", s["badges"] == [[films, "Movies"]], s["badges"])
        check(f"{where}: hints", s["hints"] == ["A This is my TV shows folder", "B Back", "Y Look again"], s["hints"])
        check(f"{where}: the last row, with Browse somewhere else just above it",
              s["names"][-2:] == ["Browse somewhere else", "I don't have TV shows"], s["names"])
        self.layout(s, where)
        self.shot("step2", size)
        m.press("q")
        s = wait(m, lambda s: s["step"] == "1")
        check(f"{where}: B goes back to screen 1, on the choice made there", s["step"] == "1" and s["id"] == films_id, s)
        m.press(ENTER)
        wait(m, lambda s: s["step"] == "2" and s["at"] == 0)
        s = self.press_until(DOWN, lambda s: s["at"] == films)
        m.press(ENTER)
        s = wait(m, lambda s: s["messages"])
        msg = s["messages"][0] if s["messages"] else {}
        check(f"{where}: the Movies folder again: the message in its focused row", s["at"] == films
              and msg.get("i") == films and msg.get("text") == onboarding.SAME and msg.get("icon"), s)
        check(f"{where}: the message is readable (white on the row's grey) and wholly in the row, on screen",
              msg.get("colour") == WHITE and msg.get("rowFill") != WHITE and msg.get("inRow") and msg.get("inView"), msg)
        self.layout(s, where)
        self.shot("message", size)
        m.press(DOWN)
        s = wait(m, lambda s: not s["messages"])
        check(f"{where}: the message goes when the focus moves", s["at"] == films + 1 and not s["messages"], s)
        next_id = s["id"]
        m.press("a")
        time.sleep(0.3)
        s = wait(m, lambda s: s["listShown"] and s["at"] >= 0)
        check(f"{where}: Y looks again, keeping the focus", s["step"] == "2" and s["id"] == next_id
              and s["badges"] == [[films, "Movies"]], s)
        tap(m, *m.send("WebDriver:ExecuteScript", {"script": TAP_JS, "args": [whole]})["value"])
        s = wait(m, lambda s: s["messages"])
        msg = s["messages"][0] if s["messages"] else {}
        check(f"{where}: a tap chooses its row: the card holds the Movies folder", s["at"] == whole
              and msg.get("text") == onboarding.HOLDS_MOVIES and msg.get("inView"), s)
        before = (snapshot(str(self.places["sd"])), snapshot(str(self.places["internal"])))
        s = self.press_until(UP, lambda s: s["at"] == 0)
        m.press(ENTER)
        s = wait(m, lambda s: s["firstScan"], 10)
        saved = json.loads(settings_file.read_text())
        check(f"{where}: a good choice saves both folders, keeping the other settings, and goes on to the result",
              s["firstScan"] and saved["movies_path"] == str(self.places["sd"] / "Films")
              and saved["tv_path"] == str(self.places["internal"] / "Videos" / "Collection 01")
              and saved["a_later_setting"] == [1, 2], {"state": s["firstScan"], "keys": list(saved)})
        check(f"{where}: Y Look again has gone from the hint bar", "Y Look again" not in s["hints"], s["hints"])
        check(f"{where}: the folders unchanged",
              (snapshot(str(self.places["sd"])), snapshot(str(self.places["internal"]))) == before)

    def once(self, slow):
        check, m = self.check, self.m
        port, settings_file = self.server()
        s = self.open(port, "w1280")
        before = settings_file.read_bytes()
        s = self.press_until(DOWN, lambda s: s["kind"] == "skip")
        m.press(ENTER)
        s = wait(m, lambda s: s["step"] == "2")
        s = self.press_until(DOWN, lambda s: s["kind"] == "skip")
        m.press(ENTER)
        s = wait(m, lambda s: s["messages"])
        msg = s["messages"][0] if s["messages"] else {}
        check("skipping both: its message in the row, nothing saved", s["kind"] == "skip"
              and msg.get("text") == onboarding.NEITHER and settings_file.read_bytes() == before, s)
        self.shot("skip-both", "w1280")
        slow.set()
        m.press("a")
        time.sleep(1.3)
        s = m.js(STATE_JS)
        check("a slow search says Looking for your videos in place of the list",
              s["looking"] == "Looking for your videos" and not s["listShown"], s)
        self.shot("looking", "w1280")
        slow.clear()
        s = wait(m, lambda s: s["listShown"], 10)
        check("then the list comes back, focus kept", s["listShown"] and s["kind"] == "skip", s)

    def saved(self, settings_file):
        """Everything this screen must leave alone: the settings file and the
        saved data (the library, Continue watching) next to it."""
        data = settings_file.parent / "data"
        return settings_file.read_bytes(), {p.name: p.read_bytes() for p in data.iterdir()}

    def no_videos(self, size):
        check, m = self.check, self.m
        where = f"no videos at {size}"
        home = self.tmp / f"nothing-here-{size}"
        make(str(home), ["Clips/short.mp4"], size=1000)  # a folder of clips isn't suggested
        self.nowhere[:] = [ff.Place("internal", "Internal storage", str(home))]
        port, settings_file = self.server()
        data = settings_file.parent / "data"
        (data / "invented-saved-library.json").write_text('{"kept": true}')
        before = self.saved(settings_file)
        set_window(m, *WINDOW)
        self.visit(port)
        set_window(m, *SIZES[size])  # after opening: opening a page resets the zoom
        wait(m, lambda s: s["screen"] == "no-videos" and s["focused"], 20, NO_VIDEOS_JS)
        # Once more at this size: the button is brought into view when the
        # focus lands on it, as at a launch in a window this size.
        m.press(ENTER)
        time.sleep(0.3)
        s = wait(m, lambda s: s["screen"] == "no-videos" and s["focused"], 10, NO_VIDEOS_JS)
        check(f"{where}: shows in place of screen 1, with no step label and no folder rows",
              s["screen"] == "no-videos" and s["title"] == "No videos found yet" and not s["stepLabel"] and s["rows"] == 0, s)
        check(f"{where}: says where it really looked", s["intro"]
              == f"Kettle looked in internal storage and found no SD card. {PLAYS_WHAT}", s["intro"])
        check(f"{where}: Enamel's three numbered steps", s["steps"] == NO_VIDEOS_STEPS, s["steps"])
        check(f"{where}: one button, Look again, focused and marked, on screen", s["button"] == "Look again"
              and s["primary"] and s["focused"] and s["marked"] and s["buttonInView"], s)
        check(f"{where}: the hint bar says A Look again", s["hints"] == ["A Look again", "B Quit"], s["hints"])
        check(f"{where}: nothing cut off, no sideways scroll", not s["overflowX"] and not s["cutOff"], s["cutOff"])
        self.shot("no-videos", size)
        # With the controller alone, every word can be reached in any window.
        for _ in range(30):
            if m.js(NO_VIDEOS_JS)["titleInView"]:
                break
            m.press(UP)
            time.sleep(0.05)
        s = m.js(NO_VIDEOS_JS)
        check(f"{where}: Up scrolls to the title, focus staying on the button", s["titleInView"] and s["focused"], s)
        for _ in range(30):
            if m.js(NO_VIDEOS_JS)["buttonInView"]:
                break
            m.press(DOWN)
            time.sleep(0.05)
        s = m.js(NO_VIDEOS_JS)
        check(f"{where}: Down brings the button back", s["buttonInView"] and s["focused"], s)
        check(f"{where}: Browse somewhere else is a second, plain button", s["browse"] == "Browse somewhere else"
              and not s["browsePrimary"], s)
        for _ in range(30):
            if m.js(NO_VIDEOS_JS)["browseFocused"]:
                break
            m.press(DOWN)
            time.sleep(0.05)
        s = m.js(NO_VIDEOS_JS)
        check(f"{where}: Down reaches it, marked and on screen, with its own hint", s["browseFocused"]
              and s["browseMarked"] and s["browseInView"] and s["hints"] == ["A Browse", "B Quit"], s)
        self.shot("no-videos-browse", size)
        m.press(UP)
        s = wait(m, lambda s: s["focused"], 5, NO_VIDEOS_JS)
        check(f"{where}: Up goes back to Look again, on screen", s["focused"] and s["buttonInView"], s)
        m.press(ENTER)
        time.sleep(0.3)
        s = wait(m, lambda s: s["screen"] == "no-videos" and s["focused"], 10, NO_VIDEOS_JS)
        check(f"{where}: Look again with still nothing keeps this screen, focused", s["screen"] == "no-videos"
              and s["focused"] and s["marked"], s)
        make(str(home), ["Films/Alpha/a.mkv", "Films/Beta/b.mkv"])
        m.press(ENTER)
        s = wait(m, lambda s: s["step"] == "1" and s["at"] == 0 and s["listShown"])
        check(f"{where}: Look again with folders now there shows screen 1, focus on the first folder",
              s["step"] == "1" and s["at"] == 0 and s["kind"] == "folder" and s["names"][0] == "Internal storage › Films"
              and s["names"][-1] == "I don't have movies", s)
        check(f"{where}: screen 1's own words are back", s["stepLabel"] == "Step 1 of 3"
              and s["title"].endswith("Which folder has your movies?")
              and s["hints"] == ["A This is my movies folder", "B Quit", "Y Look again"], s)
        self.layout(s, f"screen 1 after no videos at {size}")
        check(f"{where}: nothing written to the settings or the saved data", self.saved(settings_file) == before)
        self.nowhere.clear()

    def no_videos_once(self, slow):
        check, m = self.check, self.m
        home = self.tmp / "nothing-here-once"
        home.mkdir()
        card = self.tmp / "card-not-there-yet"
        self.nowhere[:] = [ff.Place("internal", "Internal storage", str(home)), ff.Place("sd", "SD card", str(card))]
        port, settings_file = self.server()
        before = self.saved(settings_file)
        set_window(m, *SIZES["w1280"])
        # A slow first search never shows a screen's title that may prove wrong.
        # (Slower than the loading screen stays up.)
        slow.seconds = 6
        slow.set()
        self.visit(port)
        s = wait(m, lambda s: s["looking"], 20, NO_VIDEOS_JS)
        check("a slow first search says only Looking for your videos", s["looking"] == "Looking for your videos"
              and s["title"] is None and not s["steps"], s)
        slow.clear()
        slow.seconds = 2
        s = wait(m, lambda s: s["screen"] == "no-videos" and s["focused"], 20, NO_VIDEOS_JS)
        check("a card not ready: the sentence says so, never that there is no card", s["intro"]
              == f"Kettle looked in internal storage and found the SD card isn't ready yet. {PLAYS_WHAT}", s["intro"])
        self.shot("no-videos-card-not-ready", "w1280")
        # The card turns up, empty: looked at now, and still nothing to choose.
        card.mkdir()
        tap(m, *s["buttonAt"])
        s = wait(m, lambda s: s["intro"].startswith("Kettle looked in internal storage and on the SD card."), 10, NO_VIDEOS_JS)
        check("a tap on Look again searches again: a card found but empty is said as looked at", s["intro"]
              == f"Kettle looked in internal storage and on the SD card. {PLAYS_WHAT}" and s["focused"], s)
        # Y's hint is hidden here, but Y still searches again: the card goes.
        card.rmdir()
        m.press("a")
        s = wait(m, lambda s: "isn't ready yet" in s["intro"] and s["focused"], 10, NO_VIDEOS_JS)
        check("Y still looks again on this screen, focus on the button", "isn't ready yet" in s["intro"]
              and s["focused"] and "Y Look again" not in s["hints"], s)
        # A slow Look again: the steps give way to the words, then come back.
        slow.set()
        m.press(ENTER)
        s = wait(m, lambda s: s["looking"], 10, NO_VIDEOS_JS)
        check("a slow Look again says Looking for your videos in place of the steps",
              s["looking"] == "Looking for your videos" and not s["steps"], s)
        slow.clear()
        s = wait(m, lambda s: s["steps"] and s["focused"], 10, NO_VIDEOS_JS)
        check("then the steps come back, focused", s["steps"] == NO_VIDEOS_STEPS and s["focused"] and s["looking"] is None, s)
        check("the once-over wrote nothing", self.saved(settings_file) == before)
        self.nowhere.clear()

    def browse_flow(self, size):
        check, m, dialog = self.check, self.m, self.dialog
        where = f"browse at {size}"
        port, settings_file = self.server()
        s = self.open(port, size)
        before = settings_file.read_bytes()
        s = self.press_until(DOWN, lambda s: s["kind"] == "browse")
        rows = s["rows"]
        check(f"{where}: the row has its own hint", s["hints"][0] == "A Browse", s["hints"])
        # Y searches again and stays on the row.
        m.press("a")
        s = wait(m, lambda s: s["kind"] == "browse" and s["listShown"])
        check(f"{where}: Y keeps the focus on the row", s["kind"] == "browse", s)
        # Cancelled.
        dialog.answer("", 1)
        m.press(ENTER)
        time.sleep(0.5)
        s = wait(m, lambda s: s["kind"] == "browse")
        check(f"{where}: a cancel returns the focus and changes nothing", s["kind"] == "browse" and s["rows"] == rows
              and s["marked"] == [s["at"]] and settings_file.read_bytes() == before, s)
        # A folder in no place: its own band and row, focused.
        outside = self.tmp / "private-parent" / "Outside"
        if not outside.exists():
            make(str(outside), ["Zeta/z.mkv", "Eta/e.mkv"])
        dialog.answer(outside)
        m.press(ENTER)
        s = wait(m, lambda s: s["text"] == "Somewhere else › Outside")
        check(f"{where}: a picked folder gets a row with its place, focused", s["text"] == "Somewhere else › Outside"
              and s["kind"] == "folder" and s["rows"] == rows + 1 and s["focusedInView"], s)
        check(f"{where}: and a band, and the page is told only its own name",
              any(b["text"].upper().startswith("SOMEWHERE ELSE") for b in s["bands"])
              and not any("private-parent" in n for n in s["names"]), s["bands"])
        self.layout(s, where)
        self.shot("browse-picked", size)
        picked_id = s["id"]
        # It can be chosen: on to screen 2, with the Movies badge.
        m.press(ENTER)
        s = wait(m, lambda s: s["step"] == "2" and s["at"] == 0)
        check(f"{where}: it can be chosen, and shows the Movies badge on screen 2", s["step"] == "2"
              and [b[1] for b in s["badges"]] == ["Movies"] and s["ids"][s["badges"][0][0]] == picked_id, s)
        # The Movies folder again, through the dialog: the same message, in its row.
        s = self.press_until(DOWN, lambda s: s["kind"] == "browse")
        rows = s["rows"]
        dialog.answer(outside)
        m.press(ENTER)
        s = wait(m, lambda s: s["messages"])
        msg = s["messages"][0] if s["messages"] else {}
        check(f"{where}: the Movies folder again shows the same message in its row, with no second row",
              s["id"] == picked_id and msg.get("text") == onboarding.SAME and msg.get("inView") and s["rows"] == rows, s)
        self.shot("browse-blocked", size)
        # Held open: B cancels the dialog and stays on this screen.
        s = self.press_until(DOWN, lambda s: s["kind"] == "browse")
        dialog.hold()
        dialog.answer("", 1)
        m.press(ENTER)
        s = wait(m, lambda s: "B Cancel" in s["hints"])
        check(f"{where}: while the dialog is open, the hint says B Cancel", "B Cancel" in s["hints"], s["hints"])
        check(f"{where}: and the server still answers", self.answers(port))
        m.press("q")
        s = wait(m, lambda s: "B Back" in s["hints"] and s["kind"] == "browse")
        check(f"{where}: B closes the dialog, staying on the screen with the focus on the row",
              s["step"] == "2" and s["kind"] == "browse" and "B Back" in s["hints"], s)
        dialog.release()
        # A dialog that fails says so in the row.
        dialog.answer("", 3)
        m.press(ENTER)
        s = wait(m, lambda s: s["messages"])
        msg = s["messages"][0] if s["messages"] else {}
        check(f"{where}: a dialog that fails says so in the row", s["kind"] == "browse"
              and msg.get("text") == folder_dialog.OPEN_FAILED and msg.get("inView"), s)
        # A good choice is saved, and only then.
        check(f"{where}: nothing saved yet", settings_file.read_bytes() == before)
        m.press(UP)
        s = wait(m, lambda s: not s["messages"])
        s = self.press_until(UP, lambda s: s["at"] == 0)
        m.press(ENTER)
        s = wait(m, lambda s: s["firstScan"], 10)
        check(f"{where}: the folder from the dialog is saved", s["firstScan"]
              and json.loads(settings_file.read_text())["movies_path"] == str(outside), s["firstScan"])

    def answers(self, port):
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/onboarding", timeout=2) as answer:
            return "needed" in json.load(answer)

    def browse_no_videos(self, size):
        check, m, dialog = self.check, self.m, self.dialog
        where = f"browse from no videos at {size}"
        home = self.tmp / f"nothing-at-all-{size}"
        home.mkdir()
        self.nowhere[:] = [ff.Place("internal", "Internal storage", str(home))]
        port, _ = self.server()
        set_window(m, *WINDOW)
        self.visit(port)
        set_window(m, *SIZES[size])
        wait(m, lambda s: s["screen"] == "no-videos" and s["focused"], 20, NO_VIDEOS_JS)
        for _ in range(30):
            if m.js(NO_VIDEOS_JS)["browseFocused"]:
                break
            m.press(DOWN)
            time.sleep(0.05)
        dialog.answer("", 1)
        m.press(ENTER)
        time.sleep(0.5)
        s = wait(m, lambda s: s["browseFocused"], 5, NO_VIDEOS_JS)
        check(f"{where}: a cancel returns the focus to the button", s["screen"] == "no-videos" and s["browseFocused"]
              and s["browseMarked"], s)
        dialog.answer("", 3)
        m.press(ENTER)
        s = wait(m, lambda s: s["looking"], 5, NO_VIDEOS_JS)
        check(f"{where}: a dialog that fails says so", s["looking"] == folder_dialog.OPEN_FAILED and s["browseFocused"], s)
        self.shot("no-videos-browse-failed", size)
        m.press(UP)
        s = wait(m, lambda s: not s["looking"], 5, NO_VIDEOS_JS)
        check(f"{where}: the line goes when the focus moves", s["looking"] is None and s["focused"], s)
        for _ in range(30):
            if m.js(NO_VIDEOS_JS)["browseFocused"]:
                break
            m.press(DOWN)
            time.sleep(0.05)
        make(str(home / "Picked"), ["Zeta/z.mkv"], size=1000)
        dialog.answer(home / "Picked")
        m.press(ENTER)
        s = wait(m, lambda s: s["step"] == "1" and s["text"] == "Internal storage › Picked")
        check(f"{where}: a picked folder shows screen 1, focused on its row, ready to choose", s["step"] == "1"
              and s["text"] == "Internal storage › Picked" and s["focusedInView"]
              and s["hints"][0] == "A This is my movies folder"
              and s["names"][-2:] == ["Browse somewhere else", "I don't have movies"], s)
        self.layout(s, where)
        self.nowhere.clear()

    def no_dialog(self):
        check, m, dialog = self.check, self.m, self.dialog
        for program in dialog.folder.glob("kdialog"):
            program.unlink()
        port, _ = self.server()
        s = self.open(port, "w1280")
        check("no dialog found: no row on screen 1", "Browse somewhere else" not in s["names"]
              and s["names"][-1] == "I don't have movies", s["names"])
        m.press(ENTER)
        s = wait(m, lambda s: s["step"] == "2" and s["at"] == 0)
        check("no dialog found: no row on screen 2", "Browse somewhere else" not in s["names"]
              and s["names"][-1] == "I don't have TV shows", s["names"])
        home = self.tmp / "nothing-no-dialog"
        home.mkdir()
        self.nowhere[:] = [ff.Place("internal", "Internal storage", str(home))]
        port, _ = self.server()
        self.visit(port)
        s = wait(m, lambda s: s["screen"] == "no-videos" and s["focused"], 20, NO_VIDEOS_JS)
        check("no dialog found: no second button on the no-videos screen", s["browse"] is None
              and s["button"] == "Look again", s)
        self.nowhere.clear()
        dialog.add("kdialog")

    # --- From the series review (the first onboarding review fixes) ---

    def y_from_no_list(self, size):
        """Y from a screen with no folder list lands on the first folder."""
        check, m = self.check, self.m
        where = f"Y with no list at {size}"
        # After a failed first search the only row is "I don't have movies".
        self.broken.set()
        port, _ = self.server()
        set_window(m, *WINDOW)
        self.visit(port)
        set_window(m, *SIZES[size])
        s = wait(m, lambda s: s["open"] and s["kind"] == "skip" and s["looking"], 20)
        check(f"{where}: a failed search offers only the row to skip", s["rows"] == 1 and s["kind"] == "skip"
              and s["looking"], s)
        self.broken.clear()
        m.press("a")
        s = wait(m, lambda s: s["rows"] > 1)
        check(f"{where}: after a failed search, the focus lands on the first folder, the page at its top",
              s["at"] == 0 and s["kind"] == "folder" and s["atTop"] and s["focusedInView"], s)
        self.layout(s, where)
        # Y on the Browse button of "No videos found yet".
        home = self.tmp / f"nothing-y-{size}"
        home.mkdir()
        self.nowhere[:] = [ff.Place("internal", "Internal storage", str(home))]
        port, _ = self.server()
        set_window(m, *WINDOW)
        self.visit(port)
        set_window(m, *SIZES[size])
        wait(m, lambda s: s["screen"] == "no-videos" and s["focused"], 20, NO_VIDEOS_JS)
        for _ in range(30):
            if m.js(NO_VIDEOS_JS)["browseFocused"]:
                break
            m.press(DOWN)
            time.sleep(0.05)
        m.press("a")
        time.sleep(0.3)
        s = wait(m, lambda s: s["screen"] == "no-videos" and s["browseFocused"], 5, NO_VIDEOS_JS)
        check(f"{where}: with still nothing found, Y stays on the Browse button", s["browseFocused"], s)
        make(str(home), ["Films/Alpha/a.mkv", "Films/Beta/b.mkv"])
        m.press("a")
        s = wait(m, lambda s: s["step"] == "1" and s["rows"] > 1)
        check(f"{where}: from the Browse button, the focus lands on the first folder, the page at its top",
              s["at"] == 0 and s["kind"] == "folder" and s["atTop"] and s["focusedInView"], s)
        self.layout(s, where)
        self.nowhere.clear()

    def read_the_line(self, s, where, settings_file):
        """The screen opens with the focused first row in view. The line is on
        screen too, except in the smallest box, which has no room for both: there
        Up reaches every word. A on a row scrolled away saves nothing and only
        brings it back; Down comes back too, then moves on."""
        check, m = self.check, self.m
        check(f"{where}: opens with the focused first row in view", s["at"] == 0 and s["focusedInView"], s["lookingBox"])
        if "w320" not in where:
            check(f"{where}: and the line wholly on screen, with nothing pressed", s["lookingInView"], s["lookingBox"])
        room = s["lookingBox"][2]
        no_gap = True
        went_away = False
        tops = [s["scrollTop"]]
        for _ in range(12):
            if s["scrollTop"] == 0:
                break
            above = s["scrollTop"]
            m.press(UP)
            time.sleep(0.05)
            s = m.js(STATE_JS)
            tops.append(s["scrollTop"])
            no_gap = no_gap and s["scrollTop"] + room >= above  # nothing skipped
            went_away = went_away or not s["focusedInView"]
        check(f"{where}: Up reaches the top of the page, skipping no words, the focus still on the first row",
              s["scrollTop"] == 0 and no_gap and s["at"] == 0, tops)
        m.press(UP)
        time.sleep(0.2)
        s = m.js(STATE_JS)
        check(f"{where}: one more Up leaves the page at its top", s["scrollTop"] == 0 and s["at"] == 0, s["scrollTop"])
        if "w320" in where:
            check(f"{where}: in the smallest box, reading the line scrolls the row away", went_away, tops)
        if not s["focusedInView"]:
            step, saved = s["step"], settings_file.read_bytes()
            m.press(ENTER)
            s = wait(m, lambda s: s["focusedInView"], 3)
            time.sleep(0.2)
            s = m.js(STATE_JS)
            check(f"{where}: A on the row out of view only brings it back, choosing nothing", s["step"] == step
                  and s["at"] == 0 and s["focusedInView"] and not s["firstScan"]
                  and settings_file.read_bytes() == saved, s["lookingBox"])
            for _ in range(12):
                if s["scrollTop"] == 0:
                    break
                m.press(UP)
                time.sleep(0.05)
                s = m.js(STATE_JS)
        tops = [s["scrollTop"]]
        for _ in range(12):
            if s["at"] != 0:
                break
            m.press(DOWN)
            time.sleep(0.05)
            s = m.js(STATE_JS)
            tops.append([s["scrollTop"], s["focusedInView"]])
        check(f"{where}: Down comes back to the first row, then moves on as usual", s["at"] == 1, tops)
        m.press(UP)
        return wait(m, lambda s: s["at"] == 0 and s["focusedInView"], 3)

    def picked_refused_then_look_again(self, size):
        """A refused row from the dialog: its words name Y and Browse, and both
        work, even for videos the search would never list."""
        check, m, dialog = self.check, self.m, self.dialog
        where = f"own files picked at {size}"
        home = self.tmp / f"own-picked-{size}"
        make(str(home), ["Films/Alpha/a.mkv", "Films/Beta/b.mkv"])
        self.nowhere[:] = [ff.Place("internal", "Internal storage", str(home))]
        port, settings_file = self.server(parent=home)
        s = self.open(port, size)
        before = settings_file.read_bytes()
        s = self.press_until(DOWN, lambda s: s["kind"] == "browse")
        dialog.answer(home)
        m.press(ENTER)
        s = wait(m, lambda s: s["messages"] and s["kind"] == "folder")
        msg = s["messages"][0] if s["messages"] else {}
        refused = s["id"]
        check(f"{where}: its words name Y and Browse", msg.get("text") == onboarding.OWN_FILES_PICKED
              and "Y Look again" in s["hints"], s)
        # Videos the search will find: Y lists them, and the refused row stays.
        make(str(home), ["Mine/a.mkv"])
        rows = s["rows"]
        m.press("a")
        s = wait(m, lambda s: s["rows"] == rows + 1 and s["id"] == refused)
        check(f"{where}: Y lists the new folder, the focus staying on the refused row",
              s["rows"] == rows + 1 and s["id"] == refused and "Internal storage › Mine" in s["names"], s)
        # Short clips: the search never lists them, as the words allow for.
        make(str(home / "Clips"), ["short.mkv"], size=1000)
        rows = s["rows"]
        m.press("a")
        time.sleep(0.5)
        s = wait(m, lambda s: s["listShown"] and s["id"] == refused)
        check(f"{where}: Y doesn't list short clips", s["rows"] == rows
              and "Internal storage › Clips" not in s["names"], s["names"])
        s = self.press_until(DOWN, lambda s: s["kind"] == "browse")
        dialog.answer(home / "Clips")
        m.press(ENTER)
        s = wait(m, lambda s: s["text"] == "Internal storage › Clips")
        check(f"{where}: Browse reaches them, with no message", s["text"] == "Internal storage › Clips"
              and not s["messages"], s)
        m.press(ENTER)
        s = wait(m, lambda s: s["step"] == "2" and s["at"] >= 0)
        check(f"{where}: they can be chosen", s["step"] == "2" and settings_file.read_bytes() == before, s["step"])
        s = self.press_until(DOWN, lambda s: s["kind"] == "skip")
        m.press(ENTER)
        s = wait(m, lambda s: s["firstScan"], 10)
        check(f"{where}: and saved", s["firstScan"]
              and json.loads(settings_file.read_text())["movies_path"] == str(home / "Clips"), s["firstScan"])
        self.nowhere.clear()

    def own_files_then_look_again(self, size):
        """Videos only at the top of a home folder that holds Kettle: the row's
        words say what to do, and doing it works."""
        check, m = self.check, self.m
        where = f"own files at {size}"
        home = self.tmp / f"own-home-{size}"
        make(str(home), ["loose.mkv"])
        self.nowhere[:] = [ff.Place("internal", "Internal storage", str(home))]
        port, settings_file = self.server(parent=home)
        s = self.open(port, size)
        before = settings_file.read_bytes()
        check(f"{where}: the home folder is offered", s["names"][0] == "Internal storage", s["names"])
        m.press(ENTER)
        s = wait(m, lambda s: s["messages"])
        msg = s["messages"][0] if s["messages"] else {}
        check(f"{where}: A says what to do, in the row, and stays", s["step"] == "1"
              and msg.get("text") == onboarding.OWN_FILES and msg.get("inRow") and settings_file.read_bytes() == before, s)
        self.layout(s, where)
        self.shot("own-files-only", size)
        (home / "Mine").mkdir()
        (home / "loose.mkv").rename(home / "Mine" / "loose.mkv")
        m.press("a")
        s = wait(m, lambda s: s["names"][0] == "Internal storage › Mine" and s["at"] == 0)
        check(f"{where}: Y finds the new folder, focused", s["names"][0] == "Internal storage › Mine" and s["at"] == 0, s)
        m.press(ENTER)
        s = wait(m, lambda s: s["step"] == "2" and s["at"] >= 0)
        check(f"{where}: and it can be chosen", s["step"] == "2", s)
        s = self.press_until(DOWN, lambda s: s["kind"] == "skip")
        m.press(ENTER)
        s = wait(m, lambda s: s["firstScan"], 10)
        check(f"{where}: and it is saved", s["firstScan"]
              and json.loads(settings_file.read_text())["movies_path"] == str(home / "Mine"), s["firstScan"])
        self.nowhere.clear()

    def gap_line(self, size):
        """A card that isn't ready, with a folder found elsewhere."""
        check, m = self.check, self.m
        where = f"card not ready at {size}"
        home = self.tmp / f"home-gap-{size}"
        make(str(home), ["Films/Alpha/a.mkv", "Films/Beta/b.mkv"])
        card = self.tmp / f"card-gap-{size}"
        self.nowhere[:] = [ff.Place("internal", "Internal storage", str(home)), ff.Place("sd", "SD card", str(card))]
        port, settings_file = self.server()
        s = self.open(port, size)
        line = "Kettle found the SD card isn't ready yet, so its folders aren't listed. Press Y to look again."
        check(f"{where}: screen 1 says so above the list", s["step"] == "1" and s["looking"] == line and s["at"] == 0
              and not s["lookingError"], s)
        # At this size, as at a launch in a window this size.
        m.press("a")
        time.sleep(0.3)
        s = wait(m, lambda s: s["listShown"] and s["at"] == 0)
        s = self.read_the_line(s, where, settings_file)
        self.layout(s, where)
        self.shot("card-not-ready", size)
        m.press(ENTER)
        s = wait(m, lambda s: s["step"] == "2" and s["at"] == 0)
        check(f"{where}: screen 2 says so too", s["looking"] == line, s)
        self.read_the_line(s, f"{where}, screen 2", settings_file)
        # The card turns up: the line goes, with the focus kept.
        make(str(card), ["Shows/Gamma/e1.mkv", "Shows/Delta/e1.mkv"])
        m.press("a")
        s = wait(m, lambda s: s["looking"] is None and len(s["bands"]) == 2)
        check(f"{where}: Look again with the card there: the line goes", s["looking"] is None and s["at"] == 0, s)
        self.nowhere.clear()

    def refused_rows(self, size):
        """A row that can't be chosen says why, in the row, and stays."""
        check, m, dialog = self.check, self.m, self.dialog
        where = f"refused rows at {size}"
        port, settings_file = self.server()
        s = self.open(port, size)
        before = settings_file.read_bytes()
        locked = self.tmp / f"Locked-{size}"
        locked.mkdir()
        os.chmod(locked, 0)
        try:
            s = self.press_until(DOWN, lambda s: s["kind"] == "browse")
            dialog.answer(locked)
            m.press(ENTER)
            # The row grows as its message appears and is then scrolled into
            # view: wait for that, not just the message (a flake seen in the Enamel 0.11.0 upgrade).
            s = wait(m, lambda s: s["messages"] and s["kind"] == "folder" and s["messages"][0]["inView"])
            msg = s["messages"][0] if s["messages"] else {}
            check(f"{where}: a folder that can't be read says so in its row, never that it is empty",
                  msg.get("text") == ff.CANT_BE_READ and msg.get("inView") and "Couldn't be read" in s["meta"]
                  and "No videos found" not in s["meta"], s)
            self.layout(s, where)
            self.shot("cant-be-read", size)
            m.press(ENTER)
            time.sleep(0.2)
            s = wait(m, lambda s: s["messages"])
            check(f"{where}: A on it stays on this screen", s["step"] == "1" and s["kind"] == "folder"
                  and s["messages"] and s["messages"][0]["text"] == ff.CANT_BE_READ, s)
            # The folder that holds the settings file: Kettle's own files are inside.
            s = self.press_until(DOWN, lambda s: s["kind"] == "browse")
            dialog.answer(settings_file.parent)
            m.press(ENTER)
            s = wait(m, lambda s: s["messages"] and s["kind"] == "folder")
            msg = s["messages"][0] if s["messages"] else {}
            check(f"{where}: a folder holding Kettle's own files says so in its row, wholly on screen",
                  msg.get("text") == onboarding.OWN_FILES_PICKED and msg.get("inView") and msg.get("inRow"), s)
            self.layout(s, where)
            self.shot("own-files", size)
            m.press(ENTER)
            time.sleep(0.2)
            s = wait(m, lambda s: s["messages"])
            check(f"{where}: A on it stays on this screen, nothing saved", s["step"] == "1"
                  and settings_file.read_bytes() == before, s)
        finally:
            os.chmod(locked, 0o755)

    def plain_list_words(self):
        """The plain list says a skipped kind in the normal words."""
        check, m = self.check, self.m
        port, _ = self.server(movies_path=str(self.places["sd"] / "Films"))
        set_window(m, *SIZES["w1280"])
        with mock.patch.object(server.library_index, "render", side_effect=ValueError("invented")):
            self.visit(port)
            s = wait(m, lambda s: "No folder chosen" in s["statuses"], 10)
        check("the plain list says No folder chosen, not in error style, with no broken sentence",
              "No folder chosen" in s["statuses"] and not any(t.startswith("not set") for t in s["statuses"])
              and s["statusErrors"] == [], s["statuses"])

    def visit(self, port, ending=""):
        # Through a blank page, so an ending in the address is a real load.
        self.m.send("WebDriver:Navigate", {"url": "about:blank"})
        self.m.send("WebDriver:Navigate", {"url": f"http://127.0.0.1:{port}/{ending}"})

    def own_address(self):
        check, m = self.check, self.m
        films = str(self.places["sd"] / "Films")
        port, settings_file = self.server(movies_path=films)
        set_window(m, *SIZES["w1280"])
        self.visit(port)
        s = wait(m, lambda s: s["firstScan"], 20)
        check("with a folder set and no library, the plain address goes straight to the result screen",
              s["firstScan"] and s["step"] == "3", s)
        self.visit(port, "#onboarding")
        s = wait(m, lambda s: s["open"] and s["at"] == 0 and s["listShown"], 20)
        check("the address ending in #onboarding opens the flow even with a folder set",
              s["open"] and s["step"] == "1" and s["at"] == 0, s)
        if not s["open"]:
            return
        m.press(ENTER)
        wait(m, lambda s: s["step"] == "2" and s["at"] == 0)
        m.press(DOWN)
        wait(m, lambda s: s["at"] == 1)
        m.press(ENTER)
        wait(m, lambda s: s["firstScan"], 20)
        m.press(ENTER)  # Open my library
        s = wait(m, lambda s: s["library"] and not s["open"], 10)
        saved = json.loads(settings_file.read_text())
        check("from there a good choice saves and opens Home, with that ending gone from the address",
              s["library"] and not s["open"] and s["hash"] == ""
              and saved["movies_path"] == str(self.places["internal"] / "Videos" / "Collection 01")
              and saved["tv_path"] == str(self.places["internal"] / "Videos" / "Collection 02"), s)

    def scan(self, port):
        request = urllib.request.Request(f"http://127.0.0.1:{port}/api/library/scan", data=b"{}",
                                         headers={"Content-Type": "application/json"})
        urllib.request.urlopen(request, timeout=10).read()
        end = time.time() + 30
        while time.time() < end:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/library/scan/status", timeout=10) as answer:
                status = json.load(answer)
            if status["state"] == "idle":
                break
            time.sleep(0.1)
        return status

    def to_last_step(self, port):
        """Opens the flow and gets to screen 2, on a folder that can be saved."""
        m = self.m
        self.open(port, "w1280")
        m.press(ENTER)
        wait(m, lambda s: s["step"] == "2" and s["at"] == 0)
        m.press(DOWN)
        return wait(m, lambda s: s["at"] == 1)

    def save_with_home_held(self):
        """A on the last step, the scan, then Open my library with Home's answer
        held back: back from here, Home isn't ready yet."""
        self.m.press(ENTER)
        wait(self.m, lambda s: s["firstScan"], 20)
        self.home_open.clear()
        self.m.press(ENTER)
        return wait(self.m, lambda s: not s["open"], 10)

    def second_press(self, key, name):
        """The moment after Open my library (the second onboarding review fixes, moved there by the first scan screen): a
        second press does nothing, and the keys work once Home is ready."""
        check, m = self.check, self.m
        port, settings_file = self.server()
        self.to_last_step(port)
        quits = self.quits
        try:
            s = self.save_with_home_held()
            check(f"{name}: the save is done and Home isn't ready", not s["open"] and not s["firstScan"]
                  and json.loads(settings_file.read_text())["tv_path"] != "", s)
            m.press(key)
            time.sleep(0.4)  # long enough for a wrong answer to come back
            check(f"{name}: nothing quits while Home isn't ready", self.quits == quits, self.quits)
            check(f"{name}: no loading screen in the moment", not m.js(HOME_JS)["loading"], m.js(HOME_JS))
        finally:
            self.home_open.set()
        s = wait(m, lambda s: s["library"], 10)
        time.sleep(0.4)
        home = m.js(HOME_JS)
        check(f"{name}: Home opens with no error", s["library"] and home["error"] is None, home)
        check(f"{name}: the app didn't quit", self.quits == quits, self.quits)
        m.press("q")
        time.sleep(0.3)
        check(f"{name}: once Home is ready, B works on it (its menu opens)", m.js(HOME_JS)["picker"], m.js(HOME_JS))

    def home_stalled(self):
        """Home not answering after the save is never a dead end: past the
        loading screen's 10 seconds it shows, and B quits again (the second onboarding review fixes)."""
        check, m = self.check, self.m
        port, settings_file = self.server()
        self.to_last_step(port)
        quits = self.quits
        try:
            self.save_with_home_held()
            end = time.time() + 15
            home = m.js(HOME_JS)
            while not home["loading"] and time.time() < end:
                time.sleep(0.1)
                home = m.js(HOME_JS)
            check("Home stalled: the loading screen says it is still working", home["loading"] and home["slow"], home)
            m.press(ENTER)
            time.sleep(0.4)
            home = m.js(HOME_JS)
            check("Home stalled: A stays off", home["error"] is None and self.quits == quits, home)
            m.press("q")
            end = time.time() + 5
            while self.quits == quits and time.time() < end:
                time.sleep(0.05)
            check("Home stalled: B quits", self.quits == quits + 1, self.quits)
        finally:
            self.home_open.set()
        s = wait(m, lambda s: s["library"], 10)
        time.sleep(0.2)
        home = m.js(HOME_JS)
        check("Home stalled: when it answers, Home opens with the loading screen gone and no error",
              s["library"] and not home["loading"] and home["error"] is None, home)

    def second_press_with_library(self):
        """Home with a saved library: the same, then the menu and the arrows."""
        check, m = self.check, self.m
        films = str(self.places["sd"] / "Films")
        port, _ = self.server(movies_path=films)
        self.scan(port)
        set_window(m, *SIZES["w1280"])
        self.visit(port, "#onboarding")
        s = wait(m, lambda s: s["open"] and s["at"] == 0 and s["listShown"], 20)
        s = self.press_until(DOWN, lambda s: s["names"][s["at"]] == "SD card › Films")
        m.press(ENTER)
        wait(m, lambda s: s["step"] == "2" and s["at"] == 0)
        quits = self.quits
        try:
            self.save_with_home_held()
            m.press(ENTER)
            m.press("q")
            time.sleep(0.4)
        finally:
            self.home_open.set()
        s = wait(m, lambda s: s["library"], 10)
        time.sleep(0.4)
        home = m.js(HOME_JS)
        check("with a library: A and B in the moment do nothing; Home opens with no error, nothing open",
              s["library"] and home["error"] is None and not home["picker"] and self.quits == quits, (home, self.quits))
        before = home["focus"]
        m.press(DOWN)
        time.sleep(0.2)
        home = m.js(HOME_JS)
        check("with a library: Down moves the focus on Home", home["focus"] != before, (before, home))
        m.press("q")
        time.sleep(0.2)
        home = m.js(HOME_JS)
        check("with a library: B opens Home's menu, and doesn't quit", home["picker"] and self.quits == quits, home)

    def plain_list_after_save(self):
        """Home's fallback, the plain list: the keys work there too."""
        check, m = self.check, self.m
        port, _ = self.server()
        self.to_last_step(port)
        with mock.patch.object(server.library_index, "render", side_effect=ValueError("invented")):
            m.press(ENTER)
            wait(m, lambda s: s["firstScan"], 20)
            m.press(ENTER)  # Open my library
            s = wait(m, lambda s: s["library"], 10)
            time.sleep(0.3)
            before = m.js(HOME_JS)["focus"]
            m.press(DOWN)
            time.sleep(0.2)
            after = m.js(HOME_JS)["focus"]
        check("the plain list after a save: the keys work", s["library"] and before and after and before != after, (before, after))

    def failed_save(self):
        """A failed save leaves the keys working on the onboarding screen."""
        check, m = self.check, self.m
        port, settings_file = self.server()
        s = self.to_last_step(port)
        before = settings_file.read_bytes()
        row = s["at"]
        quits = self.quits
        with mock.patch.object(server.onboarding, "save_folders", side_effect=onboarding.SaveError("invented")):
            m.press(ENTER)
            s = wait(m, lambda s: s["messages"], 10)
            msg = s["messages"][0] if s["messages"] else {}
            check("a failed save: the message in its row, still on screen 2", s["open"] and s["step"] == "2"
                  and s["at"] == row and msg.get("text") == onboarding.SAVE_FAILED
                  and settings_file.read_bytes() == before, s)
            m.press(DOWN)
            s = wait(m, lambda s: s["at"] == row + 1, 5)
            check("a failed save: Down moves on the screen", s["at"] == row + 1, s)
            m.press("q")
            s = wait(m, lambda s: s["step"] == "1", 5)
            check("a failed save: B goes back to screen 1, and doesn't quit", s["step"] == "1" and self.quits == quits, s)
            m.press(ENTER)
            s = wait(m, lambda s: s["step"] == "2" and s["at"] == 0, 5)
            check("a failed save: A goes on to screen 2", s["step"] == "2" and s["at"] == 0, s)
        m.press(DOWN)
        wait(m, lambda s: s["at"] == 1, 5)
        m.press(ENTER)
        s = wait(m, lambda s: s["firstScan"], 10)
        check("a failed save: trying again saves and goes on to the result", s["firstScan"] and settings_file.read_bytes() != before, s)

    def skipped_kind(self):
        check, m = self.check, self.m
        port, _ = self.server(movies_path=str(self.places["sd"] / "Films"))
        status = self.scan(port)
        check("a scan with one kind skipped doesn't call its folder missing",
              status["last_result"].get("ok") and "not available" not in status["last_result"].get("message", ""), status)
        set_window(m, *SIZES["w1280"])
        self.visit(port)
        s = wait(m, lambda s: s["library"] and "No folder chosen" in s["statuses"], 20)
        check('the skipped tab says "No folder chosen", never "Folder not available"',
              "No folder chosen" in s["statuses"] and "Folder not available" not in s["statuses"], s["statuses"])


def run(env, profile, shots_dir, check):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        places = {"internal": tmp / "home-of-someone", "sd": tmp / "CardLabel"}
        make(str(places["internal"]), HOME_FILES)
        make(str(places["sd"]), CARD_FILES)
        media_before = {k: snapshot(str(v)) for k, v in places.items()}
        fake = tmp / "fake-mpv"
        fake.write_text(FAKE_MPV)
        fake.chmod(0o755)
        slow = threading.Event()
        slow.seconds = 2
        nowhere = []
        broken = threading.Event()
        home_open = threading.Event()
        home_open.set()
        real_availability = server.library_index.availability

        def held_availability(roots):
            home_open.wait(20)
            return real_availability(roots)

        def list_places():
            if broken.is_set():
                raise RuntimeError("an invented failed search")
            if slow.is_set():
                time.sleep(slow.seconds)
            if nowhere:
                return [ff.Place(p.kind, p.name, p.root) for p in nowhere]
            return [ff.Place("internal", "Internal storage", str(places["internal"])),
                    ff.Place("sd", "SD card", str(places["sd"]))]

        logged = []
        patches = [mock.patch.object(ff, "list_places", list_places), mock.patch.object(server, "_log", logged.append),
                   mock.patch.object(server.library_index, "availability", held_availability),
                   mock.patch.dict(os.environ)]  # puts PATH and DISPLAY back afterwards
        for patch in patches:
            patch.start()
        mport = free_port()
        (profile / "user.js").write_text(
            f'user_pref("marionette.port", {mport});\n'
            'user_pref("browser.shell.checkDefaultBrowser", false);\n'
            'user_pref("browser.aboutwelcome.enabled", false);\n'
        )
        cmd = ["--headless", "--marionette", FIREFOX_FLAG, "--no-remote", "-profile", str(profile), "about:blank"]
        ff_proc = subprocess.Popen(
            ["firefox", *cmd] if shutil.which("firefox") else ["flatpak", "run", "org.mozilla.firefox", *cmd],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        m = None
        r = None
        try:
            m = Marionette(mport)
            r = Run(tmp, places, m, shots_dir, check, nowhere, broken, home_open)
            # Never a real dialog: from here on, the server finds only this
            # stand-in (Firefox is running already, with its own settings).
            r.dialog = StandIn(tmp / "programs")
            r.dialog.add("kdialog")
            os.environ["PATH"] = str(r.dialog.folder)
            os.environ.pop("DISPLAY", None)
            for size in ("w320", "w1280"):
                r.browse_flow(size)
                r.browse_no_videos(size)
            r.no_dialog()
            for size in SIZES:
                r.flow(size)
                r.no_videos(size)
                r.y_from_no_list(size)
                r.gap_line(size)
                r.refused_rows(size)
                r.own_files_then_look_again(size)
                r.picked_refused_then_look_again(size)
            r.once(slow)
            r.no_videos_once(slow)
            r.own_address()
            r.skipped_kind()
            r.plain_list_words()
            r.second_press(ENTER, "A twice on the last step")
            r.second_press("q", "A then B on the last step")
            r.home_stalled()
            r.second_press_with_library()
            r.plain_list_after_save()
            r.failed_save()
            check("the invented folders are byte-for-byte unchanged",
                  {k: snapshot(str(v)) for k, v in places.items()} == media_before)
            private = [str(tmp), "CardLabel", "home-of-someone", "Alpha", "Collection", "private-parent", "Outside"]
            check("no path or name in the log", not any(p in line for line in logged for p in private), logged)
        finally:
            for patch in patches:
                patch.stop()
            if m is not None:
                try:
                    m.send("Marionette:Quit", {"flags": ["eForceQuit"]})
                except (OSError, RuntimeError, ValueError):
                    pass
            ff_proc.terminate()
            try:
                ff_proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                ff_proc.kill()
            for httpd in (r.servers if r else []):
                httpd.shutdown()
                httpd.server_close()


def main():
    shots_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="onboarding-"))
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
        profile = home / ".var/app/org.mozilla.firefox/data/check-profile-onboarding"
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
