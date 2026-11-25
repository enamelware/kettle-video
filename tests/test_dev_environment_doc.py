# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The Tests section of docs/dev-environment.md stays in step with the slow
checks (the October 19 tidy-up, improvement 2): every tests/*_check.py script is named
there, the old "Parser tests will join it in the next chunk" sentence is
gone, the doc says how to run one check (scripts/test.sh check NAME), and a
check whose own description says it needs ffmpeg or mpv is not described
in the doc without that. The November 17 tidy-up, improvement 1: the Running line and the
Logs section match the README and the code.

Run from the repo root:  python3 -m unittest tests.test_dev_environment_doc -v
"""

import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "dev-environment.md"
TESTS = ROOT / "tests"


def tests_section():
    text = DOC.read_text(encoding="utf-8")
    start = text.index("\n## Tests")
    rest = text[start + 1:]
    end = re.search(r"\n## (?!#)", rest)
    return rest[: end.start()] if end else rest


def check_scripts():
    return sorted(TESTS.glob("*_check.py"))


def doc_entry(section, name):
    """The doc line (bullet or paragraph) that names this check."""
    for line in section.splitlines():
        if f"`{name}`" in line or f"`tests/{name}.py" in line:
            return line
    return None


def needs(script, tool):
    """True when the script's own description says it needs this tool."""
    doc = ast.get_docstring(ast.parse(script.read_text(encoding="utf-8"))) or ""
    flat = " ".join(doc.split())
    return re.search(rf"needs[^.]*\b{tool}\b", flat) is not None


class DevEnvironmentTestsDocTest(unittest.TestCase):
    def setUp(self):
        self.section = tests_section()

    def test_there_are_checks_to_describe(self):
        self.assertGreater(len(check_scripts()), 10)

    def test_every_check_script_is_described(self):
        missing = [s.stem for s in check_scripts()
                   if doc_entry(self.section, s.stem) is None]
        self.assertEqual(missing, [], "checks not in docs/dev-environment.md")

    def test_no_check_is_described_that_does_not_exist(self):
        named = set(re.findall(r"`(?:tests/)?(\w+_check)(?:\.py)?", self.section))
        existing = {s.stem for s in check_scripts()}
        self.assertEqual(sorted(named - existing), [])

    def test_stale_parser_sentence_is_gone(self):
        text = DOC.read_text(encoding="utf-8")
        self.assertNotIn("Parser tests will join it", text)
        self.assertNotIn("next chunk", text)

    def test_says_how_to_run_one_check(self):
        self.assertIn("scripts/test.sh check NAME", self.section)

    def test_extra_tools_a_check_needs_are_mentioned(self):
        wrong = []
        for script in check_scripts():
            entry = doc_entry(self.section, script.stem) or ""
            for tool in ("ffmpeg", "mpv"):
                if needs(script, tool) and tool not in entry:
                    wrong.append(f"{script.stem}: needs {tool}")
        self.assertEqual(wrong, [], "the doc leaves out a tool the check needs")


class SizesCheckEntryTest(unittest.TestCase):
    """The November 12 tidy-up, improvement 2: the enamel_sizes_check entry names no stale
    Enamel version as the one it draws, and matches the check's own opening
    comment. A version may still be named as history ("Since Enamel ...")."""

    NAME = "enamel_sizes_check"
    # "Enamel 0.8.0's sizes": a version stated as the one the app draws.
    STALE = re.compile(r"Enamel \d+\.\d+(?:\.\d+)?'s")

    def setUp(self):
        self.entry = doc_entry(tests_section(), self.NAME) or ""
        script = TESTS / f"{self.NAME}.py"
        doc = ast.get_docstring(ast.parse(script.read_text(encoding="utf-8")))
        self.comment = " ".join((doc or "").split())

    def test_entry_names_no_enamel_version_as_current(self):
        self.assertTrue(self.entry, "no entry for the sizes check")
        self.assertIsNone(self.STALE.search(self.entry), self.entry)
        self.assertIn("Enamel's sizes", self.entry)

    def test_check_opening_comment_names_no_enamel_version_as_current(self):
        self.assertIsNone(self.STALE.search(self.comment), self.comment)
        self.assertTrue(self.comment.startswith("Enamel's sizes on Home"))

    def test_entry_and_comment_tell_the_same_zoom_story(self):
        sentence = "Since Enamel 0.11.0 (the Enamel 0.11.0 upgrade) the root size works through zoom"
        self.assertIn(sentence, self.entry)
        self.assertIn(sentence, self.comment)
        for words in ("root font size stays the viewer's own",
                      "the text is checked as drawn"):
            self.assertIn(words, self.entry)
            self.assertIn(words, self.comment)


def section(text, heading):
    """The text of one '## heading' section, up to the next '## '."""
    start = text.index(f"\n## {heading}\n")
    rest = text[start + 1:]
    end = re.search(r"\n## (?!#)", rest)
    return rest[: end.start()] if end else rest


class RunningAndLogsTest(unittest.TestCase):
    """The November 17 tidy-up, improvement 1: docs/dev-environment.md's Running line says
    the app quits through Quit in the menu (q or B opens it with Quit chosen),
    as the README does, not that q on the list shuts it down; its Logs section
    names all three logs each run writes, as the README and the code do."""

    def setUp(self):
        self.doc = DOC.read_text(encoding="utf-8")
        self.readme = (ROOT / "README.md").read_text(encoding="utf-8")

    def test_running_line_has_no_stale_q_shutdown(self):
        flat = " ".join(self.doc.split())
        self.assertNotIn("when `q` is pressed on the list screen", flat)

    def test_running_line_matches_the_readme(self):
        words = ("choose **Quit** in the menu (`q` or B opens it with Quit "
                 "chosen; press Enter or A)")
        self.assertIn(words, " ".join(self.readme.split()))
        self.assertIn(words, " ".join(self.doc.split()))

    def test_logs_section_names_all_three_logs(self):
        logs = section(self.doc, "Logs")
        readme_logs = section(self.readme, "Logs")
        for name in ("launch-<timestamp>.log", "firefox-<timestamp>.log",
                     "mpv-<timestamp>.log"):
            self.assertIn(f"`{name}`", logs)
            self.assertIn(f"`{name}`", readme_logs)
        self.assertIn("per file played", logs)

    def test_logs_named_are_the_ones_the_code_writes(self):
        launcher = (ROOT / "launch.sh").read_text(encoding="utf-8")
        # Since the installer work the folder is the copy's logs folder ($LOG_DIR):
        # logs/ in a development copy, as the doc says.
        self.assertIn("$LOG_DIR/launch-$TIMESTAMP.log", launcher)
        self.assertIn("$LOG_DIR/firefox-$TIMESTAMP.log", launcher)
        self.assertIn('LOG_DIR="logs"', launcher)
        backend = "".join(p.read_text(encoding="utf-8")
                          for p in (ROOT / "backend").glob("*.py"))
        self.assertRegex(backend, r"mpv-\{[^}]+\}\.log")


if __name__ == "__main__":
    unittest.main()
