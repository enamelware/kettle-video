# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Where launch.sh writes its logs (the installer work, the designer's yes on the issue).

launch.sh asks the app (python3 -m backend.app_paths logs) where the logs
go: logs/ in a development copy, as before; the logs folder in the home
folder's state place (XDG_STATE_HOME, else ~/.local/state) for an installed
copy, the one with the installer's mark file; logs/ again if the answer
can't be worked out. The launch log, the Firefox log and the lock that
stops a second copy all go there.

Each test runs the real launch.sh on a temporary copy of the app with a
temporary home folder and a stand-in Firefox that opens the app and quits;
the real logs, Firefox profiles and settings are never touched.

Run: scripts/test.sh unit tests.test_launch_logs
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from backend import app_paths  # noqa: E402

COPY = ["launch.sh", "backend", "ui", "vendor", "installer"]
NAME = app_paths.read_names((ROOT / "installer" / "names.env").read_text(encoding="utf-8"))

# Opens the app the way the page does, then quits it.
FAKE_FIREFOX = r'''#!/usr/bin/env python3
import json, sys, urllib.request
url = sys.argv[-1].rstrip("/")
json.load(urllib.request.urlopen(url + "/api/mpv-status", timeout=10))
req = urllib.request.Request(url + "/api/shutdown", data=b"{}", method="POST",
                             headers={"Content-Type": "application/json"})
urllib.request.urlopen(req, timeout=10).read()
'''


class LaunchLogs(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.app, bin_dir, self.home = self.tmp / "app", self.tmp / "bin", self.tmp / "home"
        for folder in (self.app, bin_dir, self.home, self.tmp / "Films", self.tmp / "Shows"):
            folder.mkdir()
        for name in COPY:
            source = ROOT / name
            if source.is_dir():
                shutil.copytree(source, self.app / name,
                                ignore=shutil.ignore_patterns("__pycache__"))
            else:
                shutil.copy2(source, self.app / name)
        for name, text in (("firefox", FAKE_FIREFOX), ("flatpak", "#!/bin/sh\nexit 1\n")):
            (bin_dir / name).write_text(text)
            (bin_dir / name).chmod(0o755)
        self.env = dict(os.environ, HOME=str(self.home), PATH=f"{bin_dir}:{os.environ['PATH']}")
        for name in ("KETTLE_VIDEO_PORT", "KETTLE_VIDEO_LAUNCH_START", "KETTLE_DEV_UPDATE",
                     "KETTLE_LAUNCH_LOG", "MOZ_HEADLESS", "XDG_DATA_HOME", "XDG_CONFIG_HOME",
                     "XDG_STATE_HOME"):
            self.env.pop(name, None)
        self.settings = json.dumps({"movies_path": str(self.tmp / "Films"),
                                    "tv_path": str(self.tmp / "Shows"),
                                    "mpv_command": "auto", "mpv_args": []})

    def launch(self, logs):
        proc = subprocess.run(["bash", "launch.sh"], cwd=self.app, env=self.env,
                              capture_output=True, text=True, timeout=60)
        launch_logs = sorted(logs.glob("launch-*.log"))
        self.assertEqual(len(launch_logs), 1, f"one launch log in {logs}")
        text = launch_logs[0].read_text()
        self.assertEqual(proc.returncode, 0, text)
        self.assertIn("page loaded", text)
        self.assertEqual(len(list(logs.glob("firefox-*.log"))), 1, "the Firefox log beside it")
        self.assertTrue((logs / "launch.lock").exists(), "the lock beside it")
        return text

    def install_mark(self):
        (self.app / NAME["INSTALL_MARK"]).write_text("installed\n")

    def test_a_development_copy_logs_to_its_own_logs_folder(self):
        (self.app / "settings.json").write_text(self.settings)
        self.launch(self.app / "logs")
        self.assertFalse((self.home / ".local").exists(), "nothing in the home folder's places")

    def test_an_installed_copy_logs_to_the_state_folder(self):
        self.install_mark()
        state = self.tmp / "state"
        self.env["XDG_STATE_HOME"] = str(state)
        config = self.home / ".config" / NAME["APP_ID"]
        config.mkdir(parents=True)
        (config / "settings.json").write_text(self.settings)
        logs = state / NAME["APP_ID"] / "logs"
        self.launch(logs)
        self.assertFalse((self.app / "logs").exists(), "nothing inside the app files")
        self.assertTrue(any(logs.iterdir()), "the logs folder holds the logs")

    def test_an_installed_copy_without_xdg_uses_local_state(self):
        self.install_mark()
        config = self.home / ".config" / NAME["APP_ID"]
        config.mkdir(parents=True)
        (config / "settings.json").write_text(self.settings)
        self.launch(self.home / ".local" / "state" / NAME["APP_ID"] / "logs")
        self.assertFalse((self.app / "logs").exists())

    def test_logs_folder_when_the_helper_fails(self):
        # The app still imports app_paths; only its command fails.
        helper = self.app / "backend" / "app_paths.py"
        text = helper.read_text()
        self.assertIn('if __name__ == "__main__":\n    sys.exit(main())', text)
        helper.write_text(text.replace('if __name__ == "__main__":\n    sys.exit(main())',
                                       'if __name__ == "__main__":\n    sys.exit(3)'))
        (self.app / "settings.json").write_text(self.settings)
        self.launch(self.app / "logs")


if __name__ == "__main__":
    unittest.main()
