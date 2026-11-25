# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The optional settings in settings.json ("mpv_args", "data_dir", "resume",
"keep_awake"): wrong values give one plain message naming the setting, and a
file that leaves them out gets the defaults. Every settings file here is in a
temporary folder; the real settings.json is never read or written.

Run from the repo root:  python3 -m unittest tests.test_settings_values -v
"""

import json
import tempfile
import unittest
from pathlib import Path

from backend.settings import SettingsError, load_settings

GOOD = {"movies_path": "/media/Movies", "tv_path": "/media/TV Shows"}


class OptionalSettingsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def load(self, **changes):
        (self.root / "settings.json").write_text(json.dumps({**GOOD, **changes}))
        return load_settings(self.root)

    def test_defaults_when_left_out(self):
        data = self.load()
        self.assertEqual(data["mpv_args"], [])
        self.assertIs(data["resume"], True)
        self.assertIs(data["keep_awake"], True)
        self.assertEqual(data["data_dir"], str(self.root / "data"))

    def test_values_are_kept(self):
        data = self.load(mpv_args=["--hwdec=auto"], resume=False, keep_awake=False,
                         data_dir="/var/kettle")
        self.assertEqual(data["mpv_args"], ["--hwdec=auto"])
        self.assertIs(data["resume"], False)
        self.assertIs(data["keep_awake"], False)
        self.assertEqual(data["data_dir"], "/var/kettle")

    def test_relative_data_dir_is_inside_the_app_folder(self):
        self.assertEqual(self.load(data_dir="saved")["data_dir"], str(self.root / "saved"))

    def test_wrong_values_name_the_setting(self):
        cases = (
            ("mpv_args", "--fs", "list of strings"),
            ("mpv_args", ["--fs", 3], "list of strings"),
            ("mpv_args", None, "list of strings"),
            ("data_dir", "", "folder path"),
            ("data_dir", "   ", "folder path"),
            ("data_dir", 5, "folder path"),
            ("resume", "yes", "true or false"),
            ("resume", 1, "true or false"),
            ("keep_awake", "false", "true or false"),
            ("keep_awake", None, "true or false"),
        )
        for key, value, words in cases:
            with self.subTest(key=key, value=value), self.assertRaises(SettingsError) as exc:
                self.load(**{key: value})
            message = str(exc.exception)
            self.assertIn(f"'{key}'", message)
            self.assertIn(words, message)
            self.assertNotIn("Traceback", message)


if __name__ == "__main__":
    unittest.main()
