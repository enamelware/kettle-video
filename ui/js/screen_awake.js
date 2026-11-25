// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Mario Carabotta

// Keeps the screen on while a film plays (the screen wake lock fix).
//
// mpv already runs under the system's stay-awake lock (the keep-awake work), but in
// Gaming Mode Steam's own dim and screen-off timers don't look at it. Since
// its 13 October 2026 update, Steam delays them when a web browser asks to
// keep the screen on while video plays. Kettle's screen is a web page, so it
// asks Firefox for that with the standard Screen Wake Lock, from the start
// of a film until mpv closes. Reasons: docs/decisions.md.

// Starts keeping the screen on; returns the function that stops it.
// report(state) is told each change: "held", "lost" (Firefox let go, for
// example while the page was hidden; asked again once it shows), "refused",
// "unsupported" or "released".
export function keepScreenOn(report) {
  if (!navigator.wakeLock) {
    report("unsupported");
    return () => {};
  }
  let wanted = true;
  let lock = null;
  let asking = false;

  async function ask() {
    if (!wanted || lock || asking) return;
    asking = true;
    try {
      const granted = await navigator.wakeLock.request("screen");
      if (!wanted) {
        // The film ended while Firefox was answering.
        granted.release().catch(() => {});
        return;
      }
      lock = granted;
      lock.addEventListener("release", () => {
        if (lock !== granted) return;
        lock = null;
        if (wanted) report("lost");
      });
      report("held");
    } catch (err) {
      report("refused");
    } finally {
      asking = false;
    }
  }

  function onVisibilityChange() {
    if (document.visibilityState === "visible") ask();
  }

  document.addEventListener("visibilitychange", onVisibilityChange);
  ask();

  return () => {
    if (!wanted) return;
    wanted = false;
    document.removeEventListener("visibilitychange", onVisibilityChange);
    const held = lock;
    lock = null;
    if (held) held.release().catch(() => {});
    report("released");
  };
}
