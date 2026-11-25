# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Commit identity (the commit identity work): the commands in docs/dev-environment.md
("Commit identity", the ones posted for the Nova) set Enamelware and the one
noreply address the release check (the release check work) allows, for this repo only, never
the device-wide git settings. Run in a temporary repo with a temporary home
folder, they make commits authored and committed as that identity and leave
no global git settings behind.

Never reads or changes this clone's or this device's git settings.

Run: scripts/test.sh unit tests.test_commit_identity
"""

import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "dev-environment.md"
sys.path.insert(0, str(ROOT / "tools"))
import release_check  # noqa: E402

NAME = "Enamelware"


def documented_commands():
    """The git commands in the doc's "Commit identity" code block, split."""
    text = DOC.read_text(encoding="utf-8")
    section = re.search(r"^### Commit identity\n(.*?)^### ", text, re.S | re.M)
    assert section, "docs/dev-environment.md has no 'Commit identity' section"
    block = re.search(r"^```\n(.*?)^```", section.group(1), re.S | re.M)
    assert block, "the 'Commit identity' section has no command block"
    return [shlex.split(line) for line in block.group(1).splitlines() if line.strip()]


class DocumentedCommands(unittest.TestCase):

    def setUp(self):
        self.commands = documented_commands()

    def test_they_set_the_name_and_the_noreply_address(self):
        settings = {cmd[-2]: cmd[-1] for cmd in self.commands}
        self.assertEqual(settings, {"user.name": NAME, "user.email": release_check.NOREPLY})

    def test_they_change_this_repo_only(self):
        for cmd in self.commands:
            self.assertEqual(cmd[:3], ["git", "config", "--local"], cmd)
            for scope in ("--global", "--system", "--file", "-f", "--worktree"):
                self.assertNotIn(scope, cmd)

    def test_the_release_check_allows_this_address_and_no_other_account(self):
        self.assertRegex(release_check.NOREPLY, r"^\d+\+enamelware@users\.noreply\.github\.com$")
        self.assertTrue(release_check.ALLOWED_EMAIL.match(release_check.NOREPLY))
        at = "@"
        for other in ("1+enamelware" + at + "users.noreply.github.com",
                      "335260252+someone" + at + "users.noreply.github.com",
                      "enamelware" + at + "users.noreply.github.com",
                      "someone@" + "gmail.com"):
            self.assertIsNone(release_check.ALLOWED_EMAIL.match(other), other)


class InATemporaryRepo(unittest.TestCase):
    """The documented commands run as written in a fresh repo, with a
    temporary home and no system settings, so nothing of this device's is
    read or changed."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        self.env.update(HOME=self.home, XDG_CONFIG_HOME=os.path.join(self.home, ".config"),
                        GIT_CONFIG_NOSYSTEM="1")
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(self.repo)
        self.git("init", "-q", "-b", "main")
        self.git("config", "--local", "commit.gpgsign", "false")
        for cmd in documented_commands():
            subprocess.run(cmd, cwd=self.repo, env=self.env, check=True, capture_output=True)

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, env=self.env, check=True,
                              capture_output=True, text=True).stdout

    def test_a_commit_shows_the_new_identity(self):
        Path(self.repo, "note.txt").write_text("invented\n", encoding="utf-8")
        self.git("add", "note.txt")
        self.git("commit", "-q", "-m", "A test commit")
        shown = self.git("log", "-1", "--format=%an <%ae>%n%cn <%ce>").splitlines()
        expected = f"{NAME} <{release_check.NOREPLY}>"
        self.assertEqual(shown, [expected, expected])

    def test_no_device_wide_setting_is_written(self):
        self.assertFalse(Path(self.home, ".gitconfig").exists())
        self.assertFalse(Path(self.home, ".config", "git", "config").exists())
        local = self.git("config", "--local", "--list")
        self.assertIn("user.name=" + NAME, local)
        self.assertIn("user.email=" + release_check.NOREPLY, local)


if __name__ == "__main__":
    unittest.main()
