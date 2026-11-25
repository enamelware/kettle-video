# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta
"""No device, aspect ratio or screen size is named as a layout target (the responsive layout work).

The interface files, the docs that describe the app as it is, the /next
instructions and the browser checks must not name a screen's aspect ratio
(16:10, 4:3) or tie a device to a screen size. Device facts that aren't
about the screen (ARM, Armada, mpv as a Flatpak, Steam's settings) are fine,
and so is a video's own 16:9. The decisions log, the spikes and the audit
are history and are not checked.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

INTERFACE = sorted(p for p in (ROOT / "ui").rglob("*") if p.suffix in {".css", ".js", ".html"})
DOCS = [ROOT / "CLAUDE.md", ROOT / "README.md", ROOT / "docs" / "spec.md",
        ROOT / "docs" / "dev-environment.md", ROOT / "docs" / "device-setup.md",
        *sorted((ROOT / ".claude" / "commands").glob("*.md")),
        *sorted((ROOT / ".claude" / "agents").glob("*.md"))]
CHECKS = sorted((ROOT / "tests").glob("*_check.py")) + [ROOT / "tests" / "window_sizes.py"]

# A screen's aspect ratio, written any way: 16:10, 16x10, 16/10, 4:3, 4x3, 4/3.
SCREEN_RATIO = re.compile(r"(?<!\d)(?<!\d\.)(?:16\s*[:x/]\s*10|4\s*[:x/]\s*3)(?!\d)(?!\.\d)")
DEVICE = re.compile(r"\b(?:Steam Deck|Deck|Nova|Retroid|Armada)\b")
# Words that make a sentence about a screen's size or shape.
SCREEN_SIZE = re.compile(r"aspect ratio|screen size|resolution|\b\d{3,4}\s?[x×]\s?\d{3,4}\b|\b\d{3,4}\s?px wide\b",
                         re.IGNORECASE)


def sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n\s*\n|\n\s*[-*] ", text) if s.strip()]


def rel(path):
    return path.relative_to(ROOT).as_posix()


def ratio_hits(paths):
    return [f"{rel(p)}: {m.group(0)!r}" for p in paths for m in SCREEN_RATIO.finditer(p.read_text())]


def device_size_sentences(paths):
    return [f"{rel(p)}: {s[:120]!r}" for p in paths for s in sentences(p.read_text())
            if DEVICE.search(s) and SCREEN_SIZE.search(s)]


class NoLayoutTargets(unittest.TestCase):
    def test_interface_names_no_screen_ratio(self):
        self.assertEqual(ratio_hits(INTERFACE), [])

    def test_interface_names_no_device(self):
        hits = [f"{rel(p)}: {m.group(0)!r}" for p in INTERFACE for m in DEVICE.finditer(p.read_text())]
        self.assertEqual(hits, [])

    def test_docs_name_no_screen_ratio(self):
        self.assertEqual(ratio_hits(DOCS), [])

    def test_docs_tie_no_device_to_a_screen_size(self):
        self.assertEqual(device_size_sentences(DOCS), [])

    def test_checks_name_no_screen_ratio(self):
        self.assertEqual(ratio_hits(CHECKS), [])

    def test_check_window_sizes_are_labelled_by_width(self):
        from tests.window_sizes import SIZES, WINDOW
        self.assertEqual(list(SIZES), [f"w{w}" for w, _ in SIZES.values()])
        self.assertEqual(min(SIZES.values()), (320, 240), "starts at Enamel's smallest supported box")
        self.assertGreaterEqual(max(w for w, _ in SIZES.values()), 2560, "goes to very wide")
        self.assertIn(WINDOW, SIZES.values())

    def test_the_check_catches_what_it_should(self):
        self.assertTrue(SCREEN_RATIO.search("tested at 16:10 and 4:3"))
        self.assertTrue(SCREEN_RATIO.search('SIZES["16x10"]'))
        self.assertTrue(SCREEN_RATIO.search("the Nova is 4:3."))
        self.assertFalse(SCREEN_RATIO.search("aspect-ratio: 16 / 9"))
        self.assertFalse(SCREEN_RATIO.search("version 0.4.3 at 14:30"))
        self.assertTrue(device_size_sentences_in("The Nova's screen size is 1024x768."))
        self.assertTrue(device_size_sentences_in("Lay it out for the Deck's aspect ratio."))
        self.assertFalse(device_size_sentences_in("On the Nova, mpv is a Flatpak."))
        self.assertFalse(device_size_sentences_in("The Deck's screen turns off after a minute."))


MEDIA_QUERY = re.compile(r"@media\s*([^{]*)\{")
# Breakpoints come from the content: a width or height in rem or em, or a
# user preference. Never pixels, a device's size, its shape or its pixels.
SCREEN_FEATURE = re.compile(r"device-|aspect-ratio|orientation|resolution|\d\s*px\b", re.IGNORECASE)
# What a script would read to choose a layout from the window or screen.
SCREEN_READ = re.compile(r"\bscreen\.(?:width|height|availWidth|availHeight|orientation)\b"
                         r"|\bmatchMedia\b|\binnerWidth\b|\bouterWidth\b|\bouterHeight\b|\bdevicePixelRatio\b")
# The developer size readout (the sizing spike) reads them to write them in the
# launch log, never to choose a layout.
SIZE_READOUT = ROOT / "ui" / "js" / "size_readout.js"
# What a script would use to change the page.
PAGE_CHANGE = re.compile(r"\bdocument\b|\.style\b|classList|dataset|setAttribute|innerHTML|textContent"
                         r"|\.hidden\b|setProperty|\bfetch\b")


def media_queries(paths):
    return [(rel(p), q.strip()) for p in paths if p.suffix == ".css" for q in MEDIA_QUERY.findall(p.read_text())]


class NoScreenSizedLayout(unittest.TestCase):
    """The responsive layout work, "Done when": the app's own styles hold no media query named
    after a device or a screen, and no script chooses a layout from the
    window's or the screen's size."""

    def test_media_queries_come_from_the_content(self):
        bad = [(f, q) for f, q in media_queries(INTERFACE) if SCREEN_FEATURE.search(q)]
        self.assertEqual(bad, [])

    def test_media_queries_use_rem_or_em_sizes(self):
        for f, q in media_queries(INTERFACE):
            for value in re.findall(r"(?:min|max)-(?:width|height)\s*:\s*([^)]*)\)", q):
                self.assertRegex(value.strip(), r"^\d+(?:\.\d+)?r?em$", f"{f}: @media {q}")

    def test_no_script_reads_the_screen_size(self):
        scripts = [p for p in INTERFACE if p.suffix == ".js" and p != SIZE_READOUT]
        self.assertTrue(scripts)
        hits = [f"{rel(p)}: {m.group(0)}" for p in scripts for m in SCREEN_READ.finditer(p.read_text())]
        self.assertEqual(hits, [])

    def test_the_size_readout_only_reports(self):
        """The sizing spike: the one script that reads the screen's size only
        returns the numbers for the launch log. It changes nothing on the
        page, imports nothing, and only app.js uses it, to send them."""
        text = SIZE_READOUT.read_text()
        self.assertTrue(SCREEN_READ.search(text), "it measures the window and the screen")
        self.assertEqual(PAGE_CHANGE.findall(text), [])
        self.assertNotIn("import ", text)
        users = [rel(p) for p in INTERFACE if p != SIZE_READOUT and "size_readout.js" in p.read_text()]
        self.assertEqual(users, ["ui/js/app.js"])
        app = (ROOT / "ui" / "js" / "app.js").read_text()
        calls = re.findall(r"^.*measureSizes\(\).*$", app, re.MULTILINE)
        self.assertEqual(calls, ["  if (info.size_readout) api.postSizeReadout(measureSizes()).catch(() => {});"])

    def test_the_checks_catch_what_they_should(self):
        self.assertTrue(SCREEN_FEATURE.search("(max-width: 1280px)"))
        self.assertTrue(SCREEN_FEATURE.search("(min-aspect-ratio: 16/10)"))
        self.assertTrue(SCREEN_FEATURE.search("(orientation: portrait)"))
        self.assertFalse(SCREEN_FEATURE.search("(max-height: 21rem)"))
        self.assertFalse(SCREEN_FEATURE.search("(prefers-reduced-motion: reduce)"))
        self.assertTrue(SCREEN_READ.search("if (window.innerWidth < 800) compact();"))
        self.assertTrue(SCREEN_READ.search("matchMedia('(max-width: 40rem)')"))
        self.assertFalse(SCREEN_READ.search("window.scrollBy(0, window.innerHeight / 2);"))


class DecisionsLog(unittest.TestCase):
    """The responsive layout work: the decisions log has the new entry, and the earlier
    entries that named the screens as targets are kept, marked as replaced."""

    TEXT = (ROOT / "docs" / "decisions.md").read_text(encoding="utf-8")

    def entry(self, heading_part):
        parts = re.split(r"(?m)^## ", self.TEXT)
        found = [p for p in parts if p.splitlines()[0].find(heading_part) >= 0]
        self.assertEqual(len(found), 1, heading_part)
        return found[0]

    def test_new_entry(self):
        entry = self.entry("No layout is tied to a screen size, a device or an aspect ratio (the responsive layout work)")
        self.assertIn("20rem wide by 15rem tall", entry)
        self.assertIn("Text doesn't scale with width", entry)

    def test_old_screen_entries_are_kept_and_marked_replaced(self):
        old = self.entry("Development moves to the Steam Deck")
        self.assertIn("4:3", old, "the old entry is kept as it was")
        self.assertIn("*Replaced on 2026-10-22 by \"No layout is tied to a screen size", old)


def device_size_sentences_in(text):
    return [s for s in sentences(text) if DEVICE.search(s) and SCREEN_SIZE.search(s)]


if __name__ == "__main__":
    unittest.main()
