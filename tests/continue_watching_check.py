# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Drive the Continue watching carousel in a real, headless Firefox (issue
The Continue watching work). Not part of the unit tests: it needs Firefox (and ffmpeg, to make a
test picture).

Invented titles in a temporary folder and a temporary saved library. mpv
is faked: it writes what the real quit script writes (a record and a
frame), and makes the "small picture" when asked. Steps: no carousel at
first; a film stopped from the list shows up and the focus goes back to
its row; at launch the focus starts on the first tile; at every window
width in tests/window_sizes.py the tiles take Enamel's widths from the
row and a wider row shows more of them (the responsive layout work); Left, Right, Down, Up and the hint bar; A resumes and the focus
comes back to the tile; a finished film leaves; a missing file; a tap
resumes; X removes tiles one by one, down to no carousel. Prints the draw
and "back in the list" timings.

Screenshots at each window width go to the folder given as the first argument.

Run from the repo root:  python3 tests/continue_watching_check.py [screenshot-dir]
"""

import json
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
from tests.loading_screen_check import UI_DIR  # noqa: E402
from tests.window_sizes import SIZES, WINDOW, set_window  # noqa: E402
from tests.saved_library_check import DOWN, ENTER, STATE_JS, main, wait_state  # noqa: E402
from tests.test_parsed_library import MOVIE_FILES, TV_FILES  # noqa: E402

UP, RIGHT, LEFT = "", "", ""
BACKSPACE = ""

# Writes what quit_capture.lua writes, from next-stop.json beside it; run
# to shrink a picture, it copies the frame as the "small" one.
FAKE_MPV = """#!/usr/bin/env python3
import json, pathlib, shutil, sys
here = pathlib.Path(__file__).parent
args = sys.argv[1:]
for a in args:
    if a.startswith("--vo-image-outdir="):
        shutil.copyfile(args[-1], pathlib.Path(a.split("=", 1)[1], "00000001.jpg"))
        sys.exit(0)
with open(here / "played.jsonl", "a") as f:
    f.write(json.dumps(args[-1]) + "\\n")
plan = json.loads((here / "next-stop.json").read_text())
for a in args:
    if a.startswith("--script-opts-append=kettle_quit-out_dir="):
        out = pathlib.Path(a.split("kettle_quit-out_dir=", 1)[1])
        if plan.get("frame"):
            shutil.copyfile(here / "frame.jpg", out / "frame.jpg")
        (out / "record.json").write_text(json.dumps(plan["record"]))
"""

CAROUSEL_JS = """
const visible = (el) => el && !el.hidden && getComputedStyle(el).display !== 'none' && !el.closest('[hidden]');
const section = document.getElementById('continue-watching');
const tiles = [...section.querySelectorAll('.continue-tile')];
const active = document.activeElement;
const row = section.querySelector('.continue-row');
const rowBox = row.getBoundingClientRect();
const box = (el) => { const b = el.getBoundingClientRect(); return {left: b.left, right: b.right, top: b.top, bottom: b.bottom, width: b.width, height: b.height}; };
const hint = document.getElementById('hint-bar');
return {
  shown: visible(section),
  height: section.getBoundingClientRect().height,
  heading: section.querySelector('.continue-heading').textContent,
  ids: tiles.map(t => t.dataset.id),
  sizes: tiles.map(t => t.dataset.size),
  captions: tiles.map(t => t.querySelector('.continue-caption').textContent),
  pictures: tiles.map(t => { const img = t.querySelector('.continue-picture'); return !!img && img.complete && img.naturalWidth > 0; }),
  missing: tiles.map(t => t.dataset.status === 'missing'),
  missingLabels: tiles.map(t => (t.querySelector('[data-role="missing"]') || {}).textContent || ''),
  missingFilter: tiles.map(t => { const img = t.querySelector('.continue-picture'); return img ? getComputedStyle(img).filter : ''; }),
  progress: tiles.map(t => t.querySelector('.continue-progress-fill').getBoundingClientRect().width / t.querySelector('.continue-progress').getBoundingClientRect().width),
  progressColour: tiles.map(t => getComputedStyle(t.querySelector('.continue-progress-fill')).backgroundColor),
  frames: tiles.map(t => box(t.querySelector('.continue-frame'))),
  // Tile widths before the focused one grows, and the row's own width
  // (Enamel's shelf is a size container: its tiles follow its content box).
  tileWidths: tiles.map(t => t.offsetWidth),
  shelfWidth: (() => { const cs = getComputedStyle(row); return row.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight); })(),
  rem: parseFloat(getComputedStyle(document.documentElement).fontSize),
  // How much of each frame is inside the row's visible area, 0 to 1.
  inView: tiles.map(t => { const b = t.querySelector('.continue-frame').getBoundingClientRect(); return Math.max(0, Math.min(b.right, rowBox.right) - Math.max(b.left, rowBox.left)) / b.width; }),
  focusedTile: tiles.indexOf(active),
  // Enamel's accent ring (the third design system step), drawn by the tile's ::after over its frame.
  focusRing: active && tiles.includes(active) ? (() => { const cs = getComputedStyle(active, '::after');
    return cs.outlineStyle === 'solid' ? cs.outlineColor : 'none'; })() : null,
  hint: hint.innerText.replace(/\\s+/g, ' ').trim(),
  tabsTop: document.getElementById('tab-strip').getBoundingClientRect().top,
  viewportW: window.innerWidth,
  viewportH: window.innerHeight,
  activeDesc: active ? `${active.tagName}.${active.className}` : null,
  draw: performance.getEntriesByName('Continue watching: draw').map(e => e.duration),
  ready: performance.getEntriesByName('Home: ready').map(e => e.duration),
};
"""


class App:
    """One server run, like one launch of the app, with the fake mpv."""

    def __init__(self, settings, logs_dir, fake, logged):
        httpd_ref = {}
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        self.port = self.httpd.server_address[1]
        self.patches = [
            mock.patch.object(server, "_log", logged.append),
            mock.patch("backend.server.mpv.detect",
                       return_value={"available": True, "command": [str(fake)], "via": "configured"}),
        ]
        for patch in self.patches:
            patch.start()
        base = make_handler(UI_DIR, logs_dir, settings, httpd_ref, self.port)

        class Handler(base):
            def log_message(self, format, *args):
                pass

            def _handle_mpv_status(self):
                self._send_json(HTTPStatus.OK, {"available": True})

        self.httpd.RequestHandlerClass = Handler
        httpd_ref["server"] = self.httpd
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        for patch in self.patches:
            patch.stop()


def carousel(m):
    return {**m.js(STATE_JS), **m.js(CAROUSEL_JS)}


def wait(m, predicate, timeout):
    end = time.time() + timeout
    while time.time() < end:
        s = carousel(m)
        if predicate(s):
            return s
        time.sleep(0.2)
    return carousel(m)


def idle(m, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        if m.js("return fetch('/api/status').then(r => r.json())")["state"] == "idle" \
                and not m.js("return !document.getElementById('playing-status').hidden"):
            return
        time.sleep(0.2)


def shot(m, shots_dir, name):
    import base64
    for size, (w, h) in SIZES.items():
        set_window(m, w, h)
        time.sleep(0.5)
        # Headless Firefox draws a classic page scrollbar; when the resize
        # makes it appear, Firefox keeps the tiles' container sizes from
        # before it (12px wider) until the row lays out again. Lay it out
        # again, so the check measures Enamel's widths, not that leftover
        # (the Enamel 0.8.0 upgrade).
        m.js("const r = document.querySelector('.continue-row'); if (r) { r.style.display = 'none'; void r.offsetWidth; r.style.display = ''; } return true;")
        time.sleep(0.3)
        (shots_dir / f"{name}-{size}.png").write_bytes(
            base64.b64decode(m.send("WebDriver:TakeScreenshot", {})["value"]))
        yield size, carousel(m)
    set_window(m, *WINDOW)
    time.sleep(0.3)


def run(m, tmp, shots_dir, check):
    movies, tv, data = tmp / "Movies", tmp / "TV Shows", tmp / "data"
    for base, files in ((movies, MOVIE_FILES), (tv, TV_FILES)):
        for rel in files:
            (base / rel).parent.mkdir(parents=True, exist_ok=True)
            (base / rel).write_bytes(b"")
    fake = tmp / "fake" / "mpv"
    fake.parent.mkdir()
    fake.write_text(FAKE_MPV)
    fake.chmod(0o755)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=960x540",
                    "-frames:v", "1", str(fake.parent / "frame.jpg")], check=True)
    settings = {"movies_path": str(movies), "tv_path": str(tv), "mpv_command": str(fake), "mpv_args": [],
                "resume": True, "keep_awake": False, "data_dir": str(data)}
    logged = []

    def plan(position, duration=7200.0, finished=False, frame=True):
        record = {"position": position, "duration": duration, "finished": finished, "frame_saved": frame}
        (fake.parent / "next-stop.json").write_text(json.dumps({"record": record, "frame": frame}))

    def launch():
        app = App(settings, tmp, fake, logged)
        m.send("WebDriver:Navigate", {"url": f"http://127.0.0.1:{app.port}/"})
        wait_state(m, lambda s: not s["loading"] and (s["library"] or s["firstScan"]), 30)
        return app

    app = launch()
    m.press(ENTER)  # Open my library
    s = wait(m, lambda s: s["library"], 30)
    check("no carousel at first: hidden, takes no space, focus on the tabs",
          not s["shown"] and s["height"] == 0 and s["focusedTab"] == "movies", s)

    # 1. Stop a film from the list: it shows up; the focus goes back to its row.
    plan(1800)
    m.press(DOWN)
    m.press(DOWN)  # Example Film, Other Movie (no Rescan row since the Home actions work)
    s = wait(m, lambda s: s["focusedIndex"] == 1, 3)
    m.press(ENTER)
    idle(m)
    s = wait(m, lambda s: s["shown"], 5)
    check(f"stopped at 30:00: one tile, caption {s['captions']!r}",
          s["shown"] and s["captions"] == ["Other Movie · Resume at 30:00 · 90 min left"]
          and s["heading"] == "Continue watching" and s["sizes"] == ["large"], s)
    check("from the list: the focus goes back to the same row", s["focusedIndex"] == 1 and s["focusedTile"] == -1, s)
    saved = [line for line in logged if line.startswith("continue watching: stop saved in")]
    check(f"back in the list after mpv: {saved[-1:]}", bool(saved), logged)

    # 2. Stop under a minute: nothing new.
    plan(45)
    m.press(UP)
    m.press(ENTER)  # Example Film
    idle(m)
    s = wait(m, lambda s: True, 1)
    check("stopped under a minute: no tile", len(s["ids"]) == 1, s)

    # 3. More items, through the server: an episode, part 2 of a film, more episodes.
    for position, body in ((600, {"source": "tv", "path": TV_FILES[5]}),
                           (700, {"source": "movies", "path": MOVIE_FILES[1]}),
                           (800, {"source": "tv", "path": TV_FILES[2]})):
        plan(position)
        m.js(f"return fetch('/api/play', {{method: 'POST', headers: {{'Content-Type': 'application/json'}}, "
             f"body: JSON.stringify({json.dumps(body)})}}).then(r => r.json())")
        idle(m)
    app.stop()

    # 4. Launch again: the focus starts on the first tile.
    app = launch()
    s = wait(m, lambda s: s["shown"] and all(s["pictures"]), 10)
    check(f"at launch: 4 tiles, newest first, the first one large and focused: {s['captions']!r}",
          s["captions"] == ["Kiri Anime · Episode 73 · Resume at 13:20 · 107 min left", "Example Film · Part 2",
                            "Test Show · S2 E5", "Other Movie"]
          and s["sizes"] == ["large", "small", "small", "small"] and s["focusedTile"] == 0, s)
    check("every tile shows its picture", all(s["pictures"]), s)
    check(f"focused tile has Enamel's accent ring and the hint bar says {s['hint']!r}",
          s["focusRing"] == "rgb(238, 138, 114)" and s["hint"] == "A RESUME X REMOVE B QUIT", s)
    check("accent progress bars (Enamel's thin bar), one per tile, sized by the position",
          all(c == "rgb(238, 138, 114)" for c in s["progressColour"])
          and abs(s["progress"][3] - 1800 / 7200) < 0.02, s)
    check(f"draw {s['draw']} ms, Home ready {s['ready']} ms after the page opened", bool(s["draw"] and s["ready"]), s)
    in_view = []
    for size, c in shot(m, shots_dir, "carousel"):
        frames, rem, shelf = c["frames"], c["rem"], c["shelfWidth"]
        # Enamel's tile widths (the responsive layout work): two fifths of the row between
        # 10rem and 16rem, the large one three quarters between 12rem and 28.25rem (28rem before Enamel 0.8.0, the Enamel 0.8.0 upgrade).
        small = min(max(10 * rem, 0.4 * shelf), 16 * rem)
        large = min(max(12 * rem, 0.75 * shelf), 28.25 * rem)
        widths = c["tileWidths"]
        check(f"{size}: tiles take Enamel's widths from the row ({widths}; large {large:.0f}, small {small:.0f}), 16:9",
              abs(widths[0] - large) < 1.5 and all(abs(w - small) < 1.5 for w in widths[1:])
              and abs(frames[1]["width"] / frames[1]["height"] - 16 / 9) < 0.03, c)
        in_view.append((size, sum(c["inView"])))
        check(f"{size}: carousel above the tabs, no sideways page scroll",
              c["frames"][0]["bottom"] < c["tabsTop"] and not c["overflowX"], c)
    counts = [round(v, 2) for _, v in in_view]
    check(f"a wider row shows more tiles ({', '.join(f'{k}: {v:.1f}' for k, v in in_view)})",
          all(b >= a - 0.01 for a, b in zip(counts, counts[1:])) and counts[-1] > counts[0] + 1, in_view)

    # 5. Left and Right stop at the ends; Down to the tabs; Up back to the last tile.
    m.press(LEFT)
    s = wait(m, lambda s: True, 0.3)
    check("Left on the first tile stays there", s["focusedTile"] == 0, s)
    for _ in range(5):
        m.press(RIGHT)
    s = wait(m, lambda s: s["focusedTile"] == 3, 3)
    check("Right moves along and stops at the last tile, no letter jump",
          s["focusedTile"] == 3 and s["inView"][3] > 0.99, s)
    m.press(DOWN)
    s = wait(m, lambda s: s["focusedTab"] is not None, 3)
    check(f"Down goes to the tabs; the hint bar says {s['hint']!r}",
          s["focusedTab"] == "movies" and s["hint"] == "A SELECT B QUIT", s)
    m.press(UP)
    s = wait(m, lambda s: s["focusedTile"] >= 0, 3)
    check("Up from the tabs goes back to the last tile", s["focusedTile"] == 3, s)
    # At 640 wide the last tile starts out of view; moving onto it scrolls the row.
    set_window(m, *SIZES["w640"])
    time.sleep(0.5)
    m.press(LEFT)
    m.press(LEFT)
    m.press(RIGHT)
    m.press(RIGHT)
    s = wait(m, lambda s: s["focusedTile"] == 3 and s["inView"][3] > 0.99, 3)
    check("w640: moving onto the last tile scrolls the row to show it", s["inView"][3] > 0.99, s)
    for size, c in shot(m, shots_dir, "carousel-last-tile"):
        check(f"{size}: last tile focused, no sideways page scroll", c["focusedTile"] == 3 and not c["overflowX"], c)

    # 6. A resumes the tile; the focus comes back to it, now first.
    resumed_id = s["ids"][3]
    plan(2400)
    m.press(ENTER)
    idle(m)
    s = wait(m, lambda s: s["ids"] and s["ids"][0] == resumed_id and s["focusedTile"] == 0, 5)
    played = (fake.parent / "played.jsonl").read_text().splitlines()
    check("A resumes the same file, and its tile comes first with the focus",
          played[-1].endswith(json.dumps(MOVIE_FILES[2])[1:]) and s["ids"][0] == resumed_id
          and s["focusedTile"] == 0 and s["captions"][0].startswith("Other Movie · Resume at 40:00"), [s, played[-1:]])

    # 7. Finish it: it leaves, the focus goes to the first tile.
    plan(None, finished=True, frame=False)
    m.press(ENTER)
    idle(m)
    s = wait(m, lambda s: resumed_id not in s["ids"], 5)
    check("a finished film leaves; the focus goes to the first tile",
          resumed_id not in s["ids"] and len(s["ids"]) == 3 and s["focusedTile"] == 0, s)

    # 8. A missing file: dark grey, "Missing", A says so.
    (movies / MOVIE_FILES[1]).unlink()
    m.press("r")
    s = wait(m, lambda s: any(s["missing"]) and not s["rescanning"], 15)
    index = s["missing"].index(True) if any(s["missing"]) else -1
    check("missing: the tile keeps its place, dark grey, with \"Missing\"",
          index == 1 and s["missingLabels"][1] == "Missing" and "grayscale" in s["missingFilter"][1], s)
    check("after a rescan the focus stays on the carousel", s["focusedTile"] >= 0, s)
    m.press(RIGHT)
    s = wait(m, lambda s: s["focusedTile"] == 1, 3)
    m.press(ENTER)
    s = wait(m, lambda s: s["banner"], 3)
    check(f"A on a missing tile: {s['banner']!r}", s["banner"] == "File not found. Rescan or remove it.", s)
    for size, c in shot(m, shots_dir, "carousel-missing"):
        check(f"{size}: missing tile shown, no sideways page scroll", c["missing"][1] and not c["overflowX"], c)

    # 9. A tap resumes.
    plan(900)
    tapped = s["ids"][2]
    m.js("document.querySelectorAll('.continue-tile')[2].click(); return true;")
    idle(m)
    s = wait(m, lambda s: s["ids"] and s["ids"][0] == tapped, 5)
    check("a tap on a tile resumes it", s["ids"][0] == tapped and s["focusedTile"] == 0, s)

    # 10. X removes at once: focus to the next, then the previous, then the tabs.
    m.press(BACKSPACE)
    s = wait(m, lambda s: len(s["ids"]) == 2, 3)
    check("X removes the tile with no question; the focus moves to the next one (now first, large)",
          len(s["ids"]) == 2 and tapped not in s["ids"] and s["focusedTile"] == 0 and s["sizes"][0] == "large", s)
    m.press(RIGHT)
    m.press(BACKSPACE)
    s = wait(m, lambda s: len(s["ids"]) == 1, 3)
    check("X on the last tile: the focus moves to the previous one", s["focusedTile"] == 0, s)
    m.press(BACKSPACE)
    s = wait(m, lambda s: not s["shown"] and s["activeDesc"] == "DIV.tab en-tab", 3)
    check("X on the only tile: the carousel goes, the focus goes to the tabs",
          not s["shown"] and s["height"] == 0 and s["activeDesc"] == "DIV.tab en-tab", s)
    status = m.js("return fetch('/api/continue').then(r => r.json())")
    check("removed for good, and their pictures deleted",
          status["items"] == [] and not any((data / "thumbnails").glob("*.jpg")), status)
    app.stop()


if __name__ == "__main__":
    sys.exit(main(run, "continue-watching-"))
