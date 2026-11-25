#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta
#
# The one way to run Kettle's automated tests, so a single narrow permission
# rule covers them (see CLAUDE.md, "How we work").
#
#   scripts/test.sh [quick] [NAME...] [--again]
#                                    the quick check, run on every issue (aim:
#                                    under 2 minutes): the unit suite without
#                                    the timing tests and, alongside it, the
#                                    browser checks for the screens the change
#                                    touches: the ones named (e.g.
#                                    home_shell_check), plus any
#                                    tests/*_check.py the change itself adds or
#                                    edits compared with main
#   scripts/test.sh full [--again]   everything, run before any VERSION bump or
#                                    release and at the end of /next all: the
#                                    whole unit suite, timings included, then
#                                    every tests/*_check.py
#   scripts/test.sh all              the same as full
#   scripts/test.sh privacy          only the privacy guard (the privacy guard work) on
#                                    every tracked file
#   scripts/test.sh unit MODULE...   only these modules, e.g. tests.test_parser
#   scripts/test.sh check NAME       one slower check, e.g. held_key_check
#                                    (runs tests/NAME.py; most need Firefox)
#   scripts/test.sh checks           every tests/*_check.py, one after another
#
# A pass of the unit suite, of each check and of full is remembered against
# the exact code (every file git would commit, uncommitted ones included), in
# git's own folder, never in the repo. Running it again on the same code says
# it already passed instead of running it again; a full pass counts for
# everything. --again runs it anyway. Exits non-zero if anything failed.
#
# The quick and full checks both start with the privacy guard on every
# tracked file. It is never remembered: the private word list can change
# without the code changing.

set -u
cd "$(dirname "$0")/.." || exit 1

RESULTS="$(git rev-parse --git-common-dir)/kettle-test-results"

# The exact code: the tree git would commit if every change were added, made
# with a separate index so nothing is staged. Empty if git can't tell.
code_key() {
    local index="$RESULTS/index.$$"
    mkdir -p "$RESULTS"
    rm -f "$index"
    GIT_INDEX_FILE="$index" git read-tree HEAD 2>/dev/null \
        && GIT_INDEX_FILE="$index" git add -A 2>/dev/null \
        && GIT_INDEX_FILE="$index" git write-tree 2>/dev/null
    rm -f "$index"
}

# Succeeds, and says so, if one of the named results is already remembered.
already_passed() {
    local key="$1" what
    shift
    [ -n "$key" ] || return 1
    for what in "$@"; do
        if [ -f "$RESULTS/$what-$key" ]; then
            echo "Already passed on this exact code: $(cat "$RESULTS/$what-$key")"
            return 0
        fi
    done
    return 1
}

# Remembers a pass, only if the code didn't change while it ran.
remember() {
    local what="$1" key="$2"
    [ -n "$key" ] && [ "$key" = "$(code_key)" ] || return 0
    echo "$what, $(date '+%Y-%m-%d %H:%M'), commit $(git rev-parse --short HEAD)" > "$RESULTS/$what-$key"
}

unit() {
    if [ "$#" -eq 0 ]; then
        python3 -m unittest discover -s tests -t .
        return
    fi
    for module in "$@"; do
        if ! [[ "$module" =~ ^tests\.[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)*$ ]]; then
            echo "test.sh: not a test module: $module" >&2
            return 2
        fi
    done
    python3 -m unittest "$@"
}

# The privacy guard (the privacy guard work): nothing from the development devices, library or
# accounts in any tracked file. Fails when the private word list is missing.
privacy() {
    echo "== privacy guard"
    python3 tools/privacy_guard.py tracked
}

check_ok() {
    local name="$1"
    [[ "$name" =~ ^[a-z0-9_]+$ ]] && [[ "$name" != test_* ]] && [ -f "tests/$name.py" ]
}

# Most checks drive the app in a headless Firefox: a system one on PATH, or
# the Flatpak. On a machine with neither, say so plainly before the check.
firefox_note() {
    command -v firefox >/dev/null 2>&1 && return 0
    command -v flatpak >/dev/null 2>&1 && flatpak info org.mozilla.firefox >/dev/null 2>&1 && return 0
    echo "test.sh: Firefox not found. The browser checks need Firefox, either a system one on PATH or the Flatpak org.mozilla.firefox; most of them fail without it." >&2
}

check() {
    local name="$1"
    if ! check_ok "$name"; then
        echo "test.sh: no check named $name in tests/" >&2
        return 2
    fi
    firefox_note
    python3 "tests/$name.py"
}

checks() {
    local failed=0 file
    for file in tests/*_check.py; do
        echo "== $file"
        check "$(basename "$file" .py)" || failed=1
    done
    return "$failed"
}

# The checks the change itself adds or edits, compared with main.
changed_checks() {
    {
        git diff --name-only --diff-filter=d main -- 'tests/*_check.py' 2>/dev/null
        git ls-files --others --exclude-standard -- 'tests/*_check.py'
    } | sed -n 's|^tests/\(.*\)\.py$|\1|p' | sort -u
}

quick() {
    local again="" names=() name key status=0 out unit_pid unit_status
    for name in "$@"; do
        if [ "$name" = "--again" ]; then
            again=1
        elif check_ok "$name"; then
            names+=("$name")
        else
            echo "test.sh: no check named $name in tests/" >&2
            return 2
        fi
    done
    for name in $(changed_checks); do
        [[ " ${names[*]-} " == *" $name "* ]] || names+=("$name")
    done
    key="$(code_key)"
    privacy || status=1

    # The unit suite runs in the background while the checks run, since
    # both mostly wait (on servers and Firefox), not on the processor.
    unit_pid=""
    if [ -z "$again" ] && already_passed "$key" unit full; then
        :
    else
        out="$(mktemp)"
        KETTLE_QUICK=1 python3 -m unittest discover -s tests -t . > "$out" 2>&1 &
        unit_pid=$!
    fi
    for name in "${names[@]+"${names[@]}"}"; do
        echo "== tests/$name.py"
        if [ -z "$again" ] && already_passed "$key" "check-$name" full; then
            continue
        fi
        if check "$name"; then
            remember "check-$name" "$key"
        else
            status=1
        fi
    done
    if [ -n "$unit_pid" ]; then
        wait "$unit_pid"
        unit_status=$?
        echo "== unit suite (timing tests are in the full check)"
        cat "$out"
        rm -f "$out"
        if [ "$unit_status" -eq 0 ]; then
            remember unit "$key"
        else
            status=1
        fi
    fi
    [ "${#names[@]}" -gt 0 ] || echo "No browser checks named or changed: unit suite only."
    return "$status"
}

full() {
    local key status=0
    case "${1:-}" in
        ""|--again) ;;
        *) echo "usage: scripts/test.sh full [--again]" >&2; return 2 ;;
    esac
    privacy || return 1
    key="$(code_key)"
    if [ -z "${1:-}" ] && already_passed "$key" full; then
        return 0
    fi
    unit || status=1
    checks || status=1
    if [ "$status" -eq 0 ]; then
        remember full "$key"
    fi
    return "$status"
}

case "${1:-}" in
    quick) shift; quick "$@" ;;
    full|all) shift; full "$@" ;;
    unit) shift; unit "$@" ;;
    check)
        if [ "$#" -ne 2 ]; then echo "usage: scripts/test.sh check NAME" >&2; exit 2; fi
        check "$2" ;;
    checks) checks ;;
    privacy) privacy ;;
    ""|--again|*_check) quick "$@" ;;
    *)
        echo "usage: scripts/test.sh [quick] [NAME...] [--again] | full [--again] | unit MODULE... | check NAME | checks | privacy" >&2
        exit 2 ;;
esac
