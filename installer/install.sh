#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta
#
# Install Kettle Video into your home folder (the installer work).
#
#   bash install.sh [ARCHIVE]
#
# ARCHIVE is a release archive (kettle-video-<version>.tar.gz) with its
# checksum file (the same name plus .sha256) beside it. Without ARCHIVE, the
# newest one next to this script is used.
#
# Run it again with a newer archive to update (the installer's update step).
#
# What it does, in order:
#   1. checks the archive against its checksum; anything wrong stops the
#      install before anything is placed;
#   2. places the app files in ~/.local/share/kettle-video/app. On an update
#      it prints the old and new version, asks before going back to an
#      older one, and keeps the previous version until the new one has
#      started cleanly, rolling back if it doesn't (installer/update.py, the
#      step the app's own update uses too); nothing else is touched;
#   3. makes the folders for your settings (~/.config/kettle-video), your
#      data (~/.local/share/kettle-video/data) and the logs
#      (~/.local/state/kettle-video/logs), if they aren't there yet;
#   4. adds Kettle Video to the app menu, with its icon;
#   5. checks for mpv and, if it is missing, asks before installing it from
#      Flathub;
#   6. says what it did and how to add Kettle Video to Steam.
#
# It never asks for a password, never uses sudo, never changes the system
# and never writes Steam's own files. The XDG_DATA_HOME, XDG_CONFIG_HOME and
# XDG_STATE_HOME variables move those folders, as on any Linux system.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- names ---
# Every name comes from installer/names.env. The release script writes its
# lines in here when it puts this script next to the archive; in the app's
# own folder, names.env sits beside this script.
if [ -f "$SCRIPT_DIR/names.env" ]; then
  . "$SCRIPT_DIR/names.env"
fi
# --- end names ---

MPV_FLATPAK="io.mpv.Mpv"
MPV_COMMAND="flatpak install flathub $MPV_FLATPAK"

say() { printf '%s\n' "$*"; }

# Stop before anything was placed.
stop() {
  say ""
  say "Install stopped: $*"
  say "Nothing was installed or changed."
  exit 1
}

if [ -z "${APP_ID:-}" ] || [ -z "${APP_NAME:-}" ] || [ -z "${ARCHIVE_NAME:-}" ] ||
   [ -z "${DESKTOP_ENTRY:-}" ] || [ -z "${INSTALL_MARK:-}" ] || [ -z "${ICON_FILE:-}" ]; then
  stop "this install script is missing its names (installer/names.env). Download it again."
fi

say "Installing $APP_NAME"
say ""

if [ "$(id -u)" -eq 0 ]; then
  stop "run it as yourself, not as root or with sudo. $APP_NAME installs into your own home folder and never needs a password."
fi
if [ -z "${HOME:-}" ] || [ ! -d "$HOME" ]; then
  stop "your home folder couldn't be found."
fi
command -v python3 >/dev/null 2>&1 || stop "the python3 command isn't available on this system."

# --- the archive ---
if [ "$#" -gt 1 ]; then
  stop "give at most one archive. Usage: bash install.sh [$ARCHIVE_NAME-<version>.tar.gz]"
fi
if [ "$#" -eq 1 ]; then
  ARCHIVE="$1"
else
  ARCHIVE=""
  for candidate in "$SCRIPT_DIR/$ARCHIVE_NAME"-*.tar.gz; do
    [ -f "$candidate" ] || continue
    if [ -z "$ARCHIVE" ] ||
       [ "$(printf '%s\n%s\n' "$ARCHIVE" "$candidate" | sort -V | tail -n 1)" = "$candidate" ]; then
      ARCHIVE="$candidate"
    fi
  done
  [ -n "$ARCHIVE" ] || stop "no $ARCHIVE_NAME-<version>.tar.gz next to this script. Put the release archive and its .sha256 file in the same folder as install.sh."
fi

# --- update logic ---
# The shared step that checks the archive and places the app files
# (the installer's update step). In the app's own folder it is update.py beside this script;
# the release script writes it in here instead, so the install.sh next to
# the archive needs no other file.
UPDATER="$SCRIPT_DIR/update.py"
UPDATER_CODE=""
# --- end update logic ---

# --- where things go (backend/app_paths.py says the same) ---
place() {
  case "$1" in
    /*) printf '%s' "$1" ;;
    *) printf '%s' "$HOME/$2" ;;
  esac
}
DATA_HOME="$(place "${XDG_DATA_HOME:-}" .local/share)"
SHARE_DIR="$DATA_HOME/$APP_ID"
APP_DIR="$SHARE_DIR/app"
DATA_DIR="$SHARE_DIR/data"
CONFIG_DIR="$(place "${XDG_CONFIG_HOME:-}" .config)/$APP_ID"
LOGS_DIR="$(place "${XDG_STATE_HOME:-}" .local/state)/$APP_ID/logs"
APPS_DIR="$DATA_HOME/applications"
DESKTOP_FILE="$APPS_DIR/$DESKTOP_ENTRY"

version_in() { [ -f "$1/VERSION" ] && head -n 1 "$1/VERSION"; }

# --- check the archive, then place or update the app files ---
# The shared step checks the archive's checksum and contents before
# touching anything, prints the old and new version, asks before going back
# to an older one, switches to the new version in one step and, for an
# update, rolls back if the new version doesn't start cleanly. It says what
# happened itself; on anything but success the install ends here.
OLD_VERSION=""
[ -f "$APP_DIR/$INSTALL_MARK" ] && OLD_VERSION="$(version_in "$APP_DIR")"
if [ -n "$UPDATER_CODE" ]; then
  python3 -I -c "$UPDATER_CODE" install "$ARCHIVE" \
    --app-dir "$APP_DIR" --mark "$INSTALL_MARK" --name "$APP_NAME"
elif [ -f "$UPDATER" ]; then
  python3 -I "$UPDATER" install "$ARCHIVE" \
    --app-dir "$APP_DIR" --mark "$INSTALL_MARK" --name "$APP_NAME"
else
  stop "this install script is missing its update step (installer/update.py). Download it again."
fi
STATUS=$?
[ "$STATUS" -eq 0 ] || exit "$STATUS"
VERSION="$(version_in "$APP_DIR")"

if mkdir -p "$DATA_DIR" "$CONFIG_DIR" "$LOGS_DIR"; then
  say "  Folders ready for your settings, data and logs"
else
  say "  Warning: couldn't make the folders for your settings, data and logs ($DATA_DIR, $CONFIG_DIR, $LOGS_DIR)."
fi

# --- the app menu ---
# The entry is written only if it is missing or already starts the installed
# copy (the installer review fixes). Any other entry with that name, such as one an older
# install-shortcut.sh made for a development copy, is left as it is.
MENU_STATE=""
if [ -e "$DESKTOP_FILE" ] || [ -L "$DESKTOP_FILE" ]; then
  if ! { [ -f "$DESKTOP_FILE" ] && [ ! -L "$DESKTOP_FILE" ] &&
         grep -qxF "Exec=\"$APP_DIR/launch.sh\"" "$DESKTOP_FILE"; }; then
    MENU_STATE="other"
  fi
fi
if [ "$MENU_STATE" = "other" ]; then
  say "  Warning: $DESKTOP_FILE is already there and doesn't start the installed $APP_NAME"
  say "  (it may be a development copy's entry), so it was left as it is."
  say "  If it is a development copy's, run ./install-shortcut.sh again in that copy: it moves"
  say "  its entry to its own name. Then run this installer again to add $APP_NAME to the menu."
elif mkdir -p "$APPS_DIR" && cat >"$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=$APP_NAME
Comment=Your movies and TV shows, played with mpv
Exec="$APP_DIR/launch.sh"
Path=$APP_DIR
Icon=$APP_DIR/$ICON_FILE
Terminal=false
Categories=AudioVideo;Video;Player;
EOF
then
  chmod +x "$DESKTOP_FILE"
  if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APPS_DIR" >/dev/null 2>&1
  fi
  say "  $APP_NAME added to the app menu, with its icon"
  MENU_STATE="added"
else
  MENU_STATE="failed"
  say "  Warning: couldn't add $APP_NAME to the app menu. You can still start it from $APP_DIR/launch.sh."
fi

# --- mpv ---
say ""
MPV_STATE=""
if command -v mpv >/dev/null 2>&1; then
  MPV_STATE="found"
  say "mpv is installed."
elif command -v flatpak >/dev/null 2>&1 && flatpak info "$MPV_FLATPAK" >/dev/null 2>&1; then
  MPV_STATE="found"
  say "mpv is installed (the Flatpak)."
else
  say "mpv isn't installed. $APP_NAME plays every film and episode in mpv, so it needs it."
  say "It can be installed from Flathub with this command:"
  say ""
  say "    $MPV_COMMAND"
  say ""
  if ! command -v flatpak >/dev/null 2>&1; then
    MPV_STATE="no-flatpak"
    say "Flatpak isn't on this system, so mpv can't be installed from here."
  else
    answer=""
    FLATPAK_ASK=""
    if [ -n "${KETTLE_VIDEO_MPV_ANSWER:-}" ]; then
      # The one-file installer (installer/one_file_install.py) asked this in
      # its own window already, showing the same command; Flatpak's own
      # questions then take their usual answers.
      answer="$KETTLE_VIDEO_MPV_ANSWER"
      FLATPAK_ASK="--assumeyes"
      say "Install mpv now with that command? $answer (answered in the window)"
    else
      printf 'Install mpv now with that command? [y/N] '
      read -r answer || answer=""
    fi
    say ""
    case "$answer" in
      y|Y|yes|Yes|YES)
        if flatpak install $FLATPAK_ASK flathub "$MPV_FLATPAK"; then
          MPV_STATE="installed"
          say "mpv is installed."
        else
          MPV_STATE="failed"
          say "mpv wasn't installed."
        fi
        ;;
      *)
        MPV_STATE="skipped"
        say "mpv not installed."
        ;;
    esac
  fi
fi

# --- summary ---
say ""
say "Done. $APP_NAME $VERSION is installed."
say ""
say "What this did:"
if [ -n "$OLD_VERSION" ]; then
  say "- Replaced the app files in $APP_DIR: $OLD_VERSION before, $VERSION now (your settings, data and logs are untouched)"
else
  say "- Put the app files in $APP_DIR"
fi
say "- Settings go in $CONFIG_DIR/settings.json (made on the first launch)"
say "- Your library is saved in $DATA_DIR"
say "- Logs go in $LOGS_DIR (attach them to a GitHub issue if something goes wrong)"
case "$MENU_STATE" in
  added) say "- Added $APP_NAME to the app menu: $DESKTOP_FILE" ;;
  other) say "- Not added to the app menu: $DESKTOP_FILE belongs to something else (see the warning above)" ;;
  *) say "- Not added to the app menu (see the warning above); start it from $APP_DIR/launch.sh" ;;
esac
case "$MPV_STATE" in
  found) say "- mpv: already installed" ;;
  installed) say "- mpv: installed from Flathub" ;;
  *)
    say "- mpv: not installed. $APP_NAME opens on its \"mpv not found\" screen until it is."
    say "  Install it from your app store (Discover or Bazaar), or in a terminal with:"
    say "      $MPV_COMMAND"
    say "  If that asks for a password you don't have, or can't find flathub, install it"
    say "  for your user only instead:"
    say "      flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo"
    say "      flatpak install --user flathub $MPV_FLATPAK"
    ;;
esac
say ""
say "Next, add $APP_NAME to Steam (this installer never changes Steam's files):"
if [ "$MENU_STATE" = "added" ]; then
  say "1. In Desktop Mode, open the app menu and find $APP_NAME (under Multimedia)."
  say "2. Right-click it and choose Add to Steam."
else
  # The menu has no entry for the installed copy; one with its name may open
  # something else (the installer review fixes), so the steps never point at the menu.
  if [ "$MENU_STATE" = "other" ]; then
    say "1. First sort out the app menu entry: the $APP_NAME now in the app menu"
    say "   doesn't open this installed copy, so don't add that one to Steam."
    say "   If it is a development copy's, run ./install-shortcut.sh again in that copy, then"
    say "   run this installer again, and follow the steps it prints then."
  else
    say "1. $APP_NAME couldn't be added to the app menu (see the warning above). Run this"
    say "   installer again once that is fixed, and follow the steps it prints then."
  fi
  say "2. Or add it to Steam without the menu: in Steam, choose Games, then Add a"
  say "   Non-Steam Game to My Library, then Browse, and pick $APP_DIR/launch.sh."
  say "   Browse doesn't work on the Nova: there, use step 1, which adds $APP_NAME to the"
  say "   app menu so Steam lists it."
fi
say "3. In Gaming Mode, open $APP_NAME in your Library, choose the controller icon and set"
say "   its controller layout again: Steam keeps a layout for each shortcut. Which button"
say "   sends which key is in the README, under \"Adding it to Steam\"."
