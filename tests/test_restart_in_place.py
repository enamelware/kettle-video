# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""A scripted restart in place (the Update and restart work), through the real launch.sh.

An installed copy of this app (version 0.2.0, made from this folder's own
files) is placed in a temporary home by the real shared update step, and
started by the real launch.sh with a stand-in Firefox: a small script that
does what the page does. It asks for a check, says yes to Update and
restart to 0.3.0, follows the status until a new server answers, then
loads the page again (the window's reload) and reads the note. GitHub is a
stand-in: a sitecustomize module on PYTHONPATH, used only here, answers the
check from a file and "downloads" from a local folder, so nothing goes
online. The real installed copy, its data and ~/.local/share are never
touched.

Checked:
  - the launch process stays alive: launch.sh is the same process from start
    to end, and so is the server it started (the same process number,
    answering again from the new version's folder);
  - the server comes back on the new version (0.3.0), the page loads again
    from it, and says "Updated to 0.3.0" once;
  - the data folder is byte-for-byte unchanged by the update (apart from the
    date of the update check and the first launch's resume carry-over note);
  - with a version that can't start, the update rolls back and the previous
    version restarts in place, saying so.

Run: scripts/test.sh unit tests.test_restart_in_place
"""

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from backend import app_paths, app_update  # noqa: E402
from tests.test_installer import BROKEN_SERVER, snapshot  # noqa: E402

NAME = app_paths.read_names((ROOT / "installer" / "names.env").read_text(encoding="utf-8"))
COPY_FILES = ("launch.sh", "VERSION", "LICENSE", "THIRD_PARTY_LICENSES.md", "README.md")
COPY_FOLDERS = ("backend", "ui", "vendor", "installer")

# Used only by this test, through PYTHONPATH: GitHub's answer and downloads
# from the test's own files.
SITECUSTOMIZE = r'''
import os, shutil, sys
from pathlib import Path
if os.environ.get("KETTLE_TEST_GITHUB"):
    try:
        sys.path.insert(0, os.getcwd())
        import json
        from backend import app_update, update_check
        folder = Path(os.environ["KETTLE_TEST_GITHUB"])
        update_check.fetch_latest = lambda version, timeout=10: json.loads((folder / "release.json").read_text())

        def download(url, dest, user_agent, cancel, progress, limit=0):
            data = (folder / url.rsplit("/", 1)[1]).read_bytes()
            progress(len(data), len(data))
            Path(dest).write_bytes(data)

        app_update.download = download
    except Exception as exc:
        print(f"test stand-in not set up: {exc!r}", file=sys.stderr)
'''

# The window: does what the page does, and writes down what it saw.
FAKE_FIREFOX = r'''#!/usr/bin/env python3
import json, os, sys, time, urllib.request
from pathlib import Path

url = sys.argv[-1].rstrip("/")
out = Path(os.environ["RESTART_TEST_OUT"])
seen = {"launcher": os.getppid()}

def ask(path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url + path, data=data, method="GET" if body is None else "POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as answer:
        raw = answer.read()
    return json.loads(raw) if path.startswith("/api/") else raw.decode()

def server_pid():
    for line in Path(os.environ["RESTART_TEST_LOG"]).read_text().splitlines():
        if "backend pid:" in line:
            return int(line.rsplit(":", 1)[1])

def folder(pid):
    return os.path.realpath(f"/proc/{pid}/cwd")

try:
    ask("/api/mpv-status")
    seen["first_page"] = "<html" in ask("/").lower()
    seen["version_before"] = ask("/api/settings")["version"]
    before = ask("/api/updates/status")
    seen["pid_before"] = server_pid()
    seen["folder_before"] = folder(seen["pid_before"])
    seen["check"] = ask("/api/updates/check", {})
    seen["start"] = ask("/api/updates/install", {"version": "0.3.0"})
    states = []
    end = time.time() + 120
    while time.time() < end:
        time.sleep(0.2)
        try:
            now = ask("/api/updates/status")
        except OSError:
            states.append("away")
            continue
        states.append(now["state"])
        if now["boot"] != before["boot"]:
            break
    seen["states"] = states
    seen["pid_after"] = server_pid()
    seen["pid_alive"] = os.path.exists(f"/proc/{seen['pid_before']}")
    seen["folder_after"] = folder(seen["pid_before"])
    seen["launcher_alive"] = os.path.exists(f"/proc/{seen['launcher']}")
    seen["reloaded_page"] = "<html" in ask("/").lower()
    seen["note"] = ask("/api/updates/note", {})["note"]
    seen["note_again"] = ask("/api/updates/note", {})["note"]
    seen["version_after"] = ask("/api/settings")["version"]
finally:
    out.write_text(json.dumps(seen))
    try:
        ask("/api/shutdown", {})
    except OSError:
        pass
'''


def app_archive(folder, version, server=None):
    """This folder's own app files as a release archive of version, with
    its checksum file beside it."""
    prefix = f"{NAME['ARCHIVE_NAME']}-{version}"
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        def add(rel, data, mode):
            info = tarfile.TarInfo(f"{prefix}/{rel}")
            info.size, info.mode = len(data), mode
            tar.addfile(info, io.BytesIO(data))

        for name in COPY_FILES:
            data = f"{version}\n".encode() if name == "VERSION" else (ROOT / name).read_bytes()
            add(name, data, 0o755 if name.endswith(".sh") else 0o644)
        for top in COPY_FOLDERS:
            for path in sorted((ROOT / top).rglob("*")):
                if path.is_file() and "__pycache__" not in path.parts:
                    rel = str(path.relative_to(ROOT))
                    data = server if (server is not None and rel == "backend/server.py") else path.read_bytes()
                    add(rel, data, 0o755 if os.access(path, os.X_OK) else 0o644)
    archive = Path(folder) / f"{prefix}.tar.gz"
    archive.write_bytes(buffer.getvalue())
    Path(f"{archive}.sha256").write_text(
        f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n")
    return archive


def release_json(version):
    base = app_update.DOWNLOAD_BASE
    name = f"{NAME['ARCHIVE_NAME']}-{version}.tar.gz"
    return {"tag_name": f"v{version}", "body": "- Invented change",
            "assets": [{"name": name, "size": 1, "browser_download_url": f"{base}v{version}/{name}"},
                       {"name": f"{name}.sha256", "size": 1,
                        "browser_download_url": f"{base}v{version}/{name}.sha256"}]}


class RestartInPlace(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.home, bin_dir, site = self.tmp / "home", self.tmp / "bin", self.tmp / "site"
        self.github = self.tmp / "github"
        for folder in (self.home, bin_dir, site, self.github, self.tmp / "Films", self.tmp / "Shows"):
            folder.mkdir()
        (site / "sitecustomize.py").write_text(SITECUSTOMIZE)
        for name, text in (("firefox", FAKE_FIREFOX), ("flatpak", "#!/bin/sh\nexit 1\n")):
            (bin_dir / name).write_text(text)
            (bin_dir / name).chmod(0o755)
        self.places = app_paths.install_places(NAME["APP_ID"], {"HOME": str(self.home)})
        # Version 0.2.0, installed by the real shared step.
        installer = app_update.load_installer(ROOT)
        result = installer.install(app_archive(self.tmp, "0.2.0"), self.places["APP_DIR"],
                                   NAME["INSTALL_MARK"], say=lambda text: None)
        self.assertEqual(result.outcome, "installed", result.message)
        config, self.data = self.places["CONFIG_DIR"], self.places["DATA_DIR"]
        config.mkdir(parents=True)
        self.data.mkdir(parents=True)
        (config / "settings.json").write_text(json.dumps({
            "movies_path": str(self.tmp / "Films"), "tv_path": str(self.tmp / "Shows"),
            "mpv_command": "auto", "mpv_args": [], "resume": False, "keep_awake": False}))
        (self.data / "invented-notes.txt").write_text("an invented file the update must not touch\n")
        (self.github / "release.json").write_text(json.dumps(release_json("0.3.0")))
        self.out = self.tmp / "seen.json"
        self.env = dict(os.environ, HOME=str(self.home), PATH=f"{bin_dir}:{os.environ['PATH']}",
                        PYTHONPATH=str(site), KETTLE_TEST_GITHUB=str(self.github),
                        RESTART_TEST_OUT=str(self.out))
        for name in ("KETTLE_VIDEO_PORT", "KETTLE_VIDEO_LAUNCH_START", "KETTLE_LAUNCH_LOG",
                     "KETTLE_FRESH_START", "KETTLE_PRETEND_NO_MPV", "MOZ_HEADLESS", "XDG_DATA_HOME",
                     "XDG_CONFIG_HOME", "XDG_STATE_HOME", app_update.NOTE_ENV):
            self.env.pop(name, None)

    def launch(self):
        logs = self.places["LOGS_DIR"]
        # The window reads the launch log for the server's process number.
        self.env["RESTART_TEST_LOG"] = str(logs / "launch.log")
        launcher = subprocess.Popen(["bash", str(self.places["APP_DIR"] / "launch.sh")],
                                    cwd=self.home, env={**self.env, "KETTLE_LAUNCH_LOG": str(logs / "launch.log")},
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        output, _ = launcher.communicate(timeout=240)
        log = (logs / "launch.log").read_text()
        self.assertTrue(self.out.exists(), output + log)
        return launcher.returncode, json.loads(self.out.read_text()), log

    def test_update_and_restart_in_place(self):
        app_archive(self.github, "0.3.0")
        before = snapshot(self.data)
        code, seen, log = self.launch()
        self.assertTrue(seen["check"]["can_update"], seen)
        self.assertTrue(seen["start"]["ok"], seen)
        self.assertEqual(seen["version_before"], "0.2.0")
        # The same launcher and the same server process throughout.
        self.assertTrue(seen["launcher_alive"], seen)
        self.assertTrue(seen["pid_alive"], seen)
        self.assertEqual(seen["pid_after"], seen["pid_before"])
        self.assertEqual(log.count("backend pid:"), 1, log)
        self.assertNotIn("backend exited", log.split("restarting in place")[0])
        # Back on the new version, from its own folder; the page loads again.
        new_folder = os.path.realpath(self.places["APP_DIR"])
        self.assertNotEqual(new_folder, seen["folder_before"])
        self.assertEqual(seen["folder_after"], new_folder)
        self.assertEqual(seen["version_after"], "0.3.0")
        self.assertTrue(seen["reloaded_page"])
        self.assertEqual(seen["note"], "Updated to 0.3.0")
        self.assertIsNone(seen["note_again"])
        self.assertIn("installing", seen["states"])
        # Data untouched (the check only keeps its date, before the update).
        after = snapshot(self.data)
        before["update_check.json"] = after.get("update_check.json")
        # The installed copy's first launch notes it has no resume positions
        # to carry over (the each-copy-its-own-data work): nothing else.
        self.assertEqual(after.get("resume_positions.json"), b'{"carry_over": false}\n')
        before["resume_positions.json"] = after["resume_positions.json"]
        self.assertEqual(after, before)
        self.assertEqual(sorted(p.name for p in (self.places["APP_DIR"].parent / "versions").iterdir()),
                         [os.path.basename(new_folder)])
        self.assertIn("update: Updated Kettle Video from 0.2.0 to 0.3.0.", log)
        self.assertEqual(code, 0, log)

    def test_a_version_that_cannot_start_is_rolled_back_and_restarted(self):
        app_archive(self.github, "0.3.0", server=BROKEN_SERVER)
        old_folder = os.path.realpath(self.places["APP_DIR"])
        before = snapshot(self.data)
        code, seen, log = self.launch()
        self.assertTrue(seen["pid_alive"], seen)
        self.assertEqual(seen["pid_after"], seen["pid_before"])
        self.assertEqual(seen["folder_after"], old_folder)
        self.assertEqual(seen["version_after"], "0.2.0")
        self.assertEqual(seen["note"], "The update to 0.3.0 didn't work, so 0.2.0 was put back as it was.")
        after = snapshot(self.data)
        before["update_check.json"] = after.get("update_check.json")
        # The installed copy's first launch notes it has no resume positions
        # to carry over (the each-copy-its-own-data work): nothing else.
        self.assertEqual(after.get("resume_positions.json"), b'{"carry_over": false}\n')
        before["resume_positions.json"] = after["resume_positions.json"]
        self.assertEqual(after, before)
        self.assertEqual(os.path.realpath(self.places["APP_DIR"]), old_folder)
        self.assertEqual(code, 0, log)


if __name__ == "__main__":
    unittest.main()
