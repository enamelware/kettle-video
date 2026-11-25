#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta
#
# Kettle spike (the folder dialog spike): opens the folder dialog test page the way
# launch.sh opens Kettle (its server started in the background with
# python3 -u, then Firefox in kiosk mode on Kettle's own profile), and
# closes both when the page's "Quit the spike" (or B) is chosen.
#
# Started from the file manager (folder-dialog-spike.desktop) or from Steam
# as a non-Steam game. Kettle must not be open at the same time (they share
# Firefox's profile). Writes one log in the project's logs/ folder, with no
# folder names in it. Nothing is installed or changed.

cd "$(dirname "$(readlink -f "$0")")/../.." || exit 1
mkdir -p logs
LOG="logs/folder-dialog-spike-$(date +%Y%m%d-%H%M%S).log"
export KETTLE_SPIKE_PORT="${KETTLE_SPIKE_PORT:-8765}"
log() { echo "$(date +%H:%M:%S) $*" >>"$LOG"; }

log "folder dialog spike: session ${XDG_SESSION_TYPE:-unknown}, desktop ${XDG_CURRENT_DESKTOP:-none}, gamescope: $([ -n "$GAMESCOPE_WAYLAND_DISPLAY" ] && echo yes || echo no)"
python3 -u spikes/folder-dialog/server.py >>"$LOG" 2>&1 &
SERVER_PID=$!
for _ in $(seq 1 50); do
  (exec 3<>"/dev/tcp/127.0.0.1/$KETTLE_SPIKE_PORT") 2>/dev/null && break
  sleep 0.2
done

URL="http://127.0.0.1:$KETTLE_SPIKE_PORT/"
INSTANCE=""
if command -v firefox >/dev/null 2>&1; then
  PROFILE_DIR="$HOME/.mozilla/kettle-video-profile"
  if pgrep -f -- "-profile $PROFILE_DIR" >/dev/null; then
    log "Kettle is open: close it first"; kill "$SERVER_PID"; exit 1
  fi
  firefox --no-remote --new-instance -profile "$PROFILE_DIR" -kiosk "$URL" >/dev/null 2>&1 &
  FIREFOX_PID=$!
  log "system firefox"
else
  PROFILE_DIR="$HOME/.var/app/org.mozilla.firefox/data/kettle-video-profile"
  if pgrep -f -- "-profile $PROFILE_DIR" >/dev/null; then
    log "Kettle is open: close it first"; kill "$SERVER_PID"; exit 1
  fi
  ID_FILE="logs/folder-dialog-spike-instance"
  flatpak run --instance-id-fd=8 org.mozilla.firefox --no-remote -profile "$PROFILE_DIR" -kiosk "$URL" >/dev/null 2>&1 8>"$ID_FILE" &
  FIREFOX_PID=$!
  for _ in $(seq 1 50); do
    INSTANCE="$(tr -dc '0-9' <"$ID_FILE" 2>/dev/null)"
    [ -n "$INSTANCE" ] && break
    sleep 0.2
  done
  rm -f "$ID_FILE"
  log "flatpak firefox, instance ${INSTANCE:-unknown}"
fi

firefox_open() {
  if [ -n "$INSTANCE" ]; then
    flatpak ps --columns=instance 2>/dev/null | grep -qx "$INSTANCE"
  else
    kill -0 "$FIREFOX_PID" 2>/dev/null
  fi
}

while kill -0 "$SERVER_PID" 2>/dev/null && firefox_open; do
  sleep 0.5
done

# Close Firefox gently, as launch.sh does, so its profile stays healthy.
if firefox_open; then
  if [ -n "$INSTANCE" ]; then
    SANDBOX="$(flatpak ps --columns=instance,pid 2>/dev/null | awk -v i="$INSTANCE" '$1 == i { print $2 }')"
    [ -n "$SANDBOX" ] && pkill -TERM -P "$SANDBOX" -x 'firefox|firefox-bin'
  else
    kill "$FIREFOX_PID"
  fi
  for _ in $(seq 1 50); do firefox_open || break; sleep 0.2; done
  if firefox_open && [ -n "$INSTANCE" ]; then flatpak kill "$INSTANCE"; fi
fi
kill "$SERVER_PID" 2>/dev/null
log "folder dialog spike closed"
