# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Storage spike (the storage spike): the report and the spike scripts hold no real
names from this device's card.

Slow check on the real library (read-only): runs spikes/storage/privacy_check.py
against docs/spikes/storage.md, docs/decisions.md and every spike script. It
collects the user name in paths and every film, show and episode name in
the folders the Question 3 rule suggests on each mounted card. Card labels
are allowed on their own (on the Nova the card's label is the device's
name, which the report uses) but still fail inside a path.

Skipped when the spike folder has been deleted or no card is mounted.

Run from the repo root:  scripts/test.sh check storage_privacy_check
"""

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPIKE = ROOT / "spikes" / "storage"


@unittest.skipUnless(SPIKE.is_dir(), "storage spike folder removed")
class StoragePrivacyCheck(unittest.TestCase):

    def test_report_and_scripts_hold_no_private_names(self):
        sys.path.insert(0, str(SPIKE))
        try:
            import drives
            labels = [p["label"] for p in drives.places() if p["label"]]
        finally:
            sys.path.remove(str(SPIKE))
        if not labels:
            self.skipTest("no card or drive mounted")
        files = [str(ROOT / "docs" / "spikes" / "storage.md"),
                 str(ROOT / "docs" / "decisions.md")]
        files += sorted(str(p) for p in SPIKE.glob("*.py"))
        allow = [arg for label in labels for arg in ("--allow", label)]
        result = subprocess.run(
            [sys.executable, "privacy_check.py", *files, *allow],
            cwd=SPIKE, capture_output=True, text=True, timeout=300)
        print(result.stdout.strip().splitlines()[-1] if result.stdout else "")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
