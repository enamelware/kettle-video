# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Design system 4/4 (the last design system step): the app's own styles hold layout only.
Every colour, type size, spacing and radius comes from Enamel's --en-
tokens, with one labelled exception in ui/css/tokens.css: the wordmark
(Enamel has no brand tokens): --color-wordmark and its font, size and
letter spacing. The "old look" block kept for Scan my folders went in the design system finish,
and with it this test's exception for it.

Checks: no colour value anywhere in the app's CSS, page or scripts outside
that exception (the keyword transparent aside); no font size, spacing or
radius value outside the tokens (layout widths and heights aside); the old
palette and role tokens are gone and nothing uses them; the app's own
custom properties are exactly the listed layout and wordmark ones.

Run from the repo root:  python3 -m unittest tests.test_design_system_tokens -v
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "ui"
TOKENS = UI / "css" / "tokens.css"
DEFAULTS = UI / "css" / "defaults.css"

WORDMARK_TOKENS = {"--font-wordmark", "--font-size-wordmark", "--letter-spacing-label", "--color-wordmark"}
LAYOUT_TOKENS = {
    "--tab-strip-height", "--letter-strip-width", "--font-size-letter-strip",
    "--font-size-letter-strip-short",
    "--continue-missing-filter",
}
# defaults.css declares no custom property of its own since the developer
# box went (the never-online work).
DEFAULTS_TOKENS = set()

# Every token the last design system step removed (listed with its replacement in docs/spec.md).
REMOVED_TOKENS = {
    *(f"--color-{name}" for name in (
        "bar", "page", "row", "row-focus", "pill", "track", "fog", "snow", "white", "mustard",
        "sage", "cream", "brick", "ink", "surface", "raised", "line", "bg", "text",
        "text-muted", "accent", "focus", "row-bg", "focus-bg", "error-bg", "error-text",
        "button-bg", "button-text", "progress-fill", "progress-track", "bar-bg", "bar-text",
        "tab-text", "tab-selected-bg", "tab-selected-text", "glyph-bg", "glyph-text")),
    "--focus-ring-width", "--focus-ring-gap", "--radius",
    "--space-1", "--space-2", "--space-3", "--space-4", "--space-5",
    "--font-size-body", "--font-size-heading", "--font-size-subheading", "--font-size-small",
    "--row-padding-block", "--row-padding-inline", "--continue-progress-height",
}

# Colour values: hex, colour functions, and CSS named colours.
COLOUR_FUNCTION = re.compile(
    r"#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color|color-mix|light-dark)\(")
NAMED_COLOURS = set("""
aliceblue antiquewhite aqua aquamarine azure beige bisque black blanchedalmond blue blueviolet brown
burlywood cadetblue chartreuse chocolate coral cornflowerblue cornsilk crimson cyan darkblue darkcyan
darkgoldenrod darkgray darkgreen darkgrey darkkhaki darkmagenta darkolivegreen darkorange darkorchid
darkred darksalmon darkseagreen darkslateblue darkslategray darkslategrey darkturquoise darkviolet
deeppink deepskyblue dimgray dimgrey dodgerblue firebrick floralwhite forestgreen fuchsia gainsboro
ghostwhite gold goldenrod gray green greenyellow grey honeydew hotpink indianred indigo ivory khaki
lavender lavenderblush lawngreen lemonchiffon lightblue lightcoral lightcyan lightgoldenrodyellow
lightgray lightgreen lightgrey lightpink lightsalmon lightseagreen lightskyblue lightslategray
lightslategrey lightsteelblue lightyellow lime limegreen linen magenta maroon mediumaquamarine
mediumblue mediumorchid mediumpurple mediumseagreen mediumslateblue mediumspringgreen
mediumturquoise mediumvioletred midnightblue mintcream mistyrose moccasin navajowhite navy oldlace
olive olivedrab orange orangered orchid palegoldenrod palegreen paleturquoise palevioletred
papayawhip peachpuff peru pink plum powderblue purple rebeccapurple red rosybrown royalblue
saddlebrown salmon sandybrown seagreen seashell sienna silver skyblue slateblue slategray slategrey
snow springgreen steelblue tan teal thistle tomato turquoise violet wheat white whitesmoke yellow
yellowgreen currentcolor canvas canvastext highlight
""".split())
COLOUR_PROPS = re.compile(
    r"^(color|background(-color)?|box-shadow|text-shadow|border(-[a-z]+)*|outline(-[a-z]+)*"
    r"|fill|stroke|caret-color|accent-color|text-decoration(-color)?|column-rule(-color)?|filter|--[\w-]+)$")

# Properties that set a type size, spacing or radius.
SIZE_PROPS = re.compile(
    r"^(font-size|font|letter-spacing|word-spacing|line-height|padding(-[a-z]+)*|margin(-[a-z]+)*"
    r"|gap|row-gap|column-gap|border(-[a-z]+)*-radius|border-radius|scroll-margin(-[a-z]+)*"
    r"|scroll-padding(-[a-z]+)*|text-indent)$")
# line-height: 1 is a ratio, not a size.
KEYWORDS = {"calc", "min", "max", "clamp", "inset", "solid", "none", "auto", "transparent", "inherit", "normal"}


def strip_comments(text):
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def rules(path):
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", strip_comments(path.read_text(encoding="utf-8"))):
        names = [sel.strip() for sel in selectors.split(",")]
        yield names, [(p, v.strip()) for p, v in re.findall(r"([\w-]+)\s*:\s*([^;]+);", body)]


def leftover(value, allowed_vars):
    """What remains once Enamel tokens, allowed variables, keywords,
    plain numbers and arithmetic are taken out; empty means tokens only."""
    rest = re.sub(r"var\(--en-[\w-]+\)", " ", value)
    for name in allowed_vars:
        rest = rest.replace(f"var({name})", " ")
    rest = re.sub(r"[()*+/,]", " ", rest)
    return [word for word in rest.split()
            if word not in KEYWORDS and not re.fullmatch(r"-?\d*\.?\d+", word)]


class NoColourValuesTest(unittest.TestCase):
    def app_files(self):
        return [*(UI / "css").glob("*.css"), *UI.glob("*.html"), *(UI / "js").glob("*.js")]

    def test_no_colour_values_outside_the_wordmark(self):
        for path in self.app_files():
            text = path.read_text(encoding="utf-8")
            if path == TOKENS:
                text = re.sub(r"--color-wordmark:\s*#E4A83A;", "", text)
            if path.suffix == ".html":
                text = re.sub(r"&#\w+;", "", text)
            with self.subTest(file=path.name):
                self.assertEqual(COLOUR_FUNCTION.findall(strip_comments(text) if path.suffix == ".css" else text), [])

    def test_no_named_colours_in_styles(self):
        for path in (UI / "css").glob("*.css"):
            for names, decls in rules(path):
                for prop, value in decls:
                    if not COLOUR_PROPS.match(prop):
                        continue
                    words = set(re.findall(r"[a-z]+", value.lower())) - {"var"}
                    words = {w for w in words if not re.search(rf"--[\w-]*{w}", value.lower())}
                    with self.subTest(file=path.name, selector=names[0], prop=prop):
                        self.assertEqual(words & NAMED_COLOURS, set(), f"{prop}: {value}")
        for page in UI.glob("*.html"):
            self.assertNotIn("style=", page.read_text(encoding="utf-8"), page.name)
            # No styles inside the page either: they all live in the stylesheets checked above.
            self.assertNotIn("<style", page.read_text(encoding="utf-8").lower(), page.name)

    def test_the_check_catches_colours(self):
        self.assertTrue(COLOUR_FUNCTION.findall("color: #fff"))
        self.assertTrue(COLOUR_FUNCTION.findall("background: rgb(0 0 0)"))
        self.assertTrue(COLOUR_FUNCTION.findall("color: color-mix(in srgb, red, blue)"))
        self.assertFalse(COLOUR_FUNCTION.findall("background: transparent"))

    def test_scripts_set_no_colour_or_size_inline(self):
        # The scripts could slip a colour, type size, spacing or radius past
        # the stylesheet checks by setting it on an element directly.
        inline = re.compile(
            r"\.style\.(color|background(Color)?|fontSize|font|padding\w*|margin\w*|gap|rowGap|columnGap"
            r"|border\w*|boxShadow|outline\w*|letterSpacing|lineHeight|textShadow)\s*=(?!=)"
            r"|\.style\.cssText|setAttribute\(\s*[\"']style[\"']"
            r"|setProperty\(\s*[\"'](color|background(-color)?|font(-size)?|padding[\w-]*|margin[\w-]*|gap"
            r"|border[\w-]*|box-shadow|outline[\w-]*|letter-spacing|line-height)[\"']")
        for path in (UI / "js").glob("*.js"):
            with self.subTest(file=path.name):
                self.assertEqual(inline.findall(path.read_text(encoding="utf-8")), [])
        self.assertTrue(inline.search('el.style.color = "red"'))
        self.assertTrue(inline.search("el.style.setProperty('padding', '4px')"))
        self.assertFalse(inline.search("el.style.backgroundImage = `url(${src})`"))

    def test_old_look_is_gone(self):
        # The design system finish: no --own-look- token, no rule for rows without
        # Enamel's class, and no list of rows that wore the old look.
        for path in [*(UI / "css").glob("*.css"), *UI.glob("*.html"), *(UI / "js").glob("*.js")]:
            text = path.read_text(encoding="utf-8")
            with self.subTest(file=path.name):
                self.assertNotIn("--own-look-", text)
                self.assertNotIn(":not(.en-row)", text)
                self.assertNotIn("OWN_LOOK", text)
        self.assertNotIn("Old look", TOKENS.read_text(encoding="utf-8"))


class NoLooseSizesTest(unittest.TestCase):
    def test_sizes_come_from_tokens(self):
        allowed = LAYOUT_TOKENS | DEFAULTS_TOKENS
        checked = 0
        for names, decls in rules(DEFAULTS):
            extra = set()
            if ".kettle-logo" in names or '.loading-screen [data-role="label"]' in names:
                extra = WORDMARK_TOKENS
            for prop, value in decls:
                if not SIZE_PROPS.match(prop):
                    continue
                checked += 1
                with self.subTest(selector=names[0], prop=prop):
                    self.assertEqual(leftover(value, allowed | extra), [], f"{names[0]} {{ {prop}: {value} }}")
        self.assertGreater(checked, 55)

    def test_the_check_catches_loose_sizes(self):
        self.assertTrue(leftover("1rem", LAYOUT_TOKENS))
        self.assertTrue(leftover("calc(var(--en-space-gap) + 2px)", LAYOUT_TOKENS))
        self.assertTrue(leftover("var(--space-3)", LAYOUT_TOKENS))
        self.assertFalse(leftover("0 calc(-1 * var(--en-space-gutter)) var(--en-space-inset)", LAYOUT_TOKENS))


class OldTokensGoneTest(unittest.TestCase):
    def test_app_declares_only_the_listed_tokens(self):
        tokens = set(re.findall(r"(?<![\w-])(--[\w-]+)\s*:", strip_comments(TOKENS.read_text(encoding="utf-8"))))
        self.assertEqual(tokens, WORDMARK_TOKENS | LAYOUT_TOKENS)
        defaults = set(re.findall(r"(?<![\w-])(--[\w-]+)\s*:", strip_comments(DEFAULTS.read_text(encoding="utf-8"))))
        self.assertEqual(defaults, DEFAULTS_TOKENS)

    def test_nothing_uses_a_removed_token(self):
        for path in [*(UI / "css").glob("*.css"), *UI.glob("*.html"), *(UI / "js").glob("*.js")]:
            used = set(re.findall(r"--[\w-]+", path.read_text(encoding="utf-8")))
            with self.subTest(file=path.name):
                self.assertEqual(used & REMOVED_TOKENS, set())

    def test_every_app_token_used_is_declared(self):
        # A removed variable that something still used would leave a blank.
        declared = WORDMARK_TOKENS | LAYOUT_TOKENS | DEFAULTS_TOKENS
        for path in (UI / "css").glob("*.css"):
            used = set(re.findall(r"var\((--[\w-]+)", path.read_text(encoding="utf-8")))
            with self.subTest(file=path.name):
                self.assertEqual({u for u in used if not u.startswith("--en-")} - declared, set())

    def test_every_enamel_token_used_exists(self):
        kettle = set(re.findall(r"(--en-[\w-]+)\s*:", (ROOT / "vendor" / "enamel" / "tokens" / "enamel.css").read_text()))
        kettle |= set(re.findall(r"(--en-[\w-]+)\s*:",
                                 (ROOT / "vendor" / "enamel" / "components" / "enamel-components.css").read_text()))
        for path in (UI / "css").glob("*.css"):
            used = set(re.findall(r"var\((--en-[\w-]+)", path.read_text(encoding="utf-8")))
            with self.subTest(file=path.name):
                self.assertEqual(used - kettle, set())

    def test_removed_tokens_listed_in_the_spec(self):
        spec = (ROOT / "docs" / "spec.md").read_text(encoding="utf-8")
        section = spec[spec.index("### Tokens removed in the last design system step"):]
        for name in sorted(REMOVED_TOKENS):
            self.assertIn(f"`{name}`", section, name)


if __name__ == "__main__":
    unittest.main()
