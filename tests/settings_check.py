# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Drive the Settings screen in a real, headless Firefox (the Settings screen work). Not
part of the unit tests: it needs Firefox and takes about a minute.

Invented folders only: Films and Cinema for movies, Shows for TV shows, on an
invented internal storage; a saved library of Films and Shows before the page
opens; its own temporary settings.json. Checks:

  - Home's menu has Settings between Rescan library and Quit; A on it opens
    Settings on the Movies row, with A Select and B Back in the hint bar;
  - at every window width, from Enamel's smallest supported box to very
    wide: both sections are there and readable (their headings, the folder
    rows' place paths, the version and licence notes, every credit row), each
    focused row in turn is wholly in view and clear of the hint bar, the last
    one brings the closing note into view when they fit together, one focused
    row, nothing cut off sideways and no sideways scroll; screenshots;
  - a licence (guessit's, the longest) opens from its row, Down scrolls it
    to its end, its last paragraph readable above the hint bar, at every
    width; B goes back to its row; mpv's row shows its note and link;
  - A on Movies opens onboarding's folder screen for movies only: no step
    label, the current folder focused with its badge, Stop using a movies
    folder last; the TV shows folder refused with its sentence in the row;
    Cinema chosen: back on the Movies row, which now says Internal storage ›
    Cinema, and the toast shows the rescan and its result;
  - Stop using TV shows: TV shows says Not set; then stopping movies too is
    refused with its sentence in the row; B back to Settings;
  - B on Settings goes back to Home with the focus on Menu, and the old
    folder's film shows as Missing.

Screenshots go to the folder given as the first argument.

Run from the repo root:  python3 tests/settings_check.py [screenshot-dir]
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

from backend import app_update, folder_dialog, folder_finder, library_index, settings_screen  # noqa: E402
from backend.server import make_handler  # noqa: E402
from tests.loading_screen_check import UI_DIR, Marionette, free_port  # noqa: E402
from tests.window_sizes import FIREFOX_FLAG, SIZES, WINDOW, set_window  # noqa: E402

UP, DOWN = "", ""
SPACE, B, START = " ", "q", "m"
BIG = 25_000_000  # the folder search lists folders of real-sized videos
# Movies, TV shows, then Check for updates (the never-online work), then the credits.
FIRST_CREDIT = 3

STATE_JS = """
const visible = (el) => el && !el.hidden && !el.closest('[hidden]') && el.getClientRects().length > 0;
const box = (el) => { const r = el.getBoundingClientRect(); return {top: r.top, bottom: r.bottom, left: r.left, right: r.right}; };
const settings = document.getElementById('settings');
const licence = document.getElementById('licence');
const onboarding = document.getElementById('onboarding');
const menu = document.getElementById('home-menu');
const hint = document.getElementById('hint-bar');
const toast = document.getElementById('scan-toast');
const active = document.activeElement;
const focusedSet = new Set([...document.querySelectorAll('[data-focused="true"]')].filter(e => e.getClientRects().length));
if (active && active !== document.body) focusedSet.add(active);
const rows = [...settings.querySelectorAll('.settings-row')];
const text = (el) => el ? el.textContent.replace(/\\s+/g, ' ').trim() : '';
const paragraphs = [...licence.querySelectorAll('[data-role="text"] p')];
// Anything on the page wider than the window, or starting left of it.
const cutOff = [...document.querySelectorAll('#settings *, #licence *, #onboarding *')].filter(e => visible(e))
  .filter(e => { const r = e.getBoundingClientRect(); return r.right > document.documentElement.clientWidth + 1 || r.left < -1; })
  .map(e => e.className || e.tagName).slice(0, 5);
return {
  settings: visible(settings), licence: visible(licence), onboarding: visible(onboarding),
  library: visible(document.getElementById('library')),
  change: onboarding.dataset.change || null,
  step: text(onboarding.querySelector('[data-role="step"]')),
  menuOpen: menu.open && !menu.dataset.closing,
  menuRows: [...menu.querySelectorAll('.en-picker__row')].map(r => r.textContent.trim()),
  menuFocused: (menu.querySelector('.en-picker__row[data-focused="true"]') || {textContent: ''}).textContent.trim(),
  headings: [...settings.querySelectorAll('h1, h2')].map(text),
  rows: rows.map(r => ({title: text(r.querySelector('.row-title')), meta: text(r.querySelector('.en-row__meta'))})),
  notes: [...settings.querySelectorAll('[data-role="about"] .en-note')].map(text),
  endNote: text(settings.querySelector('[data-role="not-affiliated"]')),
  endBox: box(settings.querySelector('[data-role="not-affiliated"]')),
  rowCount: rows.length,
  activeIndex: rows.indexOf(active),
  activeKind: active && active.dataset ? active.dataset.kind || null : null,
  activeText: active && active !== document.body ? text(active) : '',
  activeBox: active && active !== document.body ? box(active) : null,
  message: active ? text(active.querySelector && active.querySelector('.en-row__message')) : '',
  folderRows: [...onboarding.querySelectorAll('.folder-row')].map(text),
  hintTop: box(hint).top,
  hint: hint.innerText.replace(/\\s+/g, ' ').trim(),
  viewportW: document.documentElement.clientWidth,
  viewportH: window.innerHeight,
  scrollY: window.scrollY,
  overflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth,
  cutOff,
  focusedCount: focusedSet.size,
  licenceTitle: text(licence.querySelector('[data-role="title"]')),
  licenceNotes: [...licence.querySelectorAll('.en-note')].map(text),
  paragraphs: paragraphs.length,
  lastParagraph: paragraphs.length ? box(paragraphs[paragraphs.length - 1]) : null,
  toastShown: visible(toast),
  toastText: text(toast.querySelector('.en-toast__text')),
  missingRows: [...document.querySelectorAll('#library .file-row[data-status="missing"]')].length,
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


def clear_of_hint_bar(s):
    b = s["activeBox"]
    return b is not None and b["top"] >= -0.5 and b["bottom"] <= s["hintTop"] + 0.5


def open_settings(m, check):
    s = press(m, START, lambda s: s["menuOpen"])
    check("the menu has Settings between Rescan library and Quit",
          s["menuRows"] == ["Rescan library", "Settings", "Quit", "Cancel"], s["menuRows"])
    s = press(m, DOWN, lambda s: s["menuFocused"] == "Settings")
    s = press(m, SPACE, lambda s: s["settings"] and s["activeIndex"] == 0, 10)
    return s


def check_layout(m, shots_dir, check, credits):
    for size, (w, h) in SIZES.items():
        set_window(m, w, h)
        time.sleep(0.4)
        m.press(UP)  # back to the first row at this size
        for _ in range(len(credits) + FIRST_CREDIT):
            m.press(UP)
        s = wait_state(m, lambda s: s["activeIndex"] == 0)
        shoot(m, shots_dir, f"settings-top-{size}")
        check(f"{size}: Settings opens on Movies, the title and both sections there",
              s["activeIndex"] == 0 and s["headings"] == ["Settings", "Folders", "About"], s["headings"])
        check(f"{size}: the folder rows show place paths", s["rows"][:2] == [
            {"title": "Movies", "meta": "Internal storage › Films"},
            {"title": "TV shows", "meta": "Internal storage › Shows"}], s["rows"][:2])
        check(f"{size}: the version and licence notes",
              s["notes"] == [f"Version {(REPO / 'VERSION').read_text().strip()}", "Licence: GPL-3.0-or-later"], s["notes"])
        check(f"{size}: Check for updates under the version, Last checked never",
              s["rows"][2] == {"title": "Check for updates", "meta": "Last checked: never"}, s["rows"][2])
        check(f"{size}: one row per credit", [r["title"].split(" ")[0] for r in s["rows"][FIRST_CREDIT:]]
              == [c["name"].split(" ")[0] for c in credits], s["rows"][FIRST_CREDIT:])
        for index in range(s["rowCount"]):
            if index:
                s = press(m, DOWN, lambda s, i=index: s["activeIndex"] == i)
            m.settle()
            s = m.js(STATE_JS)
            ok = clear_of_hint_bar(s) and not s["overflowX"] and not s["cutOff"] and s["focusedCount"] == 1
            if not ok or index == s["rowCount"] - 1:
                check(f"{size}: row {index + 1} focused, wholly in view and clear of the hint bar, "
                      "one focus, nothing cut off, no sideways scroll", ok, s)
        room = s["hintTop"]
        fits = s["activeBox"]["bottom"] - s["activeBox"]["top"] + (s["endBox"]["bottom"] - s["activeBox"]["bottom"]) <= room
        check(f"{size}: on the last row, {s['endNote']!r} shows when it fits with it",
              s["endNote"] == settings_screen.NOT_AFFILIATED and (not fits or s["endBox"]["bottom"] <= room + 0.5), s)
        shoot(m, shots_dir, f"settings-end-{size}")


def check_licence(m, shots_dir, check, credits):
    guessit = next(i for i, c in enumerate(credits) if c["name"] == "guessit") + FIRST_CREDIT
    for size, (w, h) in SIZES.items():
        set_window(m, w, h)
        time.sleep(0.4)
        s = m.js(STATE_JS)
        while s["activeIndex"] != guessit:
            s = press(m, DOWN if s["activeIndex"] < guessit else UP)
        s = press(m, SPACE, lambda s: s["licence"] and s["paragraphs"] > 0)
        check(f"{size}: A on guessit shows its licence, B Back and no A in the hint bar",
              s["licence"] and not s["settings"] and s["licenceTitle"] == "guessit 4.4.0"
              and s["paragraphs"] > 20 and "B BACK" in s["hint"] and "SELECT" not in s["hint"], s)
        shoot(m, shots_dir, f"settings-licence-{size}")
        s = press(m, DOWN)
        check(f"{size}: Down scrolls the licence", s["scrollY"] > 0, s["scrollY"])
        last = -1
        for _ in range(40):  # read the page every 20 presses, until it stops moving
            for _ in range(20):
                m.press(DOWN)
            s = m.js(STATE_JS)
            if s["scrollY"] == last:
                break
            last = s["scrollY"]
        check(f"{size}: Down scrolls the licence to its end, its last paragraph above the hint bar",
              s["lastParagraph"]["bottom"] <= s["hintTop"] + 0.5 and s["lastParagraph"]["bottom"] > 0
              and not s["overflowX"] and not s["cutOff"], s)
        shoot(m, shots_dir, f"settings-licence-end-{size}")
        s = press(m, B, lambda s: s["settings"])
        check(f"{size}: B goes back to Settings, on guessit's row",
              s["settings"] and not s["licence"] and s["activeIndex"] == guessit and clear_of_hint_bar(s), s)
    set_window(m, *WINDOW)
    time.sleep(0.4)
    mpv = len(credits) + FIRST_CREDIT - 1
    s = m.js(STATE_JS)
    while s["activeIndex"] != mpv:
        s = press(m, DOWN)
    check("mpv's row says it isn't bundled", s["rows"][mpv]["meta"].endswith("Not bundled"), s["rows"][mpv])
    s = press(m, SPACE, lambda s: s["licence"])
    check("A on mpv shows its note and link instead of a licence text",
          s["licenceTitle"] == "mpv" and s["paragraphs"] == 0
          and s["licenceNotes"][1:] == [settings_screen.NOT_BUNDLED_NOTE, "https://mpv.io/"], s)
    press(m, B, lambda s: s["settings"])


def focus_folder(m, name):
    """Up to the top of the folder list, then Down to the row naming name."""
    for _ in range(8):
        m.press(UP)
    s = m.js(STATE_JS)
    for _ in range(12):
        if name in s["activeText"]:
            break
        s = press(m, DOWN)
    return s


def check_folders(m, shots_dir, check, app):
    s = m.js(STATE_JS)
    while s["activeIndex"] != 0:
        s = press(m, UP)
    s = press(m, SPACE, lambda s: s["onboarding"] and s["folderRows"] and s["activeKind"] == "folder")
    shoot(m, shots_dir, "settings-movies-folder")
    check("A on Movies opens the folder screen for movies only, no step label",
          s["onboarding"] and not s["settings"] and s["change"] == "movies" and s["step"] == "", s)
    check("the current folder is focused, with its badge", "Films" in s["activeText"] and "Movies" in s["activeText"], s)
    check("Stop using a movies folder is last", s["folderRows"][-1].startswith("Stop using a movies folder"), s["folderRows"])
    check("the hint bar says This is my movies folder, Back and Look again",
          "THIS IS MY MOVIES FOLDER" in s["hint"] and "B BACK" in s["hint"] and "Y LOOK AGAIN" in s["hint"], s["hint"])
    s = m.js(STATE_JS)
    s = focus_folder(m, "Shows")
    s = press(m, SPACE, lambda s: s["message"])
    check("the TV shows folder is refused with its sentence in the row",
          s["message"] == settings_screen.SAME_TV and s["onboarding"], s)
    s = focus_folder(m, "Cinema")
    s = press(m, SPACE, lambda s: s["settings"] and s["activeIndex"] == 0, 10)
    check("Cinema chosen: back on the Movies row, which now says Internal storage › Cinema",
          s["settings"] and s["activeIndex"] == 0 and s["rows"][0]["meta"] == "Internal storage › Cinema", s)
    saved = json.loads(app["settings_file"].read_text())
    check("saved under today's keys, the other setting kept",
          saved["movies_path"] == app["cinema"] and saved["tv_path"] == app["shows"] and saved["a_later_setting"] == [1, 2],
          {k: v for k, v in saved.items() if k != "movies_path"})
    s = wait_state(m, lambda s: s["toastShown"], 5)
    check("the toast shows the rescan", s["toastShown"], s)
    s = wait_state(m, lambda s: "added" in s["toastText"], 15)
    check(f"then its result: {s['toastText']!r}", "added" in s["toastText"] and app["scans"] == 1, [s["toastText"], app["scans"]])

    # Stop using TV shows, then movies too: refused.
    s = press(m, DOWN, lambda s: s["activeIndex"] == 1)
    s = press(m, SPACE, lambda s: s["change"] == "tv" and s["folderRows"])
    while not s["activeText"].startswith("Stop using a TV shows folder"):
        s = press(m, DOWN)
    s = press(m, SPACE, lambda s: s["settings"] and s["activeIndex"] == 1, 10)
    check("Stop using a TV shows folder: back on its row, now Not set",
          s["rows"][1]["meta"] == "Not set" and json.loads(app["settings_file"].read_text())["tv_path"] == "", s["rows"][1])
    s = press(m, UP, lambda s: s["activeIndex"] == 0)
    s = press(m, SPACE, lambda s: s["change"] == "movies" and s["folderRows"])
    while not s["activeText"].startswith("Stop using a movies folder"):
        s = press(m, DOWN)
    s = press(m, SPACE, lambda s: s["message"])
    shoot(m, shots_dir, "settings-keep-one")
    check("stopping movies too is refused with its sentence in the row",
          s["message"] == settings_screen.KEEP_ONE["movies"], s)
    s = press(m, B, lambda s: s["settings"])
    check("B on the folder screen goes back to Settings on the Movies row",
          s["settings"] and s["activeIndex"] == 0 and s["rows"][0]["meta"] == "Internal storage › Cinema", s)
    s = press(m, B, lambda s: s["library"], 10)
    check("B on Settings goes back to Home with the focus on Menu",
          s["library"] and not s["settings"] and s["activeKind"] == "menu", s)
    check("the film only in the old folder shows as Missing", s["missingRows"] == 1, s["missingRows"])


def run(env, profile, shots_dir, check):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        media = tmp / "media"
        files = ["Films/Invented Alpha (2001)/Invented Alpha (2001).mkv",
                 "Films/Invented Beta (2002)/Invented Beta (2002).mkv",
                 "Cinema/Invented Alpha (2001)/Invented Alpha (2001).mkv",
                 "Cinema/Invented Delta (2004)/Invented Delta (2004).mkv",
                 "Videos/Shows/Invented Show/Season 1/Invented Show S01E01.mkv",
                 "Videos/Shows/Invented Show/Season 1/Invented Show S01E02.mkv"]
        for rel in files:
            (media / rel).parent.mkdir(parents=True, exist_ok=True)
            with open(media / rel, "wb") as f:
                f.truncate(BIG)
        app_dir = tmp / "app"
        (app_dir / "data").mkdir(parents=True)
        settings = {"movies_path": str(media / "Films"), "tv_path": str(media / "Videos" / "Shows"),
                    "mpv_command": "mpv", "mpv_args": [], "resume": False, "keep_awake": False,
                    "data_dir": str(app_dir / "data")}
        settings_file = app_dir / "settings.json"
        settings_file.write_text(json.dumps({**settings, "a_later_setting": [1, 2]}, indent=2))
        roots = {"movies": settings["movies_path"], "tv": settings["tv_path"]}
        real_scan = library_index.full_scan
        library_index.save(app_dir / "data" / library_index.FILE_NAME, real_scan(roots, None, lambda d, t: None))
        app = {"scans": 0, "settings_file": settings_file, "cinema": str(media / "Cinema"), "shows": roots["tv"]}

        def counted(*args):
            app["scans"] += 1
            time.sleep(1.2)  # long enough for the toast's progress to show
            return real_scan(*args)

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        port = httpd.server_address[1]
        base = make_handler(UI_DIR, app_dir, dict(settings), {"server": httpd}, port, None, settings_file)

        class Handler(base):
            def log_message(self, format, *args):
                pass

            def _handle_mpv_status(self):
                self._send_json(HTTPStatus.OK, {"available": True})

            def _handle_shutdown(self):
                self._send_json(HTTPStatus.OK, {"ok": True})

        httpd.RequestHandlerClass = Handler
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
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
        places = [folder_finder.Place("internal", "Internal storage", str(media))]
        credits = settings_screen.credits(REPO)
        m = None
        try:
            with mock.patch.object(library_index, "full_scan", side_effect=counted), \
                    mock.patch.object(folder_finder, "list_places", lambda: places), \
                    mock.patch.object(folder_dialog, "find", lambda: None), \
                    mock.patch.object(app_update.Updater, "can_switch", lambda self: False):
                # No Try a branch rows: this folder is a development copy, and
                # they would go online (tests/try_branch_check.py has them).
                m = Marionette(mport)
                m.send("WebDriver:Navigate", {"url": f"http://127.0.0.1:{port}/"})
                set_window(m, *WINDOW)
                wait_state(m, lambda s: s["library"] and s["activeKind"] == "movie", 30)
                s = open_settings(m, check)
                check("A on Settings opens it on the Movies row, Home hidden, A Select and B Back",
                      s["settings"] and not s["library"] and s["activeIndex"] == 0
                      and "A SELECT" in s["hint"] and "B BACK" in s["hint"], s)
                check_layout(m, shots_dir, check, credits)
                check_licence(m, shots_dir, check, credits)
                set_window(m, *WINDOW)
                time.sleep(0.4)
                check_folders(m, shots_dir, check, app)
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
    shots_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="settings-"))
    shots_dir.mkdir(parents=True, exist_ok=True)
    results = []

    def check(text, ok, detail=None):
        results.append((text if ok or detail is None else f"{text}: {json.dumps(detail, default=str)}", bool(ok)))

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        home = Path(tmp) / "home"
        env = dict(os.environ, HOME=str(home), MOZ_HEADLESS="1")
        profile = home / ".var/app/org.mozilla.firefox/data/check-profile"
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
