#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta
#
# The one way /next changes the Kettle board and progress comments, so a
# single narrow permission rule covers them (see CLAUDE.md, "How we work").
# It only ever touches this repo's issues and the Kettle project, both read
# from .claude/board.json. The board also holds other repositories' issues
# (Enamel): this script never lists, reads or moves those. A card counts
# as this repo's only when its issue lives here (GitHub's own Repository
# field); draft cards with no issue are left out too.
#
#   scripts/board.sh list                     this repo's cards: number, status, labels, title
#   scripts/board.sh add N                    put issue N on the board (no-op if there)
#   scripts/board.sh status N "Ready for dev" move issue N's card to that column
#   scripts/board.sh label N add|remove NAME  add or remove a label on issue N
#   scripts/board.sh progress N               print issue N's progress comment
#   scripts/board.sh progress N FILE          create or update it from FILE
#   scripts/board.sh close-done               close every open issue of this repo whose card is in Done
#
# A progress comment starts with the line <!-- kettle-progress -->; FILE must
# start with it too. There is only ever one per issue: it is edited in place.

set -euo pipefail
cd "$(dirname "$0")/.."

MARKER="<!-- kettle-progress -->"

# Values from .claude/board.json, by key path (e.g. statusOptions.Building).
board() {
    python3 -c '
import json, sys
value = json.load(open(".claude/board.json"))
for key in sys.argv[1].split("."):
    value = value.get(key) if isinstance(value, dict) else None
if value is None:
    sys.exit(1)
print(value)
' "$1"
}

REPO="$(board repo)"
OWNER="$(board owner)"
NUMBER="$(board projectNumber)"

fail() { echo "board.sh: $*" >&2; exit 2; }

issue_number() {
    [[ "$1" =~ ^[0-9]+$ ]] || fail "not an issue number: $1"
}

items_json() {
    gh project item-list "$NUMBER" --owner "$OWNER" --format json --limit 1000
}

# The card ID of issue N on the board (only cards from this repo). The board's
# card list can take a minute or more to include a card that was just added
# (the board script fix), so when the list doesn't have it, ask through the issue itself, which
# is up to date at once. Both ways only ever find this repo's issue.
item_id() {
    items_json | python3 -c '
import json, sys
number, repo = int(sys.argv[1]), sys.argv[2]
for item in json.load(sys.stdin)["items"]:
    content = item.get("content") or {}
    if content.get("number") == number and content.get("repository") == repo:
        print(item["id"])
        sys.exit(0)
sys.exit(1)
' "$1" "$REPO" || issue_card_id "$1" || fail "issue #$1 is not on the board"
}

# The card ID of issue N on the board, read from the issue's own list of cards.
issue_card_id() {
    gh api graphql -F owner="${REPO%%/*}" -F name="${REPO#*/}" -F number="$1" -f query='
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) {
      projectItems(first: 50) {
        nodes { id project { number owner { ... on User { login } ... on Organization { login } } } }
      }
    }
  }
}' 2>/dev/null | python3 -c '
import json, sys
project, owner = int(sys.argv[1]), sys.argv[2]
try:
    answer = json.load(sys.stdin)
except ValueError:
    sys.exit(1)  # no answer, e.g. no network
issue = ((answer.get("data") or {}).get("repository") or {}).get("issue") or {}
for node in (issue.get("projectItems") or {}).get("nodes") or []:
    board = node.get("project") or {}
    if board.get("number") == project and (board.get("owner") or {}).get("login") == owner:
        print(node["id"])
        sys.exit(0)
sys.exit(1)
' "$NUMBER" "$OWNER"
}

progress_comment_id() {
    gh api "repos/$REPO/issues/$1/comments" --paginate \
        --jq ".[] | select(.body | startswith(\"$MARKER\")) | .id" | head -n 1
}

case "${1:-}" in
    list)
        items_json | python3 -c '
import json, sys
repo = sys.argv[1]
for item in json.load(sys.stdin)["items"]:
    content = item.get("content") or {}
    if content.get("repository") != repo or not content.get("number"):
        continue  # another repository (Enamel) or a draft card
    labels = ",".join(item.get("labels") or [])
    print(content.get("number"), item.get("status"), labels, item.get("title"), sep="\t")
' "$REPO"
        ;;
    add)
        [ "$#" -eq 2 ] || fail "usage: board.sh add N"
        issue_number "$2"
        gh project item-add "$NUMBER" --owner "$OWNER" \
            --url "https://github.com/$REPO/issues/$2" >/dev/null
        echo "#$2 is on the board"
        ;;
    status)
        [ "$#" -eq 3 ] || fail 'usage: board.sh status N "Column name"'
        issue_number "$2"
        option="$(board "statusOptions.$3")" || fail "no column called \"$3\""
        item="$(item_id "$2")"
        gh project item-edit --project-id "$(board projectId)" --id "$item" \
            --field-id "$(board statusFieldId)" --single-select-option-id "$option" >/dev/null
        echo "#$2 moved to $3"
        ;;
    label)
        [ "$#" -eq 4 ] || fail "usage: board.sh label N add|remove NAME"
        issue_number "$2"
        [[ "$4" =~ ^[A-Za-z0-9:_.\ -]+$ ]] || fail "not a label name: $4"
        case "$3" in
            add) gh issue edit "$2" --repo "$REPO" --add-label "$4" >/dev/null ;;
            remove) gh issue edit "$2" --repo "$REPO" --remove-label "$4" >/dev/null ;;
            *) fail "label: say add or remove" ;;
        esac
        echo "#$2 label $3: $4"
        ;;
    progress)
        [ "$#" -eq 2 ] || [ "$#" -eq 3 ] || fail "usage: board.sh progress N [FILE]"
        issue_number "$2"
        id="$(progress_comment_id "$2")"
        if [ "$#" -eq 2 ]; then
            [ -n "$id" ] || fail "issue #$2 has no progress comment yet"
            gh api "repos/$REPO/issues/comments/$id" --jq .body
            exit 0
        fi
        [ -f "$3" ] || fail "no such file: $3"
        [ "$(head -n 1 "$3")" = "$MARKER" ] || fail "the file must start with $MARKER"
        if [ -n "$id" ]; then
            gh api -X PATCH "repos/$REPO/issues/comments/$id" -F "body=@$3" --jq .html_url
        else
            gh issue comment "$2" --repo "$REPO" --body-file "$3"
        fi
        ;;
    close-done)
        [ "$#" -eq 1 ] || fail "usage: board.sh close-done"
        done_cards="$(items_json | python3 -c '
import json, sys
repo = sys.argv[1]
for item in json.load(sys.stdin)["items"]:
    content = item.get("content") or {}
    if content.get("repository") == repo and content.get("number") and item.get("status") == "Done":
        print(content["number"])
' "$REPO")"
        closed=0
        for n in $done_cards; do
            [ "$(gh issue view "$n" --repo "$REPO" --json state --jq .state)" = "OPEN" ] || continue
            gh issue close "$n" --repo "$REPO" \
                --comment "Closed by /next: its card is in Done but the issue was still open." >/dev/null
            echo "#$n closed (its card is in Done)"
            closed=$((closed + 1))
        done
        echo "close-done: $closed closed"
        ;;
    *)
        fail "usage: board.sh list | add N | status N COLUMN | label N add|remove NAME | progress N [FILE] | close-done"
        ;;
esac
