# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Check the Continue watching row's layout in a real, headless Firefox
(the tile alignment work): the tiles stand on one shared bottom edge, like Steam's Recent
games row. Not part of the unit tests: it needs Firefox (and ffmpeg, to
make a test picture).

The server's Continue watching answer is replaced by invented tiles (one
tile, then six: a missing one, one with no picture, long names), so no
playback is needed. At every window width in tests/window_sizes.py (issue
The responsive layout work), with one tile and with six, it
measures: every frame and progress bar ends on the same line, the large
tile rises above the small ones, the large tile's caption starts at its
left edge on the line under the row, the small tiles' names sit on that
same line, the focus ring of the large tile and of a small one is fully
inside the row (not clipped top or bottom), and the row stays above the
tabs with no sideways page scroll. Screenshots go to the folder given as
the first argument.

Run from the repo root:  python3 tests/continue_row_layout_check.py [screenshot-dir]
"""

import subprocess
import sys
import threading
import time
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from backend import server  # noqa: E402
from backend.server import make_handler  # noqa: E402
from tests.continue_watching_check import carousel  # noqa: E402
from tests.loading_screen_check import UI_DIR  # noqa: E402
from tests.window_sizes import SIZES, WINDOW, set_window  # noqa: E402
from tests.saved_library_check import ENTER, main, wait_state  # noqa: E402
from tests.test_parsed_library import MOVIE_FILES, TV_FILES  # noqa: E402

RIGHT, LEFT = "\ue014", "\ue012"

# Where each tile's parts are, and how far the focus ring reaches out from
# a frame (Enamel's ring since the third design system step: its offset plus its width),
# measured in the page. The caption may start a fraction of a pixel above
# the frame's bottom line (rounding), hence the half-pixel slack below.
LAYOUT_JS = """
const section = document.getElementById('continue-watching');
const row = section.querySelector('.continue-row');
const tiles = [...section.querySelectorAll('.continue-tile')];
const box = (el) => { const b = el.getBoundingClientRect(); return {left: b.left, right: b.right, top: b.top, bottom: b.bottom, width: b.width, height: b.height}; };
const probe = document.createElement('div');
probe.style.width = 'calc(var(--en-focus-ring-offset) + var(--en-focus-ring-width))';
document.body.appendChild(probe);
const ringReach = probe.getBoundingClientRect().width;
probe.remove();
const tabs = document.getElementById('tab-strip');
// Since Enamel 0.5.0 (the Enamel 0.5.0 upgrade) the focused tile grows a little around
// its centre. The shared bottom line is the layout's, so the line-up checks
// use each part as laid out, before that growth ("frames" replaces the
// drawn boxes); the ring check uses the frames as drawn, ring grown too.
const scaleOf = (t) => new DOMMatrix(getComputedStyle(t).transform).a;
const laidOut = (t, el) => {
  const k = scaleOf(t), o = t.getBoundingClientRect(), b = el.getBoundingClientRect();
  const cx = o.left + o.width / 2, cy = o.top + o.height / 2;
  return {left: cx + (b.left - cx) / k, right: cx + (b.right - cx) / k, top: cy + (b.top - cy) / k,
          bottom: cy + (b.bottom - cy) / k, width: b.width / k, height: b.height / k};
};
return {
  row: box(row),
  heading: box(section.querySelector('.continue-heading')),
  frames: tiles.map(t => laidOut(t, t.querySelector('.continue-frame'))),
  drawnFrames: tiles.map(t => box(t.querySelector('.continue-frame'))),
  scales: tiles.map(scaleOf),
  progressBars: tiles.map(t => laidOut(t, t.querySelector('.continue-progress'))),
  captionBoxes: tiles.map(t => { const c = t.querySelector('.continue-caption'); return getComputedStyle(c).display === 'none' ? null : laidOut(t, c); }),
  ringReach,
  tabsBox: box(tabs),
};
"""

FRAME_JPG = None  # the test picture's bytes, made once with ffmpeg


def item(n, name, caption, picture=True, missing=False, share=0.5):
    return {"id": f"m{n}", "kind": "movie", "title": name, "label": "", "name": name, "caption": caption,
            "position": 3600 * share, "duration": 3600.0, "missing": missing,
            "picture": f"/api/continue/picture/k{n}" if picture else None}


SIX = [
    item(1, "Other Movie", "Other Movie · Resume at 30:00 · 90 min left", share=0.25),
    item(2, "Example Film · Part 2", "", share=0.6),
    item(3, "A Very Long Film Title That Needs Two Lines Under Its Tile", "", share=0.1),
    item(4, "Gone Film", "", missing=True, share=0.8),
    item(5, "No Picture Film", "", picture=False, share=0.4),
    item(6, "Test Show · S2 E5", "", share=0.9),
]
ONE = SIX[:1]


class App:
    """One server whose Continue watching answer is `self.items`."""

    def __init__(self, settings, logs_dir):
        httpd_ref = {}
        self.items = []
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        self.port = self.httpd.server_address[1]
        self.patches = [mock.patch.object(server, "_log", lambda line: None)]
        for patch in self.patches:
            patch.start()
        base = make_handler(UI_DIR, logs_dir, settings, httpd_ref, self.port)
        app = self

        class Handler(base):
            def log_message(self, format, *args):
                pass

            def _handle_mpv_status(self):
                self._send_json(HTTPStatus.OK, {"available": True})

            def _handle_continue(self):
                self._send_json(HTTPStatus.OK, {"items": app.items})

            def _handle_picture(self):
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(FRAME_JPG)))
                self.end_headers()
                self.wfile.write(FRAME_JPG)

        self.httpd.RequestHandlerClass = Handler
        httpd_ref["server"] = self.httpd
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        for patch in self.patches:
            patch.stop()


def state(m):
    m.settle()  # measure once the focus has finished moving (the Enamel 0.5.0 upgrade)
    return {**carousel(m), **m.js(LAYOUT_JS)}


def ring_inside(s, i):
    """True when tile i's ring, as drawn (grown with a focused tile), is inside the row."""
    return inside(s["drawnFrames"][i], s["ringReach"] * s["scales"][i], s["row"])


def wait(m, predicate, timeout):
    end = time.time() + timeout
    while time.time() < end:
        s = state(m)
        if predicate(s):
            return s
        time.sleep(0.2)
    return state(m)


def close(a, b, slack=0.6):
    return abs(a - b) <= slack


def inside(frame, reach, area):
    """True when a ring `reach` pixels around `frame` fits inside `area`."""
    return (frame["top"] - reach >= area["top"] - 0.5 and frame["bottom"] + reach <= area["bottom"] + 0.5
            and frame["left"] - reach >= area["left"] - 0.5 and frame["right"] + reach <= area["right"] + 0.5)


def check_layout(m, check, shots_dir, label, focus_small):
    import base64
    for size, (w, h) in SIZES.items():
        set_window(m, w, h)
        time.sleep(0.5)
        s = wait(m, lambda s: s["shown"], 3)
        frames, bars, caps = s["frames"], s["progressBars"], s["captionBoxes"]
        n = len(frames)
        tag = f"{label}, {size}"
        bottom = frames[0]["bottom"]
        check(f"{tag}: every frame ends on the same bottom line",
              all(close(f["bottom"], bottom) for f in frames), frames)
        check(f"{tag}: every progress bar ends on that line too",
              all(close(b["bottom"], bottom) for b in bars) and all(close(b["height"], bars[0]["height"]) for b in bars),
              bars)
        if n > 1:
            check(f"{tag}: the large tile rises above the small ones",
                  all(frames[0]["top"] < f["top"] - 10 for f in frames[1:]), frames)
        large_cap = caps[0]
        check(f"{tag}: the large tile's caption is under the row, starting at its left edge",
              large_cap is not None and close(large_cap["left"], frames[0]["left"])
              and large_cap["top"] >= bottom - 0.5 and large_cap["right"] <= frames[0]["right"] + 0.5, [large_cap, frames[0]])
        small_caps = [c for c in caps[1:] if c is not None]
        check(f"{tag}: the small tiles' names start on the same line as the large caption",
              all(close(c["top"], large_cap["top"]) for c in small_caps), caps)
        check(f"{tag}: heading above the row, row above the tabs, no sideways page scroll",
              s["heading"]["bottom"] <= frames[0]["top"]
              and max(c["bottom"] for c in caps if c is not None) < s["tabsTop"] and not s["overflowX"], s)
        # In Enamel's smallest box the page scrolls to reach the tabs;
        # from there up the row and the tabs fit on one screen.
        if size != min(SIZES, key=lambda k: SIZES[k]):
            check(f"{tag}: the tabs are on screen under the row", s["tabsBox"]["bottom"] <= s["viewportH"], s)
        # The large tile has the focus first: its ring sits wholly inside the row.
        check(f"{tag}: the large tile's focus ring is not clipped ({s['ringReach']:.1f} px)",
              s["focusedTile"] == 0 and ring_inside(s, 0), [s["drawnFrames"][0], s["scales"][0], s["row"]])
        (shots_dir / f"{label}-large-focus-{size}.png").write_bytes(
            base64.b64decode(m.send("WebDriver:TakeScreenshot", {})["value"]))
        if focus_small:
            # The first key after the page opens can go astray in headless
            # Firefox; press again if the focus didn't move.
            for _ in range(2):
                m.press(RIGHT)
                s = wait(m, lambda s: s["focusedTile"] == 1, 2)
                if s["focusedTile"] == 1:
                    break
            check(f"{tag}: a small tile's focus ring is not clipped",
                  s["focusedTile"] == 1 and ring_inside(s, 1), [s["focusedTile"], s["drawnFrames"][1], s["row"]])
            (shots_dir / f"{label}-small-focus-{size}.png").write_bytes(
                base64.b64decode(m.send("WebDriver:TakeScreenshot", {})["value"]))
            # The last tile, after the row has scrolled sideways.
            for _ in range(n):
                m.press(RIGHT)
            s = wait(m, lambda s: s["focusedTile"] == n - 1 and s["inView"][-1] > 0.99, 3)
            check(f"{tag}: the row scrolls to the last tile and its ring is not clipped",
                  s["focusedTile"] == n - 1 and ring_inside(s, n - 1),
                  [s["drawnFrames"][-1], s["row"]])
            (shots_dir / f"{label}-last-focus-{size}.png").write_bytes(
                base64.b64decode(m.send("WebDriver:TakeScreenshot", {})["value"]))
            for _ in range(n):
                m.press(LEFT)  # back to the large tile
            wait(m, lambda s: s["focusedTile"] == 0, 3)
    set_window(m, *WINDOW)
    time.sleep(0.3)


def run(m, tmp, shots_dir, check):
    global FRAME_JPG
    movies, tv, data = tmp / "Movies", tmp / "TV Shows", tmp / "data"
    for base, files in ((movies, MOVIE_FILES), (tv, TV_FILES)):
        for rel in files:
            (base / rel).parent.mkdir(parents=True, exist_ok=True)
            (base / rel).write_bytes(b"")
    frame = tmp / "frame.jpg"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=960x540",
                    "-frames:v", "1", str(frame)], check=True)
    FRAME_JPG = frame.read_bytes()
    settings = {"movies_path": str(movies), "tv_path": str(tv), "mpv_command": "mpv", "mpv_args": [],
                "resume": True, "keep_awake": False, "data_dir": str(data)}
    app = App(settings, tmp)
    try:
        m.send("WebDriver:Navigate", {"url": f"http://127.0.0.1:{app.port}/"})
        wait_state(m, lambda s: not s["loading"] and (s["library"] or s["firstScan"]), 30)
        m.press(ENTER)  # Open my library
        wait_state(m, lambda s: s["library"], 30)
        for label, items in (("one-tile", ONE), ("six-tiles", SIX)):
            app.items = items
            m.send("WebDriver:Navigate", {"url": f"http://127.0.0.1:{app.port}/"})
            s = wait(m, lambda s: not s["loading"] and s["shown"] and len(s["ids"]) == len(items) and s["focusedTile"] == 0
                     and sum(s["pictures"]) == sum(1 for i in items if i["picture"]), 20)
            check(f"{label}: {len(items)} tile(s) drawn, the first large and focused",
                  len(s["ids"]) == len(items) and s["sizes"][0] == "large" and s["focusedTile"] == 0, s)
            check_layout(m, check, shots_dir, label, focus_small=len(items) > 1)
    finally:
        app.stop()


if __name__ == "__main__":
    sys.exit(main(run, prefix="continue-row-layout-"))
