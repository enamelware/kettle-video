# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The kiosk window never goes online by itself (the never-online work). Not part of
the unit tests: it needs Firefox and takes about a minute and a half.

It starts the same Firefox launch.sh uses (system or Flatpak), headless,
with a new profile holding exactly the settings launch.sh writes, on the
app's real page served by the app's own server on this device, with
invented folders only. One thing changes: the "dead end" in those settings
(a closed door on this device, port 9) points at a stand-in on this device
instead, which writes down where each request wanted to go and hangs up at
once, as the closed door does. So nothing ever goes online, and we can see
what Firefox tried. Checks:

  - the page opens from the app's own server;
  - for 30 seconds after launch, no Firefox connection of this window
    reaches anything but this device (its sockets are read every quarter
    second, name lookups included);
  - nothing that one of launch.sh's settings switches off was even tried
    (what was tried anyway is printed: it stopped at the closed door);
  - no Terms of Use notice, no bar and no dialog over the page on the first
    launch of the new profile;
  - Firefox closed the way launch.sh closes it, then opened again on the
    same profile: still nothing over the page (no "restore your previous
    session" suggestion), and still nothing reaches anything but this
    device.

Marionette (to read Firefox's own window) is told not to change any
setting, so the window behaves as the app's does.

Run from the repo root:  python3 tests/kiosk_profile_check.py
"""

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from backend import library_index  # noqa: E402
from backend.server import make_handler  # noqa: E402
from tests.loading_screen_check import UI_DIR, Marionette, free_port  # noqa: E402
from tests.window_sizes import FIREFOX_FLAG  # noqa: E402

WATCH_S = 30
SECOND_WATCH_S = 12
DEAD_END_PORT = 9
FLATPAK_ID = "org.mozilla.firefox"

# What the audit on the never-online work saw a fresh profile try, that one of
# launch.sh's settings switches off: none of these may even be tried.
SWITCHED_OFF = (
    "location.services.mozilla.com", "services.addons.mozilla.org",
    "versioncheck-bg.addons.mozilla.org", "addons.mozilla.org",
    "detectportal.firefox.com", "push.services.mozilla.com",
    "normandy.cdn.mozilla.net", "aus5.mozilla.org", "archive.mozilla.org",
    "ciscobinary.openh264.org", "safebrowsing.googleapis.com",
    "incoming.telemetry.mozilla.org", "crash-reports.mozilla.com",
)

# Firefox's own window, read in its chrome: bars over the page (the window's
# and the tab's), open dialogs (the Terms of Use notice is one), windows and
# tabs.
CHROME_JS = """
const win = Services.wm.getMostRecentWindow("navigator:browser");
const notes = [];
for (const box of [win.gNotificationBox, win.gBrowser.getNotificationBox()]) {
  for (const n of (box && box.allNotifications) || []) {
    notes.push(n.getAttribute("value") || n.id || "a bar");
  }
}
const dialogs = [...win.document.querySelectorAll("dialog[open], .dialogOverlay[topmost='true']")]
  .map(d => d.id || d.className || d.tagName);
return {
  notes,
  dialogs,
  windowDialog: Boolean(win.gDialogBox && win.gDialogBox.isOpen),
  windows: [...Services.wm.getEnumerator(null)].length,
  tabs: win.gBrowser.tabs.length,
  url: win.gBrowser.currentURI.spec,
};
"""

SS_LINE = re.compile(r"^(?P<proto>\S+)\s+(?P<state>\S+)\s+\S+\s+\S+\s+(?P<local>\S+)\s+(?P<peer>\S+)\s+users:\((?P<users>.*)\)\s*$")
PID = re.compile(r"pid=(\d+)")


def launch_user_js() -> str:
    """The settings launch.sh writes into the kiosk profile, word for word."""
    text = (REPO / "launch.sh").read_text()
    found = re.search(r"^USER_JS_CONTENTS='(.*?)'$", text, re.S | re.M)
    if not found:
        raise RuntimeError("launch.sh's USER_JS_CONTENTS not found")
    return found.group(1)


def with_stand_in(user_js: str, port: int) -> str:
    """The same settings, the dead end pointing at the stand-in."""
    out = user_js
    for key in ("network.proxy.http_port", "network.proxy.ssl_port"):
        line = f'user_pref("{key}", {DEAD_END_PORT});'
        if out.count(line) != 1:
            raise RuntimeError(f"launch.sh's dead end ({line}) not found")
        out = out.replace(line, f'user_pref("{key}", {port});')
    return out


class StandIn:
    """The closed door, with a notebook: writes down the first line of each
    request (CONNECT host:443, or GET http://host/...) and hangs up."""

    def __init__(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(64)
        self.port = self.sock.getsockname()[1]
        self.seen = []
        self.lock = threading.Lock()
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                conn.settimeout(2)
                try:
                    first = conn.recv(4096).split(b"\r\n", 1)[0].decode("latin-1")
                except OSError:
                    first = "?"
            with self.lock:
                self.seen.append(first)

    def hosts(self):
        with self.lock:
            lines = list(self.seen)
        found = set()
        for line in lines:
            parts = line.split()
            target = parts[1] if len(parts) > 1 else line
            target = re.sub(r"^[a-z]+://", "", target).split("/", 1)[0]
            found.add(target.rsplit(":", 1)[0] if target.count(":") == 1 else target)
        return sorted(found)

    def close(self):
        self.sock.close()


def descendants(root_pid: int) -> set:
    children = {}
    for stat in Path("/proc").glob("[0-9]*/stat"):
        try:
            fields = stat.read_text().rsplit(")", 1)[1].split()
        except OSError:
            continue
        children.setdefault(int(fields[1]), []).append(int(stat.parent.name))
    found, todo = {root_pid}, [root_pid]
    while todo:
        for child in children.get(todo.pop(), []):
            if child not in found:
                found.add(child)
                todo.append(child)
    return found


def on_this_device(address: str) -> bool:
    host = address.rsplit(":", 1)[0].strip("[]").split("%", 1)[0]
    if host in ("*", "0.0.0.0", "::"):
        return True  # not connected anywhere
    # 127.0.0.53 and .54 are the system's name lookup service, which goes
    # online on Firefox's behalf: a name lookup counts as going online.
    if host.startswith("127.0.0.5"):
        return False
    return host.startswith("127.") or host in ("::1", "::ffff:127.0.0.1")


class SocketWatch:
    """Reads the system's socket list every quarter second and keeps every
    connection a process of this Firefox has to anything off this device."""

    def __init__(self, root_pid):
        self.root_pid = root_pid
        self.leaks = []
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        while not self.stop.is_set():
            pids = descendants(self.root_pid())
            out = subprocess.run(["ss", "-tunapH"], capture_output=True, text=True).stdout
            for line in out.splitlines():
                m = SS_LINE.match(line)
                if not m or not pids.intersection(int(p) for p in PID.findall(m["users"])):
                    continue
                if not on_this_device(m["peer"]):
                    entry = f"{m['proto']} {m['state']} to {m['peer']}"
                    if entry not in self.leaks:
                        self.leaks.append(entry)
            self.stop.wait(0.25)

    def finish(self):
        self.stop.set()
        self.thread.join()
        return self.leaks


class Kiosk:
    """The kiosk window, started as launch.sh starts it, closed as it does."""

    def __init__(self, profile, url, env):
        self.flatpak = shutil.which("firefox") is None
        args = ["--headless", "--marionette", FIREFOX_FLAG, "--no-remote", "-profile", str(profile), "-kiosk", url]
        self.sandbox = None
        if self.flatpak:
            read_fd, write_fd = os.pipe()
            self.proc = subprocess.Popen(
                ["flatpak", "run", f"--instance-id-fd={write_fd}", FLATPAK_ID, *args],
                env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, pass_fds=(write_fd,))
            os.close(write_fd)
            with os.fdopen(read_fd) as f:
                self.instance = f.read().strip()
        else:
            self.proc = subprocess.Popen(["firefox", *args], env=env,
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def root_pid(self):
        """The process every process of this window descends from."""
        return self.proc.pid

    def sandbox_pid(self, timeout=10):
        """Flatpak only: the sandbox's top process (0 while it starts)."""
        end = time.time() + timeout
        while not self.sandbox and time.time() < end:
            out = subprocess.run(["flatpak", "ps", "--columns=instance,child-pid"],
                                 capture_output=True, text=True).stdout
            for line in out.splitlines():
                parts = line.split()
                if len(parts) == 2 and parts[0] == self.instance and parts[1].isdigit():
                    self.sandbox = int(parts[1])
            if not self.sandbox:
                time.sleep(0.2)
        return self.sandbox

    def running(self):
        if self.proc.poll() is None:
            return True
        return bool(self.flatpak and self.sandbox and Path(f"/proc/{self.sandbox}").exists())

    def close(self, timeout=15):
        """launch.sh's way: a stop signal to Firefox (inside the sandbox for
        the Flatpak), then wait for it to close its profile properly."""
        if self.flatpak:
            sandbox = self.sandbox_pid()
            if sandbox:
                subprocess.run(["pkill", "-TERM", "-P", str(sandbox), "-x", "firefox|firefox-bin"])
        else:
            self.proc.terminate()
        end = time.time() + timeout
        while self.running() and time.time() < end:
            time.sleep(0.2)
        clean = not self.running()
        if not clean:
            if self.flatpak:
                subprocess.run(["flatpak", "kill", self.instance])
            else:
                self.proc.kill()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        return clean


def chrome_state(m):
    m.send("Marionette:SetContext", {"value": "chrome"})
    try:
        return m.js(CHROME_JS)
    finally:
        m.send("Marionette:SetContext", {"value": "content"})


def nothing_over_page(state):
    return not state["notes"] and not state["dialogs"] and not state["windowDialog"] \
        and state["windows"] == 1 and state["tabs"] == 1


def one_launch(name, profile, user_js, url, env, stand_in, served, watch_s, check):
    mport = free_port()
    (profile / "user.js").write_text(
        with_stand_in(user_js, stand_in.port)
        + f'user_pref("marionette.port", {mport});\n'
        # Marionette would otherwise switch some prompts off by itself.
        + 'user_pref("remote.prefs.recommended", false);\n')
    before = len(served)
    kiosk = Kiosk(profile, url, env)
    watch = SocketWatch(kiosk.root_pid)
    m = None
    try:
        m = Marionette(mport)
        end = time.time() + watch_s
        states = []
        while time.time() < end:
            states.append(chrome_state(m))
            time.sleep(1)
        leaks = watch.finish()
        page = [path for path in served[before:] if path == "/"]
        check(f"{name}: the page opens from the app's own server", bool(page), served[before:])
        check(f"{name}: in {watch_s} s, no connection reaches anything but this device", not leaks, leaks)
        tried = stand_in.hosts()
        stopped = [h for h in tried if any(h == s or h.endswith("." + s) for s in SWITCHED_OFF)]
        check(f"{name}: nothing a setting switches off was tried", not stopped, stopped)
        shown = [s for s in states if not nothing_over_page(s)]
        check(f"{name}: no Terms of Use notice, bar or dialog over the page, one window, one tab",
              not shown, shown[:2])
        return tried
    finally:
        if not watch.stop.is_set():
            watch.finish()
        if m is not None:
            m.sock.close()
        check(f"{name}: Firefox closes cleanly the way launch.sh closes it", kiosk.close())


def run(check, user_js=None):
    user_js = launch_user_js() if user_js is None else user_js
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        tmp = Path(tmp)
        home = tmp / "home"
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
        served = []
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        port = httpd.server_address[1]
        base = make_handler(UI_DIR, app_dir, dict(settings), {"server": httpd}, port, None, settings_file)

        class Handler(base):
            def log_message(self, format, *args):
                pass

            def do_GET(self):
                served.append(self.path)
                return super().do_GET()

            def _handle_mpv_status(self):
                self._send_json(HTTPStatus.OK, {"available": True})

        httpd.RequestHandlerClass = Handler
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        stand_in = StandIn()
        env = dict(os.environ, HOME=str(home), MOZ_HEADLESS="1")
        profile = home / ".var/app/org.mozilla.firefox/data/kettle-video-profile"
        if shutil.which("firefox"):
            profile = home / ".mozilla/kettle-video-profile"
        profile.mkdir(parents=True)
        url = f"http://127.0.0.1:{port}/"
        try:
            first = one_launch("first launch, new profile", profile, user_js, url, env,
                               stand_in, served, WATCH_S, check)
            second = one_launch("second launch, same profile", profile, user_js, url, env,
                                stand_in, served, SECOND_WATCH_S, check)
            return sorted(set(first) | set(second))
        finally:
            stand_in.close()
            httpd.shutdown()
            httpd.server_close()


def main():
    results = []

    def check(text, ok, detail=None):
        results.append((text if ok or detail is None else f"{text}: {json.dumps(detail, default=str)}", bool(ok)))

    tried = []
    try:
        tried = run(check)
    except Exception as exc:
        results.append((f"could not run ({exc!r})", False))
    for text, ok in results:
        print(f"{'ok  ' if ok else 'FAIL'} {text}")
    print("tried anyway, stopped at the closed door on this device: " + (", ".join(tried) or "nothing"))
    failures = sum(not ok for _, ok in results)
    print("all good" if not failures else f"{failures} problem(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
