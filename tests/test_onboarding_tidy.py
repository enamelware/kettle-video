# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Tidy-up after onboarding part 2 (the onboarding tidy-up). Nothing a viewer sees changes;
these keep the tidy-up from coming undone:

- the spec no longer lists the first scan and its result screen as not built,
  and lists the result screen's backend answer, GET /api/onboarding/result;
- the 10-second wait and "Still working…" are written once (still_working.js)
  and used by the loading screen, Home after onboarding and the result
  screen's scan; the loading screen's own words in index.html match them;
- onboarding's buttons and the "mpv not found" screen's Look again are built
  by one shared maker (dom.js), with the same classes and data-kind as before;
- Look again's two shared lines live in the rule for the other onboarding
  buttons, not in a rule of its own;
- the old "after the save" wording is gone from the code.

Run from the repo root:  python3 -m unittest tests.test_onboarding_tidy -v
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "ui"
SPEC = (ROOT / "docs" / "spec.md").read_text(encoding="utf-8")
APP = (UI / "js" / "app.js").read_text(encoding="utf-8")
ONBOARDING = (UI / "js" / "onboarding.js").read_text(encoding="utf-8")
DOM = (UI / "js" / "dom.js").read_text(encoding="utf-8")
STILL = (UI / "js" / "still_working.js").read_text(encoding="utf-8")
INDEX = (UI / "index.html").read_text(encoding="utf-8")
CSS = (UI / "css" / "defaults.css").read_text(encoding="utf-8")


def spec_section(title):
    start = SPEC.index(f"\n## {title}\n")
    rest = SPEC[start + 1:]
    end = rest.find("\n## ", 1)
    return rest[: end if end > 0 else len(rest)]


def css_rule(selector_line):
    """The declarations of the rule whose selector list starts with this line."""
    start = CSS.index(selector_line)
    open_brace = CSS.index("{", start)
    return CSS[start:open_brace], CSS[open_brace + 1: CSS.index("}", open_brace)]


class SpecTest(unittest.TestCase):
    def test_result_screen_not_listed_as_not_built(self):
        not_built = spec_section("Not built yet")
        missing = not_built.split(" are built.", 1)[0].split("Filename parsing", 1)[0]
        self.assertNotIn("first scan", missing)
        self.assertNotIn("result screen", missing)
        self.assertIn("the first scan screen", not_built)

    def test_result_answer_listed_with_the_other_onboarding_answers(self):
        answers = [line for line in SPEC.splitlines() if line.startswith("- `GET /api/onboarding")]
        self.assertTrue(any(line.startswith("- `GET /api/onboarding/result` →") for line in answers), answers)
        result = next(line for line in answers if line.startswith("- `GET /api/onboarding/result`"))
        for key in ('"movies"', '"tv"', '"notes"', '"nothing_found"', '"failed"'):
            self.assertIn(key, result)
        self.assertIn("never a full path", result)


class StillWorkingTest(unittest.TestCase):
    def test_written_once(self):
        self.assertRegex(STILL, r"export const STILL_WORKING_MS = 10000;")
        self.assertIn('export const STILL_WORKING = "Still working…";', STILL)
        for source in (APP, ONBOARDING):
            self.assertNotRegex(source, r"const STILL_WORKING(_MS)? =")
            self.assertNotIn("10000", source)
            self.assertNotIn("Still working", source)

    def test_shared_by_both_screens(self):
        self.assertIn('import { STILL_WORKING_MS } from "./still_working.js";', APP)
        self.assertIn('import { STILL_WORKING, STILL_WORKING_MS } from "./still_working.js";', ONBOARDING)
        # The loading screen's timer, Home after onboarding, and the scan's.
        self.assertEqual(APP.count("}, STILL_WORKING_MS);"), 2)
        self.assertEqual(ONBOARDING.count("}, STILL_WORKING_MS);"), 1)
        self.assertIn("textContent = STILL_WORKING;", ONBOARDING)

    def test_loading_screen_words_match(self):
        slow = re.search(r'<p data-role="slow" hidden>([^<]*)</p>', INDEX)
        self.assertIsNotNone(slow)
        self.assertEqual(slow.group(1), "Still working…")


class ButtonsTest(unittest.TestCase):
    def test_one_shared_maker(self):
        self.assertIn("export function actionButton(className, kind, words, primary)", DOM)
        self.assertIn("button.tabIndex = -1;", DOM)
        self.assertIn('button.type = "button";', DOM)
        for source in (APP, ONBOARDING):
            self.assertRegex(source, r'import \{ actionButton, addSpan \} from "\./dom\.js";')
            self.assertNotIn("en-button--primary", source)

    def test_same_classes_and_kinds_as_before(self):
        self.assertIn('actionButton("mpv-look-again", "mpv-look-again", "Look again", true)', APP)
        self.assertIn('actionButton("no-videos-action", kind, words, primary)', ONBOARDING)
        self.assertIn('actionButton("result-action", kind, words, primary)', ONBOARDING)
        self.assertIn('`${className} en-button${primary ? " en-button--primary" : ""}`', DOM)

    def test_look_again_joins_the_shared_rule(self):
        self.assertNotRegex(CSS, r"(^|\n)\.mpv-look-again \{")
        selectors, body = css_rule(".mpv-look-again,\n")
        self.assertIn(".no-videos-action,", selectors)
        self.assertIn(".result-action", selectors)
        self.assertIn("max-width: 100%;", body)
        self.assertIn("scroll-margin: var(--en-lift);", body)
        selectors, body = css_rule("}\n\n.no-videos-action,\n.result-action {")
        for line in ("display: flex;", "width: fit-content;", "margin-top: var(--en-space-inset);"):
            self.assertIn(line, body)
        self.assertNotIn("max-width", body)
        self.assertNotIn("scroll-margin", body)


class WordingTest(unittest.TestCase):
    def test_no_after_the_save(self):
        self.assertNotIn("openHomeAfterSave", APP)
        self.assertNotIn("after the save", APP)
        self.assertEqual(APP.count("openHomeAfterOnboarding(keyboard)"), 2)


if __name__ == "__main__":
    unittest.main()
