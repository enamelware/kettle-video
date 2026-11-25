# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Every screen with Firefox's default text size at 200% (the Enamel 0.11.0 upgrade), in a
real, headless Firefox. Not part of the unit tests: it needs Firefox and
takes about a minute.

Enamel never sets the root font size, so 1rem is the viewer's own text size,
and every part of the app must hold together at 200%: rows grow taller rather
than cutting text, the narrow layouts take over where text would be squeezed,
and nothing overlaps or is cut off. This runs tests/design_system_check.py,
the same screens, window widths and checks, with Firefox's text size doubled
as a viewer would set it in Firefox's settings, at every window size that
holds Enamel's smallest supported box at that text size (20rem by 15rem, so
640 by 480 and larger at 200%; below it Enamel only asks that the page
scrolls). design_system_check.py itself is the run at the normal size.

Screenshots go to the folder given as the first argument (default: a
temporary folder).

Run from the repo root:  python3 tests/text_size_check.py [screenshot-dir]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests import design_system_check  # noqa: E402

if __name__ == "__main__":
    sys.exit(design_system_check.main(size=200))
