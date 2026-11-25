// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Mario Carabotta

// Start-up problem (the start-up problem screen): writes the message the launcher's small
// message server gives, one paragraph per line, and closes with A or B (and
// Enter or Escape on a keyboard). Closing tells the server, which ends; the
// launcher then closes this window, as it does when the app quits. Up and
// Down scroll, so in a small window every word can be read.

// The app's own play and quit keys (keyboard.js): A sends Space, B sends q.
const CLOSE_KEYS = new Set(["Enter", " ", "Spacebar", "q", "Q", "Escape"]);

const linesEl = document.querySelector('#startup-error [data-role="lines"]');
const button = document.querySelector('#startup-error [data-kind="close"]');
let closing = false;

function post(path) {
  return fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
}

function close() {
  if (closing) return;
  closing = true;
  post("/api/close").catch(() => {});
}

async function show() {
  let lines = ["Kettle couldn't start."];
  try {
    lines = (await (await fetch("/api/startup-error")).json()).lines;
  } catch {
    // The server is already gone: the launcher is closing this window.
  }
  linesEl.replaceChildren(...lines.map((line) => {
    const p = document.createElement("p");
    p.textContent = line;
    return p;
  }));
  // Enamel's button shows focus on data-focused; the page moves the focus
  // itself, and keeps the button in view, as on "mpv not found".
  button.dataset.focused = "true";
  button.focus();
  button.scrollIntoView({ block: "nearest", inline: "nearest" });
  post("/api/shown").catch(() => {});
}

// A window made smaller (the kiosk window going full screen, say) doesn't
// leave Close out of view, as on "mpv not found" (the mpv missing screen).
window.addEventListener("resize", () => {
  if (button.dataset.focused) button.scrollIntoView({ block: "nearest", inline: "nearest" });
});

document.addEventListener("keydown", (event) => {
  if (!CLOSE_KEYS.has(event.key)) return;
  event.preventDefault();
  close();
});
button.addEventListener("click", close);

show();
