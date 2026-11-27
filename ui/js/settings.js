// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Mario Carabotta

// Settings (issue 100), opened from Home's menu. Folders: the Movies and TV
// shows rows, each opening onboarding's folder screen for that kind only.
// About: the version, the app's licence, one row per credit in
// THIRD_PARTY_LICENSES.md (A shows its licence text, a page that Up and Down
// scroll) and a last note. Built only from Enamel's rows, their meta line and
// notes; the page only ever sees place paths, ids and words.
// Check for updates (issue 111), under the version: A asks the server for
// the one check (the only thing in the app that goes online, and only then).
// While it runs the row says Checking… and nothing else waits for it. A newer
// release adds a What's new row, showing its notes the way a licence shows.
// Update and restart (issue 112), under What's new on an installed copy, or
// Pull the latest version on a development copy: A asks in Enamel's picker
// confirm (Cancel first), then the server downloads and installs (or pulls)
// in the background, its progress in Enamel's toast; B cancels while it
// downloads. The app then restarts in place and this page reloads itself.
// Try a branch (the "Try a branch" work), on a development copy only: A lists the
// remote's branches (the row says it goes online) in Enamel's picker, open
// pull requests first; a branch, then a yes, backs up the data, switches and
// restarts in place, as Pull does. Back to main, while on a branch, says
// which one; Restore data from before the last switch names the backup's
// branch and date in its confirm.

import * as api from "./api.js";
import { addSpan } from "./dom.js";

const KIND_NAMES = { movies: "Movies", tv: "TV shows" };
const NOT_SET = "Not set";
const READ_FAILED = "Couldn't read your settings.";
const LICENCE_FAILED = "Couldn't read this licence.";
const CHECKING = "Checking…";
// When the app's own server doesn't answer the check.
const CHECK_FAILED = "Couldn't check right now. Try again later.";
const NO_NOTES = "This version came without notes.";
// When the app's own server doesn't answer Update and restart.
const UPDATE_FAILED = "Couldn't update right now. Nothing was changed. Try again later.";
// How often the page asks how the update is going.
const UPDATE_POLL_MS = 400;
const LISTING = "Listing branches…";
const LIST_FAILED = "Couldn't list the branches right now. Try again later.";
const NO_TITLES = "Pull requests couldn't be read, so only branch names show.";
const TRY_META = "Goes online to list the branches on GitHub";
const ROWS = ".settings-row";

// keyboard: the app's keyboard controller. onboarding: the onboarding screen,
// whose folder screen changes one kind. onHints when the hint bar's words
// change; onClose when B leaves Settings; onFolderChanged(answer) once a folder
// change is saved (answer.scan is the rescan it started, or null). toast:
// { show(text), update(text) }, Enamel's toast (issue 112).
export function createSettings({ keyboard, onboarding, onHints, onClose, onFolderChanged, toast }) {
  const el = document.getElementById("settings");
  const statusEl = el.querySelector('[data-role="status"]');
  const foldersEl = el.querySelector('[data-role="folders"]');
  const aboutHeading = el.querySelector('[data-role="about-heading"]');
  const notesEl = el.querySelector('[data-role="about"]');
  const updatesEl = el.querySelector('[data-role="updates"]');
  const creditsEl = el.querySelector('[data-role="credits"]');
  const endEl = el.querySelector('[data-role="not-affiliated"]');
  const licenceEl = document.getElementById("licence");
  const licenceTitle = licenceEl.querySelector('[data-role="title"]');
  const licenceNotes = licenceEl.querySelector('[data-role="notes"]');
  const licenceText = licenceEl.querySelector('[data-role="text"]');
  const confirmEl = document.getElementById("confirm-update");
  const branchPickerEl = document.getElementById("branch-picker");
  const branchRowsEl = branchPickerEl.querySelector('[data-role="rows"]');
  let open = false;
  let view = "list"; // "list", "folder" (onboarding's screen) or "licence"
  let data = null; // the last /api/settings answer
  let rows = [];
  let licenceFrom = null; // the row whose text shows (a credit, or What's new)
  // The update check: kept while Settings is closed, so a check still running
  // or its result shows when Settings opens again. Never saved.
  const update = { checking: false, result: null, lastChecked: null };
  // An update or pull running (issue 112): { boot, cancelable }, else null.
  let updating = null;
  // Try a branch's list: whether it runs, and its last words (never saved).
  const branches = { listing: false, text: "" };

  function row(kind, title, meta) {
    const item = document.createElement("li");
    item.className = "settings-row en-row";
    item.tabIndex = -1;
    item.dataset.kind = kind;
    addSpan(addSpan(item, "row-line", ""), "row-title", title);
    if (meta) addSpan(item, "en-row__meta", meta);
    return item;
  }

  function note(text) {
    const p = document.createElement("p");
    p.className = "en-note";
    p.textContent = text;
    return p;
  }

  // Check for updates, with Last checked under its label and, while it runs
  // or once it has run, its result; then What's new for a newer release.
  function updateRows() {
    const check = row("update-check", "Check for updates", update.lastChecked || data.updates.last_checked);
    check.dataset.id = "update-check";
    const status = document.createElement("span");
    status.className = "en-row__meta";
    status.dataset.role = "update-status";
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    status.textContent = update.checking ? CHECKING : update.result ? update.result.text : "";
    status.hidden = !status.textContent;
    check.append(status);
    return [check, ...foundRows(), ...branchRows()];
  }

  function foundRows() {
    const found = !update.checking && update.result;
    if (!found || found.state !== "newer") return [];
    if (found.development) {
      if (!found.can_pull) return [];
      const pull = row("pull-latest", "Pull the latest version", null);
      pull.dataset.id = "pull-latest";
      return [pull];
    }
    const news = row("whats-new", "What's new", `Version ${found.version}`);
    news.dataset.id = "whats-new";
    if (!found.can_update) return [news];
    const install = row("update-restart", "Update and restart", found.download_text || null);
    install.dataset.id = "update-restart";
    return [news, install];
  }

  // Try a branch, then Back to main while on a branch, then Restore data
  // once a switch has backed it up. Development copies only.
  function branchRows() {
    const state = data.updates.branches;
    if (!state) return [];
    const tryRow = row("try-branch", "Try a branch", TRY_META);
    tryRow.dataset.id = "try-branch";
    const status = document.createElement("span");
    status.className = "en-row__meta";
    status.dataset.role = "branch-status";
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    status.textContent = branches.listing ? LISTING : branches.text;
    status.hidden = !status.textContent;
    tryRow.append(status);
    const list = [tryRow];
    if (state.on) {
      const where = state.on.label === state.on.branch ? state.on.branch : `${state.on.label} (${state.on.branch})`;
      const main = row("back-to-main", "Back to main", `Now on ${where}`);
      main.dataset.id = "back-to-main";
      list.push(main);
    }
    if (state.restore) {
      const restore = row("restore-data", "Restore data from before the last switch", state.restore.text);
      restore.dataset.id = "restore-data";
      list.push(restore);
    }
    return list;
  }

  // The rows in the list, in order, after the update rows changed.
  function listRows() {
    return [...foldersEl.children, ...updatesEl.children, ...creditsEl.children];
  }

  function render() {
    statusEl.hidden = Boolean(data);
    statusEl.textContent = data ? "" : READ_FAILED;
    rows = [];
    if (!data) {
      foldersEl.replaceChildren();
      notesEl.replaceChildren();
      updatesEl.replaceChildren();
      creditsEl.replaceChildren();
      endEl.textContent = "";
      keyboard.setRows([]);
      return;
    }
    const folderRows = ["movies", "tv"].map((kind) => {
      const folder = data.folders[kind];
      const item = row("settings-folder", KIND_NAMES[kind], folder.set ? folder.path : NOT_SET);
      item.dataset.folder = kind;
      return item;
    });
    foldersEl.replaceChildren(...folderRows);
    notesEl.replaceChildren(note(`Version ${data.version}`), note(`Licence: ${data.licence}`));
    updatesEl.replaceChildren(...updateRows());
    const creditRows = data.credits.map((credit) => {
      const title = credit.version ? `${credit.name} ${credit.version}` : credit.name;
      const item = row("credit", title, credit.bundled ? credit.short : `${credit.short} · Not bundled`);
      item.dataset.id = credit.id;
      return item;
    });
    creditsEl.replaceChildren(...creditRows);
    endEl.textContent = data.not_affiliated;
    rows = listRows();
    keyboard.setRows(rows);
  }

  // The update rows again, in place, keeping the focus on the row it was on.
  function refreshUpdates() {
    if (!open || view !== "list" || !data) return;
    const focused = rows.includes(document.activeElement) ? document.activeElement : null;
    const key = focused && (focused.dataset.folder || focused.dataset.id);
    updatesEl.replaceChildren(...updateRows());
    rows = listRows();
    keyboard.setRows(rows);
    if (key) {
      const index = rows.findIndex((item) => (item.dataset.folder || item.dataset.id) === key);
      keyboard.focusAt(index >= 0 ? index : rows.indexOf(updatesEl.firstElementChild));
    }
  }

  // The one check, only when asked. A second A while it runs does nothing.
  async function checkForUpdates() {
    if (update.checking) return;
    update.checking = true;
    update.result = null;
    refreshUpdates();
    let result;
    try {
      result = await api.checkForUpdates();
    } catch (err) {
      result = { state: "error", text: CHECK_FAILED };
    }
    update.checking = false;
    update.result = result;
    if (result.last_checked) update.lastChecked = result.last_checked;
    refreshUpdates();
  }

  async function load() {
    try {
      data = await api.getSettings();
    } catch (err) {
      data = null;
    }
  }

  // The row with this key ("movies", "tv" or a credit's id), else the first.
  function focusKey(key) {
    const index = Math.max(0, rows.findIndex((item) => item.dataset.folder === key || item.dataset.id === key));
    if (index === 0) window.scrollTo(0, 0);
    keyboard.focusAt(index);
  }

  function showList(key) {
    view = "list";
    licenceEl.hidden = true;
    el.hidden = false;
    render();
    focusKey(key);
    onHints();
  }

  // Onboarding's folder screen, for this kind only. Settings comes back on
  // that row, read again, whether the folder changed or not.
  function changeFolder(kind) {
    view = "folder";
    el.hidden = true;
    const ids = { movies: data.folders.movies.id, tv: data.folders.tv.id };
    const back = async (saved) => {
      keyboard.setBusy(true);
      await load();
      keyboard.setBusy(false);
      if (!open) return;
      showList(kind);
      if (saved && saved.changed) onFolderChanged(saved);
    };
    onboarding.openChange(kind, ids, { onSaved: back, onBack: () => back(null) });
  }

  // A licence as plain paragraphs of text, one per block in its file. There
  // is nothing to focus: Up and Down scroll the page, B goes back.
  async function showLicence(credit) {
    view = "licence";
    licenceFrom = credit.id;
    el.hidden = true;
    licenceTitle.textContent = credit.version ? `${credit.name} ${credit.version}` : credit.name;
    const notes = [note(credit.licence)];
    let paragraphs = [];
    if (credit.bundled) {
      keyboard.setBusy(true);
      try {
        const answer = await api.getLicence(credit.id);
        paragraphs = answer.text.split(/\n\s*\n/).map((block) => block.replace(/\s+/g, " ").trim()).filter(Boolean);
      } catch (err) {
        notes.push(note(LICENCE_FAILED));
      }
      keyboard.setBusy(false);
      if (!open || view !== "licence") return;
    } else {
      notes.push(note(credit.note));
      if (credit.link) notes.push(note(credit.link));
    }
    showText(notes, paragraphs);
  }

  // The reading view's notes and paragraphs; Up and Down scroll it.
  function showText(notes, paragraphs) {
    licenceNotes.replaceChildren(...notes);
    licenceText.replaceChildren(...paragraphs.map((text) => {
      const p = document.createElement("p");
      p.textContent = text;
      return p;
    }));
    keyboard.setRows([], { scrollPage: true });
    licenceEl.hidden = false;
    window.scrollTo(0, 0);
    onHints();
  }

  // What's new: the newer release's notes, from the check's own answer
  // (nothing else is fetched), as plain paragraphs: a list item or a
  // heading is a paragraph of its own, the rest of their marks go.
  function showWhatsNew() {
    const found = update.result;
    view = "licence";
    licenceFrom = "whats-new";
    el.hidden = true;
    licenceTitle.textContent = `What's new in ${found.version}`;
    const paragraphs = [];
    let lines = [];
    const flush = () => {
      if (lines.length) paragraphs.push(lines.join(" "));
      lines = [];
    };
    for (const raw of (found.notes || "").split(/\r?\n/)) {
      const line = raw.trim();
      const item = line.match(/^[-*+]\s+(.*)$/);
      const heading = line.match(/^#+\s*(.*)$/);
      if (!line || item || heading) flush();
      if (item) paragraphs.push(`• ${item[1]}`);
      else if (heading) paragraphs.push(heading[1]);
      else if (line) lines.push(line);
    }
    flush();
    const plain = paragraphs.map((text) => text.replace(/\*\*|__|`/g, "").trim()).filter(Boolean);
    showText(plain.length ? [] : [note(NO_NOTES)], plain);
  }

  // Update and restart, or Pull the latest version: Enamel's picker confirm,
  // Cancel focused first, so a stray press changes nothing. Its yes starts it.
  function confirmUpdate(item) {
    const found = update.result;
    const pull = item.dataset.kind === "pull-latest";
    ask(item, pull ? "pull" : "update", pull ? "" : found.version, pull
      ? "Pull the latest version? Kettle Video will restart."
      : `Update to ${found.version}? Kettle Video will restart.`, pull ? "Pull and restart" : "Update and restart");
  }

  // The same confirm for every action: what, its one value, the question
  // and the action row's words.
  function ask(opener, action, value, question, words) {
    confirmEl.dataset.action = action;
    confirmEl.dataset.version = value;
    confirmEl.querySelector('[data-role="question"]').textContent = question;
    confirmEl.querySelector('[data-role="action"]').textContent = words;
    window.EnamelUI.picker.open(confirmEl, opener);
  }

  function tryRowEl() {
    return updatesEl.querySelector('[data-id="try-branch"]');
  }

  // Try a branch: the one time it goes online, only when chosen. While it
  // lists, the row says so and nothing else waits for it.
  async function listBranches() {
    if (branches.listing) return;
    branches.listing = true;
    branches.text = "";
    refreshUpdates();
    let answer;
    try {
      answer = await api.listBranches();
    } catch (err) {
      answer = { ok: false, text: LIST_FAILED };
    }
    branches.listing = false;
    branches.text = answer.ok ? (answer.titles ? "" : NO_TITLES) : answer.text || LIST_FAILED;
    refreshUpdates();
    if (!answer.ok || !open || view !== "list" || updating) return;
    const cancel = document.createElement("button");
    branchRowsEl.replaceChildren(...answer.branches.map((branch) => {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "en-picker__row";
      item.tabIndex = -1;
      item.value = branch.branch;
      item.dataset.kind = "branch";
      item.dataset.label = branch.label;
      if (branch.current) item.setAttribute("aria-current", "true");
      addSpan(item, "", branch.label);
      if (branch.desc) addSpan(item, "en-picker__desc", branch.desc);
      return item;
    }), cancel);
    cancel.type = "button";
    cancel.className = "en-picker__row en-picker__cancel";
    cancel.tabIndex = -1;
    cancel.value = "cancel";
    cancel.dataset.kind = "branch-cancel";
    addSpan(cancel, "", "Cancel");
    window.EnamelUI.picker.open(branchPickerEl, tryRowEl() || document.activeElement);
  }

  // A branch chosen: the confirm says what happens, then its yes starts it.
  branchPickerEl.addEventListener("en-select", (event) => {
    const item = event.detail.row;
    if (!item || item.dataset.kind !== "branch") return;
    const label = item.dataset.label;
    const question = `Switch to ${label}? Kettle Video backs up your data, then restarts on that branch.`;
    requestAnimationFrame(() => ask(tryRowEl() || item, "switch", item.value, question, "Switch and restart"));
  });

  function confirmBackToMain(item) {
    ask(item, "main", "", "Go back to main? Kettle Video backs up your data, then restarts on main.",
      "Back to main and restart");
  }

  function confirmRestore(item) {
    const restore = data.updates.branches.restore;
    ask(item, "restore", restore.id, restore.question, "Restore and restart");
  }

  const wait = (ms) => new Promise((done) => setTimeout(done, ms));

  // After the yes: the server works in the background; the toast follows it.
  // Everything waits for it but B, which cancels while it downloads.
  async function startUpdate(action, version) {
    if (updating || keyboard.isBusy()) return;
    let answer;
    try {
      const starts = {
        pull: () => api.startPull(),
        update: () => api.startUpdate(version),
        switch: () => api.switchBranch(version),
        main: () => api.backToMain(),
        restore: () => api.restoreData(version),
      };
      answer = await starts[action]();
    } catch (err) {
      answer = { ok: false, text: UPDATE_FAILED };
    }
    if (!answer.ok) {
      toast.show(answer.text || UPDATE_FAILED);
      return;
    }
    updating = { boot: answer.boot, cancelable: answer.state === "downloading" };
    keyboard.setBusy(true);
    onHints();
    toast.show(answer.text);
    await followUpdate();
  }

  // Asks how it goes until it ends here, or a new server answers after the
  // restart: then the page loads again, from the new version.
  async function followUpdate() {
    for (;;) {
      await wait(UPDATE_POLL_MS);
      let status;
      try {
        status = await api.getUpdateStatus();
      } catch (err) {
        continue; // restarting: the server is away for a moment
      }
      if (status.boot !== updating.boot) {
        window.location.reload();
        return;
      }
      if (status.running) {
        const cancelable = status.state === "downloading";
        if (cancelable !== updating.cancelable) {
          updating.cancelable = cancelable;
          onHints();
        }
        toast.update(status.text);
        continue;
      }
      updating = null;
      keyboard.setBusy(false);
      onHints();
      toast.show(status.text || UPDATE_FAILED);
      return;
    }
  }

  confirmEl.addEventListener("en-select", (event) => {
    if (event.detail.value === "update") startUpdate(confirmEl.dataset.action, confirmEl.dataset.version);
  });

  function select(item) {
    if (!open || view !== "list" || !rows.includes(item) || keyboard.isBusy()) return;
    if (item.dataset.kind === "settings-folder") changeFolder(item.dataset.folder);
    else if (item.dataset.kind === "update-check") checkForUpdates();
    else if (item.dataset.kind === "whats-new") showWhatsNew();
    else if (item.dataset.kind === "update-restart" || item.dataset.kind === "pull-latest") confirmUpdate(item);
    else if (item.dataset.kind === "try-branch") listBranches();
    else if (item.dataset.kind === "back-to-main") confirmBackToMain(item);
    else if (item.dataset.kind === "restore-data") confirmRestore(item);
    else showLicence(data.credits.find((credit) => credit.id === item.dataset.id));
  }

  // The room above the hint bar.
  function roomBottom() {
    return window.innerHeight - (parseFloat(getComputedStyle(document.documentElement).scrollPaddingBottom) || 0);
  }

  // On the first row the title above it comes into view, on About's first
  // row the About heading and its notes, and on the last the closing note under
  // it, as far as the focused row stays wholly in view. After the keyboard
  // has placed the row.
  function showAround(item) {
    const box = item.getBoundingClientRect();
    const index = rows.indexOf(item);
    const firstAbout = rows.find((r) => r.dataset.kind !== "settings-folder");
    const above = index === 0 ? el : item === firstAbout ? aboutHeading : null;
    if (above) {
      const up = Math.min(-above.getBoundingClientRect().top, roomBottom() - box.bottom);
      if (up > 0) window.scrollBy(0, -up);
    }
    if (index === rows.length - 1) {
      const down = Math.min(endEl.getBoundingClientRect().bottom - roomBottom(), box.top);
      if (down > 0) window.scrollBy(0, down);
    }
  }

  // Enamel lifts a row on data-focused (the app moves the real focus itself).
  el.addEventListener("focusin", (event) => {
    const item = event.target.closest(ROWS);
    if (!item) return;
    item.dataset.focused = "true";
    requestAnimationFrame(() => {
      if (document.activeElement === item) showAround(item);
    });
  });
  el.addEventListener("focusout", (event) => {
    const item = event.target.closest(ROWS);
    if (item) delete item.dataset.focused;
  });
  // A tap chooses the row, as A does.
  el.addEventListener("click", (event) => {
    const item = event.target.closest(ROWS);
    if (!item || !open || keyboard.isBusy()) return;
    if (document.activeElement !== item) item.focus({ preventScroll: true });
    select(item);
  });

  function close() {
    open = false;
    el.hidden = true;
    licenceEl.hidden = true;
    rows = [];
    keyboard.setRows([]);
  }

  return {
    async open() {
      open = true;
      view = "list";
      keyboard.setBusy(true);
      await load();
      keyboard.setBusy(false);
      if (!open) return;
      showList(null);
    },
    isOpen: () => open,
    select,
    // B: from a licence back to its row; from the list back to Home. The
    // folder screen answers B itself (onboarding.back()).
    back() {
      // While an update runs, B is Cancel, until installing starts.
      if (updating) {
        if (updating.cancelable) api.cancelUpdate().catch(() => {});
        return;
      }
      if (!open || keyboard.isBusy()) return;
      if (view === "licence") {
        showList(licenceFrom);
        return;
      }
      if (view !== "list") return;
      close();
      onClose();
    },
    // The hint bar's words while it shows, else null.
    hints() {
      if (updating) return { select: null, back: updating.cancelable ? "Cancel" : null, lookAgain: false };
      if (!open || view === "folder") return null;
      return { select: view === "licence" || !data ? null : "Select", back: "Back", lookAgain: false };
    },
  };
}
