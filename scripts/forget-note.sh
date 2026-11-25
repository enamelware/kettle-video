#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta
#
# Deletes one of Claude Code's own memory notes for this project, so a
# single narrow permission rule covers it on every device (rm always asks).
#
#   scripts/forget-note.sh NOTE.md
#
# The memory folder is worked out the way Claude Code names it: the repo's
# full path with every character that isn't a letter or digit turned into
# "-", under $HOME/.claude/projects/. Only a plain .md file name inside that
# folder is accepted: no slashes, no "..", no hidden files, nothing else.
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "Usage: scripts/forget-note.sh NOTE.md" >&2
  exit 2
fi
name="$1"

if [[ ! "$name" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*\.md$ ]] || [[ "$name" == *..* ]]; then
  echo "Refused: '$name' is not a plain .md file name." >&2
  exit 1
fi
if [ "$name" = "MEMORY.md" ]; then
  echo "Refused: MEMORY.md is the index, not a note." >&2
  exit 1
fi

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
folder="$HOME/.claude/projects/$(printf '%s' "$repo" | sed 's/[^A-Za-z0-9]/-/g')/memory"
note="$folder/$name"

if [ ! -d "$folder" ]; then
  echo "No memory folder at $folder" >&2
  exit 1
fi
if [ -L "$note" ] || [ ! -f "$note" ]; then
  echo "Refused: $note is not an existing plain file." >&2
  exit 1
fi

rm -- "$note"
echo "Deleted $note"
