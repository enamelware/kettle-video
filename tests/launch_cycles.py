# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Open and quit the whole app several times in a row, the way a person
does with the controller (the start-up fix). Not part of the unit tests: it needs
Firefox and takes about a minute.

Also checks (the saved library work, the Firefox crash fix) that the app still opens after its Firefox
was forced shut (cycle 2 does that; Firefox may then restart itself once at
the next start), and that another Firefox window that is already open stays
open.

Cycle 3 starts with the profile marked as having several unfinished starts,
the state that made Firefox show "closed unexpectedly while starting" and
wait on it instead of opening the app (the saved library work, designer feedback).

It runs on a temporary copy of the app with a temporary home folder and
empty media folders, with Firefox in headless mode (no window), so the real
Firefox profile, settings and media are never touched.

Run from the repo root:  python3 tests/launch_cycles.py [cycles]
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
COPY = ["launch.sh", "backend", "ui", "vendor"]


def wait_for(predicate, timeout):
    end = time.time() + timeout
    while time.time() < end:
        result = predicate()
        if result:
            return result
        time.sleep(0.2)
    return None


def read_log(app):
    logs = sorted((app / "logs").glob("launch-*.log"))
    return logs[-1].read_text() if logs else ""


def start(app, env):
    before = set((app / "logs").glob("launch-*.log"))
    proc = subprocess.Popen(["bash", "launch.sh"], cwd=app, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log = wait_for(lambda: [p for p in (app / "logs").glob("launch-*.log") if p not in before], 10)
    return proc, log[0] if log else None


def quit_app(port):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/shutdown", data=b"{}", method="POST",
        headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=5).read()


def force_close(log_text):
    """Shut the app's Firefox without letting it save, as a crash would."""
    instance = re.search(r"flatpak firefox instance: (\d+)", log_text)
    if instance:
        subprocess.run(["flatpak", "kill", instance.group(1)], capture_output=True)
    else:
        pid = re.search(r"firefox pid: (\d+)", log_text).group(1)
        subprocess.run(["kill", "-9", pid], capture_output=True)


def profile_dir(home):
    if shutil.which("firefox"):
        return home / ".mozilla/kettle-video-profile"
    return home / ".var/app/org.mozilla.firefox/data/kettle-video-profile"


def mark_unfinished_starts(home):
    """Firefox counts starts that never finished in prefs.js; past its
    limit (3) it asks about Safe Mode instead of starting."""
    with (profile_dir(home) / "prefs.js").open("a") as f:
        f.write('user_pref("toolkit.startup.recent_crashes", 5);\n')


def start_bystander(home, env):
    """Another Firefox, like the user's own browser, open during the test."""
    profile = home / "bystander-profile"
    if shutil.which("firefox"):
        cmd = ["firefox", "--no-remote", "--new-instance", "-profile", str(profile), "about:blank"]
    else:
        profile = home / ".var/app/org.mozilla.firefox/data/bystander-profile"
        cmd = ["flatpak", "run", "org.mozilla.firefox", "--no-remote", "-profile", str(profile), "about:blank"]
    profile.mkdir(parents=True)
    subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return profile


def bystander_running(profile):
    out = subprocess.run(["pgrep", "-f", "--", f"-profile {profile}"], capture_output=True, text=True)
    return bool(out.stdout.strip())


def stop_bystander(profile):
    for pid in subprocess.run(["pgrep", "-f", "--", f"-profile {profile}"], capture_output=True, text=True).stdout.split():
        for child in subprocess.run(["pgrep", "-P", pid, "-x", "firefox|firefox-bin"],
                                    capture_output=True, text=True).stdout.split() or [pid]:
            subprocess.run(["kill", child], capture_output=True)
    wait_for(lambda: not bystander_running(profile), 20)


def main(cycles):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        app, home, movies, tv = tmp / "app", tmp / "home", tmp / "Movies", tmp / "TV"
        for d in (app, home, movies, tv):
            d.mkdir()
        (app / "logs").mkdir()
        for name in COPY:
            src = REPO / name
            (shutil.copytree if src.is_dir() else shutil.copy2)(src, app / name)
        (app / "settings.json").write_text(json.dumps(
            {"movies_path": str(movies), "tv_path": str(tv), "mpv_command": "auto", "mpv_args": []}))
        env = dict(os.environ, HOME=str(home), MOZ_HEADLESS="1")
        env.pop("KETTLE_VIDEO_PORT", None)

        failures = 0
        bystander = start_bystander(home, env)
        if not wait_for(lambda: bystander_running(bystander), 10):
            print("could not start the other Firefox window")
            return 1
        time.sleep(3)
        for i in range(1, cycles + 1):
            if i == 3:
                mark_unfinished_starts(home)
            proc, log_path = start(app, env)
            # A real page load is the only proof Firefox opened the app.
            loaded = wait_for(lambda: re.search(r"page loaded ([\d.]+) s", log_path.read_text()), 60)
            port = re.search(r"starting backend on port (\d+)", log_path.read_text()).group(1)

            second_ok = None
            if i == 1:
                # A second launch while the first one runs must not start Firefox.
                second, second_log = start(app, env)
                second.wait(timeout=10)
                text = second_log.read_text()
                second_ok = "not starting a second copy" in text and "firefox pid" not in text

            crash = i == 2 and bool(loaded)
            if crash:
                force_close(log_path.read_text())
            elif loaded:
                quit_app(port)
            proc.wait(timeout=60)
            text = log_path.read_text()
            restarted = "restarted itself" in text.split("page loaded")[0]
            if i == 3:
                # Headless Firefox never asks about Safe Mode, so check the
                # setting that stops a real window from asking is in place.
                user_js = profile_dir(home) / "user.js"
                if 'user_pref("toolkit.startup.max_resumed_crashes", -1);' not in user_js.read_text():
                    print("cycle 3: the Safe Mode question is NOT switched off in user.js")
                    failures += 1
            if crash:
                ok = "firefox exited (or was closed) first" in text
                line = f"cycle {i}: page loaded in {loaded.group(1)} s, firefox forced shut, " \
                       f"app {'stopped' if ok else 'did NOT stop'}"
            else:
                clean = re.search(r"firefox closed cleanly in about ([\d.]+) s", text)
                forced = "forcing it shut" in text
                ok = bool(loaded) and bool(clean) and not forced
                line = f"cycle {i}{' (after unfinished starts)' if i == 3 else ''}: page {'loaded in ' + loaded.group(1) + ' s' if loaded else 'NOT loaded'}"
                line += " (firefox restarted itself first)" if restarted else ""
                line += f", firefox {'closed cleanly in ' + clean.group(1) + ' s' if clean else 'FORCED' if forced else 'close not logged'}"
            failures += not ok
            if second_ok is not None:
                line += f", second launch {'blocked' if second_ok else 'NOT blocked'}"
                failures += not second_ok
            print(line, flush=True)

        survived = bystander_running(bystander)
        print(f"other Firefox window {'still open' if survived else 'CLOSED by the app'}")
        failures += not survived
        stop_bystander(bystander)
        print("all good" if not failures else f"{failures} problem(s)")
        return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 10))
