# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""scripts/board.sh acts only on this repo's issues.

The Kettle board also holds Enamel issues. These tests run the real
script with a stand-in `gh` that serves a mixed board, and check that
other repositories' cards (and draft cards) are never listed or moved, and
that /next's pick rule (step 2) only ever lands on this repo's issues.
The board script fix: a card just added but not yet in the board's list is still found
through the issue itself, only ever this repo's, on the Kettle board.
close-done closes only this repo's open issues whose cards are in Done.
Nothing here talks to GitHub.

Run: python3 -m unittest tests.test_board_script
"""

import json
import os
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "board.sh")
with open(os.path.join(ROOT, ".claude", "board.json"), encoding="utf-8") as f:
    BOARD_SETTINGS = json.load(f)
REPO = BOARD_SETTINGS["repo"]
OTHER = f"{BOARD_SETTINGS['owner']}/enamel"


def card(item_id, repo, number, status, title, labels=()):
    content = {"number": number, "repository": repo, "type": "Issue"} if repo else {"type": "DraftIssue"}
    return {"id": item_id, "content": content, "status": status, "title": title, "labels": list(labels)}


BOARD = {"items": [
    card("K1", OTHER, 3, "More to do", "Enamel: picker"),
    card("K2", OTHER, 7, "Ready for dev", "Enamel: action bar"),
    card("D1", None, None, "Ready for dev", "A draft note"),
    card("M1", REPO, 52, "Ready for dev", "Refactor the scanner", ["refactor", "size:S"]),
    card("M2", REPO, 51, "Ready for dev", "Fix a test", ["bug", "size:S"]),
    card("K3", OTHER, 51, "Building", "Enamel issue with the same number"),
    card("M3", REPO, 48, "Ready for testing", "Design system 4/4"),
]}
BOARD["totalCount"] = len(BOARD["items"])

# Each issue's own list of board cards, as GitHub answers it straight away
# (the board's card list can lag behind). Keyed by "owner/repo#number";
# the stand-in answers for whichever repository it is asked about, so asking
# Enamel instead of this repo would find Enamel's card and fail a test.
def board_card(item_id, number, owner=BOARD_SETTINGS["owner"]):
    return {"id": item_id, "project": {"number": number, "owner": {"login": owner}}}


ISSUE_CARDS = {
    # Just added: on the Kettle board, after a card on another board.
    f"{REPO}#60": [board_card("X0", 2), board_card("M9", 1)],
    f"{REPO}#61": [board_card("X1", 2)],
    # Board number 1, but someone else's board, not the Kettle one.
    f"{REPO}#62": [board_card("X2", 1, owner="someone-else")],
    # Enamel issues on the Kettle board, never to be moved by this script.
    f"{OTHER}#7": [board_card("K2", 1)],
    f"{OTHER}#63": [board_card("K9", 1)],
}

FAKE_GH = """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_GH_LOG"], "a") as log:
    log.write(" ".join(args) + "\\n")
if args[:2] == ["project", "item-list"]:
    print(os.environ["FAKE_GH_BOARD"])
elif args[:2] == ["api", "graphql"]:
    if os.environ.get("FAKE_GH_OFFLINE"):
        sys.stderr.write("error connecting to api.github.com\\n")
        sys.exit(1)
    fields = dict(a.split("=", 1) for a in args if "=" in a and not a.startswith("query="))
    key = fields["owner"] + "/" + fields["name"] + "#" + fields["number"]
    nodes = json.loads(os.environ["FAKE_GH_ISSUE_CARDS"]).get(key, [])
    print(json.dumps({"data": {"repository": {"issue": {"projectItems": {"nodes": nodes}}}}}))
elif args[:2] == ["issue", "view"]:
    print(json.loads(os.environ.get("FAKE_GH_STATES", "{}")).get(args[2], "OPEN"))
"""


class BoardScript(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        gh = os.path.join(tmp.name, "gh")
        with open(gh, "w") as f:
            f.write(FAKE_GH)
        os.chmod(gh, 0o755)
        self.log = os.path.join(tmp.name, "calls.log")
        open(self.log, "w").close()
        self.env = dict(
            os.environ,
            PATH=tmp.name + os.pathsep + os.environ["PATH"],
            FAKE_GH_LOG=self.log,
            FAKE_GH_BOARD=json.dumps(BOARD),
            FAKE_GH_ISSUE_CARDS=json.dumps(ISSUE_CARDS),
        )

    def run_script(self, *args):
        return subprocess.run(
            [SCRIPT, *args], env=self.env, capture_output=True, text=True, timeout=30
        )

    def calls(self):
        with open(self.log) as f:
            return f.read().splitlines()

    def rows(self):
        result = self.run_script("list")
        self.assertEqual(result.returncode, 0, result.stderr)
        return [line.split("\t") for line in result.stdout.splitlines()]

    def test_list_shows_only_this_repos_issues(self):
        self.assertEqual(
            [(r[0], r[1]) for r in self.rows()],
            [("52", "Ready for dev"), ("51", "Ready for dev"), ("48", "Ready for testing")],
        )

    def test_next_picks_only_this_repos_issues(self):
        # /next step 2: More to do first, then Ready for dev without the
        # refactor label, then refactor issues. Enamel's More to do card
        # and draft cards must never be picked.
        rows = self.rows()
        more = [r for r in rows if r[1] == "More to do"]
        ready = [r for r in rows if r[1] == "Ready for dev"]
        order = more + [r for r in ready if "refactor" not in r[2].split(",")] + [
            r for r in ready if "refactor" in r[2].split(",")
        ]
        self.assertEqual([r[0] for r in order], ["51", "52"])

    def test_status_moves_this_repos_card_not_the_other_with_the_same_number(self):
        result = self.run_script("status", "51", "Building")
        self.assertEqual(result.returncode, 0, result.stderr)
        edits = [c for c in self.calls() if c.startswith("project item-edit")]
        self.assertEqual(len(edits), 1)
        self.assertIn("--id M2 ", edits[0] + " ")

    def test_another_repos_issue_is_not_on_the_board(self):
        result = self.run_script("status", "7", "Building")
        self.assertEqual(result.returncode, 2)
        self.assertIn("not on the board", result.stderr)
        self.assertFalse([c for c in self.calls() if c.startswith("project item-edit")])

    def test_status_finds_a_card_the_board_list_does_not_show_yet(self):
        # Issue 60 was just added; the board's card list doesn't have it
        # yet, but the issue's own list of cards does.
        result = self.run_script("status", "60", "Drafted")
        self.assertEqual(result.returncode, 0, result.stderr)
        edits = [c for c in self.calls() if c.startswith("project item-edit")]
        self.assertEqual(len(edits), 1)
        self.assertIn("--id M9 ", edits[0] + " ")
        lookups = [c for c in self.calls() if c.startswith("api graphql")]
        self.assertEqual(len(lookups), 1)
        self.assertIn(f"owner={REPO.split('/')[0]} ", lookups[0])
        self.assertIn(f"name={REPO.split('/')[1]} ", lookups[0])

    def test_a_card_on_another_board_only_is_not_on_this_board(self):
        result = self.run_script("status", "61", "Drafted")
        self.assertEqual(result.returncode, 2)
        self.assertIn("not on the board", result.stderr)
        self.assertFalse([c for c in self.calls() if c.startswith("project item-edit")])

    def test_an_issue_on_no_board_says_so_plainly(self):
        result = self.run_script("status", "99", "Drafted")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stderr.strip(), "board.sh: issue #" "99 is not on the board")
        self.assertFalse([c for c in self.calls() if c.startswith("project item-edit")])

    def test_another_users_board_with_the_same_number_is_not_this_board(self):
        result = self.run_script("status", "62", "Drafted")
        self.assertEqual(result.returncode, 2)
        self.assertIn("not on the board", result.stderr)
        self.assertFalse([c for c in self.calls() if c.startswith("project item-edit")])

    def test_another_repos_just_added_card_is_never_moved(self):
        # Enamel's issue 63 is on the Kettle board but not in the list yet; the
        # issue lookup must ask this repo, which has no issue 63 on the board.
        result = self.run_script("status", "63", "Drafted")
        self.assertEqual(result.returncode, 2)
        self.assertIn("not on the board", result.stderr)
        self.assertFalse([c for c in self.calls() if c.startswith("project item-edit")])

    def test_no_network_on_the_issue_lookup_says_not_on_the_board(self):
        self.env["FAKE_GH_OFFLINE"] = "1"
        result = self.run_script("status", "60", "Drafted")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stderr.strip(), "board.sh: issue #" "60 is not on the board")
        self.assertFalse([c for c in self.calls() if c.startswith("project item-edit")])

    def test_list_asks_for_every_card(self):
        # GitHub returns 30 cards unless asked for more; the board has more.
        self.rows()
        listing = [c for c in self.calls() if c.startswith("project item-list")]
        self.assertEqual(len(listing), 1)
        limit = listing[0].split("--limit ", 1)[1].split()[0]
        self.assertGreaterEqual(int(limit), 1000)

    def test_a_listed_card_needs_no_extra_lookup(self):
        self.assertEqual(self.run_script("status", "51", "Building").returncode, 0)
        self.assertFalse([c for c in self.calls() if c.startswith("api graphql")])

    def test_add_and_label_name_this_repo(self):
        self.assertEqual(self.run_script("add", "51").returncode, 0)
        self.assertEqual(self.run_script("label", "51", "add", "blocked").returncode, 0)
        calls = self.calls()
        self.assertIn(f"--url https://github.com/{REPO}/issues/51", calls[-2])
        self.assertIn(f"--repo {REPO}", calls[-1])


    def test_close_done_closes_only_this_repos_open_done_issues(self):
        board = {"items": [
            card("M4", REPO, 40, "Done", "Done but still open"),
            card("M5", REPO, 41, "Done", "Done and closed"),
            card("M6", REPO, 42, "Ready for testing", "Not done"),
            card("K4", OTHER, 43, "Done", "Enamel issue in Done"),
            card("D2", None, None, "Done", "A draft note in Done"),
        ]}
        board["totalCount"] = len(board["items"])
        self.env["FAKE_GH_BOARD"] = json.dumps(board)
        self.env["FAKE_GH_STATES"] = json.dumps({"41": "CLOSED"})
        result = self.run_script("close-done")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("#" "40 closed", result.stdout)
        self.assertIn("close-done: 1 closed", result.stdout)
        closes = [c for c in self.calls() if c.startswith("issue close")]
        self.assertEqual(len(closes), 1)
        self.assertTrue(closes[0].startswith(f"issue close 40 --repo {REPO} --comment"))
        self.assertFalse([c for c in self.calls() if " 43 " in f" {c} " and c.startswith("issue")])


if __name__ == "__main__":
    unittest.main()
