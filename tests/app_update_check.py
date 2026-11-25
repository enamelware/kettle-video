# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Update and restart in Settings › About (the Update and restart work), in a real, headless
Firefox, with the controller's keys only. Not part of the unit tests: it
needs Firefox and takes about a minute.

GitHub, the download, the shared update step and the restart are stand-ins
inside the app's server (an invented release 1.1.0): nothing goes online,
nothing is installed. Firefox uses the kiosk profile's own settings from
launch.sh. Invented folders only. Checks:

  - after Check for updates finds 1.1.0: Update and restart under What's
    new, with "About 40 MB" under its label, focused wholly in view at
    every window width, from Enamel's smallest supported box to very wide;
  - A on it: Enamel's picker confirm, "Update to 1.1.0? Kettle Video will
    restart.", Update and restart then Cancel, with Cancel focused first, at
    every width (the focused row in view, nothing cut off); B closes it and
    nothing is downloaded;
  - Up and A: the download starts; Enamel's toast says "Downloading 1.1.0…
    N%", in view above the hint bar at every width, the hint bar says B
    Cancel, and Down does nothing; B cancels: "Update cancelled. Nothing was
    changed." and the keys work again;
  - again, to the end: "Installing…" with no B in the hint bar, then the
    restart: the page loads again by itself and its toast says "Updated to
    1.1.0";
  - a development copy: Pull the latest version under Check for updates,
    its confirm ("Pull the latest version? Kettle Video will restart.",
    Cancel first), and its refusal with local changes in the toast (the
    pull itself is a stand-in: this folder's own git copy is never fetched
    or changed).

Screenshots go to the folder given as the first argument.

Run from the repo root:  python3 tests/app_update_check.py [screenshot-dir]
"""

import base64
import json
import os
import secrets
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

from backend import app_update, library_index, update_check  # noqa: E402
from backend import server as server_module  # noqa: E402
from backend.server import make_handler  # noqa: E402
from tests.kiosk_profile_check import launch_user_js  # noqa: E402
from tests.loading_screen_check import UI_DIR, Marionette, free_port  # noqa: E402
from tests.window_sizes import FIREFOX_FLAG, SIZES, WINDOW, set_window  # noqa: E402

UP, DOWN = "", ""
SPACE, B, START = " ", "q", "m"
BASE = app_update.DOWNLOAD_BASE
RELEASE = {"tag_name": "v1.1.0", "body": "- Invented change",
           "assets": [{"name": "kettle-video-1.1.0.tar.gz", "size": 41_943_040,
                       "browser_download_url": f"{BASE}v1.1.0/kettle-video-1.1.0.tar.gz"},
                      {"name": "kettle-video-1.1.0.tar.gz.sha256", "size": 90,
                       "browser_download_url": f"{BASE}v1.1.0/kettle-video-1.1.0.tar.gz.sha256"}]}

STATE_JS = """
const visible = (el) => el && !el.hidden && !el.closest('[hidden]') && el.getClientRects().length > 0;
const box = (el) => { const r = el.getBoundingClientRect(); return {top: r.top, bottom: r.bottom, left: r.left, right: r.right}; };
const text = (el) => el ? el.textContent.replace(/\\s+/g, ' ').trim() : '';
const settings = document.getElementById('settings');
const menu = document.getElementById('home-menu');
const confirm = document.getElementById('confirm-update');
const toast = document.getElementById('scan-toast');
const hint = document.getElementById('hint-bar');
const active = document.activeElement;
const rows = [...settings.querySelectorAll('.settings-row')];
const updates = [...settings.querySelectorAll('[data-role="updates"] .settings-row')];
const vw = document.documentElement.clientWidth, vh = window.innerHeight;
const cutOff = [...document.querySelectorAll('#settings *, #confirm-update *, #scan-toast *')].filter(e => visible(e))
  .filter(e => { const r = e.getBoundingClientRect(); return r.right > vw + 1 || r.left < -1; })
  .map(e => e.className || e.tagName).slice(0, 5);
const focused = new Set([...document.querySelectorAll('[data-focused="true"]')].filter(e => e.getClientRects().length));
if (active && active !== document.body) focused.add(active);
return {
  marker: window.__beforeRestart === true,
  settings: visible(settings), library: visible(document.getElementById('library')),
  menuOpen: menu.open && !menu.dataset.closing,
  menuFocused: (menu.querySelector('.en-picker__row[data-focused="true"]') || {textContent: ''}).textContent.trim(),
  confirmOpen: confirm.open && !confirm.dataset.closing,
  question: text(confirm.querySelector('[data-role="question"]')),
  confirmRows: [...confirm.querySelectorAll('.en-picker__row')].map(text),
  confirmFocused: active && confirm.contains(active) ? text(active) : null,
  confirmBox: active && confirm.contains(active) ? box(active) : null,
  updates: updates.map(r => ({title: text(r.querySelector('.row-title')),
    lines: [...r.querySelectorAll('.en-row__meta')].filter(visible).map(text)})),
  activeKind: active && active.dataset ? active.dataset.kind || null : null,
  activeIndex: rows.indexOf(active),
  activeBox: active && active !== document.body ? box(active) : null,
  toast: visible(toast) && toast.dataset.closing !== 'true' ? text(toast) : null,
  toastBox: visible(toast) ? box(toast) : null,
  hintTop: box(hint).top, vw, vh,
  hint: hint.innerText.replace(/\\s+/g, ' ').trim(),
  overflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth,
  cutOff, focusedCount: focused.size,
};
"""


def state(m):
    """The page's state; while the page loads again (the restart) there
    may be none for a moment."""
    for _ in range(50):
        try:
            return m.js(STATE_JS)
        except RuntimeError:
            time.sleep(0.1)
    return m.js(STATE_JS)


def wait_state(m, predicate, timeout=5):
    end = time.time() + timeout
    s = state(m)
    while not predicate(s) and time.time() < end:
        time.sleep(0.1)
        s = state(m)
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


def toast_in_view(s):
    b = s["toastBox"]
    return b is not None and b["left"] >= -0.5 and b["right"] <= s["vw"] + 0.5 and b["top"] >= -0.5 \
        and b["bottom"] <= s["hintTop"] + 0.5 and not s["cutOff"]


def to_kind(m, kind):
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


class Stand:
    """The stand-ins: the download waits on a gate; the install waits on
    another; the restart swaps in a new server (a new boot id) with its note."""

    def __init__(self):
        self.download_gate = threading.Event()
        self.install_gate = threading.Event()
        self.downloads = 0
        self.installs = 0

    def download(self, url, dest, agent, cancel, progress, limit=0):
        if url.endswith(".sha256"):
            Path(dest).write_text("0" * 64 + "\n")
            return
        self.downloads += 1
        total = 41_943_040
        progress(total * 4 // 10, total)  # 40%
        while not self.download_gate.wait(0.1):
            if cancel.is_set():
                raise app_update.Cancelled()
        if cancel.is_set():
            raise app_update.Cancelled()
        progress(total, total)
        Path(dest).write_bytes(b"invented")

    def install(self, archive, app_dir, mark, name, **kwargs):
        self.installs += 1
        self.install_gate.wait(30)

        class Result:
            outcome, message = "updated", "Updated."
        return Result()


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
        (tmp / "share").mkdir()
        settings = {"movies_path": str(media / "Films"), "tv_path": str(media / "Shows"),
                    "mpv_command": "mpv", "mpv_args": [], "resume": False, "keep_awake": False,
                    "data_dir": str(app_dir / "data")}
        settings_file = app_dir / "settings.json"
        settings_file.write_text(json.dumps(settings))
        roots = {"movies": settings["movies_path"], "tv": settings["tv_path"]}
        library_index.save(app_dir / "data" / library_index.FILE_NAME,
                           library_index.full_scan(roots, None, lambda d, t: None))

        stand = Stand()
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        port = httpd.server_address[1]

        def handler(note=None):
            ref = {"server": httpd, "update_note": note}
            base = make_handler(UI_DIR, app_dir, dict(settings), ref, port, None, settings_file)

            class Handler(base):
                def log_message(self, format, *args):
                    pass

                def _handle_mpv_status(self):
                    self._send_json(HTTPStatus.OK, {"available": True})
            return Handler

        def restart(ref, root, note):
            # What the restart in place does, as the page sees it: a new
            # server (a new boot id) that has the note for it.
            time.sleep(0.5)
            server_module.BOOT_ID = secrets.token_hex(8)
            httpd.RequestHandlerClass = handler(note)

        development = {"on": False}
        patches = [mock.patch.object(update_check, "is_development", lambda root: development["on"]),
                   mock.patch.object(update_check, "remote_main", lambda root: "0" * 40),
                   mock.patch.object(app_update.Updater, "_pull_main",
                                     lambda self: (app_update.LOCAL_CHANGES, None)),
                   mock.patch.object(update_check, "fetch_latest", lambda version: RELEASE),
                   mock.patch.object(app_update, "installed_app_dir",
                                     lambda root, environ=None: tmp / "share" / "app"),
                   mock.patch.object(app_update, "download", stand.download),
                   mock.patch.object(app_update, "load_installer",
                                     lambda root: type("Installer", (), {"install": staticmethod(stand.install)})),
                   mock.patch.object(server_module, "request_restart", restart)]
        for patcher in patches:
            patcher.start()
        httpd.RequestHandlerClass = handler()
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        mport = free_port()
        (profile / "user.js").write_text(launch_user_js() + f'user_pref("marionette.port", {mport});\n')
        cmd = ["--headless", "--marionette", FIREFOX_FLAG, "--no-remote", "-profile", str(profile), "about:blank"]
        ff = subprocess.Popen(
            ["firefox", *cmd] if shutil.which("firefox") else ["flatpak", "run", "org.mozilla.firefox", *cmd],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        m = None
        try:
            m = Marionette(mport)
            m.send("WebDriver:Navigate", {"url": f"http://127.0.0.1:{port}/"})
            set_window(m, *WINDOW)
            wait_state(m, lambda s: s["library"] and s["activeKind"] == "movie", 30)
            check("no note before any update", m.js(STATE_JS)["toast"] is None)
            press(m, START, lambda s: s["menuOpen"])
            press(m, DOWN, lambda s: s["menuFocused"] == "Settings")
            press(m, SPACE, lambda s: s["settings"] and s["activeIndex"] == 0, 10)
            s = to_kind(m, "update-check")
            s = press(m, SPACE, lambda s: len(s["updates"]) == 3, 10)
            check("the check finds 1.1.0: What's new, then Update and restart with its size",
                  s["updates"][1:] == [{"title": "What's new", "lines": ["Version 1.1.0"]},
                                       {"title": "Update and restart", "lines": ["About 40 MB"]}], s["updates"])

            for size, (w, h) in SIZES.items():
                set_window(m, w, h)
                time.sleep(0.4)
                s = to_kind(m, "update-restart")
                shoot(m, shots_dir, f"update-row-{size}")
                check(f"{size}: Update and restart focused, in view", in_view(s), s)
                s = press(m, SPACE, lambda s: s["confirmOpen"] and s["confirmFocused"])
                shoot(m, shots_dir, f"update-confirm-{size}")
                b = s["confirmBox"]
                check(f"{size}: the confirm asks, Cancel focused first, in view, B Back in the hint bar",
                      s["question"] == "Update to 1.1.0? Kettle Video will restart."
                      and s["confirmRows"] == ["Update and restart", "Cancel"] and s["confirmFocused"] == "Cancel"
                      and b and b["top"] >= -0.5 and b["bottom"] <= s["hintTop"] + 0.5 and not s["cutOff"]
                      and not s["overflowX"], s)
                s = press(m, B, lambda s: not s["confirmOpen"] and s["activeKind"] == "update-restart")
                check(f"{size}: B closes it, back on the row", s["activeKind"] == "update-restart" and in_view(s), s)
            check("nothing downloaded after Cancel", stand.downloads == 0, stand.downloads)

            set_window(m, *WINDOW)
            time.sleep(0.4)
            s = to_kind(m, "update-restart")
            s = press(m, SPACE, lambda s: s["confirmOpen"])
            s = press(m, UP, lambda s: s["confirmFocused"] == "Update and restart")
            s = press(m, SPACE, lambda s: s["toast"] == "Downloading 1.1.0… 40%", 10)
            check("A on Update and restart: the toast says Downloading 1.1.0… 40%, B Cancel in the hint bar",
                  s["toast"] == "Downloading 1.1.0… 40%" and "B CANCEL" in s["hint"].upper()
                  and "SELECT" not in s["hint"].upper(), {k: s[k] for k in ("toast", "hint")})
            for size, (w, h) in SIZES.items():
                set_window(m, w, h)
                time.sleep(0.6)
                s = m.js(STATE_JS)
                shoot(m, shots_dir, f"update-downloading-{size}")
                check(f"{size}: the toast in view above the hint bar", toast_in_view(s) and not s["overflowX"], s)
            set_window(m, *WINDOW)
            s = press(m, DOWN)
            check("Down does nothing while it downloads", s["activeKind"] == "update-restart", s["activeKind"])
            s = press(m, B, lambda s: s["toast"] == "Update cancelled. Nothing was changed.", 10)
            check("B cancels: the toast says so", s["toast"] == "Update cancelled. Nothing was changed.", s["toast"])
            s = press(m, UP, lambda s: s["activeKind"] == "whats-new")
            check("the keys work again", s["activeKind"] == "whats-new" and "SELECT" in s["hint"].upper(), s)
            check("still on the page it was (no restart)", m.js("return document.readyState") == "complete")
            check("nothing installed", stand.installs == 0, stand.installs)

            m.js("window.__beforeRestart = true; return true;")
            s = press(m, DOWN, lambda s: s["activeKind"] == "update-restart")
            s = press(m, SPACE, lambda s: s["confirmOpen"])
            s = press(m, UP, lambda s: s["confirmFocused"] == "Update and restart")
            stand.download_gate.set()
            s = press(m, SPACE, lambda s: s["toast"] == "Installing…", 10)
            shoot(m, shots_dir, "update-installing")
            check("then Installing…, and no B Cancel any more",
                  s["toast"] == "Installing…" and "CANCEL" not in s["hint"].upper(), {k: s[k] for k in ("toast", "hint")})
            s = press(m, B)
            check("B does nothing while installing", s["toast"] == "Installing…" and s["marker"], s["toast"])
            stand.install_gate.set()
            s = wait_state(m, lambda s: not s["marker"] and s["toast"] == "Updated to 1.1.0", 30)
            shoot(m, shots_dir, "update-done")
            check("the restart: the page loads again by itself and says Updated to 1.1.0",
                  not s["marker"] and s["toast"] == "Updated to 1.1.0", {k: s[k] for k in ("marker", "toast")})
            # As at any launch, the focus starts on the selected tab.
            s = wait_state(m, lambda s: s["library"] and s["activeBox"] is not None, 30)
            time.sleep(0.5)
            check("and Home is there", s["library"], s)
            check("one download and one install, from the viewer's yes", (stand.downloads, stand.installs) == (2, 1),
                  (stand.downloads, stand.installs))

            development["on"] = True
            # Home may still be settling after the load: Start until the menu opens.
            for _ in range(10):
                if press(m, START, lambda s: s["menuOpen"], 1)["menuOpen"]:
                    break
            press(m, DOWN, lambda s: s["menuFocused"] == "Settings")
            press(m, SPACE, lambda s: s["settings"] and s["activeIndex"] == 0, 10)
            s = to_kind(m, "update-check")
            s = press(m, SPACE, lambda s: len(s["updates"]) == 2, 10)
            check("a development copy: Pull the latest version under Check for updates",
                  [u["title"] for u in s["updates"]] == ["Check for updates", "Pull the latest version"], s["updates"])
            s = press(m, DOWN, lambda s: s["activeKind"] == "pull-latest")
            s = press(m, SPACE, lambda s: s["confirmOpen"] and s["confirmFocused"])
            shoot(m, shots_dir, "pull-confirm")
            check("its confirm asks, Cancel focused first",
                  s["question"] == "Pull the latest version? Kettle Video will restart."
                  and s["confirmRows"] == ["Pull and restart", "Cancel"] and s["confirmFocused"] == "Cancel", s)
            s = press(m, UP, lambda s: s["confirmFocused"] == "Pull and restart")
            s = press(m, SPACE, lambda s: s["toast"] == app_update.LOCAL_CHANGES, 10)
            shoot(m, shots_dir, "pull-refused")
            check("with local changes it says so plainly and nothing restarts",
                  s["toast"] == app_update.LOCAL_CHANGES and s["activeKind"] == "pull-latest" and s["settings"], s)
        finally:
            stand.download_gate.set()
            stand.install_gate.set()
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
            for patcher in patches:
                patcher.stop()


def main():
    shots_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="app-update-"))
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
