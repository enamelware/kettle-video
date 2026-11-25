# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Smoke test: guessit loads from vendor/, not from a system install.

Run from the repo root:  python3 -m unittest discover -s tests -t .
"""

import unittest
from pathlib import Path

from backend.vendor_path import use_vendor

VENDOR_DIR = use_vendor()

import guessit  # noqa: E402  (must come after use_vendor)


class VendoredGuessitTest(unittest.TestCase):
    def test_packages_come_from_vendor(self):
        import babelfish
        import dateutil
        import rebulk
        import six

        for module in (guessit, rebulk, babelfish, dateutil, six):
            with self.subTest(module=module.__name__):
                path = Path(module.__file__).resolve()
                self.assertTrue(
                    path.is_relative_to(VENDOR_DIR),
                    f"{module.__name__} was imported from {path}, not from {VENDOR_DIR}",
                )

    def test_tv_episode(self):
        result = guessit.guessit("Show.Name.S02E05.720p.WEB-DL.x264-GRP.mkv")
        self.assertEqual(result.get("season"), 2)
        self.assertEqual(result.get("episode"), 5)

    def test_movie_year(self):
        result = guessit.guessit("Another Movie (2011).mkv")
        self.assertEqual(result.get("year"), 2011)


if __name__ == "__main__":
    unittest.main()
