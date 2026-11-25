# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Design system: Enamel 0.5.0 finished (the design system finish).

Checks: the app has no look of its own for Enamel's buttons (the Scan my
folders button this issue made went with its screen in the first scan screen); every class, id, data- marker (and value) and custom
property in the app's own stylesheets is used by the page or its scripts;
the spec lists every element compared with Enamel 0.5.0, the removed
tokens and the changed hooks. (The old look's removal and the token test's
lost exception: tests/test_design_system_tokens.py.)

Run from the repo root:  python3 -m unittest tests.test_design_system_finished -v
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "ui"
CSS_FILES = sorted((UI / "css").glob("*.css"))
DEFAULTS = UI / "css" / "defaults.css"
# The app's pages: Home and, since the start-up problem screen, the launcher's start-up problem page.
INDEX = "".join(path.read_text(encoding="utf-8") for path in sorted(UI.glob("*.html")))
SCRIPTS = "".join(path.read_text(encoding="utf-8") for path in sorted((UI / "js").glob("*.js")))
SPEC = (ROOT / "docs" / "spec.md").read_text(encoding="utf-8")


def strip_comments(text):
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def unused_styling(css, source):
    """Every class, id, attribute (and attribute value) a selector names and
    every custom property declared, that the page and scripts never use.
    A data- attribute counts as used under its dataset name too."""
    css = strip_comments(css)
    unused = set()
    selectors = [s for s in re.findall(r"([^{}]+)\{", css) if not s.strip().startswith("@")]

    def word_in_source(word):
        return re.search(r"(?<![\w-])" + re.escape(word) + r"(?![\w-])", source)

    for sel in selectors:
        for name in re.findall(r"\.([A-Za-z_][\w-]*)", sel):
            if not word_in_source(name):
                unused.add(f".{name}")
        for name in re.findall(r"#([A-Za-z_][\w-]*)", sel):
            if not word_in_source(name):
                unused.add(f"#{name}")
        for attr, value in re.findall(r"\[([\w-]+)(?:=\"([^\"]*)\")?\]", sel):
            camel = re.sub(r"-(\w)", lambda m: m.group(1).upper(), attr[5:]) if attr.startswith("data-") else attr
            if not (word_in_source(attr) or word_in_source(camel)):
                unused.add(f"[{attr}]")
            elif value and value not in source:
                unused.add(f'[{attr}="{value}"]')
    declared = set(re.findall(r"(?<![\w-])(--[\w-]+)\s*:", css))
    used = set(re.findall(r"var\((--[\w-]+)", css))
    unused |= declared - used
    return unused


class ScanMyFoldersGoneTest(unittest.TestCase):
    """The button this issue made was removed by the first scan screen, with its screen."""

    def test_the_temporary_screen_is_gone(self):
        for source in (INDEX, SCRIPTS, DEFAULTS.read_text(encoding="utf-8")):
            self.assertNotIn("first-scan", source)
            self.assertNotIn("Scan my folders", source)

    def test_enamels_primary_focus_is_left_to_enamel(self):
        css = strip_comments(DEFAULTS.read_text(encoding="utf-8"))
        selectors = [s.strip() for sel in re.findall(r"([^{}]+)\{", css) for s in sel.split(",")]
        self.assertEqual([s for s in selectors if "en-button" in s], [])


class UnusedStylingTest(unittest.TestCase):
    def test_nothing_in_the_app_stylesheets_is_unused(self):
        source = INDEX + SCRIPTS
        # Classes, ids and markers file by file (custom properties below, since
        # tokens.css declares them and defaults.css uses them).
        for path in CSS_FILES:
            with self.subTest(file=path.name):
                found = unused_styling(path.read_text(encoding="utf-8"), source)
                self.assertEqual({u for u in found if not u.startswith("--")}, set())

    def test_tokens_declared_in_one_file_and_used_in_another_count(self):
        # tokens.css declares, defaults.css uses: checked together.
        all_css = "".join(path.read_text(encoding="utf-8") for path in CSS_FILES)
        self.assertEqual({u for u in unused_styling(all_css, INDEX + SCRIPTS) if u.startswith("--")}, set())

    def test_the_check_catches_unused_styling(self):
        source = '<div class="kept" id="here" data-role="x"></div> el.dataset.status = "missing";'
        css = """
            :root { --kept-size: 1px; --lost-size: 2px; }
            .kept { width: var(--kept-size); }
            .gone, #here, #away { color: red; }
            [data-role="x"], [data-role="y"], [data-status="missing"], [data-never] { margin: 0; }
            .kept.en-button--primary:focus { outline: none; }
        """
        self.assertEqual(unused_styling(css, source),
                         {".gone", "#away", '[data-role="y"]', "[data-never]", "--lost-size", ".en-button--primary"})


class SpecTest(unittest.TestCase):
    def section(self):
        start = SPEC.index("## Design system: Enamel 0.5.0 finished (the design system finish)")
        return SPEC[start:SPEC.index("\n## ", start + 1)]

    def test_every_compared_element_is_listed(self):
        section = self.section()
        for element in ("Scan my folders", "Error banner", "\"Playing…\" and \"Rescanning…\"", "\"folder not found\"",
                        "\"mpv not found\" screen", "First-launch text", "Developer box", "Loading screen", "Letter strip"):
            with self.subTest(element=element):
                self.assertRegex(section, r"\n\| " + re.escape(element) + r"[^\n]*\| (\*\*moved\*\*|kept) ")

    def test_removed_tokens_and_changed_hooks_are_listed(self):
        section = self.section()
        for token in ("--own-look-text", "--own-look-bg", "--own-look-focus-bg", "--own-look-ring",
                      "--own-look-ring-width", "--own-look-ring-gap", "--own-look-font-size",
                      "--own-look-padding", "--own-look-radius"):
            self.assertIn(f"`{token}`", section)
        for hook in ('`#first-scan [data-role="action"]`', '`[data-kind="first-scan"]`', "`.file-row:not(.en-row)`"):
            self.assertIn(hook, section)

    def test_the_hooks_list_has_the_buttons(self):
        hooks = SPEC[SPEC.index("## Theming hooks (complete list"):]
        self.assertIn('.result-action.en-button[data-kind="open-library" | "change-folders"]', hooks)
        self.assertNotIn("#first-scan.first-scan", hooks)


if __name__ == "__main__":
    unittest.main()
