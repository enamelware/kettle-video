# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The remove question as an Enamel picker (the picker confirm work), checked in the
page and scripts without a browser.

Checks: the page has exactly one remove question, an Enamel picker dialog
(title with the question hook, Yes, remove with value "remove", then the
Cancel row marked as Enamel's Cancel and focused first), and none of the
old question block (no hidden main, no choices list, no file rows); the app
keeps no "question open" state of its own and no key handling of its own
for the two rows; the keyboard controller hands every key to the picker
while it is open, before anything else; Yes, remove acts on Enamel's
en-select event, and the spec lists the hooks the picker changed. The
behaviour itself (keys, tap, removing) is tests/missing_items_check.py.

Run from the repo root:  python3 -m unittest tests.test_remove_picker -v
"""

import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "ui"
INDEX = (UI / "index.html").read_text(encoding="utf-8")
APP_JS = (UI / "js" / "app.js").read_text(encoding="utf-8")
KEYBOARD_JS = (UI / "js" / "keyboard.js").read_text(encoding="utf-8")
SPEC = (ROOT / "docs" / "spec.md").read_text(encoding="utf-8")


class _Tree(HTMLParser):
    """Every element inside #confirm-remove, with its tag and attributes."""

    VOID = {"meta", "link", "br", "img", "input", "hr", "source"}

    def __init__(self):
        super().__init__()
        self.depth = 0
        self.inside = 0  # depth at which #confirm-remove opened, or 0
        self.dialogs = []  # every element with id confirm-remove
        self.elements = []  # (tag, attrs) inside it, in page order

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag not in self.VOID:
            self.depth += 1
        if attrs.get("id") == "confirm-remove":
            self.dialogs.append((tag, attrs))
            self.inside = self.depth
        elif self.inside:
            self.elements.append((tag, attrs))

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        if self.inside and self.depth == self.inside:
            self.inside = 0
        self.depth -= 1


def classes(attrs):
    return set((attrs.get("class") or "").split())


class PickerMarkupTest(unittest.TestCase):
    def setUp(self):
        self.tree = _Tree()
        self.tree.feed(INDEX)

    def test_one_question_and_it_is_a_kettle_dialog(self):
        self.assertEqual(len(self.tree.dialogs), 1, "the remove question appears more than once")
        tag, attrs = self.tree.dialogs[0]
        self.assertEqual(tag, "dialog")
        self.assertTrue({"confirm", "en-dialog"} <= classes(attrs))
        self.assertNotIn("hidden", attrs, "the dialog is opened by Enamel, not by hidden")
        self.assertNotIn("open", attrs, "the question must not start open")

    def test_picker_title_and_rows(self):
        els = self.tree.elements
        self.assertTrue(any("en-picker" in classes(a) for _, a in els))
        titles = [a for _, a in els if "en-picker__title" in classes(a)]
        self.assertEqual(len(titles), 1)
        self.assertEqual(titles[0].get("data-role"), "question")
        rows = [(t, a) for t, a in els if "en-picker__row" in classes(a)]
        self.assertEqual([a.get("data-kind") for _, a in rows], ["confirm-remove", "confirm-cancel"])
        (remove_tag, remove), (cancel_tag, cancel) = rows
        self.assertEqual((remove_tag, cancel_tag), ("button", "button"))
        self.assertEqual(remove.get("value"), "remove")
        self.assertNotIn("en-picker__cancel", classes(remove), "Yes, remove must not be the Cancel row")
        self.assertNotIn("autofocus", remove, "Yes, remove must not be focused first")
        self.assertIn("en-picker__cancel", classes(cancel))
        self.assertIn("autofocus", cancel, "Cancel must be focused first")

    def test_reassurance_line_on_yes_remove(self):
        self.assertRegex(INDEX, r'data-kind="confirm-remove"[^>]*>.*?<span class="en-picker__desc">'
                                r"Only Kettle's list changes\. Your files are never touched\.</span>")

    def test_old_question_block_is_gone(self):
        self.assertNotRegex(INDEX, r'<main[^>]*id="confirm-remove"')
        self.assertNotIn('data-role="choices"', INDEX)
        for _, attrs in self.tree.elements:
            self.assertFalse({"file-row", "parsed-row", "file-list"} & classes(attrs),
                             f"old list classes inside the question: {attrs}")
        self.assertNotIn('[data-role="choices"]', APP_JS)


class NoOwnHandlingTest(unittest.TestCase):
    def test_no_question_state_of_its_own(self):
        self.assertNotRegex(APP_JS, r"\bconfirming\b")
        for name in ("closeRemoveConfirm", "cancelRemove"):
            self.assertNotIn(name, APP_JS)

    def test_app_builds_no_question_rows_and_no_key_handling_for_them(self):
        # The rows are in the page; the app never makes or handles them.
        self.assertNotRegex(APP_JS, r'kind:\s*"confirm-(cancel|remove)"')
        self.assertNotRegex(APP_JS, r'kind\s*===\s*"confirm-(cancel|remove)"')
        self.assertNotRegex(APP_JS, r"OWN_LOOK_KINDS = new Set\(\[[^\]]*confirm-")

    def test_keyboard_hands_keys_to_the_picker_first(self):
        # Nothing in handleKeydown may run before the picker check, or a key
        # would be acted on by both the app and the picker.
        body = KEYBOARD_JS[KEYBOARD_JS.index("function handleKeydown(event) {"):]
        first = body.split("\n")[1].strip()
        self.assertEqual(first, "if (pickerOpen()) {")
        self.assertRegex(body, r"if \(pickerOpen\(\)\) \{\s*handlePickerKey\(event\);\s*return;\s*\}")
        self.assertIn("window.EnamelUI.picker.isOpen()", KEYBOARD_JS)

    def test_picker_key_handler_only_chooses_or_cancels(self):
        start = KEYBOARD_JS.index("function handlePickerKey(event) {")
        body = KEYBOARD_JS[start:KEYBOARD_JS.index("\n}\n", start)]
        self.assertIn("event.preventDefault();", body)
        calls = set(re.findall(r"window\.EnamelUI\.picker\.(\w+)\(", body))
        self.assertEqual(calls, {"select", "cancel"})

    def test_yes_remove_acts_on_kettle_select(self):
        self.assertRegex(APP_JS, r'confirmEl\.addEventListener\("en-select",[^}]*'
                                 r'event\.detail\.value === "remove"\) confirmRemove\(keyboard\)')
        self.assertIn("window.EnamelUI.picker.open(confirmEl, row)", APP_JS)


class SpecListsHookChangesTest(unittest.TestCase):
    def test_changed_hooks_listed_with_replacements(self):
        start = SPEC.index("## Design system: the remove question as an Enamel picker (the picker confirm work)")
        section = SPEC[start:SPEC.index("\n## ", start + 1)]
        for hook in ('`#confirm-remove.confirm`', '`[data-role="question"]`', '`[data-role="choices"]`',
                     '`[data-kind="confirm-cancel"]`', '`[data-kind="confirm-remove"]`'):
            self.assertIn(hook, section, hook)
        self.assertRegex(section, r'`\[data-role="choices"\]`[^\n]*removed')


if __name__ == "__main__":
    unittest.main()
