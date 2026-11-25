# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Tests for the playback controls (the playback controls work): the options Kettle gives mpv
at every launch, Kettle's key file (backend/mpv_input.conf) and the wording
script it calls. The real mpv is checked by
tests/playback_controls_mpv_check.py (not part of the unit tests).

Run from the repo root:  python3 -m unittest tests.test_playback_controls -v
"""

import os
import re
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from backend.mpv import (
    FLATPAK_APP_ID, KEY_FILE, PLAYBACK_CONTROLS_SCRIPT, QUIT_CAPTURE_SCRIPT, build_command, play,
)

FILE = Path("/media/Example Film (2001)/Example Film (2001).mkv")
SYSTEM = ["/usr/bin/mpv"]
FLATPAK = ["flatpak", "run", FLATPAK_APP_ID]

# The issue's button table: button -> what it does. "nothing" buttons
# either send a key that is set to "ignore", or send no key at all.
BUTTONS = {
    "A": "play-pause",
    "B": "quit",
    "D-pad Left": "back-10s",
    "D-pad Right": "forward-10s",
    "left stick left": "back-10s",
    "left stick right": "forward-10s",
    "L1": "back-1min",
    "R1": "forward-1min",
    "X": "next-subtitle",
    "Y": "next-audio",
    "D-pad Up": "show-where",
    "D-pad Down": "nothing",
    "L2": "nothing",
    "R2": "nothing",
    "right stick": "nothing",
    "Start": "nothing",
    "Select": "nothing",
}
# Keyboard keys for Desktop Mode: the same as these buttons.
KEYBOARD = {"SPACE": "A", "LEFT": "D-pad Left", "RIGHT": "D-pad Right", "ESC": "B"}
# The keys Kettle's Steam layout sends (docs/device-setup.md).
LAYOUT_KEYS = {
    "A": "SPACE", "B": "q", "D-pad Left": "LEFT", "D-pad Right": "RIGHT", "L1": "j", "R1": "l",
    "X": "BS", "Y": "a", "D-pad Up": "UP", "D-pad Down": "DOWN",
    # Start opens Kettle's menu in the list (the Home actions work); nothing in mpv.
    "Start": "m",
}


def parse_key_file():
    """[(key, command, labels)] for each binding line, and the buttons on
    the "nothing:" comment line (buttons that send no key)."""
    bindings, no_key = [], []
    for line in KEY_FILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("# nothing:"):
            no_key += [b.strip() for b in stripped.split(":", 1)[1].split(",")]
            continue
        if not stripped or stripped.startswith("#"):
            continue
        binding, _, comment = stripped.partition("#")
        key, command = binding.split(None, 1)
        labels = [label.strip() for label in comment.split(",") if label.strip()]
        bindings.append((key, command.strip(), labels))
    return bindings, no_key


def action(command):
    """'script-binding playback_controls/back-10s' -> 'back-10s';
    'ignore' -> 'nothing'; 'quit' -> 'quit'."""
    if command == "ignore":
        return "nothing"
    if command.startswith("script-binding playback_controls/"):
        return command.rsplit("/", 1)[1]
    return command


class LaunchOptionsTest(unittest.TestCase):
    def test_bar_off_and_key_file_passed(self):
        for command in (SYSTEM, FLATPAK):
            for resume in (True, False):
                args = build_command(command, FILE, [], resume)
                self.assertIn("--osc=no", args)
                self.assertIn("--input-default-bindings=no", args)
                self.assertIn(f"--input-conf={KEY_FILE}", args)
                self.assertIn(f"--script={PLAYBACK_CONTROLS_SCRIPT}", args)
                self.assertEqual(args[-1], str(FILE))

    def test_on_screen_text_style(self):
        args = build_command(SYSTEM, FILE, [], True)
        for option in ("--osd-level=1", "--osd-font=sans-serif", "--osd-font-size=40",
                       "--osd-color=#FFFFFF", "--osd-border-color=#000000", "--osd-border-size=2.5"):
            self.assertIn(option, args)

    def test_files_ship_with_the_app(self):
        for path in (KEY_FILE, PLAYBACK_CONTROLS_SCRIPT):
            self.assertTrue(path.is_absolute())
            self.assertTrue(path.is_file(), path)
            # Inside the app's folder: the Flatpak mpv reads it from there.
            self.assertTrue(path.is_relative_to(Path(__file__).resolve().parent.parent))

    def test_user_mpv_args_still_win(self):
        args = build_command(SYSTEM, FILE, ["--osc=yes", "--osd-font-size=60"], True)
        self.assertIn("--osc=yes", args)
        self.assertNotIn("--osc=no", args)
        self.assertNotIn("--osd-font-size=40", args)
        self.assertEqual(sum(a.startswith("--osd-font-size") for a in args), 1)

    def test_kettles_title_is_passed(self):
        # D-pad Up shows Kettle's title, not the file name (the designer's choice A).
        for resume in (True, False):
            args = build_command(SYSTEM, FILE, [], resume, title="Film 3 (2003) · Part 2")
            self.assertIn("--force-media-title=Film 3 (2003) · Part 2", args)
            self.assertEqual(args[-1], str(FILE))

    def test_no_title_outside_the_library(self):
        args = build_command(SYSTEM, FILE, [], True, title=None)
        self.assertFalse(any(a.startswith("--force-media-title") for a in args))

    def test_users_own_title_option_wins(self):
        args = build_command(SYSTEM, FILE, ["--force-media-title=Mine"], True, title="Kettle's")
        self.assertEqual([a for a in args if a.startswith("--force-media-title")], ["--force-media-title=Mine"])

    def test_nothing_points_at_mpvs_settings_folder(self):
        # Everything is passed at launch: no option names mpv's own
        # settings folder, and none asks mpv to write its settings.
        for resume in (True, False):
            for arg in build_command(FLATPAK, FILE, [], resume, Path("/tmp/kettle-quit-x")):
                self.assertNotIn(".config/mpv", arg)
                self.assertNotIn(".var/app", arg)
                self.assertNotIn("--config-dir", arg)

    def test_play_writes_nothing_to_mpvs_settings_folder(self):
        # A fake mpv that only prints, run with HOME in a fresh folder:
        # afterwards that home holds no mpv settings folder.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            fake = Path(tmp) / "fake_mpv.py"
            fake.write_text(textwrap.dedent("""
                import sys
                print("   cplayer: Exiting... (Quit)")
            """))
            with mock.patch.dict(os.environ, {"HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config")}):
                result = play([sys.executable, "-u", str(fake)], FILE, Path(tmp) / "mpv.log")
            self.assertTrue(result["ok"])
            self.assertEqual(list(home.iterdir()), [])


class KeyFileTest(unittest.TestCase):
    def setUp(self):
        self.bindings, self.no_key = parse_key_file()

    def labels(self):
        return [label for _, _, labels in self.bindings for label in labels] + self.no_key

    def test_every_button_appears_exactly_once(self):
        labels = self.labels()
        for button in BUTTONS:
            self.assertEqual(labels.count(button), 1, button)

    def test_buttons_do_what_the_table_says(self):
        by_label = {label: action(command) for _, command, labels in self.bindings for label in labels}
        for button, does in BUTTONS.items():
            if button in self.no_key:
                self.assertEqual(does, "nothing", button)
            else:
                self.assertEqual(by_label[button], does, button)

    def test_unused_buttons_explicitly_do_nothing(self):
        unused = {b for b, does in BUTTONS.items() if does == "nothing"}
        bound = {label: command for _, command, labels in self.bindings for label in labels}
        for button in unused:
            if button in self.no_key:
                continue
            self.assertEqual(bound[button], "ignore", button)
        # Every button with no key in the layout is named as such.
        self.assertEqual(set(self.no_key), unused - set(bound))

    def test_layout_keys_match(self):
        keys = {label: key for key, _, labels in self.bindings for label in labels}
        for button, key in LAYOUT_KEYS.items():
            self.assertEqual(keys[button], key, button)

    def test_keyboard_keys_do_the_same(self):
        commands = {key: command for key, command, _ in self.bindings}
        for key, button in KEYBOARD.items():
            self.assertEqual(commands[key], commands[LAYOUT_KEYS[button]], key)

    def test_touch_one_tap_only(self):
        commands = {key: command for key, command, _ in self.bindings}
        self.assertEqual(action(commands["MBTN_LEFT"]), "play-pause")
        # A second quick tap is not a double click (fullscreen by default).
        self.assertEqual(commands["MBTN_LEFT_DBL"], "ignore")
        self.assertEqual({k for k in commands if k.startswith(("MBTN", "WHEEL"))},
                         {"MBTN_LEFT", "MBTN_LEFT_DBL"})

    def test_no_duplicate_keys(self):
        keys = [key for key, _, _ in self.bindings]
        self.assertEqual(len(keys), len(set(keys)))
        # mpv key names are case sensitive: no key bound twice in two cases.
        self.assertEqual(len({k.lower() for k in keys}), len(keys))

    def test_only_listed_keys_are_bound(self):
        keys = {key for key, _, _ in self.bindings}
        self.assertEqual(keys, set(LAYOUT_KEYS.values()) | set(KEYBOARD) | {"MBTN_LEFT", "MBTN_LEFT_DBL"})

    def test_every_action_exists_in_the_script(self):
        script = PLAYBACK_CONTROLS_SCRIPT.read_text(encoding="utf-8")
        defined = set(re.findall(r'mp\.add_key_binding\(nil, "([a-z0-9-]+)"', script))
        used = {action(c) for _, c, _ in self.bindings if c.startswith("script-binding")}
        self.assertEqual(used, defined)
        # The script binds no keys itself: the key file decides.
        self.assertNotRegex(script, r'add_(forced_)?key_binding\("')


class QuitCaptureKeysTest(unittest.TestCase):
    """B (q) and Esc still go through the Continue watching script (the Continue watching work)."""

    def test_forced_bindings_survive_default_keys_off(self):
        script = QUIT_CAPTURE_SCRIPT.read_text(encoding="utf-8")
        self.assertRegex(script, r'mp\.add_forced_key_binding\("q", "kettle-quit", quit_with_capture\)')
        self.assertRegex(script, r'mp\.add_forced_key_binding\("ESC", "kettle-quit-esc", quit_with_capture\)')
        self.assertNotRegex(script, r'mp\.add_key_binding\(')

    def test_key_file_quits_plainly_without_the_script(self):
        commands = {key: command for key, command, _ in parse_key_file()[0]}
        self.assertEqual(commands["q"], "quit")
        self.assertEqual(commands["ESC"], "quit")


if __name__ == "__main__":
    unittest.main()
