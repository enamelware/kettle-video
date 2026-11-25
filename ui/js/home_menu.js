// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Mario Carabotta

// Home's menu and scan toast (the Home actions work): the words only, no page, so the
// browser checks can call them directly.

export function plural(n, word) {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

// The menu's rows, in order: { value, title, destructive? }. "Remove N
// missing items" only when there are some; while a scan runs the first row
// reads "Scanning…" and choosing it starts nothing. Settings (issue 100)
// comes just before Quit. Cancel is always last. Quit is the one
// destructive row (issue 98): since Enamel 0.13.0 that row looks like the
// others until it has the focus, then turns red.
export function menuRows({ missing = 0, scanning = false } = {}) {
  const rows = [{ value: scanning ? "scanning" : "rescan", title: scanning ? "Scanning…" : "Rescan library" }];
  if (missing > 0) rows.push({ value: "remove-missing", title: `Remove ${plural(missing, "missing item")}` });
  rows.push({ value: "settings", title: "Settings" });
  rows.push({ value: "quit", title: "Quit", destructive: true });
  rows.push({ value: "cancel", title: "Cancel" });
  return rows;
}

// The toast while a scan runs: "Scanning…", then "Scanning… 124 files" once
// the scan has counted some.
export function scanProgressText(status) {
  const done = status && status.files_done > 0 ? status.files_done : 0;
  return done > 0 ? `Scanning… ${plural(done, "file")}` : "Scanning…";
}

export const SCAN_FAILED = "Couldn't scan the library. The saved library is unchanged.";
export const SCAN_BUSY = "Rescan unavailable while playing";

// The toast once the scan is over: the backend's result in words ("3
// added, 1 missing", "No changes"), or why it didn't run.
export function scanResultText(result) {
  if (!result) return SCAN_FAILED;
  if (result.busy) return SCAN_BUSY;
  if (!result.ok) return result.error || SCAN_FAILED;
  return result.message || "No changes";
}
