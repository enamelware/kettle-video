# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta
"""The app's Enamel names are the ones Enamel gives (the Enamel rename).

Checks, without a browser: every Enamel token, class, state attribute and
event name the app's page, scripts and styles use is a new name listed in
vendor/enamel/MIGRATION.md, or (since Enamel 0.8.0, the Enamel 0.8.0 upgrade, which adds
tokens and component variables after the rename) a custom property the
vendored tokens or components declare, so no name was guessed; and every
function the
app calls on window.EnamelUI (picker open, select, cancel, isOpen; toast
show, update) is one the vendored behaviour script really provides, so a
wrong global or function name fails here and not only on the device.

Run from the repo root:  python3 -m unittest tests.test_enamel_names -v
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "ui"
VENDOR = ROOT / "vendor" / "enamel"
SCRIPT = VENDOR / "components" / "enamel-components.js"

# Enamel names: tokens (--en-...), state attributes (data-en-...), and
# classes or events (en-... not after a word character or a dash).
NAME = re.compile(r"--en-[\w-]*\w|data-en-[\w-]*\w|(?<![\w-])en-[a-z0-9_-]*[a-z0-9]")
CALL = re.compile(r"window\.EnamelUI\.(\w+)\.(\w+)\(")


def app_files():
    return [UI / "index.html", *sorted((UI / "js").glob("*.js")), *sorted((UI / "css").glob("*.css"))]


def migration_new_names():
    """The New column of every table in MIGRATION.md."""
    text = (VENDOR / "MIGRATION.md").read_text(encoding="utf-8")
    return set(re.findall(r"^\| `[^`]+` \| `([^`]+)` \|$", text, re.M))


def declared_properties():
    """Every --en- custom property the vendored tokens and components declare
    (Enamel 0.8.0 added some after MIGRATION.md's rename list, the Enamel 0.8.0 upgrade)."""
    names = set()
    for path in (VENDOR / "tokens" / "enamel.css", VENDOR / "components" / "enamel-components.css"):
        names |= set(re.findall(r"(--en-[\w-]*\w)\s*:", path.read_text(encoding="utf-8")))
    return names


def declared_classes():
    """Every en- class the vendored components style (Enamel 0.9.0 added the
    onboarding parts after MIGRATION.md's rename list, the folder choice screens)."""
    css = (VENDOR / "components" / "enamel-components.css").read_text(encoding="utf-8")
    return set(re.findall(r"\.(en-[a-z0-9_-]*[a-z0-9])", css))


def known_names():
    return migration_new_names() | declared_properties() | declared_classes()


def used_names():
    found = {}
    for path in app_files():
        for name in NAME.findall(path.read_text(encoding="utf-8")):
            found.setdefault(name, path.name)
    return found


def script_api():
    """{"picker": {...}, "toast": {...}} as window.EnamelUI sets them."""
    js = SCRIPT.read_text(encoding="utf-8")
    block = js[js.index("window.EnamelUI = {"):]
    block = block[:block.index("\n  };")]
    # Each part starts on its own line ("    picker: {"); its functions are
    # the "name:" keys up to the next part.
    parts = re.split(r"(?m)^    (\w+): \{", block)[1:]
    return {part: set(re.findall(r"(?:^|[{,\s])(\w+):", body))
            for part, body in zip(parts[::2], parts[1::2])}


class NamesFromMigrationTest(unittest.TestCase):
    def test_migration_lists_the_new_names(self):
        new = migration_new_names()
        for name in ("--en-accent", "en-picker__row", "data-en-motion", "en-select", "EnamelUI",
                     "tokens/enamel.css"):
            self.assertIn(name, new)

    def test_the_app_uses_enamel_names(self):
        # The check below would pass on nothing; make sure it has work to do.
        used = used_names()
        for name in ("--en-space-gap", "--en-c-hintbar-height", "en-row", "en-picker__cancel", "en-select"):
            self.assertIn(name, used)

    def test_every_enamel_name_used_is_in_migration(self):
        new = known_names()
        unknown = {name: where for name, where in used_names().items() if name not in new}
        self.assertEqual(unknown, {})

    def test_the_check_catches_a_guessed_name(self):
        new = migration_new_names()
        for guess in ("--en-gap", "en-rowz", "data-en-reduced", "en-choose"):
            with self.subTest(guess=guess):
                self.assertEqual(NAME.findall(f" {guess};"), [guess])
                self.assertNotIn(guess, new)
                self.assertNotIn(guess, known_names())

    def test_names_added_in_0_8_0_are_known(self):
        # Declared by the vendored files, not in the 0.7.0 rename list (the Enamel 0.8.0 upgrade).
        for name in ("--en-size-button", "--en-c-shelf-gap", "--en-root-size"):
            self.assertIn(name, known_names())


class ScriptFunctionsTest(unittest.TestCase):
    def test_the_script_sets_window_enamelui(self):
        api = script_api()
        self.assertEqual(set(api), {"picker", "toast"})
        # The only global it sets is EnamelUI (spelled without the old name,
        # which tests/test_design_system_name.py keeps out of the repo).
        self.assertEqual(re.findall(r"window\.(\w+)\s*=", SCRIPT.read_text(encoding="utf-8")), ["EnamelUI"])

    def test_every_call_the_app_makes_exists(self):
        api = script_api()
        calls = set()
        for path in (UI / "js").glob("*.js"):
            calls |= set(CALL.findall(path.read_text(encoding="utf-8")))
        # The calls the picker and the toast rely on are all there.
        self.assertTrue({("picker", "open"), ("picker", "select"), ("picker", "cancel"),
                         ("picker", "isOpen"), ("toast", "show"), ("toast", "update")} <= calls)
        missing = sorted(f"{part}.{fn}" for part, fn in calls if fn not in api.get(part, set()))
        self.assertEqual(missing, [])

    def test_only_enamelui_is_used_as_the_global(self):
        for path in (UI / "js").glob("*.js"):
            text = path.read_text(encoding="utf-8")
            with self.subTest(file=path.name):
                globals_used = set(re.findall(r"window\.(\w+UI)\b", text))
                self.assertLessEqual(globals_used, {"EnamelUI"})


if __name__ == "__main__":
    unittest.main()
