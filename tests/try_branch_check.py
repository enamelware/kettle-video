# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Try a branch, Back to main and Restore data in Settings › About (the
"Try a branch" work), on a development copy, in a real, headless Firefox,
with the controller's keys only. Not part of the unit tests: it needs
Firefox and takes about a minute.

git, GitHub's pull request list, the start check and the restart are
stand-ins inside the app's server: nothing goes online, and this folder's
own git copy is never fetched, switched or changed. The backups and the
restore are the real ones, in a temporary data folder with invented
contents. Firefox uses the kiosk profile's own settings from launch.sh.
Checks:

  - on main with no backup: Try a branch (saying it goes online) under
    Check for updates, and neither Back to main nor Restore; opening
    Settings goes online for nothing;
  - A on Try a branch: Enamel's picker with the open pull requests first
    ("#42 · …", the branch under it), then the other branches, then
    Cancel, the focused row in view at every window width, from Enamel's
    smallest supported box to very wide; B closes it;
  - a branch and its confirm ("Switch to #40 · …?", Cancel first); its yes
    backs up the data and restarts: the page loads again and says "Now on
    #40 · Movies detail screen";
  - on the branch: Back to main says which branch and issue, and Restore
    data names the backup's branch and date, both in view at every width;
  - Restore's confirm names the branch and date; with a local change, Back
    to main refuses in plain words and stays on the branch;
  - Back to main restarts on main ("Back on main"); Restore puts the data
    back exactly and says so.

Screenshots go to the folder given as the first argument.

Run from the repo root:  python3 tests/try_branch_check.py [screenshot-dir]
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
from types import SimpleNamespace
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from backend import app_update, library_index, try_branch, update_check  # noqa: E402
from backend import server as server_module  # noqa: E402
from backend.server import make_handler  # noqa: E402
from tests.app_update_check import STATE_JS as UPDATE_STATE_JS  # noqa: E402
from tests.app_update_check import in_view, to_kind  # noqa: E402
from tests.kiosk_profile_check import launch_user_js  # noqa: E402
from tests.loading_screen_check import UI_DIR, Marionette, free_port  # noqa: E402
from tests.window_sizes import FIREFOX_FLAG, SIZES, WINDOW, set_window  # noqa: E402

UP, DOWN = "", ""  # WebDriver's arrow keys
SPACE, B, START = " ", "q", "m"
PULLS = [{"branch": "issue-40", "number": 41, "title": "Movies detail screen"},
         {"branch": "issue-42", "number": 43, "title": "Invented season picker"}]
BRANCHES = ["main", "issue-40", "issue-42", "tidy-words"]

_HEAD, _, _TAIL = UPDATE_STATE_JS.rpartition("\nreturn {")
STATE_JS = _HEAD + "\n" + ("return {" + _TAIL).replace("return {", """
const picker = document.getElementById('branch-picker');
const pickerActive = active && picker.contains(active) ? active : null;
const pickerCut = [...picker.querySelectorAll('*')].filter(e => visible(e))
  .filter(e => { const r = e.getBoundingClientRect(); return r.right > vw + 1 || r.left < -1; }).length;
return {
  pickerOpen: picker.open && !picker.dataset.closing,
  pickerRows: [...picker.querySelectorAll('.en-picker__row')].map(r => [...r.children].map(text).join(' / ')),
  pickerCurrent: [...picker.querySelectorAll('.en-picker__row[aria-current="true"]')].map(r => r.value),
  pickerFocused: pickerActive ? text(pickerActive) : null,
  pickerBox: pickerActive ? box(pickerActive) : null,
  pickerCut,
""", 1)


def state(m):
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
        return state(m)
    return wait_state(m, predicate, timeout)


def shoot(m, shots_dir, name):
    m.settle()
    (shots_dir / f"{name}.png").write_bytes(base64.b64decode(m.send("WebDriver:TakeScreenshot", {})["value"]))


def box_in_view(b, s):
    return b is not None and b["top"] >= -0.5 and b["bottom"] <= s["hintTop"] + 0.5


def snapshot(folder: Path) -> dict:
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in sorted(folder.rglob("*"))
            if p.is_file() and p.relative_to(folder).parts[0] != "backups"}


def open_settings(m):
    for _ in range(10):
        if press(m, START, lambda s: s["menuOpen"], 1)["menuOpen"]:
            break
    press(m, DOWN, lambda s: s["menuFocused"] == "Settings")
    return press(m, SPACE, lambda s: s["settings"] and s["activeIndex"] == 0, 10)


def run(env, profile, shots_dir, check):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        media = tmp / "media"
        for rel in ("Films/Invented Alpha (2001)/Invented Alpha (2001).mkv",
                    "Shows/Invented Show/Season 1/Invented Show S01E01.mkv"):
            (media / rel).parent.mkdir(parents=True, exist_ok=True)
            (media / rel).write_bytes(b"\0")
        app_dir = tmp / "app"
        data = app_dir / "data"
        data.mkdir(parents=True)
        settings = {"movies_path": str(media / "Films"), "tv_path": str(media / "Shows"),
                    "mpv_command": "mpv", "mpv_args": [], "resume": False, "keep_awake": False,
                    "data_dir": str(data)}
        settings_file = app_dir / "settings.json"
        settings_file.write_text(json.dumps(settings))
        roots = {"movies": settings["movies_path"], "tv": settings["tv_path"]}
        library_index.save(data / library_index.FILE_NAME,
                           library_index.full_scan(roots, None, lambda d, t: None))
        (data / "continue.json").write_text('{"invented": "before the switch"}\n')

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        port = httpd.server_address[1]
        copy = {"branch": "main", "local_changes": False, "pull_calls": 0, "online": 0}

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
            time.sleep(0.5)
            server_module.BOOT_ID = secrets.token_hex(8)
            httpd.RequestHandlerClass = handler(note)

        def pulls(version):
            copy["pull_calls"] += 1
            return PULLS

        def remote_branches(root, git):
            copy["online"] += 1
            return BRANCHES

        def ready(root, git, branch, start):
            if copy["local_changes"]:
                raise try_branch.Refused(try_branch.LOCAL_CHANGES)

        def switch_to(root, git, branch, start):
            ready(root, git, branch, start)
            copy["branch"] = branch

        patches = [mock.patch.object(update_check, "is_development", lambda root: True),
                   mock.patch.object(update_check, "remote_main", lambda root: "0" * 40),
                   mock.patch.object(try_branch, "current_branch", lambda root, git: copy["branch"]),
                   mock.patch.object(try_branch, "head", lambda root, git: "0" * 40),
                   mock.patch.object(try_branch, "remote_branches", remote_branches),
                   mock.patch.object(try_branch, "fetch_pulls", pulls),
                   mock.patch.object(try_branch, "fetch_branch", lambda root, git, b: f"origin/{b}"),
                   mock.patch.object(try_branch, "ready", ready),
                   mock.patch.object(try_branch, "switch_to", switch_to),
                   mock.patch.object(app_update, "load_installer", lambda root: SimpleNamespace(
                       started_cleanly=lambda root, environ: (True, ""))),
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
            s = open_settings(m)
            s = to_kind(m, "try-branch")
            check("on main with no backup: Check for updates, then Try a branch saying it goes online",
                  s["updates"] == [{"title": "Check for updates", "lines": ["Last checked: never"]},
                                   {"title": "Try a branch",
                                    "lines": ["Goes online to list the branches on GitHub"]}], s["updates"])
            check("opening Settings went online for nothing", (copy["online"], copy["pull_calls"]) == (0, 0), copy)

            s = press(m, SPACE, lambda s: s["pickerOpen"] and s["pickerFocused"], 10)
            check("A lists: open pull requests first, with issue number and title, then the others, then Cancel",
                  s["pickerRows"] == ["#42 · Invented season picker", "#40 · Movies detail screen",
                                      "tidy-words", "Cancel"], s["pickerRows"])
            check("it went online once, on the viewer's choice", (copy["online"], copy["pull_calls"]) == (1, 1), copy)
            s = press(m, B, lambda s: not s["pickerOpen"] and s["activeKind"] == "try-branch")
            check("B closes it, back on the row", s["activeKind"] == "try-branch", s["activeKind"])

            for size, (w, h) in SIZES.items():
                set_window(m, w, h)
                time.sleep(0.4)
                s = to_kind(m, "try-branch")
                check(f"{size}: Try a branch focused, in view", in_view(s), s)
                s = press(m, SPACE, lambda s: s["pickerOpen"] and s["pickerFocused"], 10)
                s = press(m, DOWN, lambda s: s["pickerFocused"] and s["pickerFocused"].startswith("#40"))
                shoot(m, shots_dir, f"branch-picker-{size}")
                check(f"{size}: the picker's focused row in view, nothing cut off",
                      box_in_view(s["pickerBox"], s) and not s["pickerCut"] and not s["overflowX"], s)
                s = press(m, B, lambda s: not s["pickerOpen"] and s["activeKind"] == "try-branch")

            set_window(m, *WINDOW)
            time.sleep(0.4)
            s = to_kind(m, "try-branch")
            s = press(m, SPACE, lambda s: s["pickerOpen"] and s["pickerFocused"], 10)
            s = press(m, DOWN, lambda s: s["pickerFocused"] and s["pickerFocused"].startswith("#40"))
            s = press(m, SPACE, lambda s: s["confirmOpen"] and s["confirmFocused"], 5)
            shoot(m, shots_dir, "switch-confirm")
            check("a branch, then its confirm: what happens, Cancel focused first",
                  s["question"] == "Switch to #40 · Movies detail screen? Kettle Video backs up your data, "
                                   "then restarts on that branch."
                  and s["confirmRows"] == ["Switch and restart", "Cancel"] and s["confirmFocused"] == "Cancel", s)
            m.js("window.__beforeRestart = true; return true;")
            s = press(m, UP, lambda s: s["confirmFocused"] == "Switch and restart")
            s = press(m, SPACE, lambda s: not s["marker"] and s["toast"] == "Now on #40 · Movies detail screen", 30)
            shoot(m, shots_dir, "switched")
            check("its yes: backed up, switched, the page loads again and says Now on #40",
                  not s["marker"] and s["toast"] == "Now on #40 · Movies detail screen" and copy["branch"] == "issue-40",
                  {k: s[k] for k in ("marker", "toast")})
            backups = try_branch.list_backups(data)
            check("one backup, in the data folder's own backups folder, from main",
                  len(backups) == 1 and backups[0]["from"] == "main" and backups[0]["path"].parent == data / "backups",
                  [b["id"] for b in backups])
            before = snapshot(data)
            when = try_branch.when_text(backups[0])

            s = wait_state(m, lambda s: s["library"] and s["activeBox"] is not None, 30)
            time.sleep(0.5)
            s = open_settings(m)
            s = to_kind(m, "back-to-main")
            check("on the branch: Back to main says which branch and issue; Restore names the branch and date",
                  s["updates"][1:] == [
                      {"title": "Try a branch", "lines": ["Goes online to list the branches on GitHub"]},
                      {"title": "Back to main", "lines": ["Now on #40 · Movies detail screen (issue-40)"]},
                      {"title": "Restore data from before the last switch", "lines": [f"Saved {when}, on main"]}],
                  s["updates"])
            for size, (w, h) in SIZES.items():
                set_window(m, w, h)
                time.sleep(0.4)
                for kind in ("back-to-main", "restore-data"):
                    s = to_kind(m, kind)
                    shoot(m, shots_dir, f"{kind}-{size}")
                    check(f"{size}: {kind} focused, in view", in_view(s), s)
            set_window(m, *WINDOW)
            time.sleep(0.4)

            s = to_kind(m, "restore-data")
            s = press(m, SPACE, lambda s: s["confirmOpen"] and s["confirmFocused"])
            shoot(m, shots_dir, "restore-confirm")
            check("Restore's confirm names the branch and date, Cancel first",
                  s["question"] == f"Put back your data as it was on {when}, on main? Kettle Video will restart."
                  and s["confirmRows"] == ["Restore and restart", "Cancel"] and s["confirmFocused"] == "Cancel", s)
            s = press(m, B, lambda s: not s["confirmOpen"])

            copy["local_changes"] = True
            s = to_kind(m, "back-to-main")
            s = press(m, SPACE, lambda s: s["confirmOpen"] and s["confirmFocused"])
            check("Back to main asks first", s["confirmRows"] == ["Back to main and restart", "Cancel"], s)
            s = press(m, UP, lambda s: s["confirmFocused"] == "Back to main and restart")
            s = press(m, SPACE, lambda s: s["toast"] == try_branch.LOCAL_CHANGES, 10)
            shoot(m, shots_dir, "back-to-main-refused")
            check("with a local change it refuses plainly and stays on the branch",
                  s["toast"] == try_branch.LOCAL_CHANGES and copy["branch"] == "issue-40" and s["settings"], s)
            check("and makes no backup", len(try_branch.list_backups(data)) == 1)
            copy["local_changes"] = False

            # The branch changes the data; Back to main, then Restore.
            (data / "continue.json").write_text('{"invented": "changed on the branch"}\n')
            m.js("window.__beforeRestart = true; return true;")
            s = to_kind(m, "back-to-main")
            s = press(m, SPACE, lambda s: s["confirmOpen"] and s["confirmFocused"])
            s = press(m, UP, lambda s: s["confirmFocused"] == "Back to main and restart")
            s = press(m, SPACE, lambda s: not s["marker"] and s["toast"] == "Back on main", 30)
            check("Back to main restarts on main", s["toast"] == "Back on main" and copy["branch"] == "main", s["toast"])

            (data / "continue.json").write_text('{"invented": "changed on main"}\n')
            s = wait_state(m, lambda s: s["library"] and s["activeBox"] is not None, 30)
            time.sleep(0.5)
            s = open_settings(m)
            s = to_kind(m, "restore-data")
            check("on main: no Back to main, Restore still there",
                  [u["title"] for u in s["updates"]] == ["Check for updates", "Try a branch",
                                                         "Restore data from before the last switch"], s["updates"])
            newest = try_branch.list_backups(data)[0]
            m.js("window.__beforeRestart = true; return true;")
            s = press(m, SPACE, lambda s: s["confirmOpen"] and s["confirmFocused"])
            check("its confirm names the newest backup: from the branch",
                  "on #40 · Movies detail screen" in s["question"], s["question"])
            s = press(m, UP, lambda s: s["confirmFocused"] == "Restore and restart")
            s = press(m, SPACE, lambda s: not s["marker"] and s["toast"]
                      and s["toast"].startswith("Your data is back"), 30)
            shoot(m, shots_dir, "restored")
            check("Restore puts the data back exactly and says so",
                  snapshot(data) == snapshot(newest["path"] / "data")
                  and s["toast"] == f"Your data is back as it was on {try_branch.when_text(newest)}", s["toast"])
            check("the data as it was on the branch, before going back",
                  (data / "continue.json").read_text() == '{"invented": "changed on the branch"}\n'
                  and before != snapshot(data))
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
            for patcher in patches:
                patcher.stop()


def main():
    shots_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="try-branch-"))
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
