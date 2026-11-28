// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Mario Carabotta

// Start-up problem (the start-up problem screen): writes the message the launcher's small
// message server gives, one paragraph per line, and closes with A or B (and
// Enter or Escape on a keyboard). Closing tells the server, which ends; the
// launcher then closes this window, as it does when the app quits. Up and
// Down scroll, so in a small window every word can be read.
//
// Back to main (the "Try a branch" work): on a development copy on a branch that
// couldn't start, the server also offers Back to main. Close stays focused
// first; Left and Right move between the two, A presses the focused one, B
// always closes. Its answer is shown in the status line, and the button goes.

// The app's own play and quit keys (keyboard.js): A sends Space, B sends q.
const A_KEYS = new Set(["Enter", " ", "Spacebar"]);
const B_KEYS = new Set(["q", "Q", "Escape"]);
const MOVE_KEYS = new Set(["ArrowLeft", "ArrowRight"]);

const linesEl = document.querySelector('#startup-error [data-role="lines"]');
const statusEl = document.querySelector('#startup-error [data-role="status"]');
const button = document.querySelector('#startup-error [data-kind="close"]');
const mainButton = document.querySelector('#startup-error [data-kind="back-to-main"]');
const aHint = document.querySelector('[data-role="a-hint"]');
let closing = false;
let switching = false;
let focused = button;

function post(path) {
  return fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
}

function close() {
  if (closing) return;
  closing = true;
  post("/api/close").catch(() => {});
}

// Enamel's button shows focus on data-focused; the page moves the focus
// itself, and keeps the button in view, as on "mpv not found".
function focus(el) {
  for (const b of [button, mainButton]) delete b.dataset.focused;
  focused = el;
  el.dataset.focused = "true";
  el.focus();
  el.scrollIntoView({ block: "nearest", inline: "nearest" });
  aHint.textContent = el === mainButton ? "Back to main" : "Close";
}

async function backToMain() {
  if (switching || closing) return;
  switching = true;
  let answer;
  try {
    answer = await (await post("/api/back-to-main")).json();
  } catch {
    answer = { ok: false, text: "Couldn't go back to main. Nothing was changed." };
  }
  switching = false;
  statusEl.textContent = answer.text || "";
  statusEl.hidden = !statusEl.textContent;
  if (answer.ok) {
    mainButton.hidden = true;
    focus(button);
  }
}

async function show() {
  let message = { lines: ["Kettle couldn't start."] };
  try {
    message = await (await fetch("/api/startup-error")).json();
  } catch {
    // The server is already gone: the launcher is closing this window.
  }
  const lines = [...message.lines];
  if (message.back_to_main) lines.push(`This copy is on ${message.back_to_main}.`);
  linesEl.replaceChildren(...lines.map((line) => {
    const p = document.createElement("p");
    p.textContent = line;
    return p;
  }));
  mainButton.hidden = !message.back_to_main;
  focus(button);
  post("/api/shown").catch(() => {});
}

// A window made smaller (the kiosk window going full screen, say) doesn't
// leave the focused button out of view, as on "mpv not found" (the mpv missing screen).
window.addEventListener("resize", () => {
  if (focused.dataset.focused) focused.scrollIntoView({ block: "nearest", inline: "nearest" });
});

document.addEventListener("keydown", (event) => {
  if (B_KEYS.has(event.key)) {
    event.preventDefault();
    close();
  } else if (A_KEYS.has(event.key)) {
    event.preventDefault();
    if (focused === mainButton && !mainButton.hidden) backToMain();
    else close();
  } else if (MOVE_KEYS.has(event.key) && !mainButton.hidden) {
    event.preventDefault();
    focus(focused === button ? mainButton : button);
  }
});
button.addEventListener("click", close);
mainButton.addEventListener("click", backToMain);

show();
