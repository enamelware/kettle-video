#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta
#
# Add a development copy (this folder) to the app menu, so Steam lists it.
#
# A development copy has its own menu entry, DEV_DESKTOP_ENTRY in
# installer/names.env (kettle-video-dev.desktop, named "Kettle Video (dev)"),
# so it never takes over, or is taken over by, the entry the installer makes
# for an installed copy (DESKTOP_ENTRY, the installer review fixes). Earlier versions of this
# script wrote DESKTOP_ENTRY; if that entry starts this folder's launch.sh it
# is this script's own, and it is moved to the new name. Any other entry is
# left alone.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

APP_NAME="" DESKTOP_ENTRY="" DEV_DESKTOP_ENTRY="" INSTALL_MARK=""
if [ -f "$SCRIPT_DIR/installer/names.env" ]; then
  . "$SCRIPT_DIR/installer/names.env"
fi
if [ -z "$APP_NAME" ] || [ -z "$DESKTOP_ENTRY" ] || [ -z "$DEV_DESKTOP_ENTRY" ] ||
   [ -z "$INSTALL_MARK" ]; then
  echo "installer/names.env is missing or incomplete, so nothing was written."
  exit 1
fi

if [ -f "$SCRIPT_DIR/$INSTALL_MARK" ]; then
  echo "This is an installed copy of $APP_NAME: the installer already added it to the app menu."
  echo "Nothing was written. (This script is for development copies.)"
  exit 1
fi

chmod +x "$SCRIPT_DIR/launch.sh"

APPS_DIR="$HOME/.local/share/applications"
DESKTOP_FILE="$APPS_DIR/$DEV_DESKTOP_ENTRY"
OLD_FILE="$APPS_DIR/$DESKTOP_ENTRY"

mkdir -p "$APPS_DIR"

cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=$APP_NAME (dev)
Comment=Local movies/TV browser (launches mpv), development copy in $SCRIPT_DIR
Exec=$SCRIPT_DIR/launch.sh
Path=$SCRIPT_DIR
Icon=applications-multimedia
Terminal=false
Categories=Game;
EOF

chmod +x "$DESKTOP_FILE"

echo "Wrote $DESKTOP_FILE"

# The entry earlier versions of this script wrote, only if it starts this
# folder: never the installed copy's, never anyone else's.
if [ -f "$OLD_FILE" ] && [ ! -L "$OLD_FILE" ] &&
   grep -qxF "Exec=$SCRIPT_DIR/launch.sh" "$OLD_FILE"; then
  rm -f -- "$OLD_FILE"
  echo "Removed $OLD_FILE: this copy's entry from before, now $DEV_DESKTOP_ENTRY."
fi

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APPS_DIR"
  echo "Refreshed desktop database."
else
  echo "update-desktop-database not found — skipping (Steam may still pick this up without it)."
fi

echo
echo "Next: restart Steam (or just reopen 'Add a Non-Steam Game' from My Library)."
echo "'$APP_NAME (dev)' should now be listed directly — no need to use Browse."
