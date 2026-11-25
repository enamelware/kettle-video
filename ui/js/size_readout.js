// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Mario Carabotta

// The size readout (the sizing spike), a developer option: off unless
// settings.json has "debug_size_readout": true.
//
// It measures the window and the screen once, at start, for one line in the
// launch log. It reads the screen's size only to report it: nothing here
// changes the page, and no layout depends on these numbers (CLAUDE.md, "No
// layout is tied to a screen size"). Firefox gives a page no separate zoom
// value; its zoom is part of the device pixel ratio, and the log line says so.

// The sizes, in CSS pixels, and the device pixel ratio.
export function measureSizes() {
  return {
    window_width: window.innerWidth,
    window_height: window.innerHeight,
    device_pixel_ratio: window.devicePixelRatio,
    screen_width: window.screen.width,
    screen_height: window.screen.height,
  };
}
