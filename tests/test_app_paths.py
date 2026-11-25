# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Where a copy of the app keeps its settings, data and logs (backend/app_paths.py).

Covers, in temporary folders with invented names: a folder with no mark
file is a development copy and keeps everything inside itself; a marked
folder uses the standard home-folder places; a relative or empty XDG
setting is ignored; a missing or unreadable names.env falls back to the
default names; names.env's quotes and comments are read correctly.

Run: scripts/test.sh unit tests.test_app_paths
"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from backend import app_paths  # noqa: E402


def make_app(base: Path, names_text=None, marked=False, mark="test-mark") -> Path:
    app = base / "app"
    (app / "installer").mkdir(parents=True)
    if names_text is not None:
        (app / "installer" / "names.env").write_text(names_text, encoding="utf-8")
    if marked:
        (app / mark).write_text("", encoding="utf-8")
    return app


NAMES = 'APP_ID="demo-app"\nINSTALL_MARK="test-mark"\n'


class ReadNamesTests(unittest.TestCase):
    def test_quotes_comments_and_blank_lines(self):
        got = app_paths.read_names(
            "# a comment\n\nA=\"one\"\nB='two'\n  C = three \nno equals here\n"
        )
        self.assertEqual(got, {"A": "one", "B": "two", "C": "three"})

    def test_commented_out_line_with_equals_is_ignored(self):
        # A comment that looks like a setting must not be read as one.
        got = app_paths.read_names('A="one"\n# A="two"\n  # B="three"\n')
        self.assertEqual(got, {"A": "one"})

    def test_mismatched_quotes_are_kept(self):
        self.assertEqual(app_paths.read_names("A=\"one'"), {"A": "\"one'"})

    def test_value_keeps_inner_equals(self):
        self.assertEqual(app_paths.read_names('X="a=b"'), {"X": "a=b"})


class NamesFallbackTests(unittest.TestCase):
    def test_missing_file_uses_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            got = app_paths.names(Path(tmp))
        self.assertEqual(got["APP_ID"], app_paths.DEFAULT_APP_ID)
        self.assertEqual(got["INSTALL_MARK"], app_paths.DEFAULT_INSTALL_MARK)

    def test_unreadable_text_uses_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(Path(tmp))
            (app / "installer" / "names.env").write_bytes(b"\xff\xfe\x00bad")
            got = app_paths.names(app)
        self.assertEqual(got["APP_ID"], app_paths.DEFAULT_APP_ID)

    def test_names_env_that_cannot_be_opened_uses_defaults(self):
        # names.env is a folder: reading it fails with an OS error.
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(Path(tmp))
            (app / "installer" / "names.env").mkdir()
            got = app_paths.names(app)
        self.assertEqual(got["APP_ID"], app_paths.DEFAULT_APP_ID)
        self.assertEqual(got["INSTALL_MARK"], app_paths.DEFAULT_INSTALL_MARK)

    def test_missing_names_env_still_finds_the_default_mark(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(Path(tmp), marked=True, mark=app_paths.DEFAULT_INSTALL_MARK)
            p = app_paths.for_app(app, {"HOME": "/h"})
        self.assertTrue(p.installed)
        self.assertEqual(p.data_dir,
                         Path("/h/.local/share") / app_paths.DEFAULT_APP_ID / "data")

    def test_partial_file_fills_in_the_rest(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(Path(tmp), 'APP_ID="only-id"\n')
            got = app_paths.names(app)
        self.assertEqual(got["APP_ID"], "only-id")
        self.assertEqual(got["INSTALL_MARK"], app_paths.DEFAULT_INSTALL_MARK)


class ForAppTests(unittest.TestCase):
    def test_no_mark_is_a_development_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(Path(tmp), NAMES)
            p = app_paths.for_app(app, {"HOME": tmp, "XDG_DATA_HOME": "/somewhere"})
            self.assertFalse(p.installed)
            self.assertEqual(p.settings_file, app / "settings.json")
            self.assertEqual(p.data_dir, app / "data")
            self.assertEqual(p.logs_dir, app / "logs")

    def test_mark_uses_standard_places(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(Path(tmp), NAMES, marked=True)
            home = Path(tmp) / "home"
            p = app_paths.for_app(app, {"HOME": str(home)})
        self.assertTrue(p.installed)
        self.assertEqual(p.settings_file, home / ".config/demo-app/settings.json")
        self.assertEqual(p.data_dir, home / ".local/share/demo-app/data")
        self.assertEqual(p.logs_dir, home / ".local/state/demo-app/logs")

    def test_absolute_xdg_settings_are_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(Path(tmp), NAMES, marked=True)
            env = {"HOME": "/h", "XDG_CONFIG_HOME": "/c", "XDG_DATA_HOME": "/d",
                   "XDG_STATE_HOME": "/s"}
            p = app_paths.for_app(app, env)
        self.assertEqual(p.settings_file, Path("/c/demo-app/settings.json"))
        self.assertEqual(p.data_dir, Path("/d/demo-app/data"))
        self.assertEqual(p.logs_dir, Path("/s/demo-app/logs"))

    def test_relative_or_empty_xdg_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(Path(tmp), NAMES, marked=True)
            env = {"HOME": "/h", "XDG_CONFIG_HOME": "relative/dir", "XDG_DATA_HOME": "",
                   "XDG_STATE_HOME": "."}
            p = app_paths.for_app(app, env)
        self.assertEqual(p.settings_file, Path("/h/.config/demo-app/settings.json"))
        self.assertEqual(p.data_dir, Path("/h/.local/share/demo-app/data"))
        self.assertEqual(p.logs_dir, Path("/h/.local/state/demo-app/logs"))

    def test_mark_must_be_a_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(Path(tmp), NAMES)
            (app / "test-mark").mkdir()
            self.assertFalse(app_paths.is_installed(app))

    def test_only_the_mark_named_in_names_env_counts(self):
        # A file with the default mark's name is not the mark when names.env
        # names another one: still a development copy.
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(Path(tmp), NAMES, marked=True,
                           mark=app_paths.DEFAULT_INSTALL_MARK)
            p = app_paths.for_app(app, {"HOME": "/h"})
            self.assertFalse(p.installed)
            self.assertEqual(p.settings_file, app / "settings.json")


if __name__ == "__main__":
    unittest.main()
