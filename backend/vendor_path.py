# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Make the bundled third-party packages in vendor/ importable.

Call use_vendor() before importing guessit (or anything else from vendor/).
It puts vendor/ first on sys.path, so the bundled copy wins over any copy
installed on the system. It cannot help if guessit was already imported
from somewhere else earlier in the same process.

See THIRD_PARTY_LICENSES.md for what is in vendor/.
"""

import sys
from pathlib import Path

VENDOR_DIR = Path(__file__).resolve().parent.parent / "vendor"


def use_vendor() -> Path:
    path = str(VENDOR_DIR)
    if path in sys.path:
        sys.path.remove(path)
    sys.path.insert(0, path)
    return VENDOR_DIR
