// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Mario Carabotta

// Small helpers for building the page, shared by the screens.

export function addSpan(parent, className, text) {
  const span = document.createElement("span");
  if (className) span.className = className;
  span.textContent = text;
  parent.appendChild(span);
  return span;
}

// One of Enamel's buttons for a screen's own actions: the app's class first,
// data-kind saying which action, primary or not. The app moves the focus
// itself, so it can't be reached with Tab (the onboarding tidy-up: shared by onboarding's
// buttons and the "mpv not found" screen's Look again).
export function actionButton(className, kind, words, primary) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `${className} en-button${primary ? " en-button--primary" : ""}`;
  button.tabIndex = -1;
  button.dataset.kind = kind;
  button.textContent = words;
  return button;
}
