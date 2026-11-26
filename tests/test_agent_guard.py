# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Tests for the project agents' guard, .claude/hooks/agent_guard.py (the agent guard fixes;
test-writer and refactor-scout added with the idle-work fallback).

Each test feeds the hook a tool call as JSON, exactly as Claude Code does,
and checks whether it lets it through (exit 0) or refuses it (exit 2).

Run: python3 -m unittest tests.test_agent_guard
"""

import fnmatch
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUARD = os.path.join(ROOT, ".claude", "hooks", "agent_guard.py")
AGENTS = os.path.join(ROOT, ".claude", "agents")
PEEK = os.path.join(ROOT, "scripts", "peek.sh")


def run_guard(role, tool, tool_input, project=ROOT):
    call = {"tool_name": tool, "tool_input": tool_input, "cwd": project}
    env = dict(os.environ, CLAUDE_PROJECT_DIR=project)
    result = subprocess.run(
        [sys.executable, GUARD, role],
        input=json.dumps(call),
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    return result.returncode


def bash(role, command):
    return run_guard(role, "Bash", {"command": command})


READ_ONLY_ALLOWED = [
    "git status",
    "git status --porcelain",
    "git status --short --branch",
    "git diff",
    "git diff main",
    "git diff main --stat",
    "git diff main -- tests/test_parser.py",
    "git diff --cached --name-only",
    "git diff -U10 main",
    "git log",
    "git log main..HEAD",
    "git log --oneline -5",
    "git log -n 3 --format=%h",
    'git log --format="%h %s" main..HEAD',
    "git log --stat main..HEAD",
    "git show HEAD",
    "git show HEAD --stat",
    "git show main:CLAUDE.md",
    "gh issue view 30",
    "gh issue view 30 --comments",
    "gh issue view 30 --json body,comments",
    "gh issue view 30 --json title,body,comments,labels",
]

REFUSED_FOR_BOTH = [
    # Options that write a file or run another program.
    "git diff --output=/tmp/x",
    "git diff main --output=CLAUDE.md",
    "git log --output=/tmp/x",
    "git show --output=/tmp/x HEAD",
    "git diff --out=/tmp/x",  # git accepts this abbreviation of --output
    "git diff --output /tmp/x",  # the value as a separate word
    "git diff -po",  # short options glued together
    "git diff --ext-diff",
    "git log -p --ext-diff",
    "git diff --textconv",
    "git diff --no-index /etc/passwd README.md",
    "git diff -o /tmp/x",
    # Global git options before the subcommand.
    "git -c diff.external=sh diff",
    "git -C /tmp status",
    # Other git commands.
    "git commit -m x",
    "git push",
    "git checkout main",
    "git restore CLAUDE.md",
    # Chaining, redirection and shell expansion.
    "git status; rm -rf tests",
    "git status && git push",
    "git log | head",
    "git diff > out.txt",
    "git diff $(echo --output=x)",
    "git diff `echo --output=x`",
    "git diff $OPT",
    "git diff {--output=x,main}",
    "git diff \\--output=x",
    "git diff -*",
    'git log --format="%h" "unclosed',
    # gh beyond reading one issue.
    "gh issue view 30 --web",
    "gh issue view 30 --json body,comments --jq .body",
    "gh issue view 30 --json body,assignees,secret",
    "gh issue view abc",
    "gh issue comment 30 --body x",
    "gh issue edit 30 --add-label blocked",
    "gh api repos/x/y/issues/30",
    # Anything else.
    "ls",
    "cat CLAUDE.md",
    "python3 -c 'print(1)'",
    "",
]

ALL_ROLES = ("reviewer", "test-checker", "test-writer", "refactor-scout")

ISSUE_LISTS_ALLOWED = [
    "gh issue list",
    "gh issue list --state open",
    "gh issue list --state all --label refactor --limit 200",
    "gh issue list --state open --json number,title,labels,body --limit 100",
]

ISSUE_LISTS_REFUSED = [
    "gh issue list --web",
    "gh issue list --json number,assignees",
    "gh issue list --json number --jq .[]",
    "gh issue list --state merged",
    "gh issue list --label",
    "gh issue list --limit lots",
    "gh issue list --repo someone/else",
    "gh issue list --search x",
]

TEST_RUNNERS = [
    "scripts/test.sh",
    "scripts/test.sh unit tests.test_parser",
    "scripts/test.sh check held_key_check",
    "scripts/test.sh checks",
    "scripts/test.sh all",
    "scripts/test.sh quick",
    "scripts/test.sh quick home_shell_check held_key_check",
    "scripts/test.sh home_shell_check",
    "scripts/test.sh --again",
    "scripts/test.sh full",
    "scripts/test.sh full --again",
    "python3 -m unittest discover -s tests -t .",
    "python3 -m unittest tests.test_parser",
    "python3 -m tests.held_key_check",
    "python3 tests/held_key_check.py",
]


class ReadOnlyCommands(unittest.TestCase):
    def test_allowed_for_every_agent(self):
        for role in ALL_ROLES:
            for command in READ_ONLY_ALLOWED:
                with self.subTest(role=role, command=command):
                    self.assertEqual(bash(role, command), 0)

    def test_refused_for_every_agent(self):
        for role in ALL_ROLES:
            for command in REFUSED_FOR_BOTH + ISSUE_LISTS_REFUSED:
                with self.subTest(role=role, command=command):
                    self.assertEqual(bash(role, command), 2)


class IssueLists(unittest.TestCase):
    def test_test_writer_and_scout_may_list_issues(self):
        for role in ("test-writer", "refactor-scout"):
            for command in ISSUE_LISTS_ALLOWED:
                with self.subTest(role=role, command=command):
                    self.assertEqual(bash(role, command), 0)

    def test_checking_agents_may_not_list_issues(self):
        for role in ("reviewer", "test-checker"):
            for command in ISSUE_LISTS_ALLOWED:
                with self.subTest(role=role, command=command):
                    self.assertEqual(bash(role, command), 2)

    def test_no_agent_may_create_or_change_issues(self):
        for role in ALL_ROLES:
            for command in (
                "gh issue create --title x --body y",
                "gh issue edit 30 --add-label refactor",
                "scripts/board.sh add 30",
                "gh label create refactor",
            ):
                with self.subTest(role=role, command=command):
                    self.assertEqual(bash(role, command), 2)


class TestRunners(unittest.TestCase):
    def test_test_checker_and_writer_may_run_tests(self):
        for role in ("test-checker", "test-writer"):
            for command in TEST_RUNNERS:
                with self.subTest(role=role, command=command):
                    self.assertEqual(bash(role, command), 0)

    def test_reviewer_may_run_tests(self):
        # Since sizes scale the checks, the reviewer runs the quick check itself.
        for command in TEST_RUNNERS:
            with self.subTest(command=command):
                self.assertEqual(bash("reviewer", command), 0)

    def test_scout_may_not_run_tests(self):
        for role in ("refactor-scout",):
            for command in TEST_RUNNERS:
                with self.subTest(role=role, command=command):
                    self.assertEqual(bash(role, command), 2)

    def test_test_runners_cannot_chain_or_expand(self):
        for command in (
            "python3 -m unittest; git push",
            "python3 -m unittest $X",
            "python3 tests/x.py > CLAUDE.md",
            "python3 backend/server.py",
            "python3 -m backend.scanner",
            "python3 tests/../backend/server.py",
            "python3 -m tests.x; rm -rf ui",
            "scripts/test.sh; git push",
            "scripts/test.sh check ../backend/server",
            "scripts/test.sh unit $X",
            "scripts/board.sh list",
            "scripts/branch-done.sh 1",
        ):
            for role in ("test-checker", "test-writer"):
                with self.subTest(role=role, command=command):
                    self.assertEqual(bash(role, command), 2)


class FileWrites(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.project = tmp.name
        for folder in ("tests", "backend", "docs", "ui"):
            os.mkdir(os.path.join(self.project, folder))

    def write(self, role, path, tool="Write"):
        key = "notebook_path" if tool == "NotebookEdit" else "file_path"
        return run_guard(role, tool, {key: path}, project=self.project)

    def test_test_checker_may_write_inside_tests(self):
        for path in (
            "tests/test_new.py",
            os.path.join(self.project, "tests", "fixtures", "x.txt"),
        ):
            for tool in ("Write", "Edit", "MultiEdit"):
                with self.subTest(path=path, tool=tool):
                    self.assertEqual(self.write("test-checker", path, tool), 0)

    def test_test_checker_may_not_write_outside_tests(self):
        outside = (
            "backend/server.py",
            os.path.join(self.project, "backend", "server.py"),
            "tests/../backend/server.py",
            "CLAUDE.md",
            "testsuite/x.py",  # a name that merely starts with "tests"
            "/tmp/x.py",
            "",
        )
        for path in outside:
            for tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
                with self.subTest(path=path, tool=tool):
                    self.assertEqual(self.write("test-checker", path, tool), 2)

    def test_link_inside_tests_pointing_out_is_refused(self):
        os.symlink(
            os.path.join(self.project, "backend"),
            os.path.join(self.project, "tests", "escape"),
        )
        self.assertEqual(self.write("test-checker", "tests/escape/server.py"), 2)

    def test_scout_may_not_write_anywhere(self):
        for role in ("refactor-scout",):
            for path in ("tests/test_new.py", "docs/spec.md", "README.md"):
                for tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
                    with self.subTest(role=role, path=path, tool=tool):
                        self.assertEqual(self.write(role, path, tool), 2)

    def test_test_checker_may_not_write_docs(self):
        for path in ("docs/spec.md", "README.md"):
            with self.subTest(path=path):
                self.assertEqual(self.write("test-checker", path), 2)

    def test_test_writer_may_write_tests_and_docs(self):
        for path in (
            "tests/test_new.py",
            "docs/spec.md",
            os.path.join(self.project, "docs", "decisions.md"),
            "README.md",
        ):
            for tool in ("Write", "Edit", "MultiEdit"):
                with self.subTest(path=path, tool=tool):
                    self.assertEqual(self.write("test-writer", path, tool), 0)

    def test_test_writer_may_not_write_app_code(self):
        for path in (
            "backend/server.py",
            "ui/index.html",
            "CLAUDE.md",
            "docs/../backend/server.py",
            "README.md.bak",
            "docsuite/x.md",  # a name that merely starts with "docs"
            "vendor/enamel/DESIGN.md",
            ".claude/agents/test-writer.md",
            "",
        ):
            for tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
                with self.subTest(path=path, tool=tool):
                    self.assertEqual(self.write("test-writer", path, tool), 2)


class Roles(unittest.TestCase):
    def test_unknown_role_is_refused(self):
        self.assertEqual(bash("builder", "git status"), 2)
        self.assertEqual(bash("", "git status"), 2)

    def test_other_tools_pass_through(self):
        # Read, Grep and Glob are not limited by the guard (see decisions.md).
        self.assertEqual(run_guard("reviewer", "Read", {"file_path": "CLAUDE.md"}), 0)


class AgentInstructions(unittest.TestCase):
    """The agents must be told to read the issue in a form that works here."""

    def test_agents_read_issue_body_with_an_allowed_command(self):
        for name in ("reviewer", "test-checker", "test-writer"):
            with self.subTest(agent=name):
                with open(os.path.join(AGENTS, name + ".md"), encoding="utf-8") as f:
                    text = f.read()
                self.assertIn("gh issue view N --json body,comments", text)
                self.assertNotIn("gh issue view N --comments", text)
                self.assertEqual(
                    bash(name, "gh issue view 30 --json body,comments"), 0
                )

    def test_agents_use_the_guard(self):
        for name in ALL_ROLES:
            with self.subTest(agent=name):
                with open(os.path.join(AGENTS, name + ".md"), encoding="utf-8") as f:
                    text = f.read()
                self.assertIn(f".claude/hooks/agent_guard.py\" {name}", text)


class ReviewerTidyUps(unittest.TestCase):
    """The reviewer fixes tidy-ups itself in one small commit, only on an
    issue branch, never in vendor/, the launcher, the installer, settings or
    CLAUDE.md, and never pushes."""

    def repo(self, branch):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        subprocess.run(["git", "init", "-q", "-b", branch, tmp.name], check=True)
        return tmp.name

    def bash_in(self, folder, command):
        return run_guard("reviewer", "Bash", {"command": command}, project=folder)

    def test_commits_tidy_ups_on_an_issue_branch(self):
        folder = self.repo("issue-21")
        for command in ("git add tests/test_x.py backend/server.py", "git add docs/decisions.md README.md",
                        'git commit -m "WIP issue-21: reviewer tidy-ups"', "scripts/test.sh"):
            with self.subTest(command=command):
                self.assertEqual(self.bash_in(folder, command), 0)
        for path in ("tests/test_x.py", "backend/server.py", "ui/js/app.js", "docs/spec.md"):
            with self.subTest(path=path):
                self.assertEqual(run_guard("reviewer", "Edit", {"file_path": path}, project=folder), 0)

    def test_never_on_main_nor_outside_its_areas(self):
        main, branch = self.repo("main"), self.repo("issue-21")
        self.assertEqual(self.bash_in(main, 'git commit -m "WIP issue-21: reviewer tidy-ups"'), 2)
        self.assertEqual(self.bash_in(main, "git add tests/test_x.py"), 2)
        for command in ("git add vendor/enamel/VERSION", "git add launch.sh", "git add CLAUDE.md",
                        "git add ENAMEL_PIN", "git add .claude/settings.json", "git add -A",
                        'git commit -m "Refs #' '21: done"', 'git commit --amend -m "WIP issue-21: x"',
                        "git push origin issue-21"):
            with self.subTest(command=command):
                self.assertEqual(self.bash_in(branch, command), 2)
        for path in ("vendor/enamel/tokens/enamel.css", "launch.sh", "install-shortcut.sh",
                     "settings.example.json", "CLAUDE.md", ".claude/hooks/agent_guard.py"):
            with self.subTest(path=path):
                self.assertEqual(run_guard("reviewer", "Edit", {"file_path": path}, project=branch), 2)

    def test_only_the_reviewer_commits(self):
        folder = self.repo("issue-21")
        for role in ("test-checker", "test-writer", "refactor-scout"):
            with self.subTest(role=role):
                self.assertEqual(run_guard(role, "Bash", {"command": 'git commit -m "WIP issue-21: x"'},
                                           project=folder), 2)


class PeekThroughTheGuard(unittest.TestCase):
    """Every agent reads Enamel's repo through scripts/peek.sh, never git -C."""

    def test_every_agent_may_peek(self):
        for role in ALL_ROLES:
            for command in ("scripts/peek.sh log --oneline -5", "scripts/peek.sh show --stat HEAD",
                            "scripts/peek.sh status --short", "scripts/peek.sh tag",
                            "scripts/peek.sh tag --list", "scripts/peek.sh rev-parse HEAD",
                            "scripts/peek.sh ls-files"):
                with self.subTest(role=role, command=command):
                    self.assertEqual(bash(role, command), 0)

    def test_unsafe_peeks_are_refused(self):
        for role in ALL_ROLES:
            for command in ("scripts/peek.sh push", "scripts/peek.sh commit -m x",
                            "scripts/peek.sh diff --output=x", "scripts/peek.sh tag -d v0.7.0",
                            "scripts/peek.sh log && git push", "scripts/peek.sh log | head",
                            "git -C ../enamel log"):
                with self.subTest(role=role, command=command):
                    self.assertEqual(bash(role, command), 2)

    def test_every_agent_is_told_the_command_rules(self):
        # Helpers don't always pick up CLAUDE.md, so each agent file says it.
        for role in ALL_ROLES:
            with open(os.path.join(AGENTS, role + ".md"), encoding="utf-8") as f:
                text = f.read()
            for words in ("scripts/peek.sh", "without `git -C`", "`&&`"):
                with self.subTest(agent=role, words=words):
                    self.assertIn(words, text)

    def test_the_builder_prompt_states_the_command_rules(self):
        with open(os.path.join(ROOT, ".claude", "commands", "next.md"), encoding="utf-8") as f:
            text = f.read()
        prompt = text[text.index("You are the builder for Kettle issue"):]
        prompt = prompt[:prompt.index("`\n")]
        for words in ("scripts/peek.sh", "without git -C", "&&"):
            with self.subTest(words=words):
                self.assertIn(words, prompt)


class PeekScript(unittest.TestCase):
    """scripts/peek.sh itself runs only read-only git and never writes a file."""

    def peek(self, *args):
        return subprocess.run([PEEK, *args], capture_output=True, text=True, timeout=10).returncode

    def test_refuses_anything_but_read_only_commands(self):
        for args in (["push"], ["commit", "-m", "x"], ["checkout", "main"], ["reset", "--hard"],
                     ["config", "x", "y"], ["-C", "/tmp", "log"], []):
            with self.subTest(args=args):
                self.assertNotEqual(self.peek(*args), 0)

    def test_refuses_writing_or_running_anything(self):
        for args in (["diff", "--output=out.txt"], ["log", "--out=x"], ["diff", "--ext-diff"],
                     ["show", "--textconv"], ["diff", "--no-index", "/etc/hostname", "README.md"],
                     ["tag", "v9"], ["tag", "-d", "v0.7.0"], ["tag", "--list", "-f", "x"]):
            with self.subTest(args=args):
                self.assertNotEqual(self.peek(*args), 0)


class SharedSettings(unittest.TestCase):
    """A new ask or deny rule must never catch a read-only command (CLAUDE.md,
    "How we work"), and the workflow scripts run without asking."""

    READ_ONLY = [
        "git log --oneline -5", "git log -p -- backend/parser.py", "git log main..issue-14",
        "git show HEAD:CLAUDE.md", "git show --stat HEAD~1", "git status", "git status --short",
        "git diff", "git diff main...issue-14", "git diff --stat -- docs/",
        "gh issue view 14", "gh issue view 14 --json body,comments", "gh issue list",
        "gh issue list --state open --label blocked", "ls", "ls -la docs", "cat CLAUDE.md",
        "grep -rn tile ui/", "scripts/board.sh list", "scripts/peek.sh log --oneline -3",
        "scripts/peek.sh diff --stat HEAD~1", "scripts/peek.sh tag --list",
    ]

    def rules(self, kind):
        with open(os.path.join(ROOT, ".claude", "settings.json"), encoding="utf-8") as f:
            permissions = json.load(f)["permissions"]
        return [r[5:-1] for r in permissions.get(kind, []) if r.startswith("Bash(")]

    def test_no_ask_or_deny_rule_catches_a_read_only_command(self):
        for kind in ("ask", "deny"):
            for rule in self.rules(kind):
                for command in self.READ_ONLY:
                    with self.subTest(rule=f"{kind}: Bash({rule})", command=command):
                        caught = fnmatch.fnmatchcase(command, rule) or \
                            fnmatch.fnmatchcase(command, rule.replace(" *", "*"))
                        self.assertFalse(caught)

    def test_the_workflow_scripts_are_allowed(self):
        allow = self.rules("allow")
        for script in ("scripts/forget-note.sh", "scripts/peek.sh", "scripts/board.sh", "scripts/test.sh"):
            with self.subTest(script=script):
                self.assertIn(script + " *", allow)

    def test_git_minus_c_still_asks(self):
        self.assertIn("git -C *", self.rules("ask"))


def session(command):
    """What the session check does with a command: "ask", "through", or
    "error" if it ever refuses or prints anything else."""
    call = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": ROOT}
    result = subprocess.run([sys.executable, GUARD, "session"], input=json.dumps(call),
                            capture_output=True, text=True, timeout=10,
                            env=dict(os.environ, CLAUDE_PROJECT_DIR=ROOT))
    if result.returncode != 0:
        return "error"
    if not result.stdout.strip():
        return "through"
    out = json.loads(result.stdout)["hookSpecificOutput"]
    return out["permissionDecision"] if out["hookEventName"] == "PreToolUse" else "error"


class SessionPushCheck(unittest.TestCase):
    """The session settings work: every session asks first before a push with
    a colon in its target, and lets everything else go on to the rules."""

    ASKS = [
        "git push origin issue-5:main",
        "git push origin issue-26:main",
        "git push origin main:issue-5",
        "git push origin :issue-5",
        "git push origin :main",
        "git push -u origin issue-5:main",
        "git push --force-with-lease origin issue-5:main",
        "git push origin refs/heads/issue-5:refs/heads/main",
        "git push git@github.com:someone/elsewhere.git main",
        'git push origin "issue-5:main"',
        "git -c push.default=current push origin issue-5:main",
        "/usr/bin/git push origin issue-5:main",
        "git status && git push origin issue-5:main",
        "git commit -q -m done; git push origin issue-5:main",
        "git status\ngit push origin issue-5:main",
        "git push origin issue-5:main 'unclosed",
        "echo a#b; git push origin issue-5:main",
        "git push origin issue-5:main # a note",
    ]
    THROUGH = [
        # The workflow's own pushes (next.md and the release work).
        "git push", "git push -q", "git push -u origin issue-26", "git push origin main",
        "git push origin issue-26", "git push -q origin main",
        # Not a push, even with a colon in it.
        'git commit -q -m "WIP issue-26: code"', "git show HEAD:CLAUDE.md",
        "git log --format=%h:%s", 'git commit -m "fix: one" && git push',
        "gh issue comment 26 --body-file notes.md",
    ]

    def test_a_colon_push_is_asked_about(self):
        for command in self.ASKS:
            with self.subTest(command=command):
                self.assertEqual(session(command), "ask")

    def test_normal_pushes_and_other_commands_go_through(self):
        for command in self.THROUGH + SharedSettings.READ_ONLY:
            with self.subTest(command=command):
                self.assertEqual(session(command), "through")

    def test_other_tools_and_broken_input_go_through(self):
        for call in ('{"tool_name": "Read", "tool_input": {"file_path": "a:b"}}', "not json", "[]"):
            with self.subTest(call=call):
                result = subprocess.run([sys.executable, GUARD, "session"], input=call,
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual((result.returncode, result.stdout), (0, ""))


class SessionSettings(unittest.TestCase):
    """The shared settings start with no warning: the check above is wired to
    every Bash command, no rule uses a colon-star (Claude Code warns about any
    rule with one), and only plugins that exist are switched on."""

    def settings(self):
        with open(os.path.join(ROOT, ".claude", "settings.json"), encoding="utf-8") as f:
            return json.load(f)

    def test_the_session_check_runs_before_every_bash_command(self):
        hooks = self.settings()["hooks"]["PreToolUse"]
        commands = [h["command"] for entry in hooks if entry["matcher"] == "Bash"
                    for h in entry["hooks"]]
        self.assertIn('python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/agent_guard.py" session', commands)

    def test_no_rule_has_a_colon_star(self):
        permissions = self.settings()["permissions"]
        for kind in ("allow", "ask", "deny"):
            for rule in permissions.get(kind, []):
                with self.subTest(rule=f"{kind}: {rule}"):
                    self.assertNotIn(":*", rule)

    def test_only_the_handbook_plugin_is_switched_on(self):
        self.assertEqual(self.settings()["enabledPlugins"], {"enamelware@enamelware": True})


class AgentModels(unittest.TestCase):
    """test-writer runs on Sonnet and refactor-scout on Opus, as asked."""

    def test_models(self):
        for name, model in (("test-writer", "sonnet"), ("refactor-scout", "opus")):
            with self.subTest(agent=name):
                with open(os.path.join(AGENTS, name + ".md"), encoding="utf-8") as f:
                    head = f.read().split("---")[1]
                self.assertIn(f"\nmodel: {model}\n", head)


class Decisions(unittest.TestCase):
    """docs/decisions.md must say what the guard can and can't enforce."""

    def test_limits_are_written_down(self):
        path = os.path.join(ROOT, "docs", "decisions.md")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        heading = "The checking agents' guard: what it can and can't enforce"
        self.assertIn(heading, text)
        section = text[text.index(heading):]
        next_heading = section.find("\n## ", 1)
        if next_heading != -1:
            section = section[:next_heading]
        self.assertIn("**What it can enforce:**", section)
        self.assertIn("**What it can't enforce:**", section)
        # The known gap from the issue: test-checker can write and run a script.
        self.assertIn("test-checker can run code it wrote", section)
        self.assertIn("--output", section)
        self.assertIn("--ext-diff", section)
        # The guard's own docstring points at this section.
        with open(GUARD, encoding="utf-8") as f:
            self.assertIn(heading, f.read())


if __name__ == "__main__":
    unittest.main()
