# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The quick and full checks (CLAUDE.md, "How we work"): the timing tests run
only in full, scripts/test.sh refuses checks that don't exist, and a pass is
remembered outside the repo against the exact code.

Doesn't run the suite from inside the suite: it only runs scripts/test.sh
with arguments it refuses before testing anything.

Run: scripts/test.sh unit tests.test_quick_and_full
"""

import importlib
import os
import subprocess
import unittest
from unittest import mock

from tests import full_only, test_library_movies, test_library_rescan, test_library_tv, test_parser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEST_SH = os.path.join(ROOT, "scripts", "test.sh")

TIMING_TESTS = [
    test_library_rescan.TimingTest,
    test_library_movies.MovieGroupingTimingTest,
    test_parser.TimingTest,
    test_library_tv.TvGroupingTimingTest,
]


def run(*args):
    return subprocess.run([TEST_SH, *args], capture_output=True, text=True, timeout=30)


class TimingTestsRunInFullOnly(unittest.TestCase):
    def marker(self, quick):
        env = {"KETTLE_QUICK": "1"} if quick else {}
        with mock.patch.dict(os.environ, env, clear=False):
            if not quick:
                os.environ.pop("KETTLE_QUICK", None)
            return importlib.reload(full_only).full_only

    def tearDown(self):
        importlib.reload(full_only)

    def test_skipped_in_quick(self):
        @self.marker(quick=True)
        class Timing(unittest.TestCase):
            def test_it(self):
                pass
        result = unittest.TestResult()
        Timing("test_it").run(result)
        self.assertEqual(len(result.skipped), 1)

    def test_run_otherwise(self):
        @self.marker(quick=False)
        class Timing(unittest.TestCase):
            def test_it(self):
                pass
        result = unittest.TestResult()
        Timing("test_it").run(result)
        self.assertEqual((result.testsRun, len(result.skipped)), (1, 0))

    def test_the_timing_tests_are_marked(self):
        for cls in TIMING_TESTS:
            with self.subTest(test=cls.__qualname__):
                path = os.path.join(ROOT, cls.__module__.replace(".", os.sep) + ".py")
                with open(path, encoding="utf-8") as f:
                    self.assertIn(f"@full_only\nclass {cls.__name__}(", f.read())


class TestScript(unittest.TestCase):
    def test_refuses_a_check_that_does_not_exist(self):
        for args in (["quick", "no_such_check"], ["no_such_check"], ["quick", "../backend/server"],
                     ["full", "extra"], ["check", "test_parser"], ["nonsense"]):
            with self.subTest(args=args):
                self.assertEqual(run(*args).returncode, 2)

    def test_passes_are_remembered_in_gits_folder_not_the_repo(self):
        with open(TEST_SH, encoding="utf-8") as f:
            text = f.read()
        self.assertIn('RESULTS="$(git rev-parse --git-common-dir)/kettle-test-results"', text)
        # The code key uses its own index, so nothing is ever staged.
        self.assertIn('GIT_INDEX_FILE="$index" git add -A', text)
        self.assertIn("KETTLE_QUICK=1 python3 -m unittest discover", text)


if __name__ == "__main__":
    unittest.main()
