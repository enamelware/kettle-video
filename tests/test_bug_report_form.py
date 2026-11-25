# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The GitHub bug report form (the bug report form work).

  - the form is valid by GitHub's rules for issue forms: a name, a
    description and a body of known field types, each input with a label,
    unique ids, dropdowns with options;
  - it asks for everything the issue lists: the device (Steam Deck,
    Retroid Pocket Nova, or another, named), the operating system and its
    version, Desktop or Gaming Mode, the Kettle Video version with where to
    find it, what happened, what was expected, the steps and whether it
    happens every time, and asks to leave out personal file and folder names;
  - blank issues stay allowed, so issues made with a title and body
    directly (the way /draft makes them) never go through the form.

GitHub reads the form as YAML. The standard library has no YAML reader, so
the form keeps to a small part of YAML (block mappings and lists, quoted
strings, flow lists of quoted strings) and this file reads that part,
failing on anything outside it.

Run from the repo root:  python3 -m unittest tests.test_bug_report_form -v
"""

import json
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TEMPLATES = REPO / ".github" / "ISSUE_TEMPLATE"
FORM = TEMPLATES / "bug_report.yml"
CONFIG = TEMPLATES / "config.yml"

TYPES = {"markdown", "textarea", "input", "dropdown", "checkboxes"}


class NotTheSubset(ValueError):
    pass


def _scalar(text: str):
    text = text.strip()
    if text in ("true", "false"):
        return text == "true"
    if text.startswith('"'):
        # A YAML double-quoted string without odd escapes reads as JSON.
        return json.loads(text)
    if text.startswith("["):
        return json.loads(text)
    if re.fullmatch(r"[A-Za-z0-9 _.-]+", text):
        return text
    raise NotTheSubset(f"unquoted value: {text!r}")


def read_yaml(text: str):
    """Block mappings and lists, two spaces a level, scalars as _scalar."""
    lines = []
    for number, raw in enumerate(text.splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if "\t" in raw:
            raise NotTheSubset(f"line {number}: a tab")
        indent = len(raw) - len(raw.lstrip(" "))
        if indent % 2:
            raise NotTheSubset(f"line {number}: odd indent")
        lines.append((indent, raw.strip(), number))

    def block(i, indent):
        if lines[i][1].startswith("- "):
            return seq(i, indent)
        return mapping(i, indent)

    def mapping(i, indent):
        out = {}
        while i < len(lines) and lines[i][0] == indent and not lines[i][1].startswith("- "):
            _, text, number = lines[i]
            match = re.fullmatch(r"([a-z_]+):(?: (.*))?", text)
            if not match:
                raise NotTheSubset(f"line {number}: not a key")
            key, value = match.groups()
            if key in out:
                raise NotTheSubset(f"line {number}: {key} twice")
            if value is None:
                out[key], i = block(i + 1, lines[i + 1][0])
                if lines[i - 1][0] <= indent:
                    raise NotTheSubset(f"line {number}: empty {key}")
            else:
                out[key], i = _scalar(value), i + 1
        return out, i

    def seq(i, indent):
        out = []
        while i < len(lines) and lines[i][0] == indent and lines[i][1].startswith("- "):
            _, text, number = lines[i]
            rest = text[2:]
            if re.match(r"[a-z_]+:", rest):
                # "- key: value" starts a mapping two spaces in.
                lines[i] = (indent + 2, rest, number)
                item, i = mapping(i, indent + 2)
            else:
                item, i = _scalar(rest), i + 1
            out.append(item)
        return out, i

    data, end = mapping(0, 0)
    if end != len(lines):
        raise NotTheSubset(f"line {lines[end][2]}: not read")
    return data


def form():
    return read_yaml(FORM.read_text(encoding="utf-8"))


def fields():
    return {item["id"]: item for item in form()["body"] if "id" in item}


class TheFormIsValid(unittest.TestCase):
    def test_top_level(self):
        data = form()
        self.assertEqual(set(data) - {"name", "description", "body", "labels", "title", "assignees"}, set())
        self.assertTrue(data["name"].strip())
        self.assertTrue(data["description"].strip())
        self.assertEqual(data["labels"], ["bug"])
        self.assertTrue(data["body"])

    def test_each_field(self):
        body = form()["body"]
        self.assertTrue(any(item["type"] != "markdown" for item in body))
        ids = [item["id"] for item in body if "id" in item]
        self.assertEqual(len(ids), len(set(ids)))
        labels = [item["attributes"]["label"] for item in body if item["type"] != "markdown"]
        self.assertEqual(len(labels), len(set(labels)))
        for item in body:
            with self.subTest(field=item.get("id", item["type"])):
                self.assertIn(item["type"], TYPES)
                self.assertEqual(set(item) - {"type", "id", "attributes", "validations"}, set())
                attributes = item["attributes"]
                if item["type"] == "markdown":
                    self.assertTrue(attributes["value"].strip())
                    self.assertNotIn("validations", item)
                    continue
                self.assertRegex(item["id"], r"^[a-z0-9-]+$")
                self.assertTrue(attributes["label"].strip())
                if item["type"] == "dropdown":
                    options = attributes["options"]
                    self.assertTrue(options)
                    self.assertEqual(len(options), len(set(options)))
                    self.assertTrue(all(isinstance(o, str) and o.strip() for o in options))
                if "validations" in item:
                    self.assertEqual(set(item["validations"]), {"required"})
                    self.assertIsInstance(item["validations"]["required"], bool)

    def test_the_reader_refuses_what_it_cant_read(self):
        for text in ("name: Bug: report\n", "name:\n", "a:\n   b: \"c\"\n", "name: \"x\"\nname: \"y\"\n"):
            with self.subTest(text=text):
                with self.assertRaises((NotTheSubset, ValueError, IndexError)):
                    read_yaml(text)


class TheFormAsksForEverything(unittest.TestCase):
    def test_the_device(self):
        device = fields()["device"]
        self.assertEqual(device["type"], "dropdown")
        self.assertEqual(device["attributes"]["options"],
                         ["Steam Deck", "Retroid Pocket Nova", "Other (name it below)"])
        self.assertTrue(device["validations"]["required"])
        other = fields()["other-device"]
        self.assertEqual(other["type"], "input")

    def test_the_system_and_mode(self):
        self.assertIn("version", fields()["system"]["attributes"]["label"])
        self.assertTrue(fields()["system"]["validations"]["required"])
        mode = fields()["mode"]
        self.assertEqual(mode["type"], "dropdown")
        self.assertIn("Desktop Mode", mode["attributes"]["options"])
        self.assertIn("Gaming Mode", mode["attributes"]["options"])

    def test_the_version_and_where_to_find_it(self):
        version = fields()["version"]
        self.assertTrue(version["validations"]["required"])
        self.assertIn("Settings › About", version["attributes"]["description"])
        self.assertIn("VERSION file", version["attributes"]["description"])

    def test_what_happened(self):
        for field in ("what-happened", "expected", "steps"):
            with self.subTest(field=field):
                self.assertEqual(fields()[field]["type"], "textarea")
                self.assertTrue(fields()[field]["validations"]["required"])
        every_time = fields()["every-time"]
        self.assertEqual(every_time["type"], "dropdown")
        self.assertIn("Every time", every_time["attributes"]["options"])

    def test_the_note_about_personal_names(self):
        notes = [item["attributes"]["value"] for item in form()["body"] if item["type"] == "markdown"]
        self.assertTrue(any("Please leave out personal file and folder names." in n for n in notes))

    def test_the_settings_screen_shows_the_version(self):
        # The form sends people to Settings › About for the version.
        self.assertIn("note(`Version ${data.version}`)",
                      (REPO / "ui" / "js" / "settings.js").read_text(encoding="utf-8"))


class DraftStillWorks(unittest.TestCase):
    def test_blank_issues_stay_allowed(self):
        config = read_yaml(CONFIG.read_text(encoding="utf-8"))
        self.assertIs(config["blank_issues_enabled"], True)

    def test_draft_makes_issues_with_a_title_and_body(self):
        draft = (REPO / ".claude" / "commands" / "draft.md").read_text(encoding="utf-8")
        self.assertIn("gh issue create --title ... --body ...", draft)
        self.assertNotIn("--template", draft)

    def test_the_form_is_the_only_template(self):
        self.assertEqual(sorted(p.name for p in TEMPLATES.iterdir()), ["bug_report.yml", "config.yml"])


if __name__ == "__main__":
    unittest.main()
