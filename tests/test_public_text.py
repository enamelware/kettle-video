# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The public voice work: the public-text check, the "Public writing" rule,
the "How this repo is built" page, and development tools that say what they
need on a stranger's machine.

The public-text check (tools/public_text.py, run inside the release check)
finds old issue numbers of the private repo, the person running the project
named by role outside the instructions to Claude Code, claude.ai links and links to
the private board. These tests plant each kind in text and see it caught,
see ordinary text pass, and see the repo itself has none left, so none can
come back. Planted values are built from parts, so this file passes the
check itself.

    scripts/test.sh unit tests.test_public_text
"""

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import public_text as pt  # noqa: E402
import release_check  # noqa: E402
import privacy_guard  # noqa: E402

HASH = "#"
THE_OWNER = "the " + "own" + "er"
OWNERS = "Own" + "er's"

PLANTED = [
    (pt.ISSUE_NUMBER, "Built in issue " + HASH + "14."),
    (pt.ISSUE_NUMBER, "(" + HASH + "82 to " + HASH + "92)"),
    (pt.ISSUE_NUMBER, "since " + HASH + "120, motion included"),
    (pt.ISSUE_NUMBER, "Refs " + HASH + "21: done"),
    (pt.ISSUE_NUMBER, "issue " + HASH + "30; and more"),
    (pt.ISSUE_NUMBER, "/* Home shell (issue " + HASH + "33): */"),
    (pt.OWNER_WORDING, "Chosen by " + THE_OWNER + " on the issue."),
    (pt.OWNER_WORDING, OWNERS + " decision."),
    (pt.ISSUE_NUMBER, "after the saved library work/" + HASH + "19 fix"),
    (pt.ISSUE_NUMBER, "Needed by: " + HASH + "114"),
    (pt.OWNER_WORDING, "Resume starts early (the resume work, " + "own" + "er feedback)"),
    (pt.OWNER_WORDING, "both " + "own" + "er decisions under CLAUDE.md"),
    (pt.OWNER_WORDING, "(" + "own" + 'er: "it is recognised")'),
    (pt.OWNER_WORDING, "the project's " + "own" + "er chose it"),
    (pt.CLAUDE_LINK, "See https://" + "claude" + ".ai/" + "chat/0123abcd for the brief."),
    (pt.BOARD_LINK, "https://github.com/" + "users/someone/projects/1"),
]

NOT_FINDINGS = [
    "Commit messages say `Refs " + HASH + "N`; a phrase such as \"" + HASH + "N " + HASH + "M failed\".",
    "body { background: " + HASH + "111; color: " + HASH + "eee; border: 2px solid " + HASH + "444; }",
    "--osd-border-color=" + HASH + "000000 and " + HASH + "3F4553 rows",
    "&" + HASH + "39; and https://example.org/" + HASH + "12 and f\"{REPO}" + HASH + "60\"",
    "Built in the onboarding work, after the keep-awake fix.",
    "The designer chose this; the file's owner is root.",
    "Claude Code is Anthropic's coding agent.",
    "a { color: " + HASH + "111 } and style=\"color: " + HASH + "222\" and border: 1px solid " + HASH + "4444,",
    "  repository(" + "own" + "er: $" + "own" + "er, name: $name) {",
    "gh project item-add 1 --" + "own" + "er \"$OWNER\"",
]


class Planted(unittest.TestCase):
    def test_each_kind_is_caught(self):
        for what, line in PLANTED:
            for path in ("README.md", "docs/decisions.md", "backend/server.py", "tests/test_x.py"):
                with self.subTest(path=path, line=line):
                    self.assertIn((2, what), pt.findings(path, "fine\n" + line + "\n"))

    def test_a_short_number_after_a_colon_is_caught(self):
        # The way /draft writes links between issues: "Needs:" or "Series:", then a number.
        # A CSS colour has 3, 4, 6 or 8 digits, so one or two digits after a
        # colon can only be an issue number.
        for line in ("Needs: " + HASH + "14 first.", "Series: " + HASH + "7, then more",
                     "Needed by: " + HASH + "21"):
            for path in ("README.md", "docs/decisions.md", "CHANGELOG.md", "tests/test_x.py"):
                with self.subTest(path=path, line=line):
                    self.assertIn((1, pt.ISSUE_NUMBER), pt.findings(path, line + "\n"))

    def test_every_kind_is_planted(self):
        self.assertEqual({pt.ISSUE_NUMBER, pt.OWNER_WORDING, pt.CLAUDE_LINK, pt.BOARD_LINK},
                         {what for what, _ in PLANTED})

    def test_ordinary_text_passes(self):
        for line in NOT_FINDINGS:
            with self.subTest(line=line):
                self.assertEqual(pt.findings("docs/x.md", line), [])

    def test_instructions_keep_their_wording_but_not_their_numbers(self):
        for path in ("CLAUDE.md", ".claude/commands/next.md", ".claude/agents/reviewer.md"):
            with self.subTest(path=path):
                self.assertEqual(pt.findings(path, "Ask " + THE_OWNER + ".\n"), [])
                self.assertEqual(pt.findings(path, "Since issue " + HASH + "48.\n"), [(1, pt.ISSUE_NUMBER)])
                self.assertEqual(pt.findings(path, "claude" + ".ai/" + "x\n"), [(1, pt.CLAUDE_LINK)])

    def test_only_the_boards_own_address_in_its_settings_passes(self):
        own = '  "projectUrl": "https://github.com/' + 'users/someone/projects/1",'
        self.assertEqual(pt.findings(pt.BOARD_SETTINGS, "{\n" + own + "\n}\n"), [])
        self.assertEqual(pt.findings("docs/x.md", own), [(1, pt.BOARD_LINK)])
        other = '  "notes": "https://github.com/' + 'users/someone/projects/2",'
        self.assertEqual(pt.findings(pt.BOARD_SETTINGS, other), [(1, pt.BOARD_LINK)])

    def test_third_party_files_are_left_out(self):
        for path in ("vendor/enamel/DESIGN.md", "ui/fonts/RubikMonoOne-OFL.txt"):
            self.assertEqual(pt.findings(path, "issue " + HASH + "7 by " + THE_OWNER + "\n"), [])


class InTheReleaseCheck(unittest.TestCase):
    """The public-text check runs inside the release check, on every tracked file."""

    def test_it_is_part_of_the_release_check(self):
        self.assertIn("public_text", release_check.PUBLIC_TEXT_CHECKS)

    def test_a_planted_number_fails_the_release_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            (repo / "docs").mkdir()
            (repo / "docs" / "notes.md").write_text("Fine.\nSince issue " + HASH + "48 the app changed.\n")
            subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
            subprocess.run(["git", "-c", "user.name=Example", "-c", "user.email=a@example.invalid",
                            "commit", "-q", "-m", "invented"], cwd=repo, check=True)
            check = release_check.Check(privacy_guard.Matcher({"other": ["zzzinventedword"]}), set(),
                                        history=None, old_names=False)
            found = check.run(release_check.repo_items(repo))
        self.assertEqual(found, ["docs/notes.md, line 2: " + pt.ISSUE_NUMBER])


class TheRepo(unittest.TestCase):
    def test_no_findings_in_the_repo(self):
        self.assertEqual(pt.repo_findings(), [], 'text breaks CLAUDE.md "Public writing"')

    def test_no_private_history_links_or_commit_addresses(self):
        """Links into the private repo's commits or issues, by the release check's own rule."""
        found = []
        for path in pt.published_files():
            if path.startswith(pt.THIRD_PARTY) or path.lower().endswith(pt.BINARY):
                continue
            try:
                text = (ROOT / path).read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            found += [f"{path}, line {n}" for n, line in enumerate(text.splitlines(), 1)
                      if release_check.REPO_LINK.search(line)]
        self.assertEqual(found, [])
        check = release_check.Check(privacy_guard.Matcher({"other": ["zzzinventedword"]}), set(),
                                    history=str(ROOT), old_names=False)
        commits = []
        for path in pt.published_files():
            if path.startswith(pt.THIRD_PARTY) or path.lower().endswith(pt.BINARY):
                continue
            try:
                text = (ROOT / path).read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            commits += [f"{path}, line {n}" for n in check.commit_lines(text)]
        self.assertEqual(commits, [], "commit addresses of this repo's history")

    @unittest.skipIf(os.environ.get("KETTLE_QUICK") == "1",
                     "about 40 seconds: runs in the full check (scripts/test.sh full)")
    def test_the_whole_release_check_passes_on_the_repo(self):
        """Every rule of the release check at once, public text included, on
        every tracked file: titles against the invented list, emails, Steam,
        secrets, old names, links and commit addresses. The private word list
        is used where this device has one, otherwise an invented stand-in
        (the privacy guard in scripts/test.sh fails without the real one)."""
        try:
            words = privacy_guard.read_list(privacy_guard.DEFAULT_LIST)
        except privacy_guard.ListProblem:
            words = {"other": ["zzzinventedword"]}
        check = release_check.Check(privacy_guard.Matcher(words), release_check.invented_titles(ROOT),
                                    history=str(ROOT), old_names=True)
        self.assertEqual(check.run(release_check.repo_items(ROOT)), [],
                         "the release check finds something in the repo")


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def section(text, heading):
    m = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(1) if m else ""


class TheRule(unittest.TestCase):
    def test_claude_md_has_the_section(self):
        rule = section(read("CLAUDE.md"), "Public writing")
        self.assertTrue(rule, 'CLAUDE.md has no "Public writing" section')
        for words in ("Project voice", '"the designer"', "Steam Deck (SteamOS)", "Retroid Pocket Nova (Armada)",
                      "Example content is always invented", "No old issue numbers or commit addresses in files",
                      "public tickets", "Past commits are never rewritten", "docs/how-this-repo-is-built.md",
                      "tools/public_text.py", "tools/release_check.py", "On another machine",
                      "Text addressed to the app's users"):
            self.assertIn(words, rule)

    def test_the_readme_links_the_page(self):
        self.assertIn("(docs/how-this-repo-is-built.md)", read("README.md"))

    def test_the_page_explains_the_workflow(self):
        page = read("docs/how-this-repo-is-built.md")
        for words in ("Claude Code", "designer", "The board itself is private", "**Drafted**", "**Ready for dev**",
                      "**Building**", "**More to do**", "**Ready for testing**", "**Done**", "**/draft**",
                      "**/next**", "**/tidy**", "**reviewer**", "**test-checker**", "**test-writer**",
                      "**refactor-scout**", "| S |", "| M |", "| L |", "docs/decisions.md",
                      "Steam Deck (SteamOS)", "Retroid Pocket Nova (Armada)", "privacy guard"):
            self.assertIn(words, page)

    def test_the_page_links_only_to_public_places(self):
        page = read("docs/how-this-repo-is-built.md")
        for link in re.findall(r"\]\(([^)]+)\)", page):
            with self.subTest(link=link):
                if link.startswith("http"):
                    self.assertTrue(link.startswith("https://www.anthropic.com/"), link)
                else:
                    self.assertTrue((ROOT / "docs" / link).resolve().exists(), link)


class OnAStrangersMachine(unittest.TestCase):
    """Each development tool that needs this device's set-up says what it needs."""

    def test_the_doc_names_each_need(self):
        doc = read("docs/dev-environment.md")
        part = doc.split("### On another machine", 1)[1].split("\n### ", 1)[0]
        for words in ("privacy_guard.py build", "enamelware/enamel.git", "scripts/peek.sh",
                      "tools/update_enamel.py", "org.mozilla.firefox", "settings.json", "gh"):
            self.assertIn(words, part)

    def test_a_missing_word_list_says_how_to_make_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(privacy_guard.ListProblem) as caught:
                privacy_guard.read_list(Path(tmp) / "words.txt")
        self.assertIn("python3 tools/privacy_guard.py build", str(caught.exception))

    def test_a_missing_enamel_folder_says_how_to_get_one(self):
        import update_enamel
        reason = update_enamel.why_not_released(Path("/nowhere-invented/enamel"), "0.1.0")
        self.assertIn("isn't on this device", reason)
        self.assertIn("git clone https://github.com/enamelware/enamel.git", reason)
        self.assertIn("second argument", reason)

    def test_peek_says_how_to_get_enamel(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "kettle-video" / "scripts"
            copy.mkdir(parents=True)
            (copy / "peek.sh").write_bytes((ROOT / "scripts" / "peek.sh").read_bytes())
            result = subprocess.run(["bash", str(copy / "peek.sh"), "log"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("No other Kettle repository", result.stderr)
        self.assertIn("git clone https://github.com/enamelware/enamel.git", result.stderr)

    def test_test_sh_says_when_firefox_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp)
            for tool in ("python3", "git", "bash", "dirname", "cat", "date", "mkdir", "rm"):
                found = subprocess.run(["bash", "-c", f"command -v {tool}"], capture_output=True, text=True)
                if found.stdout.strip():
                    os.symlink(found.stdout.strip(), bin_dir / tool)
            script = read("scripts/test.sh")
            body = script.split("firefox_note() {", 1)[1].split("\n}\n", 1)[0]
            result = subprocess.run(["bash", "-c", "firefox_note() {" + body + "\n}\nfirefox_note"],
                                    capture_output=True, text=True, env={"PATH": str(bin_dir)})
        self.assertIn("Firefox not found", result.stderr)
        self.assertIn("org.mozilla.firefox", result.stderr)
        self.assertIn("firefox_note\n    python3 \"tests/$name.py\"", script)


class SpecExamplesAreInvented(unittest.TestCase):
    """The release check reads titles only from file names and title fields, so
    the spec's sorting examples, written in prose, are kept in step with the
    invented titles the order tests use."""

    def test_the_order_examples_are_the_tests_titles(self):
        spec = read("docs/spec.md")
        part = spec.split("**Order and letter groups**", 1)[1].split("\n", 1)[0]
        tests = read("tests/test_library_order.py")
        # Every quoted title in the article rule, single words included
        # ("Thelwick", "Theatre of Example"), is one the order tests use.
        rule = part.split("**A leading", 1)[1].split("The answer gives", 1)[0]
        quoted = re.findall(r'"([^"]+)"', rule)
        self.assertGreaterEqual(len(quoted), 12, quoted)
        for title in quoted:
            with self.subTest(title=title):
                self.assertIn(f'"{title}"', tests)


if __name__ == "__main__":
    unittest.main()
