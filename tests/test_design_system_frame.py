# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Design system 2/4 (the second design system step): the page frame and the simple screens
(loading, first launch, messages, tabs, hint bar, top bar) take their look
from Enamel.

Checks: in the app's own styles for these screens, every colour, type size,
spacing and radius is a --en- token (layout widths and heights may be the
app's own; the wordmark and its PLAYER label are the listed exceptions);
the tabs and hint bar carry Enamel's classes next to the app's hooks;
there are no L1/R1 shoulder glyphs; no Enamel accent is chosen.

Run from the repo root:  python3 -m unittest tests.test_design_system_frame -v
"""

import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "ui"
DEFAULTS = UI / "css" / "defaults.css"

# Every rule for the screens in this issue, by selector.
SCREEN_SELECTORS = {
    "body",
    ".status",
    '.status[data-state="error"]',
    ".banner",
    ".banner-info",
    ".full-message",
    ".loading-screen",
    ".loading-screen p",
    '.loading-screen [data-role="label"]',
    ".kettle-logo",
    ".action-bar",
    ".tab-strip",
    ".tab",
    ".tab-count",
    ".tab:focus",
    ".hint-bar",
    ".hint[hidden]",
}

# Properties that set a colour, type size, spacing or radius.
STYLE_PROPS = re.compile(
    r"^(color|background(-color)?|box-shadow|border(-[a-z]+)*|outline(-[a-z]+)*|font-size|font-family"
    r"|padding(-[a-z]+)*|margin(-[a-z]+)*|gap|row-gap|column-gap|letter-spacing)$"
)

# Not --en- tokens, but allowed: layout heights, and the wordmark (Enamel
# has no brand tokens; listed under "Gaps in the design system").
LAYOUT_VARS = {"--tab-strip-height"}
WORDMARK_VARS = {
    ".kettle-logo": {"--font-wordmark", "--font-size-wordmark", "--color-wordmark"},
    '.loading-screen [data-role="label"]': {"--letter-spacing-label"},
}

KEYWORDS = {"calc", "inset", "solid", "none", "auto", "0", "-1", "transparent", "inherit", "normal"}


def rules():
    css = re.sub(r"/\*.*?\*/", "", DEFAULTS.read_text(), flags=re.S)
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        names = [sel.strip() for sel in selectors.split(",")]
        yield names, re.findall(r"([\w-]+)\s*:\s*([^;]+);", body)


def leftover(value, allowed_vars):
    """What remains of a value once Enamel tokens, allowed variables,
    keywords and arithmetic are taken out; empty means it's all tokens."""
    rest = re.sub(r"var\(--en-[\w-]+\)", " ", value)
    for name in allowed_vars:
        rest = rest.replace(f"var({name})", " ")
    rest = re.sub(r"[()*+/,]", " ", rest)
    return [word for word in rest.split() if word not in KEYWORDS]


class _Classes(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.elements.append((attrs.get("id"), set((attrs.get("class") or "").split()), attrs))


class TokensOnlyTest(unittest.TestCase):
    def test_every_screen_rule_exists(self):
        found = {name for names, _ in rules() for name in names}
        self.assertEqual(SCREEN_SELECTORS - found, set(), "rules for these screens went missing")

    def test_screen_styles_use_only_enamel_tokens(self):
        checked = 0
        for names, declarations in rules():
            for name in names:
                if name not in SCREEN_SELECTORS:
                    continue
                allowed = LAYOUT_VARS | WORDMARK_VARS.get(name, set())
                for prop, value in declarations:
                    if not STYLE_PROPS.match(prop):
                        continue
                    checked += 1
                    with self.subTest(selector=name, prop=prop):
                        self.assertEqual(leftover(value, allowed), [], f"{name} {{ {prop}: {value} }}")
        self.assertGreater(checked, 30)

    def test_check_catches_old_values(self):
        # The check itself: an old app token or a raw value is caught.
        self.assertTrue(leftover("var(--color-bg)", LAYOUT_VARS))
        self.assertTrue(leftover("var(--space-3)", LAYOUT_VARS))
        self.assertTrue(leftover("12px", LAYOUT_VARS))
        self.assertTrue(leftover("#000000", LAYOUT_VARS))
        self.assertFalse(leftover("0 calc(-1 * var(--en-space-gutter)) var(--en-space-inset)", LAYOUT_VARS))

    def test_no_old_glyph_or_hint_styling_left(self):
        # The hint bar and glyphs are Enamel's: the app keeps no look of its own for them.
        names = {name for names, _ in rules() for name in names}
        self.assertNotIn(".button-glyph", names)
        self.assertNotIn(".hint", names)


class KettleClassesTest(unittest.TestCase):
    def setUp(self):
        parser = _Classes()
        parser.feed((UI / "index.html").read_text())
        self.elements = parser.elements

    def with_class(self, name):
        return [classes for _, classes, _ in self.elements if name in classes]

    def test_tabs_are_kettle_tabs_with_counts(self):
        self.assertEqual(self.with_class("tab-strip"), [{"tab-strip", "en-tabs"}])
        self.assertEqual(self.with_class("tab"), [{"tab", "en-tab"}] * 2)
        self.assertEqual(self.with_class("tab-count"), [{"tab-count", "en-tab__count"}] * 2)

    def test_hint_bar_is_kettle_hint_bar(self):
        self.assertEqual(self.with_class("hint-bar"), [{"hint-bar", "en-hintbar"}])
        # A, X, B, and since the folder choice screens onboarding's Y Look again.
        self.assertEqual(self.with_class("hint"), [{"hint", "en-hint"}] * 4)
        self.assertEqual(self.with_class("button-glyph"), [{"button-glyph", "en-glyph"}] * 4)

    def test_no_shoulder_glyphs_and_default_accent(self):
        page = (UI / "index.html").read_text()
        self.assertNotIn("en-glyph--shoulder", page)
        self.assertNotIn("data-en-accent", page)
        for path in (UI / "js").glob("*.js"):
            self.assertNotIn("en-accent", path.read_text(), path.name)


if __name__ == "__main__":
    unittest.main()
