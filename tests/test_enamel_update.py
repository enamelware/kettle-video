# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The design system's 0.5.0 comes in (the Enamel 0.5.0 upgrade), now named Enamel (the Enamel rename).

Checks: the update tool copies 0.5.0's behaviour script
(components/enamel-components.js) and the vendored copy is at least 0.5.0;
the script carries the vendored version and the MIT licence; the licences
page names every file the tool copies; only the page itself loads the
script, none of the app's modules (since the picker confirm work; the page's order and the
server sending it are in tests/test_enamel.py);
every Enamel class the app uses still exists in the vendored stylesheet.

Run from the repo root:  python3 -m unittest tests.test_enamel_update -v
"""

import re
import unittest
from pathlib import Path

from tools import update_enamel as tool

ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "ui"
VENDOR = ROOT / "vendor" / "enamel"
SCRIPT = "components/enamel-components.js"


def strip_comments(text):
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


class NewScriptTest(unittest.TestCase):
    def test_the_tool_copies_the_script(self):
        self.assertIn(SCRIPT, tool.FILES)
        self.assertTrue((VENDOR / SCRIPT).is_file())

    def test_vendored_version_is_at_least_050(self):
        version = tuple(int(n) for n in (VENDOR / "VERSION").read_text().strip().split("."))
        self.assertGreaterEqual(version, (0, 5, 0))

    def test_script_carries_the_version_and_licence(self):
        version = (VENDOR / "VERSION").read_text().strip()
        head = (VENDOR / SCRIPT).read_text()[:400]
        self.assertIn(f"version {version}.", head)
        self.assertIn("SPDX-License-Identifier: MIT", head)

    def test_only_the_page_loads_the_script(self):
        # Since the picker confirm work the page loads it once, with a plain script tag; the
        # app's modules use window.EnamelUI and never load it themselves.
        self.assertEqual((UI / "index.html").read_text().count("enamel-components.js"), 1)
        for path in (UI / "js").glob("*.js"):
            self.assertNotIn("enamel-components.js", path.read_text(encoding="utf-8"), path.name)


class LicencesPageTest(unittest.TestCase):
    def test_every_copied_file_is_listed(self):
        text = (ROOT / "THIRD_PARTY_LICENSES.md").read_text()
        row = next((line for line in text.splitlines() if line.startswith("| Enamel")), "")
        for name in tool.FILES:
            with self.subTest(name=name):
                self.assertIn(f"`{name}`", row)


class ClassesStillExistTest(unittest.TestCase):
    # An Enamel class name: "en-" not preceded by a word character or a
    # dash (so --en- tokens and data-en- attributes don't count).
    CLASS = re.compile(r"(?<![-\w])en-[a-z0-9_-]*[a-z0-9]")

    def defined(self):
        css = strip_comments((VENDOR / "components" / "enamel-components.css").read_text())
        css += strip_comments((VENDOR / "tokens" / "enamel.css").read_text())
        # Classes the behaviour script looks for, with no style of their own
        # (the toast's text, .en-toast__text; the Home actions work).
        js = (VENDOR / SCRIPT).read_text()
        return set(re.findall(r"\.(en-[\w-]+)", css)) | set(re.findall(r'"\.(en-[\w-]+)"', js))

    def used(self):
        found = {}
        for path in [UI / "index.html", *(UI / "js").glob("*.js")]:
            for name in self.CLASS.findall(path.read_text(encoding="utf-8")):
                found.setdefault(name, path.name)
        for path in (UI / "css").glob("*.css"):
            for name in re.findall(r"\.(en-[\w-]+)", strip_comments(path.read_text(encoding="utf-8"))):
                found.setdefault(name, path.name)
        return found

    def test_the_app_uses_enamel_classes(self):
        # The check below would pass on nothing; make sure it has work to do.
        used = self.used()
        for name in ("en-row", "en-rows", "en-tile", "en-shelf", "en-tabs", "en-hintbar", "en-progress"):
            self.assertIn(name, used)

    def events(self):
        # Enamel's own event names (en-select, en-cancel; the picker confirm work) look
        # like class names; they must exist as events in its script instead.
        js = (VENDOR / SCRIPT).read_text()
        return set(re.findall(r'new CustomEvent\("(en-[\w-]+)"', js))

    def test_every_enamel_class_used_exists(self):
        defined = self.defined() | self.events()
        missing = {name: where for name, where in self.used().items() if name not in defined}
        self.assertEqual(missing, {})

    def test_the_picker_events_exist(self):
        self.assertTrue({"en-select", "en-cancel"} <= self.events())
        self.assertFalse(self.events() & self.defined(), "an event name is also a class")


if __name__ == "__main__":
    unittest.main()
