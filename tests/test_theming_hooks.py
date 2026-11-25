# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Theming hooks list (the docs catch-up): every class name, id, data- marker and
data-kind value the page uses must appear in docs/spec.md's "Theming hooks"
section, so the public snippet API is fully documented.

Run from the repo root:  python3 -m unittest discover -s tests -t . -v
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "ui"
SPEC = ROOT / "docs" / "spec.md"


def hooks_section():
    text = SPEC.read_text(encoding="utf-8")
    start = text.index("## Theming hooks")
    end = text.find("\n## ", start + 1)
    return text[start:] if end == -1 else text[start:end]


def camel_to_kebab(name):
    return re.sub(r"[A-Z]", lambda m: "-" + m.group(0).lower(), name)


def html_hooks():
    html = (UI / "index.html").read_text(encoding="utf-8")
    classes, ids, data = set(), set(), set()
    for value in re.findall(r'\bclass="([^"]*)"', html):
        classes.update(value.split())
    ids.update(re.findall(r'\bid="([^"]*)"', html))
    for name, value in re.findall(r'\b(data-[a-z-]+)="([^"]*)"', html):
        data.add((name, value))
    return classes, ids, data


def js_hooks():
    classes, data_names, kinds = set(), set(), set()
    for path in sorted((UI / "js").glob("*.js")):
        js = path.read_text(encoding="utf-8")
        for value in re.findall(r'className\s*=\s*"([^"]*)"', js):
            classes.update(value.split())
        for value in re.findall(r'addSpan\([^,]+,\s*"([^"]+)"', js):
            classes.update(value.split())
        for name in re.findall(r"\.dataset\.([A-Za-z]+)", js):
            data_names.add("data-" + camel_to_kebab(name))
        data_names.update(re.findall(r'"(data-[a-z-]+)"', js))
        kinds.update(re.findall(r'\bkind:\s*"([a-z-]+)"', js))
        kinds.update(re.findall(r'kind\s*===\s*"([a-z-]+)"', js))
    return classes, data_names, kinds


def js_marker_values():
    """(data-name, value) pairs the scripts set, e.g. dataset.role = "summary"."""
    pairs = set()
    for path in sorted((UI / "js").glob("*.js")):
        js = path.read_text(encoding="utf-8")
        for name, value in re.findall(r'\.dataset\.([A-Za-z]+)\s*=\s*"([^"]+)"', js):
            pairs.add(("data-" + camel_to_kebab(name), value))
    return pairs


def css_attribute_hooks():
    """(data-name, value or None) pairs used in defaults.css selectors."""
    css = (UI / "css" / "defaults.css").read_text(encoding="utf-8")
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    pairs = set()
    for name, value in re.findall(r'\[(data-[a-z-]+)(?:="([^"]*)")?\]', css):
        pairs.add((name, value or None))
    return pairs


class ThemingHooksTest(unittest.TestCase):
    longMessage = False

    def setUp(self):
        self.doc = hooks_section()

    def assertListed(self, needle, where):
        self.assertIn(needle, self.doc, f"{needle} ({where}) is missing from spec.md's Theming hooks")

    def test_html_classes_ids_and_markers_are_listed(self):
        classes, ids, data = html_hooks()
        self.assertTrue(classes and ids and data)
        for name in classes:
            self.assertListed(f".{name}", "class in index.html")
        for name in ids:
            self.assertListed(f"#{name}", "id in index.html")
        for name, value in data:
            # Values may be grouped: data-tab="movies" | "tv".
            self.assertListed(f'{name}="', "marker in index.html")
            self.assertListed(f'"{value}"', f"value of {name} in index.html")

    def test_classes_and_markers_set_by_the_scripts_are_listed(self):
        classes, data_names, kinds = js_hooks()
        self.assertTrue(classes and data_names and kinds)
        for name in classes:
            self.assertListed(f".{name}", "class set by ui/js")
        for name in data_names:
            self.assertListed(name, "marker set by ui/js")
        for kind in kinds:
            self.assertListed(f'"{kind}"', "data-kind value in ui/js")

    def test_marker_values_set_by_the_scripts_are_listed(self):
        # Values such as data-role="summary" or data-status="missing" are
        # set by the scripts, not in index.html, so check each pair.
        pairs = js_marker_values()
        self.assertTrue(pairs)
        for name, value in pairs:
            self.assertListed(f'{name}="{value}"', "marker and value set by ui/js")

    def test_markers_styled_by_defaults_are_listed(self):
        for name, value in css_attribute_hooks():
            if value is None:
                self.assertListed(f"[{name}]", "marker styled in defaults.css")
            else:
                self.assertListed(f'{name}="', "marker styled in defaults.css")
                self.assertListed(f'"{value}"', f"value of {name} styled in defaults.css")

    def test_classes_styled_by_defaults_are_listed(self):
        css = (UI / "css" / "defaults.css").read_text(encoding="utf-8")
        css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        css = re.sub(r"url\([^)]*\)", "", css)
        selectors = re.findall(r"([^{}]+)\{", css)
        names = set()
        for selector in selectors:
            if selector.strip().startswith("@"):
                continue
            names.update(re.findall(r"\.([a-zA-Z][\w-]*)", selector))
        self.assertTrue(names)
        for name in names:
            self.assertListed(f".{name}", "class styled in defaults.css")


if __name__ == "__main__":
    unittest.main()
