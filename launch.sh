#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Where the logs go (the installer work): logs/ in this folder for a development
# copy, ~/.local/state/kettle-video/logs for an installed one
# (backend/app_paths.py). If that can't be worked out, logs/ as before.
LOG_DIR="$(python3 -m backend.app_paths logs 2>/dev/null)"
[ -n "$LOG_DIR" ] || LOG_DIR="logs"
mkdir -p "$LOG_DIR"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
# If the launcher is started again (KETTLE_LAUNCH_LOG set), it keeps writing
# to the same log and counts from the first start.
LOGFILE="${KETTLE_LAUNCH_LOG:-$LOG_DIR/launch-$TIMESTAMP.log}"
FIREFOX_LOG="$LOG_DIR/firefox-$TIMESTAMP.log"
LAUNCH_START="${KETTLE_VIDEO_LAUNCH_START:-$(date +%s.%N)}"
export KETTLE_VIDEO_LAUNCH_START="$LAUNCH_START"

log() {
  echo "$(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$LOGFILE"
}

# Only one copy of the app at a time (the start-up fix): two Firefox windows on the
# same profile give "Firefox is already running, but is not responding".
# The lock is released automatically when this script ends, however it ends.
exec 9>"$LOG_DIR/launch.lock"
if ! flock -n 9; then
  log "the app is already open or still starting — not starting a second copy"
  exit 0
fi

seconds_since_launch() {
  python3 -c "import sys, time; print(f'{time.time() - float(sys.argv[1]):.1f}')" "$LAUNCH_START"
}

BACKEND_PID=""
FIREFOX_PID=""
FIREFOX_IS_FLATPAK=0
FIREFOX_CLOSE_WAIT=15
PROFILE_DIR=""
# Flatpak only: the sandbox that holds THIS kiosk window (the Firefox crash fix). The
# `flatpak run` command can end while Firefox keeps running inside it, for
# example when Firefox restarts itself, so we watch the sandbox instead.
FLATPAK_INSTANCE=""
FLATPAK_SANDBOX_PID=""
FLATPAK_ID_FILE=""

stop_backend() {
  if [ -n "$BACKEND_PID" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill "$BACKEND_PID" 2>/dev/null
  fi
}

# Pid of the sandbox's top process for our Flatpak instance. Looked up once
# (asking Flatpak takes about 20 ms), then checked cheaply with kill -0.
flatpak_sandbox_running() {
  if [ -z "$FLATPAK_SANDBOX_PID" ]; then
    FLATPAK_SANDBOX_PID="$(flatpak ps --columns=instance,child-pid 2>/dev/null |
      awk -v id="$FLATPAK_INSTANCE" '$1 == id { print $2 }')"
    # Not listed yet: the sandbox is still starting if the launcher is.
    if [ -z "$FLATPAK_SANDBOX_PID" ]; then
      [ -n "$FIREFOX_PID" ] && kill -0 "$FIREFOX_PID" 2>/dev/null
      return
    fi
  fi
  kill -0 "$FLATPAK_SANDBOX_PID" 2>/dev/null
}

# Is this app's Firefox still open? Firefox sometimes restarts itself (after
# an update, or when its profile wasn't closed properly). The restarted copy
# has a new pid, so we look for it before saying Firefox has closed.
firefox_running() {
  if [ "$FIREFOX_IS_FLATPAK" -eq 1 ] && [ -n "$FLATPAK_INSTANCE" ]; then
    flatpak_sandbox_running || return 1
    if [ -n "$FIREFOX_PID" ] && ! kill -0 "$FIREFOX_PID" 2>/dev/null; then
      log "flatpak launcher ended but firefox is still open (it restarted itself, or is closing)"
      FIREFOX_PID=""
    fi
    return 0
  fi
  if [ -n "$FIREFOX_PID" ] && kill -0 "$FIREFOX_PID" 2>/dev/null; then
    return 0
  fi
  if [ "$FIREFOX_IS_FLATPAK" -eq 0 ] && [ -n "$PROFILE_DIR" ]; then
    local restarted
    restarted="$(pgrep -n -f -- "-profile $PROFILE_DIR")"
    if [ -n "$restarted" ]; then
      log "firefox restarted itself (new pid $restarted)"
      FIREFOX_PID="$restarted"
      return 0
    fi
  fi
  return 1
}

# Ask Firefox to close and give it time: forcing it shut too early can leave
# its profile broken for the next launch (the saved library work, the start-up fix).
wait_for_firefox_to_close() {
  for i in $(seq 1 $((FIREFOX_CLOSE_WAIT * 5))); do
    if ! firefox_running; then
      log "firefox closed cleanly in about $((i / 5)).$((i % 5 * 2)) s"
      return 0
    fi
    sleep 0.2
  done
  return 1
}

stop_firefox() {
  if [ "$FIREFOX_IS_FLATPAK" -eq 1 ]; then
    if [ -z "$FLATPAK_INSTANCE" ]; then
      # Never `flatpak kill org.mozilla.firefox`: that closes every Firefox
      # window on the device, including the user's own browser (the Firefox crash fix).
      if [ -n "$FIREFOX_PID" ] && kill -0 "$FIREFOX_PID" 2>/dev/null; then
        kill "$FIREFOX_PID" 2>/dev/null
      fi
      return
    fi
    flatpak_sandbox_running || return
    # A stop signal to the sandbox itself isn't passed on, so send it to
    # Firefox inside it; that's what lets Firefox close its profile properly.
    pkill -TERM -P "$FLATPAK_SANDBOX_PID" -x 'firefox|firefox-bin' 2>/dev/null
    if ! wait_for_firefox_to_close; then
      log "firefox did not close within $FIREFOX_CLOSE_WAIT s — forcing it shut"
      flatpak kill "$FLATPAK_INSTANCE" 2>/dev/null
    fi
    return
  fi
  if firefox_running; then
    kill "$FIREFOX_PID" 2>/dev/null
    if ! wait_for_firefox_to_close; then
      log "firefox did not close within $FIREFOX_CLOSE_WAIT s — forcing it shut"
      kill -9 "$FIREFOX_PID" 2>/dev/null
    fi
  fi
}

cleanup() {
  stop_firefox
  stop_backend
  [ -n "$FLATPAK_ID_FILE" ] && rm -f "$FLATPAK_ID_FILE"
}
trap cleanup INT TERM EXIT

PYVER_STRING="$(python3 --version 2>&1)"
log "python3 version: $PYVER_STRING"
if ! python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"; then
  log "WARNING: python3 is older than 3.10; the bundled guessit in vendor/ requires 3.10+"
fi

port_in_use() {
  (exec 3<>"/dev/tcp/127.0.0.1/$1" && exec 3>&-) 2>/dev/null
}

free_port() {
  python3 -c "import socket; s = socket.socket(); s.bind(('127.0.0.1', 0)); print(s.getsockname()[1]); s.close()"
}

# Dedicated profile kept OUTSIDE the project, per the designer's decision:
# system Firefox uses a normal non-sandboxed location, Flatpak Firefox uses
# its own writable data dir — neither needs a Flatpak permission change.
USER_JS_CONTENTS='user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("browser.aboutwelcome.enabled", false);
user_pref("startup.homepage_welcome_url", "");
user_pref("startup.homepage_welcome_url.additional", "");
user_pref("browser.sessionstore.resume_from_crash", false);
user_pref("browser.tabs.warnOnClose", false);
user_pref("datareporting.policy.firstRunURL", "");
user_pref("toolkit.telemetry.reportingpolicy.firstRun", false);
user_pref("toolkit.startup.max_resumed_crashes", -1);
// Kettle Video never goes online by itself (the never-online work): everything below
// switches off the traffic Firefox makes by itself, for this kiosk profile only.
// Update and add-on checks by Firefox itself
user_pref("app.update.auto", false);
user_pref("extensions.update.enabled", false);
user_pref("extensions.update.autoUpdateDefault", false);
user_pref("extensions.getAddons.cache.enabled", false);
user_pref("extensions.systemAddon.update.enabled", false);
user_pref("extensions.systemAddon.update.url", "");
user_pref("extensions.htmlaboutaddons.recommendations.enabled", false);
user_pref("browser.discovery.enabled", false);
// Usage reports (telemetry) and crash reports
user_pref("toolkit.telemetry.enabled", false);
user_pref("toolkit.telemetry.unified", false);
user_pref("toolkit.telemetry.archive.enabled", false);
user_pref("toolkit.telemetry.server", "");
user_pref("toolkit.telemetry.updatePing.enabled", false);
user_pref("toolkit.telemetry.bhrPing.enabled", false);
user_pref("toolkit.telemetry.firstShutdownPing.enabled", false);
user_pref("toolkit.telemetry.newProfilePing.enabled", false);
user_pref("toolkit.telemetry.shutdownPingSender.enabled", false);
user_pref("datareporting.healthreport.uploadEnabled", false);
user_pref("datareporting.policy.dataSubmissionEnabled", false);
user_pref("datareporting.usage.uploadEnabled", false);
user_pref("browser.newtabpage.activity-stream.feeds.telemetry", false);
user_pref("browser.newtabpage.activity-stream.telemetry", false);
user_pref("browser.crashReports.unsubmittedCheck.autoSubmit2", false);
user_pref("breakpad.reportURL", "");
// Studies and experiments
user_pref("app.normandy.enabled", false);
user_pref("app.normandy.api_url", "");
user_pref("app.shield.optoutstudies.enabled", false);
user_pref("messaging-system.rsexperimentloader.enabled", false);
// Safe Browsing lists (the window only ever shows the pages of the app)
user_pref("browser.safebrowsing.malware.enabled", false);
user_pref("browser.safebrowsing.phishing.enabled", false);
user_pref("browser.safebrowsing.blockedURIs.enabled", false);
user_pref("browser.safebrowsing.downloads.enabled", false);
user_pref("browser.safebrowsing.downloads.remote.enabled", false);
user_pref("browser.safebrowsing.provider.google4.updateURL", "");
user_pref("browser.safebrowsing.provider.google4.gethashURL", "");
user_pref("browser.safebrowsing.provider.google.updateURL", "");
user_pref("browser.safebrowsing.provider.google.gethashURL", "");
user_pref("browser.safebrowsing.provider.mozilla.updateURL", "");
user_pref("browser.safebrowsing.provider.mozilla.gethashURL", "");
// Media plugin downloads (OpenH264, Widevine)
user_pref("media.gmp-manager.url", "");
user_pref("media.gmp-gmpopenh264.enabled", false);
user_pref("media.gmp-widevinecdm.enabled", false);
user_pref("media.eme.enabled", false);
// Connection checks, web push, location and region, search updates
user_pref("network.captive-portal-service.enabled", false);
user_pref("network.connectivity-service.enabled", false);
user_pref("network.trr.mode", 5);
user_pref("dom.push.enabled", false);
user_pref("dom.push.connection.enabled", false);
user_pref("geo.enabled", false);
user_pref("geo.provider.network.url", "");
user_pref("browser.region.network.url", "");
user_pref("browser.region.update.enabled", false);
user_pref("browser.search.update", false);
// Background downloads: link prefetching, new tab content, suggestions,
// translations, Firefox accounts, the "what is new" page
user_pref("network.prefetch-next", false);
user_pref("network.dns.disablePrefetch", true);
user_pref("network.predictor.enabled", false);
user_pref("network.http.speculative-parallel-limit", 0);
user_pref("browser.newtab.preload", false);
user_pref("browser.newtabpage.enabled", false);
user_pref("browser.topsites.contile.enabled", false);
user_pref("extensions.pocket.enabled", false);
user_pref("browser.urlbar.quicksuggest.enabled", false);
user_pref("browser.translations.enable", false);
user_pref("identity.fxaccounts.enabled", false);
user_pref("browser.startup.homepage_override.mstone", "ignore");
// Dead end: anything not for the server of the app on this device
user_pref("network.proxy.type", 1);
user_pref("network.proxy.http", "127.0.0.1");
user_pref("network.proxy.http_port", 9);
user_pref("network.proxy.ssl", "127.0.0.1");
user_pref("network.proxy.ssl_port", 9);
user_pref("network.proxy.share_proxy_settings", true);
user_pref("network.proxy.allow_hijacking_localhost", false);
// ... with no way round it: Firefox would otherwise go direct when the door
// is closed, and let its own settings downloads skip the proxy
user_pref("network.proxy.failover_direct", false);
user_pref("network.proxy.allow_bypass", false);
// The Terms of Use notice Firefox shows on the first launch of a new profile
user_pref("termsofuse.bypassNotification", true);
// The "restore your previous session" suggestion on a later launch
user_pref("browser.startup.couldRestoreSession.count", -1);
'

# Written at every launch, so settings added later reach existing profiles.
# max_resumed_crashes -1: never stop on "Firefox closed unexpectedly while
# starting" (a Safe Mode question no one can answer with a controller). A
# start Firefox didn't finish, for example after a hard close, adds to its
# count; past 3 it asked instead of opening the app (the saved library work).
write_profile_prefs() {
  local profile_dir="$1"
  mkdir -p "$profile_dir"
  printf '%s' "$USER_JS_CONTENTS" > "$profile_dir/user.js"
}

# Which Firefox the app can use: "system", "flatpak", or empty for none.
# Looked up before the backend starts, so a missing Firefox is said on
# screen at once (the start-up problem screen).
FIREFOX_KIND=""
if command -v firefox >/dev/null 2>&1; then
  FIREFOX_KIND="system"
  log "found system firefox"
elif flatpak info org.mozilla.firefox >/dev/null 2>&1; then
  FIREFOX_KIND="flatpak"
  log "found flatpak firefox"
fi

# The kiosk window's own Firefox profile, outside the app folder. Each copy
# has its own (the each-copy-its-own-data work): kettle-video-profile for the
# installed copy, kettle-video-dev-profile for a development copy, so neither
# ever reads or changes the other's browser storage (backend/app_paths.py
# says which, from installer/names.env). This script writes its settings at
# every launch and the app keeps nothing in the browser, so a new profile
# loses nothing. The profile used before the rename to Kettle Video (the
# Kettle Video rename) is never changed or deleted; the log only says it can
# be removed by hand.
if [ "$FIREFOX_KIND" = "system" ]; then
  PROFILE_HOME="$HOME/.mozilla"
else
  PROFILE_HOME="$HOME/.var/app/org.mozilla.firefox/data"
fi
PROFILE_NAME="$(python3 -m backend.app_paths profile 2>/dev/null)"
case "$PROFILE_NAME" in
  ""|*/*|.|..)
    # The same answer from the install mark, if Python couldn't give it.
    if [ -f "$SCRIPT_DIR/kettle-video-installed" ]; then
      PROFILE_NAME="kettle-video-profile"
    else
      PROFILE_NAME="kettle-video-dev-profile"
    fi
    ;;
esac
log "firefox profile: $PROFILE_NAME"
OLD_PROFILE_NAME="media-player-profile"
if [ -n "$FIREFOX_KIND" ] && [ -d "$PROFILE_HOME/$OLD_PROFILE_NAME" ]; then
  log "the old Firefox profile folder $OLD_PROFILE_NAME (in $PROFILE_HOME) is no longer used; it can be removed by hand"
fi

# Open the kiosk window on a page (the app, or the start-up problem).
start_firefox() {
  local url="$1"
  PROFILE_DIR="$PROFILE_HOME/$PROFILE_NAME"
  if [ "$FIREFOX_KIND" = "system" ]; then
    write_profile_prefs "$PROFILE_DIR"
    firefox --no-remote --new-instance -profile "$PROFILE_DIR" -kiosk "$url" >>"$FIREFOX_LOG" 2>&1 9>&- &
    FIREFOX_PID=$!
  else
    FIREFOX_IS_FLATPAK=1
    write_profile_prefs "$PROFILE_DIR"
    FLATPAK_ID_FILE="$LOG_DIR/firefox-instance-$TIMESTAMP"
    flatpak run --instance-id-fd=8 org.mozilla.firefox --no-remote -profile "$PROFILE_DIR" -kiosk "$url" >>"$FIREFOX_LOG" 2>&1 8>"$FLATPAK_ID_FILE" 9>&- &
    FIREFOX_PID=$!
    for _ in $(seq 1 50); do
      FLATPAK_INSTANCE="$(tr -dc '0-9' <"$FLATPAK_ID_FILE" 2>/dev/null)"
      [ -n "$FLATPAK_INSTANCE" ] && break
      kill -0 "$FIREFOX_PID" 2>/dev/null || break
      sleep 0.2
    done
    rm -f "$FLATPAK_ID_FILE"
    if [ -n "$FLATPAK_INSTANCE" ]; then
      log "flatpak firefox instance: $FLATPAK_INSTANCE"
    else
      log "could not tell which flatpak instance is the app's firefox; watching the launcher only"
    fi
  fi
  log "firefox pid: $FIREFOX_PID (output going to $FIREFOX_LOG)"
}

# Wait until either the backend (or the start-up message server) or the
# app's Firefox is gone. Polling rather than `wait`, because the Firefox we
# started may not be the one still open.
wait_while_both_open() {
  while kill -0 "$BACKEND_PID" 2>/dev/null && firefox_running; do
    sleep 0.5
  done
}

# With no Firefox: the same words in a dialog the system already has
# (zenity on SteamOS, else kdialog). A in Gaming Mode presses its OK.
show_startup_dialog() {
  local text
  text="$(python3 -m backend.startup_error text "$1" "$LOGFILE" 2>>"$LOGFILE" 9>&-)"
  if command -v zenity >/dev/null 2>&1; then
    log "showing the start-up problem in a zenity dialog"
    zenity --error --no-markup --title="Kettle Video" --text="$text" >>"$LOGFILE" 2>&1 9>&-
  elif command -v kdialog >/dev/null 2>&1; then
    log "showing the start-up problem in a kdialog dialog"
    kdialog --title "Kettle Video" --error "$text" >>"$LOGFILE" 2>&1 9>&-
  else
    log "could not show the start-up problem on screen: no firefox, zenity or kdialog"
  fi
}

# Never fail silently (the start-up problem screen): say on screen why the app couldn't
# start, what to do, and where this log is. With Firefox, a small message
# server (backend/startup_error.py, standard library only) gives the page
# and ends when it is closed with A or B; the launcher then closes Firefox.
show_startup_error() {
  local reason="$1" port ready=0
  log "showing the start-up problem on screen ($reason)"
  if [ -z "$FIREFOX_KIND" ]; then
    show_startup_dialog "$reason"
    return
  fi
  port="$(free_port)"
  python3 -u -m backend.startup_error serve "$reason" "$LOGFILE" "$port" >>"$LOGFILE" 2>&1 9>&- &
  BACKEND_PID=$!
  for _ in $(seq 1 50); do
    kill -0 "$BACKEND_PID" 2>/dev/null || break
    if port_in_use "$port"; then
      ready=1
      break
    fi
    sleep 0.2
  done
  if [ "$ready" -ne 1 ]; then
    log "the start-up message page did not start — trying a dialog instead"
    stop_backend
    show_startup_dialog "$reason"
    return
  fi
  start_firefox "http://127.0.0.1:$port/"
  wait_while_both_open
  stop_firefox
  stop_backend
}

if [ -z "$FIREFOX_KIND" ]; then
  log "firefox not found (checked system PATH and flatpak org.mozilla.firefox)"
  show_startup_error no-firefox
  exit 1
fi

PREFERRED_PORT="${KETTLE_VIDEO_PORT:-8756}"
if port_in_use "$PREFERRED_PORT"; then
  FREE_PORT="$(free_port)"
  log "port $PREFERRED_PORT is already in use — using $FREE_PORT instead"
  export KETTLE_VIDEO_PORT="$FREE_PORT"
else
  export KETTLE_VIDEO_PORT="$PREFERRED_PORT"
fi

log "starting backend on port $KETTLE_VIDEO_PORT"
python3 -u -m backend.server >>"$LOGFILE" 2>&1 9>&- &
BACKEND_PID=$!
log "backend pid: $BACKEND_PID"

log "waiting for backend to open port $KETTLE_VIDEO_PORT"
READY=0
for _ in $(seq 1 50); do
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    log "backend exited early — see log above for the error"
    show_startup_error backend-stopped
    exit 1
  fi
  if port_in_use "$KETTLE_VIDEO_PORT"; then
    READY=1
    break
  fi
  sleep 0.2
done

if [ "$READY" -ne 1 ]; then
  log "backend never opened its port — aborting"
  stop_backend
  show_startup_error backend-silent
  exit 1
fi
log "backend is ready"

URL="http://127.0.0.1:$KETTLE_VIDEO_PORT/"
start_firefox "$URL"

wait_while_both_open
EXIT_CODE=0

if kill -0 "$BACKEND_PID" 2>/dev/null; then
  log "firefox exited (or was closed) first after $(seconds_since_launch) s — stopping backend"
  if ! grep -q "page loaded" "$LOGFILE"; then
    log "firefox closed without ever opening the app; if this keeps happening, the app's Firefox profile ($PROFILE_NAME) may be damaged"
  fi
  stop_backend
  wait "$BACKEND_PID" 2>/dev/null
else
  wait "$BACKEND_PID" 2>/dev/null
  EXIT_CODE=$?
  log "backend exited first with status $EXIT_CODE — stopping firefox"
fi

stop_firefox

log "shutdown complete"
exit "$EXIT_CODE"
