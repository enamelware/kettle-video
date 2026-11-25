# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Table-driven tests for backend.parser, from tests/fixtures/names.json.

Run from the repo root:  python3 -m unittest discover -s tests -t . -v
"""

import json
import subprocess
import sys
import time
import unicodedata
import unittest
from pathlib import Path

from backend.parser import ParsedName, parse_name, title_sort_key
from tests.full_only import full_only

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "names.json").read_text("utf-8"))


def _run_python(code: str) -> str:
    return subprocess.run(
        [sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()


class ParseNameTest(unittest.TestCase):
    def check(self, case):
        result = parse_name(case["name"], case["kind"])
        for field_name, expected in case["expect"].items():
            self.assertEqual(getattr(result, field_name), expected, field_name)
        return result

    def test_cases(self):
        for case in FIXTURES["cases"]:
            with self.subTest(name=case["name"]):
                result = self.check(case)
                self.assertEqual(result.flags, case.get("flags", []), "flags")
                self.assertEqual(result.raw, case["name"], "raw")

    def test_never_raises(self):
        odd = ["", "   ", ".mkv", "[]", "....", "()", "x" * 2000, "S01E01" * 50]
        for name in odd:
            for kind in ("movie", "episode"):
                with self.subTest(name=name[:40], kind=kind):
                    result = parse_name(name, kind)
                    self.assertIsInstance(result, ParsedName)
                    self.assertEqual(result.raw, name)

    def test_bad_kind_raises(self):
        with self.assertRaises(ValueError):
            parse_name("Example Movie.mkv", "film")

    def test_import_is_lazy(self):
        loaded = _run_python("import sys, backend.parser; print('guessit' in sys.modules)")
        self.assertEqual(loaded, "False")


class NumbersInEpisodeTitleLimitsTest(unittest.TestCase):
    """The name reader fixes: when a number cuts an episode title short, the words after
    it come back only when they are plain words; tags in brackets and odd
    symbols never join the title (docs/decisions.md)."""

    def test_plain_words_after_the_number_come_back(self):
        result = parse_name("Example Show - 03 - The 100 Doors, Again.mkv", "episode")
        self.assertEqual((result.season, result.episode), (None, 3))
        self.assertEqual(result.episode_title, "The 100 Doors, Again")

    def test_bracket_tag_after_the_words_stays_out(self):
        for name in ("Example Show - 03 - The 100 Doors {x} Here.mkv",
                     "Example Show - 03 - The 100 Doors (Extended Cut).mkv",
                     "Example Show - 11 - 511 Example Place (Extended Cut).mkv"):
            with self.subTest(name=name):
                title = parse_name(name, "episode").episode_title or ""
                for ch in "{}()":
                    self.assertNotIn(ch, title)

    def test_odd_symbols_after_the_number_keep_the_reader_s_own_title(self):
        # "+" is not a plain word, so nothing after the number is pulled in.
        result = parse_name("Example Show - 03 - The 100 Doors + More.mkv", "episode")
        self.assertEqual(result.episode, 3)
        self.assertNotIn("+", result.episode_title or "")


class TitleSortKeyTest(unittest.TestCase):
    def test_accents_sort_with_plain_letters(self):
        titles = ["Zeta Example", "Élan Example", "echo Example", "Ever Example", "Delta Example"]
        self.assertEqual(
            sorted(titles, key=title_sort_key),
            ["Delta Example", "echo Example", "Élan Example", "Ever Example", "Zeta Example"],
        )

    def test_decomposed_accent_sorts_like_composed(self):
        mac = unicodedata.normalize("NFD", "Élan Example")
        self.assertEqual(title_sort_key(mac), title_sort_key("Élan Example"))

    def test_order_is_stable_for_titles_that_differ_only_by_accent(self):
        self.assertLess(title_sort_key("Elan Example"), title_sort_key("Élan Example"))

    def test_empty_title(self):
        self.assertEqual(title_sort_key(""), ("", ""))


# Average measured on the Retroid Pocket Nova after parser chunk 2.
CHUNK2_NOVA_MS = 7.6


@full_only
class TimingTest(unittest.TestCase):
    """Informational only: prints timings, asserts nothing."""

    def test_timing(self):
        first = _run_python(
            "import time; t = time.perf_counter(); from backend.parser import parse_name; "
            "parse_name('Example.Movie.1995.mkv', 'movie'); print(time.perf_counter() - t)"
        )

        patterns = [
            ("Example.Movie.{n}.{y}.1080p.BluRay.x264-GRP.mkv", "movie"),
            ("Another Example Film {n} ({y}).mp4", "movie"),
            ("Show.Name.{n}.S{s:02}E{e:02}.720p.WEB-DL.x264-GRP.mkv", "episode"),
            ("[grp] Example Show {n} - {e:02} - Some Title [480p].mkv", "episode"),
            ("Show Name {n} - {s}x{e:02}.mkv", "episode"),
        ]
        names = []
        for i in range(500):
            pattern, kind = patterns[i % len(patterns)]
            names.append((pattern.format(n=i, y=1950 + i % 70, s=i % 9 + 1, e=i % 24 + 1), kind))

        parse_name("warm up", "movie")
        start = time.perf_counter()
        for name, kind in names:
            parse_name(name, kind)
        average_ms = (time.perf_counter() - start) / len(names) * 1000

        print(
            f"\n  parse_name timing: {average_ms:.2f} ms per name over {len(names)} names "
            f"(chunk 2 on the Nova: {CHUNK2_NOVA_MS} ms); "
            f"first call in a fresh process (import + setup): {float(first):.2f} s"
        )
