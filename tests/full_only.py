# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Marks a test that runs only in the full check, not the quick one.

For the timing tests, which only print how long a large invented library
takes and cost most of the unit suite's time. `scripts/test.sh` (quick)
sets KETTLE_QUICK=1 to skip them; `scripts/test.sh full`, and running
unittest directly, run them as before (see CLAUDE.md, "How we work").
"""

import os
import unittest

full_only = unittest.skipIf(
    os.environ.get("KETTLE_QUICK") == "1",
    "timing only: runs in the full check (scripts/test.sh full)",
)
