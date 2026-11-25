# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Webview spike (the webview spike): the throwaway virtual environments it creates
inside spikes/webview/ (Route B's .venv-b, Route C's 546 MB .venv-c) stay
git-ignored, so they can never be committed by accident and deleting the
folder removes everything.

Skipped when the spike folder has been deleted (as the report's removal
steps say) or when git is not available.

Run from the repo root:  python3 -m unittest tests.test_webview_spike -v
"""

import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPIKE = ROOT / "spikes" / "webview"


@unittest.skipUnless(SPIKE.is_dir(), "webview spike folder removed")
@unittest.skipUnless(shutil.which("git") and (ROOT / ".git").exists(),
                     "not a git checkout")
class WebviewSpikeVenvIgnored(unittest.TestCase):

    def ignored(self, relative):
        result = subprocess.run(
            ["git", "check-ignore", "-q", "--no-index", relative],
            cwd=ROOT, capture_output=True)
        return result.returncode == 0

    def test_route_venvs_are_ignored(self):
        for venv in (".venv-b", ".venv-c"):
            for inside in ("bin/python", "lib/python3.14/site-packages/x.py",
                           "pyvenv.cfg"):
                path = f"spikes/webview/{venv}/{inside}"
                with self.subTest(path=path):
                    self.assertTrue(self.ignored(path),
                                    f"{path} is not git-ignored")

    def test_venv_used_by_the_shortcut_is_ignored(self):
        # run-webview.sh (the Gaming Mode shortcut) runs Route C's venv;
        # whatever folder it names must be covered by the ignore rule.
        script = (SPIKE / "run-webview.sh").read_text(encoding="utf-8")
        self.assertIn("spikes/webview/.venv-c/bin/python", script)
        self.assertTrue(self.ignored("spikes/webview/.venv-c/bin/python"))

    def test_spike_scripts_are_not_ignored(self):
        # The ignore rule must not swallow the spike's own scripts.
        for name in ("probe.py", "window_gtk.py", "window_pywebview.py",
                     "run-webview.sh", "measure.py", "screenshots.py",
                     "common.py", "quit_check.py", ".gitignore"):
            with self.subTest(name=name):
                self.assertFalse(self.ignored(f"spikes/webview/{name}"))


if __name__ == "__main__":
    unittest.main()
