// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Mario Carabotta

// How long the first mpv check may take before the loading screen gives up
// on it (the settings mistakes work). It answers at once in normal use; a cold Flatpak check
// can take a few seconds.
const MPV_STATUS_TIMEOUT_MS = 30000;

// Throws unless the answer is { available: true | false, ... }, so a broken
// or silent backend never leaves the loading screen spinning.
async function readMpvStatus(res) {
  if (!res.ok) throw new Error(`mpv status request failed: ${res.status}`);
  const status = await res.json();
  if (!status || typeof status.available !== "boolean") {
    throw new Error("unexpected mpv status answer");
  }
  return status;
}

export async function getMpvStatus() {
  return readMpvStatus(await fetch("/api/mpv-status", {
    signal: AbortSignal.timeout(MPV_STATUS_TIMEOUT_MS),
  }));
}

// Look again on the "mpv not found" screen (the mpv missing screen): the same answer, with
// mpv_command read again from settings.json first.
export async function lookForMpvAgain() {
  return readMpvStatus(await fetch("/api/mpv-status/look-again", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    signal: AbortSignal.timeout(MPV_STATUS_TIMEOUT_MS),
  }));
}

export async function getLibrary() {
  const res = await fetch("/api/library");
  if (!res.ok) throw new Error(`library request failed: ${res.status}`);
  return res.json();
}

// The saved library (the saved library work): loads at once, never scans. A fixture
// count (developer only, the Movies list work) asks for that many invented films.
export async function getParsedLibrary(fixture) {
  const res = await fetch(fixture ? `/api/library/parsed?fixture=${fixture}` : "/api/library/parsed");
  if (!res.ok) throw new Error(`parsed library request failed: ${res.status}`);
  return res.json();
}

// Starts a scan of both folders, or joins the one already running. While a
// film plays it answers { busy: true } instead (the quick rescan and Remove work).
export async function startScan() {
  const res = await fetch("/api/library/scan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  if (res.status === 409) return res.json();
  if (!res.ok) throw new Error(`scan request failed: ${res.status}`);
  return res.json();
}

// Deletes everything marked missing from the saved library (the quick rescan and Remove work):
// { ok, removed } or { ok: false, error }.
export async function removeMissing() {
  const res = await fetch("/api/library/remove-missing", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  return res.json();
}

export async function getScanStatus() {
  const res = await fetch("/api/library/scan/status");
  if (!res.ok) throw new Error(`scan status request failed: ${res.status}`);
  return res.json();
}

// Developer options: { fresh_start, size_readout } when on (the fresh start mode, the sizing spike).
export async function getDevInfo() {
  const res = await fetch("/api/dev");
  if (!res.ok) throw new Error(`dev info request failed: ${res.status}`);
  return res.json();
}

// Check for updates (issue 111): the only request that goes online, and only
// when the viewer chooses the row. The server makes it and answers with
// { state: "current" | "newer" | "error", text, last_checked, notes, ... }.
export async function checkForUpdates() {
  const res = await fetch("/api/updates/check", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  if (!res.ok) throw new Error(`update check failed: ${res.status}`);
  return res.json();
}

// Update and restart, Pull the latest version (issue 112). Each starts only
// after the viewer's yes in Settings; the server does the work in the
// background and the page follows it with getUpdateStatus().
async function postUpdate(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok && res.status !== 409) throw new Error(`${path} failed: ${res.status}`);
  return res.json();
}

// { ok: true, boot, state, text } once started, or { ok: false, text }.
export function startUpdate(version) {
  return postUpdate("/api/updates/install", { version });
}

export function startPull() {
  return postUpdate("/api/updates/pull", {});
}

// Only while downloading: { ok }.
export function cancelUpdate() {
  return postUpdate("/api/updates/cancel", {});
}

// Try a branch (the "Try a branch" work), development copies only. The list
// goes online, only when the viewer chooses the row: { ok, branches, titles }
// or { ok: false, text }. The others start like Pull, after the viewer's yes.
export async function listBranches() {
  return postUpdate("/api/branches/list", {});
}

export function switchBranch(branch) {
  return postUpdate("/api/branches/switch", { branch });
}

export function backToMain() {
  return postUpdate("/api/branches/main", {});
}

export function restoreData(id) {
  return postUpdate("/api/branches/restore", { id });
}

// { state, text, running, boot }: boot changes once the restarted server answers.
export async function getUpdateStatus() {
  const res = await fetch("/api/updates/status", { cache: "no-store" });
  if (!res.ok) throw new Error(`update status failed: ${res.status}`);
  return res.json();
}

// After a restart in place: { note } ("Updated to 1.1.0"), given once.
export function takeUpdateNote() {
  return postUpdate("/api/updates/note", {});
}

// Developer option (the sizing spike): the sizes for the launch log's readout line.
export async function postSizeReadout(sizes) {
  const res = await fetch("/api/size-readout", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(sizes),
  });
  if (!res.ok) throw new Error(`size readout request failed: ${res.status}`);
  return res.json();
}

// How long a play or status request may take before the backend counts as
// not answering (the stuck Playing fix). Both answer at once in normal use.
const PLAYBACK_REQUEST_TIMEOUT_MS = 10000;

// A refused play (already playing, mpv missing, bad path) still comes back
// as { error, hint }; a backend that doesn't answer, or answers with
// something that isn't JSON, throws. A film from the Movies list is asked
// for by its ID (the Movies list work), everything else by its relative path.
export async function play(source, path, id) {
  const res = await fetch("/api/play", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(id ? { source, id } : { source, path }),
    signal: AbortSignal.timeout(PLAYBACK_REQUEST_TIMEOUT_MS),
  });
  return res.json();
}

// A Continue watching tile resumes by its ID (the Continue watching work); same answers as play.
export async function resume(id) {
  const res = await fetch("/api/play", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ continue: id }),
    signal: AbortSignal.timeout(PLAYBACK_REQUEST_TIMEOUT_MS),
  });
  return res.json();
}

// The Continue watching carousel (the Continue watching work): { items: [...] }, at most 6.
export async function getContinue() {
  const res = await fetch("/api/continue");
  if (!res.ok) throw new Error(`continue watching request failed: ${res.status}`);
  return res.json();
}

// X on a tile: { ok }. The resume position is kept.
export async function removeContinue(id) {
  const res = await fetch("/api/continue/remove", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id }),
  });
  if (!res.ok) throw new Error(`continue watching remove failed: ${res.status}`);
  return res.json();
}

// Throws unless the answer is { state: "playing" | "idle", ... }.
export async function getStatus() {
  const res = await fetch("/api/status", {
    signal: AbortSignal.timeout(PLAYBACK_REQUEST_TIMEOUT_MS),
  });
  if (!res.ok) throw new Error(`status request failed: ${res.status}`);
  const status = await res.json();
  if (!status || (status.state !== "playing" && status.state !== "idle")) {
    throw new Error("unexpected status answer");
  }
  return status;
}

// Notes in the launch log what happened to the screen wake lock during a
// film (the screen wake lock fix): "held", "lost", "refused", "unsupported" or "released".
// Only a note, so a backend that doesn't answer changes nothing.
export async function reportWakeLock(state) {
  try {
    await fetch("/api/wake-lock", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ state }),
    });
  } catch (err) {
    // Nothing to do: the film plays on either way.
  }
}

export async function shutdown() {
  const res = await fetch("/api/shutdown", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  return res.json();
}

// Onboarding (the folder choice screens): { needed } is true when settings.json has
// neither folder, so the first launch asks for them. It answers at once from
// memory; the time limit is for a backend that has stopped answering, which is
// also asked when the mpv check has just failed (the mpv missing screen).
const ONBOARDING_TIMEOUT_MS = 10000;

export async function getOnboarding() {
  const res = await fetch("/api/onboarding", {
    signal: AbortSignal.timeout(ONBOARDING_TIMEOUT_MS),
  });
  if (!res.ok) throw new Error(`onboarding request failed: ${res.status}`);
  return res.json();
}

// The folders with videos, grouped by place (the folder finder): ids, names and
// counts, never a full path. Searches again on every call.
export async function findFolders() {
  const res = await fetch("/api/onboarding/folders");
  if (!res.ok) throw new Error(`folder search failed: ${res.status}`);
  return res.json();
}

// "Browse somewhere else" (the Browse somewhere else work): opens the system's folder dialog, and
// answers when it closes, however long that takes, so no time limit here.
// movies: the id chosen on screen 1, or null. { ok: true, picked: false } for
// a cancel; { ok: true, picked: true, folder, place_kind, message } for a
// folder (message when it can't be used); { ok: false, message } otherwise.
// From Settings (issue 100), settingsKind ("movies" or "tv") checks the
// folder against the other kind's folder as it is.
export async function browseFolder(movies, settingsKind) {
  const res = await fetch("/api/onboarding/browse", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settingsKind ? { movies, settings: settingsKind } : { movies }),
  });
  if (!res.ok) throw new Error(`folder dialog failed: ${res.status}`);
  return res.json();
}

// Closes a folder dialog that is open; browseFolder then answers as a cancel.
export async function closeBrowse() {
  await fetch("/api/onboarding/browse/close", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
}

// The choice, by id (null for "I don't have ..."): { ok: true } once both
// folders are saved, or { ok: false, message } to show in the row.
export async function chooseFolders(movies, tv) {
  const res = await fetch("/api/onboarding/choose", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ movies, tv }),
  });
  if (!res.ok) throw new Error(`folder choice failed: ${res.status}`);
  return res.json();
}

// What the scan found, for the result screen (the first scan screen): counts, each folder's
// place and name, and the notes, never a full path.
export async function getScanResult() {
  const res = await fetch("/api/onboarding/result");
  if (!res.ok) throw new Error(`scan result failed: ${res.status}`);
  return res.json();
}

// The Settings screen (issue 100): { folders, version, licence, credits,
// not_affiliated }. Each folder is its place path and id, never a full path.
export async function getSettings() {
  const res = await fetch("/api/settings");
  if (!res.ok) throw new Error(`settings request failed: ${res.status}`);
  return res.json();
}

// A credit's licence text, by the credit's id: { ok, name, text }.
export async function getLicence(id) {
  const res = await fetch(`/api/settings/licence?id=${encodeURIComponent(id)}`);
  if (!res.ok) throw new Error(`licence request failed: ${res.status}`);
  return res.json();
}

// One kind's folder from Settings, by id (null for "Stop using ..."):
// { ok: true, changed, scan } or { ok: false, message } to show in the row.
// scan is the rescan the change started (as startScan answers), or null.
export async function chooseSettingsFolder(kind, id) {
  const res = await fetch("/api/settings/folder", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind, id }),
  });
  if (!res.ok) throw new Error(`folder change failed: ${res.status}`);
  return res.json();
}
