# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The size readout (the sizing spike): one log line, at start, saying how big the
page is and how the screen is scaled. Pure logic, no HTTP awareness.

Developer only, off unless settings.json has "debug_size_readout": true.
The page measures and sends the numbers; this module checks them and
writes them as fixed words and numbers, so nothing the page made up
reaches the log. Sizes only: no titles, folders or paths.

Firefox gives a page no separate zoom value: its zoom is part of the
device pixel ratio (at 150% zoom the ratio is 1.5 and every CSS size
shrinks to match). The line says so instead of inventing a number.
"""

import math
from typing import Mapping

SETTING = "debug_size_readout"

# The page sends window_width, window_height, screen_width and screen_height
# in CSS pixels, and device_pixel_ratio. Far beyond any real screen, so a broken measurement is refused rather
# than written down.
MAX_CSS_PX = 100_000
MAX_RATIO = 16


def _number(values: Mapping, key: str, most: float) -> float:
    value = values.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a number")
    if not math.isfinite(value) or not 0 < value <= most:
        raise ValueError(f"{key} is out of range")
    return value


def _px(value: float) -> str:
    """A size as a whole number when it is one, else to one decimal."""
    return str(int(value)) if value == int(value) else f"{value:.1f}"


def _ratio(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def line(values: Mapping) -> str:
    """The readout line for these measurements. ValueError if one is
    missing, not a number, or not a plausible size."""
    if not isinstance(values, Mapping):
        raise ValueError("the readout must be an object")
    ww = _number(values, "window_width", MAX_CSS_PX)
    wh = _number(values, "window_height", MAX_CSS_PX)
    ratio = _number(values, "device_pixel_ratio", MAX_RATIO)
    sw = _number(values, "screen_width", MAX_CSS_PX)
    sh = _number(values, "screen_height", MAX_CSS_PX)
    return (
        f"size readout: window {_px(ww)}x{_px(wh)} CSS px; "
        f"device pixel ratio {_ratio(ratio)}; "
        f"screen {_px(sw)}x{_px(sh)} CSS px = {round(sw * ratio)}x{round(sh * ratio)} screen px; "
        "Firefox zoom: part of the device pixel ratio (Firefox doesn't report it separately)"
    )
