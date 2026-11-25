# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta
"""Everything is called Kettle Video (the Kettle Video rename).

The app's earlier names (the "Media Player" working title, written
media-player, media_player or MEDIA_PLAYER in ids, and the never-used
"Kettle Watch" and "Kettle Player") must not come back. Every file git
tracks is checked, except:
- vendor/, which holds unmodified copies that are never edited;
- this file, which has to spell the old names to look for them;
- entries in the decisions log or a changelog dated on or before the
  rename day, the October audit and the dated spike reports in docs/spikes/:
  they are history and keep the names they were written with;
- launch.sh's one line naming the Firefox profile used before the rename,
  which it looks for only to say in the log that it is no longer used.
"kettle-video-private" is the private repo's new name, not an old one.
The design system's old names have their own check,
tests/test_design_system_name.py.

Also: the launcher starts a fresh kettle-video-profile and never touches
the old profile folder, in each case (old only, new only, both, neither),
and install-shortcut.sh writes kettle-video-dev.desktop named Kettle Video
(dev) (a development copy's own entry since the installer review fixes).
Both run on temporary copies with a temporary home folder; the real
Firefox profiles, Steam and settings.json are never touched.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
THIS = "tests/test_kettle_video_name.py"
RENAMED_ON = "2026-11-17"
HISTORY = {"docs/decisions.md", "CHANGELOG.md", "docs/changelog.md"}
HISTORY_FILES = ("docs/audit-2026-10.md",)
HISTORY_FOLDERS = ("docs/spikes/",)
OLD = re.compile(r"media[-_ ]?player|kettle[-_ ]?(?:watch|player)", re.I)
OLD_PROFILE_LINE = ("launch.sh", 'OLD_PROFILE_NAME="media-player-profile"')
ALLOWED = {OLD_PROFILE_LINE}
ENTRY = re.compile(r"(?m)^(?=#{2,3} )")
DATE = re.compile(r"^#{2,3} (?:\[?v?[\w.]*\]?\s*[—-]?\s*)?(\d{4}-\d{2}-\d{2})")


def tracked_files():
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
    return [name for name in out.decode().split("\0") if name]


def is_history(name):
    return name in HISTORY_FILES or name.startswith(HISTORY_FOLDERS)


def current_text(name, text):
    """The part of a file that describes things as they are now."""
    if is_history(name):
        return ""
    if name not in HISTORY:
        return text
    kept = []
    for entry in ENTRY.split(text):
        date = DATE.match(entry)
        if not (date and date.group(1) <= RENAMED_ON):
            kept.append(entry)
    return "".join(kept)


def hits(files):
    """files: (name, text) pairs. Returns 'name: line' for each old name."""
    found = []
    for name, text in files:
        for line in current_text(name, text).splitlines():
            if (name, line.strip()) in ALLOWED:
                continue
            if OLD.search(line):
                found.append(f"{name}: {line.strip()[:120]}")
    return found


def repo_files():
    for name in tracked_files():
        if name.startswith("vendor/") or name == THIS:
            continue
        path = ROOT / name
        if path.is_file():
            yield name, path.read_bytes().decode("utf-8", errors="replace")


class NoOldAppNames(unittest.TestCase):
    def test_no_file_uses_an_old_name(self):
        files = list(repo_files())
        self.assertGreater(len(files), 50, "git ls-files should list the repo")
        self.assertEqual(hits(files), [])

    def test_no_file_lives_under_an_old_name(self):
        self.assertEqual([name for name in tracked_files() if OLD.search(name)], [])

    def test_the_check_catches_what_it_should(self):
        for line in ("<title>Media Player</title>", 'DESKTOP_FILE="$APPS_DIR/media-player.desktop"',
                     'port = os.environ["MEDIA_PLAYER_PORT"]', "media-player: locks: none",
                     "Kettle Watch is next.", "the kettle-player folder", "import mediaplayer"):
            with self.subTest(line=line):
                self.assertTrue(hits([("README.md", line)]))
        decisions = ("## 2026-10-19 — Old entry\n\nThe Media Player working title.\n\n"
                     "## 2026-11-17 — The rename (the Kettle Video rename)\n\nWas media-player.\n\n"
                     "## 2026-11-18 — Later entry\n\nStill says media-player.\n")
        self.assertEqual(hits([("docs/decisions.md", decisions)]),
                         ["docs/decisions.md: Still says media-player."])
        self.assertTrue(hits([("docs/spec.md", "## 2026-10-01 — Not history\n\nMedia Player\n")]),
                        "dated headings only count in the decisions log or a changelog")
        self.assertTrue(hits([("launch.sh", 'PROFILE_NAME="media-player-profile"')]),
                        "only the one line naming the old profile is allowed")
        self.assertTrue(hits([(".claude/board.json", '"repo": "enamelware/media-player",')]),
                        "the board settings name the renamed repo")
        self.assertTrue(hits([("docs/spikes.md", "Media Player")]), "only docs/spikes/ is history")

    def test_new_names_pass(self):
        for line in ("Kettle Video", "kettle-video.desktop", "KETTLE_VIDEO_PORT",
                     "git@github.com:enamelware/kettle-video-private.git", "kettle-video-profile",
                     "mpv-player/mpv", "a media file", "Kettle Audio"):
            with self.subTest(line=line):
                self.assertEqual(hits([("README.md", line)]), [])
        self.assertEqual(hits(sorted(ALLOWED)), [])


# --- The Firefox profile, with launch.sh on a temporary copy ---------------

COPY = ["launch.sh", "backend", "ui", "vendor"]

# Notes how it was started, opens the app the way the page does, then quits.
FAKE_FIREFOX = r'''#!/usr/bin/env python3
import json, os, sys, urllib.request
url = sys.argv[-1].rstrip("/")
json.load(urllib.request.urlopen(url + "/api/mpv-status", timeout=10))
with open(os.environ["FAKE_OUT"], "w") as out:
    json.dump({"args": sys.argv[1:]}, out)
req = urllib.request.Request(url + "/api/shutdown", data=b"{}", method="POST",
                             headers={"Content-Type": "application/json"})
urllib.request.urlopen(req, timeout=10).read()
'''

OLD_NOTE = "the old Firefox profile folder media-player-profile"


def snapshot(folder):
    """Every file and folder under folder, with its bytes."""
    return {str(p.relative_to(folder)): (p.read_bytes() if p.is_file() else None)
            for p in sorted(folder.rglob("*"))}


class FreshProfile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        self.app, bin_dir, self.home = tmp / "app", tmp / "bin", tmp / "home"
        for d in (self.app, bin_dir, self.home, tmp / "Movies", tmp / "TV"):
            d.mkdir()
        for name in COPY:
            src = ROOT / name
            if src.is_dir():
                shutil.copytree(src, self.app / name, ignore=shutil.ignore_patterns("__pycache__"))
            else:
                shutil.copy2(src, self.app / name)
        (self.app / "settings.json").write_text(json.dumps(
            {"movies_path": str(tmp / "Movies"), "tv_path": str(tmp / "TV"),
             "mpv_command": "auto", "mpv_args": []}))
        for name, text in (("firefox", FAKE_FIREFOX), ("flatpak", "#!/bin/sh\nexit 1\n")):
            (bin_dir / name).write_text(text)
            (bin_dir / name).chmod(0o755)
        self.out = tmp / "firefox-out.json"
        self.env = dict(os.environ, HOME=str(self.home), PATH=f"{bin_dir}:{os.environ['PATH']}",
                        FAKE_OUT=str(self.out))
        for name in ("KETTLE_VIDEO_PORT", "KETTLE_VIDEO_LAUNCH_START", "KETTLE_DEV_UPDATE",
                     "KETTLE_LAUNCH_LOG", "MOZ_HEADLESS"):
            self.env.pop(name, None)
        self.old = self.home / ".mozilla" / "media-player-profile"
        self.new = self.home / ".mozilla" / "kettle-video-profile"

    def tearDown(self):
        self.tmp.cleanup()

    def make_old(self):
        (self.old / "storage").mkdir(parents=True)
        (self.old / "prefs.js").write_text('user_pref("kept", true);\n')
        (self.old / "user.js").write_text("// the old profile's own settings\n")
        (self.old / "storage" / "data.bin").write_bytes(bytes(range(256)))
        return snapshot(self.old)

    def launch(self):
        proc = subprocess.run(["bash", "launch.sh"], cwd=self.app, env=self.env,
                              capture_output=True, text=True, timeout=60)
        logs = sorted((self.app / "logs").glob("launch-*.log"))
        self.assertEqual(len(logs), 1, "one launch log")
        log = logs[0].read_text()
        self.assertEqual(proc.returncode, 0, log)
        self.assertIn("page loaded", log)
        args = json.loads(self.out.read_text())["args"]
        return log, args[args.index("-profile") + 1]

    def test_old_only(self):
        before = self.make_old()
        log, profile = self.launch()
        self.assertEqual(profile, str(self.new))
        self.assertTrue((self.new / "user.js").is_file(), "the fresh profile gets its settings")
        self.assertEqual(snapshot(self.old), before, "the old profile is never changed")
        self.assertEqual(log.count(OLD_NOTE), 1, "said once, in one line")
        self.assertIn("is no longer used; it can be removed by hand", log)

    def test_new_only(self):
        self.new.mkdir(parents=True)
        (self.new / "prefs.js").write_text('user_pref("mine", 1);\n')
        log, profile = self.launch()
        self.assertEqual(profile, str(self.new))
        self.assertEqual((self.new / "prefs.js").read_text(), 'user_pref("mine", 1);\n')
        self.assertNotIn(OLD_NOTE, log)
        self.assertFalse(self.old.exists())

    def test_both(self):
        before = self.make_old()
        self.new.mkdir(parents=True)
        log, profile = self.launch()
        self.assertEqual(profile, str(self.new))
        self.assertEqual(snapshot(self.old), before)
        self.assertEqual(log.count(OLD_NOTE), 1)

    def test_neither(self):
        log, profile = self.launch()
        self.assertEqual(profile, str(self.new))
        self.assertTrue((self.new / "user.js").is_file())
        self.assertFalse(self.old.exists(), "the old folder is never made")
        self.assertNotIn(OLD_NOTE, log)


class DesktopEntry(unittest.TestCase):
    def test_install_shortcut_writes_kettle_video(self):
        # A development copy's own entry since the installer review fixes (tests/test_menu_entries.py).
        with tempfile.TemporaryDirectory() as tmp:
            app, home = Path(tmp) / "app", Path(tmp) / "home"
            (app / "installer").mkdir(parents=True)
            home.mkdir()
            shutil.copy2(ROOT / "install-shortcut.sh", app / "install-shortcut.sh")
            shutil.copy2(ROOT / "installer" / "names.env", app / "installer" / "names.env")
            (app / "launch.sh").write_text("#!/bin/sh\n")
            env = dict(os.environ, HOME=str(home))
            subprocess.run(["bash", "install-shortcut.sh"], cwd=app, env=env,
                           capture_output=True, text=True, check=True, timeout=60)
            apps = home / ".local" / "share" / "applications"
            self.assertEqual(sorted(p.name for p in apps.glob("*.desktop")),
                             ["kettle-video-dev.desktop"])
            entry = (apps / "kettle-video-dev.desktop").read_text()
            self.assertIn("\nName=Kettle Video (dev)\n", entry)
            self.assertIn(f"\nExec={app}/launch.sh\n", entry)


class VisibleNames(unittest.TestCase):
    def test_window_titles_say_kettle_video(self):
        for page in ("ui/index.html", "ui/startup-error.html"):
            with self.subTest(page=page):
                self.assertIn("<title>Kettle Video</title>", (ROOT / page).read_text())


if __name__ == "__main__":
    unittest.main()
