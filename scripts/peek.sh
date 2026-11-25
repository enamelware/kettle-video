#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta
#
# Reads the other Kettle repository (Enamel, the design system) without
# `git -C`, so a single narrow permission rule covers it on every device
# (`git -C` always asks, because it can point git at any folder).
#
#   scripts/peek.sh log --oneline -5
#   scripts/peek.sh show v0.7.0:VERSION
#   scripts/peek.sh tag --list
#
# The repository is found next to this one: ../enamel. Only these git
# commands are accepted: log, show, status, diff, tag (listing only),
# rev-parse and ls-files. Options that write files, run other programs or
# read outside the repository are refused.
set -euo pipefail

usage() {
  echo "Usage: scripts/peek.sh log|show|status|diff|tag|rev-parse|ls-files [ARGS...]" >&2
  exit 2
}

[ "$#" -ge 1 ] || usage
command="$1"
shift

case "$command" in
  log|show|status|diff|tag|rev-parse|ls-files) ;;
  *) echo "Refused: git $command is not a read-only command peek.sh allows." >&2; exit 1 ;;
esac

for word in "$@"; do
  case "$word" in
    # --output writes a file (git also accepts --out, --outp...);
    # --ext-diff and --textconv run other programs; --no-index reads files
    # outside the repository; -o/-O are spellings that write or read files.
    --ou*|--ext*|--tex*|--no-in*|--exec*|--upload*|-o*|-O*)
      echo "Refused: option $word is not allowed." >&2; exit 1 ;;
  esac
done

if [ "$command" = "tag" ]; then
  # Listing only: no arguments, or a listing option first. Anything else
  # (a name, -d, -a, -f, -m...) could create, move or delete a tag.
  case "${1:-}" in
    ""|-l|--list|-n*|--sort=*|--contains|--no-contains|--points-at|--merged|--no-merged|--format=*) ;;
    *) echo "Refused: peek.sh only lists tags (git tag --list ...)." >&2; exit 1 ;;
  esac
  for word in "$@"; do
    case "$word" in
      -d|--delete|-a|--annotate|-s|--sign|-u*|--local-user*|-f|--force|-m*|--message*|-F*|--file*|-e|--edit|--create-reflog)
        echo "Refused: peek.sh only lists tags." >&2; exit 1 ;;
    esac
  done
fi

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
parent="$(dirname "$here")"
other="$parent/enamel"
if [ ! -d "$other/.git" ]; then
  echo "No other Kettle repository next to this one ($parent/enamel)." >&2
  echo "peek.sh reads Enamel, the design system, from a clone in that folder:" >&2
  echo "git clone https://github.com/enamelware/enamel.git \"$parent/enamel\"" >&2
  exit 1
fi

extra=()
case "$command" in
  log|show|diff) extra=(--no-ext-diff --no-textconv) ;;
esac

# --no-optional-locks: even `git status` leaves the other repo's index alone.
exec git --no-pager --no-optional-locks -C "$other" "$command" "${extra[@]}" "$@"
