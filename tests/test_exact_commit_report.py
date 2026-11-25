# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""A test report names the commit it is about (the exact-commit report work).

Checks that:
- the workflow's instructions ask the builder for the commit it hands over and
  the quick check's exit code on it, in single and batch mode, and tell the
  reviewer to compare that commit with the branch tip;
- the agents' guard lets the reviewer and test-checker read the branch tip;
- scripts/test.sh keys a remembered pass to the exact code: a changed file or
  a new file that isn't committed changes the key, an ignored file doesn't.

Run: python3 -m unittest tests.test_exact_commit_report
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEXT = os.path.join(ROOT, ".claude", "commands", "next.md")
TIDY = os.path.join(ROOT, ".claude", "commands", "tidy.md")
REVIEWER = os.path.join(ROOT, ".claude", "agents", "reviewer.md")
TEST_CHECKER = os.path.join(ROOT, ".claude", "agents", "test-checker.md")
GUARD = os.path.join(ROOT, ".claude", "hooks", "agent_guard.py")
TEST_SH = os.path.join(ROOT, "scripts", "test.sh")
DECISIONS = os.path.join(ROOT, "docs", "decisions.md")

HANDED_OVER = "Handed over: commit <short commit>, quick check exit code <code>."


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class InstructionsTest(unittest.TestCase):
    def test_single_mode_hand_over(self):
        text = read(NEXT)
        self.assertIn("**Hand-over**", text)
        self.assertIn("git log -1 --format=%h", text)
        self.assertIn("a pass from earlier code doesn't count", text)
        self.assertIn('"Already passed on this exact code" counts as 0', text)

    def test_every_checking_prompt_carries_the_hand_over(self):
        text = read(NEXT)
        prompts = re.findall(r"`Issues? #N[^`]*Check the change on branch issue-N[^`]*`", text)
        self.assertGreaterEqual(len(prompts), 2, "the single-issue and bundle prompts")
        for prompt in prompts:
            self.assertIn(HANDED_OVER, prompt)
        self.assertIn(HANDED_OVER, read(TIDY))

    def test_batch_builder_reply_names_commit_and_exit_code(self):
        text = read(NEXT)
        builder = re.search(r"`You are the builder for Kettle issue #N.*?`\n", text, re.S)
        self.assertIsNotNone(builder)
        self.assertIn("READY FOR CHECKS: commit <short commit>, quick check exit code <code>",
                      builder.group(0))
        self.assertIn("hand-over", builder.group(0))
        fix_round = re.search(r"\*\*Any FAIL\*\*: send the builder.*", text)
        self.assertIn("new commit and exit code", fix_round.group(0))

    def test_reviewer_compares_report_with_branch_tip(self):
        text = read(REVIEWER)
        self.assertIn("git log -1 --format=%h issue-N", text)
        self.assertIn("if the two commits differ, the exit code is missing", text)
        self.assertIn("run the quick check named in your prompt yourself on the branch tip", text)
        self.assertIn("Report check: the report said", text)
        self.assertIn("post that line on the issue", read(NEXT))

    def test_test_checker_names_commit_and_exit_code(self):
        text = read(TEST_CHECKER)
        self.assertEqual(text.count("Quick check: commit <short commit>"), 2,
                         "both the PASS and the FAIL answer")
        self.assertIn("A pass from before your last change doesn't count.", text)

    def test_decision_recorded(self):
        self.assertRegex(read(DECISIONS),
                         r"## \d{4}-\d\d-\d\d — A test report names the commit it is about")


class GuardTest(unittest.TestCase):
    def guard(self, role, command):
        call = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": ROOT}
        env = dict(os.environ, CLAUDE_PROJECT_DIR=ROOT)
        return subprocess.run([sys.executable, GUARD, role], input=json.dumps(call),
                              capture_output=True, text=True, env=env, timeout=10).returncode

    def test_agents_may_read_the_branch_tip_and_run_the_quick_check(self):
        for role in ("reviewer", "test-checker"):
            self.assertEqual(self.guard(role, "git log -1 --format=%h issue-17"), 0, role)
            self.assertEqual(self.guard(role, "scripts/test.sh home_shell_check"), 0, role)
            self.assertEqual(self.guard(role, "scripts/test.sh"), 0, role)


class CodeKeyTest(unittest.TestCase):
    """Runs test.sh's own code_key function in a throwaway git repo."""

    def setUp(self):
        text = read(TEST_SH)
        match = re.search(r"^code_key\(\) \{\n.*?^\}\n", text, re.S | re.M)
        self.assertIsNotNone(match, "code_key() not found in scripts/test.sh")
        self.function = match.group(0)
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name
        self.env = dict(os.environ, HOME=self.repo, GIT_CONFIG_NOSYSTEM="1",
                        GIT_AUTHOR_NAME="Test", GIT_AUTHOR_EMAIL="test@example.invalid",
                        GIT_COMMITTER_NAME="Test", GIT_COMMITTER_EMAIL="test@example.invalid")
        self.git("init", "-q")
        self.write(".gitignore", "ignored.txt\n")
        self.write("film.txt", "An Invented Film\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "start")

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args):
        subprocess.run(["git", "-c", "core.hooksPath=/dev/null", *args], cwd=self.repo,
                       env=self.env, check=True, capture_output=True, timeout=30)

    def write(self, name, text):
        with open(os.path.join(self.repo, name), "w", encoding="utf-8") as f:
            f.write(text)

    def key(self):
        script = self.function + 'RESULTS="$(git rev-parse --git-common-dir)/kettle-test-results"\ncode_key\n'
        out = subprocess.run(["bash", "-c", script], cwd=self.repo, env=self.env,
                             capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        key = out.stdout.strip()
        self.assertRegex(key, r"^[0-9a-f]{40,64}$")
        return key

    def test_same_code_same_key(self):
        self.assertEqual(self.key(), self.key())

    def test_uncommitted_change_changes_the_key(self):
        before = self.key()
        self.write("film.txt", "An Invented Film, changed\n")
        self.assertNotEqual(self.key(), before)
        self.write("film.txt", "An Invented Film\n")
        self.assertEqual(self.key(), before)

    def test_new_uncommitted_file_changes_the_key(self):
        before = self.key()
        self.write("new.txt", "A new file\n")
        self.assertNotEqual(self.key(), before)

    def test_ignored_file_leaves_the_key(self):
        before = self.key()
        self.write("ignored.txt", "Ignored\n")
        self.assertEqual(self.key(), before)

    def test_nothing_is_staged(self):
        self.write("film.txt", "An Invented Film, changed\n")
        self.key()
        staged = subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=self.repo,
                                env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(staged.stdout, "")


if __name__ == "__main__":
    unittest.main()
