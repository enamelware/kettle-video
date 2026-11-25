#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta
#
# Uninstall Kettle Video from your home folder (the uninstaller work).
#
#   bash ~/.local/share/kettle-video/app/installer/uninstall.sh
#
# It removes what the installer (install.sh, update.py) put in place:
#   - the app files: ~/.local/share/kettle-video/app (a shortcut to the
#     current version) and ~/.local/share/kettle-video/versions;
#   - the app menu entry (kettle-video.desktop);
#   - the kiosk window's Firefox profile (kettle-video-profile), which holds
#     nothing personal: the launcher rebuilds it at every launch (the designer's
#     decision on the uninstaller work).
#
# It keeps your data: the library and Continue watching
# (~/.local/share/kettle-video/data), your settings
# (~/.config/kettle-video) and the logs (~/.local/state/kettle-video/logs).
# It removes those too only if you ask, and then only after you confirm.
#
# Every place comes from installer/names.env (beside this script) and the
# same standard folders the installer uses (XDG_DATA_HOME, XDG_CONFIG_HOME
# and XDG_STATE_HOME respected), never from a path typed in or a guess.
# Everything is checked before anything is removed; if something looks
# unexpected (the app isn't installed there, a folder isn't what the
# installer made, a place outside your home folder, the app still open) it
# stops and says so, with nothing removed.
#
# It never touches your movies and TV shows, mpv (it stays installed, with
# the resume positions it keeps itself), or Steam's files: the Steam
# shortcut is removed by hand. It never uses sudo.

set -u

main() {
  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

  say() { printf '%s\n' "$*"; }
  # Stop before anything was removed.
  stop() {
    say ""
    say "Uninstall stopped: $*"
    say "Nothing was removed."
    exit 1
  }
  ask() {
    local answer=""
    printf '%s [y/N] ' "$1"
    read -r answer || answer=""
    say ""
    case "$answer" in
      y|Y|yes|Yes|YES) return 0 ;;
    esac
    return 1
  }

  # --- names ---
  APP_ID="" APP_NAME="" DESKTOP_ENTRY="" INSTALL_MARK="" FIREFOX_PROFILE=""
  if [ -f "$script_dir/names.env" ]; then
    . "$script_dir/names.env"
  fi
  if [ -z "$APP_ID" ] || [ -z "$APP_NAME" ] || [ -z "$DESKTOP_ENTRY" ] ||
     [ -z "$INSTALL_MARK" ] || [ -z "$FIREFOX_PROFILE" ]; then
    stop "this uninstall script is missing its names (installer/names.env beside it)."
  fi
  local name
  for name in "$APP_ID" "$DESKTOP_ENTRY" "$INSTALL_MARK" "$FIREFOX_PROFILE"; do
    case "$name" in
      */*|.|..) stop "installer/names.env holds a name that isn't a plain name ($name)." ;;
    esac
  done

  say "Uninstalling $APP_NAME"
  say ""

  if [ "$(id -u)" -eq 0 ]; then
    stop "run it as yourself, not as root or with sudo. $APP_NAME is installed in your own home folder."
  fi
  case "${HOME:-}" in
    /?*) ;;
    *) stop "your home folder couldn't be found." ;;
  esac
  [ -d "$HOME" ] || stop "your home folder couldn't be found."
  local home_real
  home_real="$(cd "$HOME" && pwd -P)" || stop "your home folder couldn't be found."
  [ "$home_real" != "/" ] || stop "your home folder is the whole system."

  # --- where things are (install.sh and backend/app_paths.py say the same) ---
  place() {
    case "$1" in
      /*) printf '%s' "$1" ;;
      *) printf '%s' "$HOME/$2" ;;
    esac
  }
  local data_home share_dir app_dir versions_dir data_dir config_dir state_dir logs_dir
  local desktop_file
  data_home="$(place "${XDG_DATA_HOME:-}" .local/share)"
  share_dir="$data_home/$APP_ID"
  app_dir="$share_dir/app"
  versions_dir="$share_dir/versions"
  data_dir="$share_dir/data"
  config_dir="$(place "${XDG_CONFIG_HOME:-}" .config)/$APP_ID"
  state_dir="$(place "${XDG_STATE_HOME:-}" .local/state)/$APP_ID"
  logs_dir="$state_dir/logs"
  desktop_file="$data_home/applications/$DESKTOP_ENTRY"
  # The kiosk window's profile, in the two places launch.sh keeps it
  # (system Firefox, Flatpak Firefox).
  local profiles=("$HOME/.mozilla/$FIREFOX_PROFILE"
                  "$HOME/.var/app/org.mozilla.firefox/data/$FIREFOX_PROFILE")

  # Inside the home folder, once every shortcut on the way is followed.
  in_home() {
    local real
    real="$(realpath -m -- "$1" 2>/dev/null)" || return 1
    case "$real" in
      "$home_real"/?*) return 0 ;;
    esac
    return 1
  }
  local where
  for where in "$share_dir" "$desktop_file" "$config_dir" "$state_dir" "${profiles[@]}"; do
    in_home "$where" ||
      stop "$where is outside your home folder ($HOME), so it is left alone."
  done

  # --- the app files: only what the installer made ---
  # app is a shortcut to a folder in versions/ beside it (the installer's update step), or, for an
  # install made before updates existed (the installer work), a folder with the mark.
  local layout=""
  if [ -L "$app_dir" ]; then
    local target
    target="$(readlink -- "$app_dir")"
    case "$target" in
      versions/*/*|versions/*..*) ;;
      versions/?*) layout="link" ;;
    esac
    [ -n "$layout" ] ||
      stop "$app_dir points somewhere the installer never puts the app ($target)."
  elif [ -d "$app_dir" ]; then
    [ -f "$app_dir/$INSTALL_MARK" ] ||
      stop "$app_dir wasn't made by the installer (its mark file is missing)."
    layout="folder"
  elif [ -e "$app_dir" ]; then
    stop "$app_dir isn't what the installer made."
  else
    stop "$APP_NAME isn't installed here: $app_dir is missing."
  fi
  # versions/ may already be gone if an earlier uninstall stopped part way.
  if [ -e "$versions_dir" ] || [ -L "$versions_dir" ]; then
    { [ -d "$versions_dir" ] && [ ! -L "$versions_dir" ]; } ||
      stop "$versions_dir isn't the folder the installer made."
  fi

  # --- the menu entry: only the one that starts this app ---
  # Any other entry with that name (a development copy's, made by an older
  # install-shortcut.sh, or anything else) is left alone and the uninstall
  # carries on (the installer review fixes).
  local entry_found="" entry_other=""
  if [ -e "$desktop_file" ] || [ -L "$desktop_file" ]; then
    if [ -f "$desktop_file" ] && [ ! -L "$desktop_file" ] &&
       grep -qxF "Exec=\"$app_dir/launch.sh\"" "$desktop_file"; then
      entry_found=1
    else
      entry_other=1
    fi
  fi

  # --- the Firefox profile ---
  local profile found_profiles=()
  for profile in "${profiles[@]}"; do
    if [ -e "$profile" ] || [ -L "$profile" ]; then
      { [ -d "$profile" ] && [ ! -L "$profile" ]; } ||
        stop "$profile isn't the Firefox profile folder the app makes."
      found_profiles+=("$profile")
    fi
  done

  # --- not while the app is open, or an install or update is running ---
  if [ -f "$logs_dir/launch.lock" ] && command -v flock >/dev/null 2>&1; then
    exec 9<"$logs_dir/launch.lock" || stop "couldn't check whether $APP_NAME is open."
    flock -n 9 || stop "$APP_NAME is open. Close it (Quit in its menu), then run this again."
  fi
  if [ -d "$versions_dir" ] && command -v flock >/dev/null 2>&1; then
    exec 8<"$versions_dir" || stop "couldn't check whether an install or update is running."
    flock -n 8 || stop "an install or update is running. Wait for it to finish, then run this again."
  fi

  # --- your movies and TV shows are never inside what is removed ---
  local settings_file="$config_dir/settings.json" media=""
  if [ -f "$settings_file" ]; then
    media="$(python3 -I -c '
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as f:
        data = json.load(f)
except (OSError, ValueError):
    sys.exit(0)
if isinstance(data, dict):
    for key in ("movies_path", "tv_path"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            print(value.strip())
' "$settings_file" 2>/dev/null)"
  fi
  # Stop if a media folder is (or is inside) a place about to be removed.
  guard_media() {
    local removed folder removed_real folder_real
    removed="$1"
    removed_real="$(realpath -m -- "$removed" 2>/dev/null)" || return 0
    while IFS= read -r folder; do
      [ -n "$folder" ] || continue
      case "$folder" in
        "~"/*) folder="$HOME/${folder#\~/}" ;;
      esac
      folder_real="$(realpath -m -- "$folder" 2>/dev/null)" || continue
      case "$folder_real/" in
        "$removed_real"/*)
          stop "your media folder $folder is inside $removed, which the uninstall would remove." ;;
      esac
    done <<<"$media"
  }
  for where in "$app_dir" "$versions_dir" "${found_profiles[@]}"; do
    if [ -e "$where" ]; then guard_media "$where"; fi
  done
  if [ -n "$entry_found" ]; then guard_media "$desktop_file"; fi

  # --- what will happen ---
  say "This removes:"
  say "- the app files: $app_dir"
  [ -d "$versions_dir" ] && say "  and $versions_dir"
  if [ -n "$entry_found" ]; then
    say "- $APP_NAME in the app menu: $desktop_file"
  fi
  for profile in "${found_profiles[@]}"; do
    say "- the app window's Firefox profile (nothing personal in it): $profile"
  done
  if [ -n "$entry_other" ]; then
    say "It leaves $desktop_file alone: it doesn't start the installed $APP_NAME."
  fi
  say ""
  say "It keeps your data, unless you ask below:"
  say "- your library and Continue watching: $data_dir"
  say "- your settings: $config_dir"
  say "- the logs: $logs_dir"
  say "Your movies and TV shows, mpv and Steam are never touched."
  say ""
  if ! ask "Uninstall $APP_NAME?"; then
    say "Nothing was removed."
    exit 0
  fi

  local remove_data=""
  if ask "Also delete your library, settings and logs? (If you install $APP_NAME again, it starts from scratch.)"; then
    for where in "$data_dir" "$config_dir" "$logs_dir"; do
      if [ -e "$where" ] || [ -L "$where" ]; then
        { [ -d "$where" ] && [ ! -L "$where" ]; } ||
          stop "$where isn't the folder the installer made, so it is left alone."
        guard_media "$where"
      fi
    done
    say "This deletes them for good; it can't be undone:"
    say "- $data_dir"
    say "- $config_dir"
    say "- $logs_dir"
    if ask "Delete your library, settings and logs?"; then
      remove_data=1
    else
      say "Your library, settings and logs are kept."
    fi
  fi

  # --- remove ---
  local problems=0
  remove() {
    rm -rf -- "$1" || { say "  Warning: couldn't remove $1."; problems=1; }
  }
  if [ -n "$entry_found" ]; then
    remove "$desktop_file"
    if command -v update-desktop-database >/dev/null 2>&1; then
      update-desktop-database "$(dirname "$desktop_file")" >/dev/null 2>&1
    fi
  fi
  for profile in "${found_profiles[@]}"; do
    remove "$profile"
  done
  if [ -n "$remove_data" ]; then
    remove "$data_dir"
    remove "$config_dir"
    remove "$logs_dir"
    rmdir -- "$state_dir" 2>/dev/null
  fi
  # The versions first, the app shortcut last: if this stops part way, the
  # shortcut is still there and running this again finishes the job.
  [ -d "$versions_dir" ] && remove "$versions_dir"
  remove "$app_dir"
  rmdir -- "$share_dir" 2>/dev/null

  say ""
  if [ "$problems" -ne 0 ]; then
    say "Done, with warnings: some files couldn't be removed (listed above)."
  else
    say "Done. $APP_NAME is uninstalled."
  fi
  if [ -n "$remove_data" ]; then
    say "Your library, settings and logs were deleted."
  else
    say "Your library, settings and logs are kept; installing $APP_NAME again picks them up."
  fi
  say "mpv is still installed."
  say ""
  say "One step is yours: remove $APP_NAME from Steam by hand (this never changes Steam's"
  say "files). In Desktop Mode, open Steam, right-click $APP_NAME in your Library and choose"
  say "Manage, then Remove non-Steam game from your library."
  [ "$problems" -eq 0 ]
}

{ main "$@"; exit $?; }
