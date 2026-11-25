# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Brand colour checks (the Brand v0.1 work, the Home shell work and the last design system step). Since the last design system step the app
takes every colour from Enamel, except the Mustard wordmark and the old
look kept for Scan my folders (ui/css/tokens.css). Checks: their contrast on
the colours they sit on (Enamel's read from
vendor/enamel/tokens/enamel.css), no red text, the olive shades the Home shell work
removed stay gone, and no muted text on a focused row.

Run from the repo root:  python3 -m unittest discover -s tests -t . -v
"""

import re
import unittest
from pathlib import Path

UI = Path(__file__).resolve().parent.parent / "ui"
UI_CSS = UI / "css"
TOKENS = UI_CSS / "tokens.css"
DEFAULTS = UI_CSS / "defaults.css"
ENAMEL_TOKENS = UI.parent / "vendor" / "enamel" / "tokens" / "enamel.css"

MUSTARD = "#E4A83A"  # the wordmark, the one brand colour left (the last design system step)

# The dark olive shades the Home shell work removed: nothing may use them any more.
REMOVED_SHADES = ("#1A1C16", "#24271F", "#33372C")

TEXT = 4.5  # WCAG AA, normal text


def enamel_tokens() -> dict:
    """Enamel's --en-* tokens as first declared (the default accent)."""
    found = {}
    for name, value in re.findall(r"(--en-[\w-]+)\s*:\s*([^;]+);", ENAMEL_TOKENS.read_text()):
        found.setdefault(name, value.strip())
    return found


def read_tokens(path=TOKENS) -> dict:
    """Every token the app declares, plus Enamel's, with var() references
    followed to a hex value where there is one."""
    raw = {name: value.strip() for name, value in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", path.read_text())}
    raw.update(enamel_tokens())

    def resolve(name, seen=()):
        value = raw[name]
        ref = re.fullmatch(r"var\((--[\w-]+)\)", value)
        if ref:
            if ref.group(1) in seen:
                raise ValueError(f"token loop at {name}")
            return resolve(ref.group(1), seen + (name,))
        return value.upper()

    return {name: resolve(name) for name in raw}


def luminance(hex_colour: str) -> float:
    channels = [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


# (foreground, background, minimum): the wordmark on the loading screen. The
# old look kept for Scan my folders went in the design system finish (Enamel's button now).
REQUIRED_PAIRS = [
    ("--color-wordmark", "--en-surface-page", TEXT),
]


class PaletteTest(unittest.TestCase):
    def setUp(self):
        self.tokens = read_tokens()

    def test_wordmark_stays_mustard(self):
        self.assertEqual(self.tokens["--color-wordmark"], MUSTARD)

    def test_contrast(self):
        for fg, bg, minimum in REQUIRED_PAIRS:
            ratio = contrast(self.tokens[fg], self.tokens[bg])
            self.assertGreaterEqual(ratio, minimum, f"{fg} on {bg}: {ratio:.2f}")


class ColourUseTest(unittest.TestCase):
    """Danger red is never text, the removed shades are gone, and the
    focused row has no muted text. (No colour values outside the tokens:
    tests/test_design_system_tokens.py.)"""

    def setUp(self):
        self.css = DEFAULTS.read_text()

    def declarations(self):
        return re.findall(r"(?<![\w-])([\w-]+)\s*:\s*([^;{}]+);", self.css)

    def rules(self):
        css = re.sub(r"/\*.*?\*/", "", self.css, flags=re.S)
        return [(sel.strip(), body) for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css)]

    def test_no_red_text(self):
        for prop, value in self.declarations():
            if prop == "color":
                self.assertNotIn("--en-danger", value)
                self.assertNotIn("--en-red", value)

    def test_removed_shades_gone(self):
        text = TOKENS.read_text().upper()
        for shade in REMOVED_SHADES:
            self.assertNotIn(shade, text)

    def test_no_fog_on_focused_row(self):
        # Since the third design system step the list rows are Enamel's: on the focused row
        # every muted line steps up to soft text (vendor/enamel/DESIGN.md),
        # never stays muted (Fog or Enamel's muted).
        fog = {"--en-text-muted"}
        muted = (".row-label", ".row-year", ".row-subtitle", ".row-note", ".row-path")
        covered = set()
        for selectors, body in self.rules():
            for selector in selectors.split(","):
                selector = selector.strip()
                if ":focus" not in selector or ".file-row" not in selector:
                    continue
                colours = re.findall(r"(?<![\w-])color\s*:\s*var\((--[\w-]+)\)", body)
                self.assertFalse(set(colours) & fog, f"muted text on a focused row: {selector}")
                if colours and colours[-1] == "--en-text-soft" and ".en-row" in selector:
                    covered.update(m for m in muted if selector.endswith(m))
        self.assertEqual(covered, set(muted), "every secondary line turns soft on a focused row")

def report() -> str:
    tokens = read_tokens()
    return "\n".join(
        f"{fg} on {bg}: {contrast(tokens[fg], tokens[bg]):.1f} to 1 (needs {minimum:g})"
        for fg, bg, minimum in REQUIRED_PAIRS
    )


if __name__ == "__main__":
    print(report())
