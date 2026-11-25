# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Kettle check (the server shutdown check): is anything left running after the app closes?

Adapted from the webview spike quitting check (spikes/webview/quit_check.py), for the
real app: launch.sh with Firefox in kiosk mode. Changes no app code. Since
the fix (option A), it also says whether a playing film kept its resume
position and its Continue watching picture.

Each case starts the app exactly as the Steam shortcut does (launch.sh),
waits for Home, optionally plays a film, closes the app one way, waits, and
lists what is left: the app's server, the app's Firefox, mpv, and whether
the server's port still answers. Leftovers are then cleared so the next
case starts clean. Only the app's own Firefox is ever touched (found by its
Flatpak instance), never the user's own browser.

While it runs, mpv saves positions into a temporary folder (a
--watch-later-dir added to settings.json for the run and removed after),
so the real resume positions are never changed; data/continue.json
and data/thumbnails are put back as they were. Media files are only read.

    python3 spikes/kiosk-quit/quit_check.py [CASE ...]
"""

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LAUNCHER = os.path.join(ROOT, "launch.sh")
SETTINGS = os.path.join(ROOT, "settings.json")
DATA = os.path.join(ROOT, "data")
LOG = os.path.join(ROOT, "logs", "quit-check-launch.log")
PORT = 8756
SETTLE = 3  # seconds to wait after the close before looking for leftovers


def sh(args):
    return subprocess.run(args, capture_output=True, text=True).stdout


def flatpak_instances(app):
    """{instance: child_pid} for running Flatpak instances of app."""
    out = sh(["flatpak", "ps", "--columns=instance,child-pid,application"])
    found = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[2] == app:
            found[parts[0]] = int(parts[1])
    return found


def children(pid):
    out = sh(["pgrep", "-P", str(pid)])
    return [int(p) for p in out.split()]


def descendants(pid):
    found, todo = [], [pid]
    while todo:
        for child in children(todo.pop()):
            found.append(child)
            todo.append(child)
    return found


def port_answers(port=PORT):
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def servers():
    out = sh(["pgrep", "-f", "python3 -u -m backend.server"])
    return [int(p) for p in out.split() if int(p) != os.getpid()]


class App:
    """One run of launch.sh and what it started."""

    def __init__(self, firefox_before, mpv_before):
        self.firefox_before = firefox_before
        self.mpv_before = mpv_before
        self.log_start = os.path.getsize(LOG) if os.path.exists(LOG) else 0
        env = dict(os.environ, KETTLE_LAUNCH_LOG=LOG)
        env.pop("KETTLE_VIDEO_PORT", None)
        # Its own session, as Steam gives each game its own process group.
        self.launcher = subprocess.Popen(
            ["bash", LAUNCHER], cwd=ROOT, env=env, start_new_session=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.play_thread = None

    def log(self):
        try:
            with open(LOG, encoding="utf-8", errors="replace") as f:
                f.seek(self.log_start)
                return f.read()
        except FileNotFoundError:
            return ""

    def wait_for(self, text, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if text in self.log():
                return True
            time.sleep(0.2)
        return False

    def port(self):
        for line in self.log().splitlines():
            if "starting backend on port" in line:
                return int(line.rsplit(" ", 1)[1])
        return PORT

    def url(self, path):
        return f"http://127.0.0.1:{self.port()}{path}"

    def firefox_instances(self):
        return {i: p for i, p in flatpak_instances("org.mozilla.firefox").items()
                if i not in self.firefox_before}

    def mpv_instances(self):
        return {i: p for i, p in flatpak_instances("io.mpv.Mpv").items()
                if i not in self.mpv_before}

    def firefox_main_pid(self):
        """Host pid of the app's Firefox main process (inside its sandbox)."""
        for top in self.firefox_instances().values():
            for pid in [top, *descendants(top)]:
                try:
                    with open(f"/proc/{pid}/cmdline", "rb") as f:
                        args = f.read().split(b"\0")
                except OSError:
                    continue
                if args and args[0].endswith(b"/firefox") and b"-contentproc" not in args:
                    return pid
        return None

    def play(self, movie_id):
        def request():
            body = json.dumps({"source": "movies", "id": movie_id}).encode()
            req = urllib.request.Request(self.url("/api/play"), data=body, method="POST",
                                         headers={"Content-Type": "application/json"})
            try:
                urllib.request.urlopen(req, timeout=600).read()
            except Exception:
                pass  # the server may be stopped while mpv plays
        self.play_thread = threading.Thread(target=request, daemon=True)
        self.play_thread.start()
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if self.mpv_instances():
                time.sleep(6)  # let the film actually play for a few seconds
                return True
            time.sleep(0.2)
        return False


def first_movie_id():
    """The first saved film whose file is on the card (only read, never changed)."""
    with open(os.path.join(DATA, "library.json"), encoding="utf-8") as f:
        entry = json.load(f)["sources"]["movies"]
    for item in entry["items"]:
        if item["parts"] and os.path.exists(os.path.join(entry["root"], item["parts"][0]["path"])):
            return item["id"]
    raise SystemExit("No saved film is on the card, so mpv can't be tested.")


# --- ways of closing ------------------------------------------------------

def close_own_quit(app):
    """The app's own Quit (what the Quit item on Home sends)."""
    req = urllib.request.Request(app.url("/api/shutdown"), data=b"{}", method="POST",
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=5).read()


def close_exit_game(app):
    """Like Steam's "Exit game": stop signal to every process the launcher
    started, then a hard kill to whatever is still there after 5 s (Steam's
    reaper does the same with its own children)."""
    tree = [app.launcher.pid, *descendants(app.launcher.pid)]
    for pid in tree:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    time.sleep(5)
    for pid in [app.launcher.pid, *descendants(app.launcher.pid)]:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def close_stop_launcher(app):
    """A stop signal to the launcher alone."""
    os.kill(app.launcher.pid, signal.SIGTERM)


def close_window(app):
    """Close the app's Firefox window as the window's X button does, through
    the desktop's window manager (KWin), picking the window by its process."""
    pid = app.firefox_main_pid()
    script = os.path.join(tempfile.gettempdir(), f"kettle-close-{os.getpid()}.js")
    with open(script, "w") as f:
        f.write("for (const w of workspace.windowList()) {"
                f" if (w.pid === {pid}) w.closeWindow(); }}\n")
    name = f"kettle-close-{os.getpid()}"
    qdbus = shutil.which("qdbus6") or "qdbus"
    script_id = sh([qdbus, "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.loadScript",
                    script, name]).strip()
    sh([qdbus, "org.kde.KWin", f"/Scripting/Script{script_id}", "org.kde.kwin.Script.run"])
    time.sleep(0.5)
    sh([qdbus, "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.unloadScript", name])
    os.remove(script)


def close_kill_firefox(app):
    """Firefox crashes: hard kill of the app's Firefox main process."""
    os.kill(app.firefox_main_pid(), signal.SIGKILL)


def close_kill_launcher(app):
    """The launcher itself crashes: hard kill of launch.sh only."""
    os.kill(app.launcher.pid, signal.SIGKILL)


CLOSES = {
    "own-quit": ("App's own Quit", close_own_quit),
    "exit-game": ('Like Steam "Exit game" (stop signal to all, kill after 5 s)', close_exit_game),
    "stop-launcher": ("Stop signal to the launcher only", close_stop_launcher),
    "close-window": ("Firefox window closed (window manager)", close_window),
    "kill-firefox": ("Firefox killed (pretend crash)", close_kill_firefox),
    "kill-launcher": ("Launcher killed (pretend crash)", close_kill_launcher),
}


# --- bookkeeping ----------------------------------------------------------

def leftovers(app):
    left = []
    if servers():
        left.append("server")
    if app.firefox_instances():
        left.append("Firefox")
    if app.mpv_instances() or sh(["pgrep", "-x", "mpv"]).strip():
        left.append("mpv")
    if port_answers(app.port()):
        left.append(f"port {app.port()} in use")
    if app.launcher.poll() is None:
        left.append("launcher")
    return left


def clear(app):
    for pid in servers():
        os.kill(pid, signal.SIGKILL)
    for instance in [*app.firefox_instances(), *app.mpv_instances()]:
        subprocess.run(["flatpak", "kill", instance], capture_output=True)
    if app.launcher.poll() is None:
        app.launcher.kill()
    app.launcher.wait(timeout=20)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and (servers() or app.firefox_instances()
                                           or app.mpv_instances()):
        time.sleep(0.3)


def position_saved(watch_dir):
    return any(os.scandir(watch_dir))


def empty_dir(path):
    for entry in os.scandir(path):
        os.remove(entry.path)


def picture_saved_since(moment):
    """Did the app keep a Continue watching picture after `moment`? (The
    designer's Gaming Mode feedback on the server shutdown check: none after "Exit game".)"""
    folder = os.path.join(DATA, "thumbnails")
    try:
        return any(e.stat().st_mtime >= moment for e in os.scandir(folder))
    except FileNotFoundError:
        return False


def run_case(key, with_mpv, watch_dir, firefox_before, mpv_before):
    label, close = CLOSES[key]
    empty_dir(watch_dir)
    case_start = time.time()
    app = App(firefox_before, mpv_before)
    try:
        loaded = app.wait_for("page loaded", 40)
        playing = None
        if loaded and with_mpv:
            playing = app.play(first_movie_id())
        started = time.monotonic()
        close(app)
        # How soon the server is gone (looked at every 0.1 s, up to 20 s).
        gone_after = None
        while time.monotonic() - started < 20:
            if not servers():
                gone_after = time.monotonic() - started
                break
            time.sleep(0.1)
        time.sleep(SETTLE)
        left = leftovers(app)
        saved = position_saved(watch_dir) if with_mpv else None
        picture = picture_saved_since(case_start) if with_mpv else None
    finally:
        clear(app)
    return {
        "case": label, "mpv": with_mpv, "home": loaded, "playing": playing,
        "server_gone_s": None if gone_after is None else round(gone_after, 1),
        "left": left, "position_saved": saved, "picture_saved": picture,
    }


def second_start(firefox_before, mpv_before):
    app = App(firefox_before, mpv_before)
    try:
        loaded = app.wait_for("page loaded", 40)
        second = App(firefox_before, mpv_before)
        second.launcher.wait(timeout=20)
        refused = "not starting a second copy" in second.log()
        windows = len(app.firefox_instances())
        still_ok = app.launcher.poll() is None and port_answers(app.port())
        close_own_quit(app)
        app.launcher.wait(timeout=30)
        time.sleep(SETTLE)
        left = leftovers(app)
        third = App(firefox_before, mpv_before)
        third_ok = third.wait_for("page loaded", 40)
        close_own_quit(third)
        third.launcher.wait(timeout=30)
        time.sleep(SETTLE)
        left_third = leftovers(third)
    finally:
        clear(app)
    return {"home": loaded, "second_refused": refused, "firefox_windows": windows,
            "first_still_ok": still_ok, "left_after_quit": left,
            "start_again_ok": third_ok, "left_after_third": left_third}


def main():
    wanted = sys.argv[1:] or list(CLOSES) + ["second-start"]
    if servers():
        raise SystemExit("The app's server is already running; close Kettle first.")
    firefox_before = set(flatpak_instances("org.mozilla.firefox"))
    mpv_before = set(flatpak_instances("io.mpv.Mpv"))
    if mpv_before or sh(["pgrep", "-x", "mpv"]).strip():
        raise SystemExit("mpv is already running; close it first.")

    # Back up what a run could change, and put it back whatever happens.
    work = tempfile.mkdtemp(prefix="kettle-quit-check-")
    watch_dir = os.path.join(work, "watch_later")
    os.makedirs(watch_dir)
    with open(SETTINGS, "rb") as f:
        settings_bytes = f.read()
    shutil.copytree(DATA, os.path.join(work, "data"),
                    ignore=shutil.ignore_patterns("spikes"))
    settings = json.loads(settings_bytes)
    # Start at 1:30: Continue watching keeps only films stopped after a minute.
    settings["mpv_args"] = [*settings.get("mpv_args", []), f"--watch-later-dir={watch_dir}", "--start=90"]
    results = []
    try:
        with open(SETTINGS, "w") as f:
            json.dump(settings, f, indent=2)
        for key in wanted:
            if key == "second-start":
                r = second_start(firefox_before, mpv_before)
                print(json.dumps({"case": "second start", **r}), flush=True)
                continue
            for with_mpv in (False, True):
                r = run_case(key, with_mpv, watch_dir, firefox_before, mpv_before)
                results.append(r)
                print(json.dumps(r), flush=True)
    finally:
        with open(SETTINGS, "wb") as f:
            f.write(settings_bytes)
        backup = os.path.join(work, "data")
        for name in ("continue.json", "library.json"):
            shutil.copy2(os.path.join(backup, name), os.path.join(DATA, name))
        # The server deletes a film's picture when it is stopped early, so
        # the pictures folder is put back whole, not just tidied.
        thumbs = os.path.join(DATA, "thumbnails")
        shutil.rmtree(thumbs)
        shutil.copytree(os.path.join(backup, "thumbnails"), thumbs)
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
