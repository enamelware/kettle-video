// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Mario Carabotta

import * as api from "./api.js";
import { actionButton, addSpan } from "./dom.js";
import { createKeyboardController, pickerOpen, showPresses } from "./keyboard.js";
import { menuRows, plural, scanProgressText, scanResultText, SCAN_FAILED } from "./home_menu.js";
import { createOnboarding } from "./onboarding.js";
import { createSettings } from "./settings.js";
import { keepScreenOn } from "./screen_awake.js";
import { STILL_WORKING_MS } from "./still_working.js";
import { measureSizes } from "./size_readout.js";

const loadingEl = document.getElementById("loading");
const libraryEl = document.getElementById("library");
const episodesEl = document.getElementById("episodes");
const mpvMissingEl = document.getElementById("mpv-missing");
const errorBannerEl = document.getElementById("error-banner");
const playingStatusEl = document.getElementById("playing-status");
const confirmEl = document.getElementById("confirm-remove");
// Update and restart's question (issue 112), asked from Settings.
const confirmUpdateEl = document.getElementById("confirm-update");
const sections = {
  movies: document.querySelector('.source[data-source="movies"]'),
  tv: document.querySelector('.source[data-source="tv"]'),
};
const tabStripEl = document.getElementById("tab-strip");
const tabs = {
  movies: tabStripEl.querySelector('[data-tab="movies"]'),
  tv: tabStripEl.querySelector('[data-tab="tv"]'),
};
const TAB_ORDER = ["movies", "tv"];
const letterStripEl = sections.movies.querySelector('[data-role="letters"]');
const actionBarEl = document.getElementById("action-bar");
const menuButtonEl = actionBarEl.querySelector('[data-kind="menu"]');
const menuEl = document.getElementById("home-menu");
const menuRowsEl = menuEl.querySelector('[data-role="rows"]');
const scanToastEl = document.getElementById("scan-toast");
const backHintEl = document.querySelector('#hint-bar [data-role="back"]');
const selectHintEl = document.querySelector('#hint-bar [data-role="select"]');
const removeHintEl = document.querySelector('#hint-bar [data-role="remove"]');
const lookAgainHintEl = document.querySelector('#hint-bar [data-role="look-again"]');
const continueEl = document.getElementById("continue-watching");
const tilesEl = continueEl.querySelector('[data-role="tiles"]');

// "parsed": the saved library view (the parsed library view, the saved library work).
// "plain": the plain file list, used when the parsed view can't load.
let mode = "parsed";
let parsed = null; // the last parsed library answer
let tabRows = { movies: [], tv: [] }; // each tab's list, in key order
let activeTab = "movies"; // remembered for the session (the Home shell work)
let openShow = null; // the show whose episodes are on screen, or null
let rescanning = false;
let movieLetters = []; // the Movies list's letter groups: { letter, index }
let continueItems = []; // the Continue watching carousel, newest first (the Continue watching work)
let continueTiles = []; // its tiles, in the same order
let onboarding = null; // the first-launch folder choice (the folder choice screens)
let settingsScreen = null; // Settings, from Home's menu (issue 100)
let homeStale = false; // a folder changed in Settings: Home is read again on the way back
let ignoringBack = false; // just after Open my library, see openHomeAfterOnboarding
let mpvLookAgain = null; // the "mpv not found" screen's button, while it shows (the mpv missing screen)
// Developer only (the Movies list work): ?fixture=2000 in the page address shows 2,000
// invented films instead of the saved ones.
const fixtureCount = new URLSearchParams(window.location.search).get("fixture");

// A message appearing above the lists pushes them down; in a short window
// that can move the focused tab, tile or row under the hint bar, so it is
// brought back into view (the responsive layout work).
function keepFocusInView() {
  const focused = document.activeElement;
  if (focused && focused !== document.body) focused.scrollIntoView({ block: "nearest", inline: "nearest" });
}

function showError(message) {
  errorBannerEl.textContent = message;
  errorBannerEl.hidden = false;
  keepFocusInView();
}

function clearError() {
  errorBannerEl.hidden = true;
  errorBannerEl.textContent = "";
}

function setStatus(statusEl, text, isError) {
  statusEl.textContent = text;
  statusEl.hidden = !text;
  if (isError) statusEl.dataset.state = "error";
  else delete statusEl.dataset.state;
}

function renderSection(source, data) {
  const section = sections[source];
  const statusEl = section.querySelector('[data-role="status"]');
  const groupsEl = section.querySelector('[data-role="groups"]');
  groupsEl.innerHTML = "";

  if (source === "movies") showLetterStrip([]);
  if (data.status === "not_found") {
    const reason = data.reason || "folder not found";
    // No path means no folder was chosen (the folder choice screens): a choice, not a fault.
    if (data.path) setStatus(statusEl, `${reason}: ${data.path}`, true);
    else setStatus(statusEl, reason, false);
    return [];
  }
  setStatus(statusEl, "", false);

  if (data.groups.length === 0) {
    setStatus(statusEl, "no video files found", false);
    return [];
  }

  const rows = [];
  for (const group of data.groups) {
    const heading = document.createElement("h3");
    heading.className = "group-heading";
    heading.textContent = group.name;
    groupsEl.appendChild(heading);

    const list = document.createElement("ul");
    list.className = "file-list en-rows";
    for (const file of group.files) {
      const item = document.createElement("li");
      item.className = "file-row en-row";
      item.tabIndex = -1;
      item.textContent = file.name;
      item.dataset.source = source;
      item.dataset.path = file.path;
      item.dataset.key = file.path;
      list.appendChild(item);
      rows.push(item);
    }
    groupsEl.appendChild(list);
  }
  return rows;
}

function showLibrary(keyboard, library, focusKey) {
  movieLetters = [];
  tabRows = { movies: renderSection("movies", library.movies), tv: renderSection("tv", library.tv) };
  showLibraryView(keyboard, focusKey);
}

async function loadLibrary(keyboard, focusKey) {
  showLibrary(keyboard, await api.getLibrary(), focusKey);
}

// --- Home shell (the Home shell work): tabs and hint bar ---

// B goes back one level from a show's episodes, and quits elsewhere. On a
// Continue watching tile, A resumes and X removes (the Continue watching work).
function updateHints() {
  // Onboarding (the folder choice screens): its own words for A and B, and Y Look again.
  // Settings (issue 100) too, and onboarding's folder screen opened from it.
  const choosing = (onboarding && onboarding.hints()) || (settingsScreen && settingsScreen.hints());
  lookAgainHintEl.hidden = !(choosing && choosing.lookAgain);
  // No words for a key that does nothing, as during onboarding's scan (the first scan screen).
  selectHintEl.parentElement.hidden = Boolean(choosing) && !choosing.select;
  backHintEl.parentElement.hidden = Boolean(choosing) && !choosing.back;
  if (choosing) {
    selectHintEl.textContent = choosing.select || "";
    backHintEl.textContent = choosing.back || "";
    removeHintEl.hidden = true;
    return;
  }
  // The "mpv not found" screen's button (the mpv missing screen).
  if (mpvLookAgain) {
    selectHintEl.textContent = "Look again";
    backHintEl.textContent = "Quit";
    removeHintEl.hidden = true;
    return;
  }
  backHintEl.textContent = openShow || pickerOpen() ? "Back" : "Quit";
  const onTile = continueTiles.includes(document.activeElement);
  selectHintEl.textContent = onTile ? "Resume" : "Select";
  removeHintEl.hidden = !onTile;
}

// The tab strip is one line of tabs tall, and taller when its tabs wrap
// onto another line in a narrow window (the responsive layout work). --tab-strip-height
// follows its real height, so the page's scroll room and the letter strip,
// which sit under it, never run under a second line of tabs.
// (Until the Home polish the docked action bar above it was measured too; the Menu
// button now scrolls with the page, so nothing above the tabs is pinned.)
function watchHeight(el, property) {
  const root = document.documentElement;
  new ResizeObserver(() => {
    const height = el.getBoundingClientRect().height;
    if (height > 0) root.style.setProperty(property, `${height}px`);
    else root.style.removeProperty(property);
  }).observe(el);
}

// Since the folder choice screens the hint bar's real height reaches the page's root too: Enamel's
// script keeps --en-c-hintbar-height on the bar's parent (body), but the
// page's scroll room is set at the root, where it was the one-line height,
// so a row moved to could stop under a hint bar whose hints wrap (onboarding's
// longer hints wrap sooner).
function watchTabStripHeight(keyboard) {
  watchHeight(tabStripEl, "--tab-strip-height");
  const hintBar = document.getElementById("hint-bar");
  watchHeight(hintBar, "--en-c-hintbar-height");
  // Onboarding's A hint changes with the focused row (the Browse somewhere else work), so the bar
  // can grow after the row moved to was placed: it stays clear of the bar.
  new ResizeObserver(() => {
    if (onboarding && onboarding.isOpen()) onboarding.keepFocusInView();
    if (mpvLookAgain) keyboard.refocus();
  }).observe(hintBar);
}

// --- Home actions (the Home actions work): the action bar, its menu, the scan toast ---

// The bar shows on Home: the library lists and a show's episodes. Not on
// the first-launch screen, the mpv messages or the plain-list fallback.
function showActionBar(visible) {
  actionBarEl.hidden = !visible;
}

function homeShown() {
  return !actionBarEl.hidden;
}

// Enamel's button shows focus on keyboard focus or data-focused; the app
// moves the focus itself, so it marks the focused bar button.
function markBarFocus(event) {
  for (const button of actionBarEl.querySelectorAll(".en-button")) {
    if (button === event.target && event.type === "focusin") button.dataset.focused = "true";
    else if (button === event.target) delete button.dataset.focused;
  }
}

// Opens the menu over Home. focusQuit (B) starts on Quit; otherwise (the
// Menu button, Start) on the first row. Enamel moves the focus, closes
// it and puts the focus back on opener; its events (set up in main) act.
function openMenu(focusQuit, opener) {
  const rows = menuRows({ missing: parsed ? parsed.missing_count : 0, scanning: rescanning });
  menuRowsEl.replaceChildren(
    ...rows.map(({ value, title, destructive }) => {
      const row = document.createElement("button");
      row.type = "button";
      row.className = value === "cancel" ? "en-picker__row en-picker__cancel" : "en-picker__row";
      if (destructive) row.classList.add("en-picker__row--destructive");
      row.tabIndex = -1;
      row.value = value;
      row.dataset.kind = `menu-${value}`;
      if (focusQuit && value === "quit") row.autofocus = true;
      addSpan(row, "", title);
      return row;
    }),
  );
  window.EnamelUI.picker.open(menuEl, opener || document.activeElement);
}

// Enamel puts the focus back on the picker's opener when it closes. A
// scan that ended while it was open redraws the lists, so that row or tile
// may be gone, and the focus is left on the closing dialog or nowhere: it
// then goes where the keyboard says it is.
function keepFocusAfterPicker(keyboard) {
  const focused = document.activeElement;
  if (!focused || focused === document.body || focused.closest(".en-dialog")) keyboard.refocus();
}

// A row chosen in the menu. Cancel and B only close it (Enamel).
function handleMenuChoice(keyboard, value) {
  if (value === "rescan") handleRescan(keyboard);
  else if (value === "remove-missing") {
    if (!rescanning && parsed && parsed.missing_count > 0) showRemoveConfirm(document.activeElement);
  } else if (value === "settings") openSettings(keyboard);
  else if (value === "quit") handleQuit();
  // "scanning": a scan is already running; nothing starts.
}

// Enamel's toast, one at a time: a new text replaces the old one, and it
// leaves three seconds after its last change. It never takes the focus.
function showToast(text) {
  window.EnamelUI.toast.show(text, { element: scanToastEl });
}

// A new text for the toast showing (its timer starts again), else a new one.
function updateToast(text) {
  if (scanToastEl.hidden || scanToastEl.dataset.closing === "true") showToast(text);
  else window.EnamelUI.toast.update(text);
}

// After Update and restart (issue 112) this page loaded again from the new
// version: the toast says what happened ("Updated to 1.1.0"), once.
async function showUpdateNote() {
  try {
    const { note } = await api.takeUpdateNote();
    if (note) showToast(note);
  } catch (err) {
    // Nothing to say.
  }
}

function showTabStrip(visible) {
  tabStripEl.hidden = !visible;
  updateContinueVisibility();
}

function selectedTab() {
  return tabStripEl.hidden ? null : tabs[activeTab];
}

// Marks a tab selected and shows its list, with each tab's count.
function markTab(tab) {
  activeTab = tab;
  for (const name of TAB_ORDER) {
    tabs[name].setAttribute("aria-selected", String(name === tab));
    sections[name].hidden = name !== tab;
    tabs[name].querySelector('[data-role="count"]').textContent = String(tabRows[name].length);
  }
}

// Left or Right on the tabs, or a tap on one: shows that tab's list (leaving
// a show's episodes) and keeps the focus on the tabs.
function switchTab(keyboard, tab) {
  if (tab === activeTab && !openShow) return;
  showLibraryView(keyboard, null, tab);
}

function stepTab(keyboard, step) {
  const next = TAB_ORDER[TAB_ORDER.indexOf(activeTab) + step];
  if (next) switchTab(keyboard, next);
}

// --- Parsed library view (the parsed library view, interim) ---

// One focusable row: title, muted subtitle, and the original paths, which
// only show while d is on. A missing film, show or episode (the quick rescan and Remove work) is
// dimmed and always says so in words: "Missing", "1 of 2 parts missing".
// Notes and subtitles take Enamel's row meta style.
function parsedRow({ kind, source, playPath, key, label, title, subtitle, notes, paths, missing, missingNote }) {
  const item = document.createElement("li");
  item.className = "file-row parsed-row en-row";
  item.tabIndex = -1;
  item.dataset.kind = kind;
  item.dataset.key = key;
  if (missing) item.dataset.status = "missing";
  if (playPath) {
    item.dataset.source = source;
    item.dataset.path = playPath;
  }
  const line = document.createElement("span");
  line.className = "row-line";
  if (label) addSpan(line, "row-label", label);
  addSpan(line, "row-title", title);
  if (missingNote) addSpan(line, "row-note en-row__meta", missingNote).dataset.role = "missing";
  for (const note of notes || []) addSpan(line, "row-note en-row__meta", note);
  item.appendChild(line);
  if (subtitle) addSpan(item, "row-subtitle en-row__meta", subtitle);
  for (const path of paths) addSpan(item, "row-path", path);
  return item;
}

// --- Movies list (the Movies list work): rows, letter groups, letter strip ---

// "Title (2001)" -> ["Title", "2001"]; the back end writes the year last.
function splitYear(displayTitle) {
  const match = /^(.*) \((\d{4})\)$/s.exec(displayTitle);
  return match ? [match[1], match[2]] : [displayTitle, ""];
}

// The title (two lines at most until focused), the year in fog, then the
// labels in words: "2 parts", "Missing" or "1 of 2 parts missing".
function movieRow(item) {
  const [title, year] = splitYear(item.display_title);
  const row = parsedRow({
    kind: "movie",
    source: "movies",
    // Several parts: the first one that is there, for now.
    playPath: (item.parts.find((p) => !p.missing) || item.parts[0]).path,
    key: item.parts[0].path,
    title,
    paths: item.parts.map((p) => p.path),
    missing: item.missing,
    missingNote: item.missing_note,
  });
  row.dataset.id = item.id;
  row.dataset.letter = item.letter;
  const titleEl = row.querySelector(".row-title");
  let after = titleEl;
  if (year) {
    const yearEl = document.createElement("span");
    yearEl.className = "row-year";
    yearEl.textContent = year;
    after.after(yearEl);
    after = yearEl;
  }
  if (item.subtitle) {
    const partsEl = document.createElement("span");
    partsEl.className = "row-note en-row__meta";
    partsEl.dataset.role = "parts";
    partsEl.textContent = item.subtitle;
    after.after(partsEl);
  }
  return row;
}

const LETTER_SHOWN = { other: "…" };

// Where each letter group starts in the Movies tab's rows.
function letterStarts(rows) {
  const starts = [];
  rows.forEach((row, index) => {
    const letter = row.dataset.letter;
    if (letter && (starts.length === 0 || starts[starts.length - 1].letter !== letter)) {
      starts.push({ letter, index });
    }
  });
  return starts;
}

// The touch-only strip down the right edge: only letters that have films.
// It is never focusable, so the controller never lands on it.
function showLetterStrip(starts) {
  letterStripEl.innerHTML = "";
  for (const { letter } of starts) {
    const item = document.createElement("span");
    item.className = "letter-strip-letter";
    item.dataset.letter = letter;
    item.textContent = LETTER_SHOWN[letter] || letter;
    letterStripEl.appendChild(item);
  }
  letterStripEl.hidden = starts.length === 0;
  markLetter(starts.length ? starts[0].letter : null);
}

// The current letter is bold with a marker, never colour alone.
function markLetter(letter) {
  let changed = false;
  for (const item of letterStripEl.children) {
    if (item.dataset.letter === letter) {
      changed = !item.hasAttribute("aria-current");
      item.setAttribute("aria-current", "true");
    } else {
      item.removeAttribute("aria-current");
    }
  }
  if (changed) keepCurrentLetterInView();
}

// Where every letter can't fit at a readable size the strip scrolls (the letter strip fix), so
// the marked letter is kept in view. Only the strip moves, never the page.
function keepCurrentLetterInView() {
  const item = letterStripEl.querySelector('[aria-current="true"]');
  if (!item || letterStripEl.scrollHeight <= letterStripEl.clientHeight) return;
  const top = item.offsetTop;
  const bottom = top + item.offsetHeight;
  if (top < letterStripEl.scrollTop) letterStripEl.scrollTop = top;
  else if (bottom > letterStripEl.scrollTop + letterStripEl.clientHeight) letterStripEl.scrollTop = bottom - letterStripEl.clientHeight;
}

// Writes a timing to the developer console, and keeps it as a standard
// performance measure ("Movies list: draw", "Movies list: jump") so checks
// can read it.
function logTiming(name, began, done, detail) {
  requestAnimationFrame(() => {
    const frame = performance.now();
    performance.measure(name, { start: began, end: done });
    performance.measure(`${name} to next frame`, { start: began, end: frame });
    console.info(
      `${name}: ${detail} in ${(done - began).toFixed(1)} ms (${(frame - began).toFixed(1)} ms to the next frame)`,
    );
  });
}

function focusLetter(keyboard, start) {
  const began = performance.now();
  keyboard.focusAt(start.index);
  logTiming("Movies list: jump", began, performance.now(), `to ${start.letter}`);
}

// Left or Right inside the Movies list: the first film of the previous or
// next letter that has films. No wrapping round. Anywhere else (a picker,
// the first-launch screen) they do nothing.
function jumpLetter(keyboard, step) {
  if (mode !== "parsed" || openShow || pickerOpen() || activeTab !== "movies" || movieLetters.length === 0) return;
  const row = keyboard.currentRow();
  if (!row || !tabRows.movies.includes(row)) return;
  const at = movieLetters.findIndex((start) => start.letter === row.dataset.letter);
  const target = at < 0 ? (step > 0 ? movieLetters[0] : null) : movieLetters[at + step];
  if (target) focusLetter(keyboard, target);
}

// --- Continue watching (the Continue watching work): the carousel above the tabs ---

const REMOVE_TILE_FAILED = "Couldn't remove it from Continue watching.";

// The carousel shows above the tabs of the library lists, never in a show's
// episodes, on the question, the first-launch screen or the plain list. With
// nothing to show it is hidden completely: no heading, no gap.
function updateContinueVisibility() {
  continueEl.hidden = tabStripEl.hidden || !episodesEl.hidden || mode !== "parsed" || continueTiles.length === 0;
}

function progressShare(item) {
  return item.duration ? Math.min(Math.max(item.position / item.duration, 0), 1) : 0;
}

// One tile: the frame where you stopped (or a plain surface with the name),
// a thin progress bar along its bottom edge, and "Missing" in its top-left
// corner when the file isn't there. The first tile is large, with the whole
// caption underneath; the others show only the name. Enamel's tile and
// thin progress classes sit next to the app's (the third design system step).
function continueTile(item, large) {
  const tile = document.createElement("div");
  tile.className = large ? "continue-tile en-tile en-tile--large" : "continue-tile en-tile";
  tile.tabIndex = -1;
  tile.dataset.id = item.id;
  tile.dataset.kind = item.kind;
  tile.dataset.size = large ? "large" : "small";
  if (item.missing) tile.dataset.status = "missing";
  const frame = document.createElement("div");
  frame.className = "continue-frame en-tile__frame";
  if (item.picture) {
    tile.dataset.picture = "";
    const picture = document.createElement("img");
    picture.className = "continue-picture";
    picture.alt = "";
    picture.decoding = "async";
    // A picture that can't load leaves the plain surface with the name.
    picture.addEventListener("error", () => {
      picture.remove();
      delete tile.dataset.picture;
    });
    picture.src = item.picture;
    frame.appendChild(picture);
  }
  addSpan(frame, "continue-surface-name", item.name);
  if (item.missing) addSpan(frame, "continue-missing", "Missing").dataset.role = "missing";
  const share = progressShare(item);
  const bar = addSpan(frame, "continue-progress en-progress en-progress--thin", "");
  bar.style.setProperty("--value", `${share * 100}%`);
  addSpan(bar, "continue-progress-fill en-progress__fill", "").style.setProperty("--progress", String(share));
  tile.appendChild(frame);
  addSpan(tile, "continue-caption en-tile__title", large ? item.caption : item.name);
  return tile;
}

// Pictures load on their own once the tiles are on the page, so they never
// hold up Home.
function renderContinue(items) {
  const began = performance.now();
  continueItems = items;
  continueTiles = items.map((item, index) => continueTile(item, index === 0));
  tilesEl.replaceChildren(...continueTiles);
  updateContinueVisibility();
  logTiming("Continue watching: draw", began, performance.now(), `${items.length} tiles`);
}

// Any problem just leaves the carousel out.
async function fetchContinue() {
  try {
    const answer = await api.getContinue();
    return Array.isArray(answer.items) ? answer.items : [];
  } catch (err) {
    return [];
  }
}

// After a film started from a tile: the tile just watched (it comes first),
// else the first tile, else the tabs.
function focusAfterResume(keyboard, id) {
  const index = continueTiles.findIndex((tile) => tile.dataset.id === id);
  if (!keyboard.focusTile(Math.max(index, 0))) keyboard.focusTabs();
}

// X on a tile: removed at once, no question. The focus moves to the next
// tile, or the previous one if it was the last, or the tabs.
async function removeTile(keyboard, tile) {
  const index = continueTiles.indexOf(tile);
  if (index < 0) return;
  clearError();
  keyboard.setBusy(true);
  let result;
  try {
    result = await api.removeContinue(tile.dataset.id);
  } catch (err) {
    result = { ok: false };
  }
  keyboard.setBusy(false);
  if (!result.ok) {
    showError(REMOVE_TILE_FAILED);
    keyboard.refocus();
    return;
  }
  renderContinue(continueItems.filter((item) => item.id !== tile.dataset.id));
  if (!keyboard.focusTile(Math.min(index, continueTiles.length - 1))) keyboard.focusTabs();
}

function sectionStatus(data) {
  // Skipped in onboarding (the folder choice screens): a choice, not a fault.
  if (data.folder_set === false) return "No folder chosen";
  if (!data.available) return "Folder not available";
  if (!data.has_library) return "Not scanned yet";
  return data.items.length === 0 ? "no video files found" : "";
}

// A section keeps its saved items even when its folder isn't there now
// (card out): they stay listed under a muted "Folder not available".
function renderParsedSection(source, data) {
  const section = sections[source];
  const statusEl = section.querySelector('[data-role="status"]');
  const groupsEl = section.querySelector('[data-role="groups"]');
  groupsEl.innerHTML = "";
  setStatus(statusEl, sectionStatus(data), false);

  const list = document.createElement("ul");
  list.className = "file-list en-rows";
  const rows = [];
  for (const item of data.items) {
    const row =
      source === "movies"
        ? movieRow(item)
        : parsedRow({
            kind: "show",
            key: item.path,
            title: item.display_title,
            subtitle: item.subtitle,
            paths: [item.path === "." ? "(loose files in the TV Shows folder)" : item.path],
            missing: item.missing,
            missingNote: item.missing_note,
          });
    list.appendChild(row);
    rows.push(row);
  }
  groupsEl.appendChild(list);
  if (source === "movies") {
    movieLetters = letterStarts(rows);
    showLetterStrip(movieLetters);
  }
  return rows;
}

// --- Saved library: scanning (the saved library work; from the menu since the Home actions work) ---

const SCAN_POLL_MS = 1000;
const FILE_NOT_FOUND = "File not found. Rescan or remove it.";
const REMOVE_FAILED = "Couldn't remove the missing items. The saved library is unchanged.";

// Something to show on Home. A scan that finds nothing still saves a library,
// an empty one, and Remove can empty one: Home has no way out of those, so they
// go to the result screen's scan too, with its Change folders (the first scan screen).
// Missing items are still items: Home is where they can be removed.
function hasLibrary(answer) {
  return answer.movies.items.length > 0 || answer.tv.items.length > 0;
}

function progressText(status) {
  return status && status.files_total > 0
    ? `Scanning… ${status.files_done} of ${status.files_total}`
    : "Scanning…";
}

// Runs a scan, or joins the one already running, and reports progress once
// a second. Resolves to the scan's result: { ok } or { ok: false, error },
// or { ok: false, busy: true } while a film plays.
async function runScan(onProgress) {
  try {
    const status = await api.startScan();
    if (status.busy) return { ok: false, busy: true };
    return await followScan(onProgress, status);
  } catch (err) {
    return { ok: false, error: SCAN_FAILED };
  }
}

// Follows a scan already started (status: its answer), never starting one,
// so a scan that ends at once is never followed by a second (issue 100).
async function followScan(onProgress, status) {
  try {
    while (status.state === "scanning") {
      onProgress(status);
      await sleep(SCAN_POLL_MS);
      status = await api.getScanStatus();
    }
    return status.last_result || { ok: false, error: SCAN_FAILED };
  } catch (err) {
    return { ok: false, error: SCAN_FAILED };
  }
}

// Without a focusKey (at launch) the focus is on the selected tab. Since
// the Home actions work, Rescan and Remove are in the menu, not at the top of the lists.
async function showParsedLibrary(keyboard, answer, focusKey) {
  parsed = answer;
  const began = performance.now();
  const movieRows = renderParsedSection("movies", answer.movies);
  tabRows = { movies: movieRows, tv: renderParsedSection("tv", answer.tv) };
  showLibraryView(keyboard, focusKey);
  logDrawTime(movieRows.length, began);
}

// How long the Movies list takes to draw, in the developer console (the Movies list work).
function logDrawTime(count, began) {
  if (activeTab === "movies") void sections.movies.offsetHeight; // lay it out now
  logTiming("Movies list: draw", began, performance.now(), `${count} rows`);
}

// --- Removing missing items (the quick rescan and Remove work): only ever after a Yes ---

// The question is an Enamel picker confirm (the picker confirm work), over the list:
// Cancel is focused first, and Enamel moves the focus, closes the picker
// and puts the focus back where the menu was opened from (the Home actions work). Its events
// (set up in main) do the rest: en-select with "remove" removes, en-cancel
// needs nothing.
function showRemoveConfirm(row) {
  clearError();
  confirmEl.querySelector('[data-role="question"]').textContent = `Remove ${plural(parsed.missing_count, "missing item")}?`;
  window.EnamelUI.picker.open(confirmEl, row);
}

async function confirmRemove(keyboard) {
  keyboard.setBusy(true);
  let result;
  try {
    result = await api.removeMissing();
  } catch (err) {
    result = { ok: false };
  }
  keyboard.setBusy(false);
  if (!result.ok) {
    showError(REMOVE_FAILED);
    keyboard.refocus();
    return;
  }
  await reloadLibrary(keyboard, focusedKey(keyboard));
}

// The key of the row with the focus, to keep the place after a reload.
function focusedKey(keyboard) {
  const row = keyboard.currentRow();
  return row ? row.dataset.key : null;
}

// Folders are set and there is no saved library: straight to the result
// screen, which scans them and shows what it found (the designer's answer on the first scan screen).
function showFirstScan() {
  showOnboardingShell();
  onboarding.openScan();
}

// Loads the saved library again and shows it, keeping the place if possible.
// The carousel is read again too: a rescan can find a missing file (the Continue watching work).
// The focus stays on the action bar if it was there (the Home actions work).
async function reloadLibrary(keyboard, focusKey) {
  const tileIndex = keyboard.currentTileIndex();
  const onBar = keyboard.isOnBar();
  const continuing = fetchContinue();
  let answer;
  try {
    answer = await api.getParsedLibrary(fixtureCount);
  } catch (err) {
    answer = { ok: false, error: "Couldn't read the library." };
  }
  const items = await continuing;
  if (!answer.ok) {
    await fallBackToPlain(keyboard, answer.error);
    return;
  }
  if (!hasLibrary(answer)) {
    showFirstScan();
    return;
  }
  renderContinue(items);
  const show = openShow ? findShow(answer, openShow.path) : null;
  const shownBefore = openShow;
  await showParsedLibrary(keyboard, answer, shownBefore ? shownBefore.path : focusKey);
  if (show) {
    showEpisodes(keyboard, show, focusKey);
    // No row to go back to: the focus was on the tabs, so it stays there.
    if (!focusKey) keyboard.focusTabs();
  } else if (tileIndex >= 0) {
    // It was on a tile: back to the carousel (the tabs stay if it's empty).
    keyboard.focusTile(tileIndex);
  }
  // While a picker is open the focus is Enamel's; it goes back where the
  // picker was opened from when it closes.
  if (onBar && !pickerOpen()) keyboard.focusBar();
}

function focusByKey(keyboard, rows, key) {
  const index = key ? rows.findIndex((row) => row.dataset.key === key) : -1;
  keyboard.focusAt(Math.max(index, 0));
}

// A key is looked for in the selected tab first.
function tabHolding(key) {
  const holds = (tab) => tabRows[tab].some((row) => row.dataset.key === key);
  if (!key || holds(activeTab)) return activeTab;
  return TAB_ORDER.find(holds) || activeTab;
}

// Shows a tab's list (by default the one holding focusKey, else the selected
// one) and focuses the row with focusKey, or else the tab itself.
function showLibraryView(keyboard, focusKey, tab = tabHolding(focusKey)) {
  openShow = null;
  episodesEl.hidden = true;
  libraryEl.hidden = false;
  showActionBar(mode === "parsed");
  showTabStrip(true);
  markTab(tab);
  updateHints();
  const rows = tabRows[tab];
  keyboard.setRows(rows);
  if (focusKey && rows.some((row) => row.dataset.key === focusKey)) focusByKey(keyboard, rows, focusKey);
  else keyboard.focusTabs();
}

function showEpisodes(keyboard, show, focusKey) {
  openShow = show;
  episodesEl.querySelector('[data-role="show-title"]').textContent = show.display_title;
  episodesEl.querySelector('[data-role="show-subtitle"]').textContent = show.subtitle;
  const seasonsEl = episodesEl.querySelector('[data-role="seasons"]');
  seasonsEl.innerHTML = "";

  const rows = [];
  for (const season of show.seasons) {
    if (show.seasons.length > 1) {
      const heading = document.createElement("h3");
      heading.className = "group-heading";
      heading.textContent = season.label;
      seasonsEl.appendChild(heading);
    }
    const list = document.createElement("ul");
    list.className = "file-list en-rows";
    for (const episode of season.episodes) {
      const row = parsedRow({
        kind: "episode",
        source: "tv",
        playPath: episode.path,
        key: episode.path,
        label: episode.label,
        title: episode.title,
        notes: episode.notes,
        paths: [episode.path],
        missing: episode.missing,
        missingNote: episode.missing_note,
      });
      list.appendChild(row);
      rows.push(row);
    }
    seasonsEl.appendChild(list);
  }

  libraryEl.hidden = true;
  episodesEl.hidden = false;
  updateContinueVisibility();
  markTab("tv");
  updateHints();
  window.scrollTo(0, 0);
  keyboard.setRows(rows);
  focusByKey(keyboard, rows, focusKey);
}

function findShow(answer, path) {
  return answer.tv.items.find((show) => show.path === path) || null;
}

function handleSelect(keyboard, row) {
  if (row.dataset.status === "missing") {
    showError(FILE_NOT_FOUND);
    return;
  }
  if (row.dataset.kind === "show") {
    const show = findShow(parsed, row.dataset.key);
    if (show) showEpisodes(keyboard, show);
    return;
  }
  if (rescanning) return; // the list is about to be replaced
  handlePlay(keyboard, row);
}

// B goes back one level from a show's episodes. Elsewhere on Home it opens
// the menu on Quit (the Home actions work): B then A quits, B then B backs out. Where there is
// no menu (first launch, mpv messages, loading, playing) it quits.
function handleBack(keyboard) {
  if (mode === "parsed" && openShow) {
    if (!keyboard.isBusy()) showLibraryView(keyboard, openShow.path);
    return;
  }
  if (homeShown() && !keyboard.isBusy()) {
    openMenu(true);
    return;
  }
  handleQuit();
}

function toggleDetails() {
  document.body.toggleAttribute("data-show-paths");
}

// Shows the error sentence and switches to today's plain file list.
async function fallBackToPlain(keyboard, message) {
  mode = "plain";
  openShow = null;
  episodesEl.hidden = true;
  showActionBar(false);
  showError(message);
  try {
    await loadLibrary(keyboard);
  } catch (err) {
    showError("Couldn't read the library.");
  }
}

// Rescan (the menu's row, or r): the saved library stays on screen and in
// use while Enamel's toast counts the files (the Home actions work), then the lists update,
// the focus keeps its place, and the toast says what changed.
async function handleRescan(keyboard) {
  if (mode !== "parsed" || rescanning || pickerOpen() || onboarding.isOpen() || settingsScreen.isOpen() || mpvLookAgain) return;
  rescanning = true;
  clearError();
  showToast(scanProgressText(null));
  const result = await runScan((status) => window.EnamelUI.toast.update(scanProgressText(status)));
  if (result.ok) await reloadLibrary(keyboard, focusedKey(keyboard));
  rescanning = false;
  // A film playing that this page didn't start (it was reloaded) answers
  // busy: the toast says so.
  showToast(scanResultText(result));
}

// --- Loading screen ---

// After STILL_WORKING_MS (still_working.js), the loading screen says it is
// still working (the loading screen work).
// The loading screen stays at least this long, even when the library is
// ready sooner, so it never just flashes (the loading screen work, designer feedback).
const LOADING_MIN_MS = 2000;
let stillWorkingTimer = null;
let loadingShownAt = 0;

// While the screen shows, the list underneath ignores keys; q still quits.
function showLoading(keyboard) {
  const slowEl = loadingEl.querySelector('[data-role="slow"]');
  loadingShownAt = performance.now();
  keyboard.setBusy(true);
  stillWorkingTimer = setTimeout(() => {
    slowEl.hidden = false;
  }, STILL_WORKING_MS);
}

async function hideLoading(keyboard) {
  const remaining = LOADING_MIN_MS - (performance.now() - loadingShownAt);
  if (remaining > 0) await sleep(remaining);
  clearTimeout(stillWorkingTimer);
  loadingEl.hidden = true;
  keyboard.setBusy(false);
}

// --- Developer options ---

// Fresh start (the fresh start mode): the "FRESH START" marker on every screen, so a
// session with a new, empty data folder is never mistaken for the real one.
function showFreshStart() {
  document.documentElement.dataset.freshStart = "";
  for (const marker of document.querySelectorAll(".fresh-start")) marker.hidden = false;
}

async function showDevInfo() {
  let info;
  try {
    info = await api.getDevInfo();
  } catch (err) {
    return;
  }
  if (info.fresh_start) showFreshStart();
  // Size readout (the sizing spike): one line in the launch log, nothing on screen.
  if (info.size_readout) api.postSizeReadout(measureSizes()).catch(() => {});
}

// --- Playback ---

const STATUS_POLL_MS = 500;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// Shown when the backend stops answering, or answers with something
// unexpected, around playback (the stuck Playing fix).
const PLAY_START_LOST = "Playback couldn't start: the app lost contact with its backend.";
const PLAY_LOST = "The app lost contact with its backend during playback.";
// A few missed answers in a row before giving up, so one slow answer
// during a long film doesn't end the wait.
const STATUS_MISSES_ALLOWED = 3;

// Resolves with mpv's last result once it has exited; throws if the backend
// stops answering.
async function pollUntilIdle() {
  let misses = 0;
  while (true) {
    let status;
    try {
      status = await api.getStatus();
      misses = 0;
    } catch (err) {
      misses += 1;
      if (misses >= STATUS_MISSES_ALLOWED) throw err;
    }
    if (status && status.state !== "playing") {
      return status.last_result;
    }
    await sleep(STATUS_POLL_MS);
  }
}

function errorText(result, fallback) {
  const parts = [result.error || fallback];
  if (result.hint) parts.push(result.hint);
  return parts.join(" — ");
}

async function handlePlay(keyboard, row) {
  clearError();
  keyboard.setBusy(true);
  const fromTile = continueTiles.includes(row);

  let startResult;
  try {
    startResult = await (fromTile
      ? api.resume(row.dataset.id)
      : api.play(row.dataset.source, row.dataset.path, row.dataset.id));
  } catch (err) {
    startResult = { error: PLAY_START_LOST };
  }
  if (!startResult || !startResult.started) {
    keyboard.setBusy(false);
    showError(errorText(startResult || {}, "could not start playback"));
    return;
  }

  playingStatusEl.hidden = false;
  keepFocusInView();
  // The screen stays on until mpv closes, however it closes (the screen wake lock fix).
  const stopKeepingScreenOn = startResult.keep_awake ? keepScreenOn(api.reportWakeLock) : () => {};
  // No rescans while a film plays (the quick rescan and Remove work): r, Start and B are ignored
  // while busy, so the menu can't open.
  let lastResult;
  let lost = false;
  try {
    lastResult = await pollUntilIdle();
  } catch (err) {
    lost = true;
  }
  stopKeepingScreenOn();
  playingStatusEl.hidden = true;
  keyboard.setBusy(false);
  if (lost) {
    showError(PLAY_LOST);
    keyboard.refocus();
    return;
  }

  if (lastResult && !lastResult.ok) {
    showError(errorText(lastResult, "playback failed"));
  }

  if (mode === "plain") {
    // The plain list is read again; the focus goes back to the same file.
    await loadLibrary(keyboard, row.dataset.key);
    return;
  }
  // The parsed list is remembered; the carousel is read again (the Continue watching work). Started
  // from a tile, the focus goes back to the carousel; from a row, to that
  // row (docs/decisions.md).
  renderContinue(await fetchContinue());
  if (fromTile) focusAfterResume(keyboard, row.dataset.id);
  else keyboard.refocus();
}

// Quit (the Home actions work): no question. The server stops (closing a playing film first,
// the server shutdown check), and the launcher then closes the window.
async function handleQuit() {
  try {
    await api.shutdown();
  } catch (err) {
    // backend is already gone or unreachable; nothing more to do here.
  }
}

// Shown when the mpv check itself fails or doesn't answer (the settings mistakes work).
const MPV_CHECK_FAILED = "The app couldn't check whether mpv is ready to play.";

// What the screen says for an mpv check's answer; null when the check failed.
// A problem with mpv_command comes with its hint; otherwise mpv is missing and
// the install hint shows. Each version ends by saying how to leave.
function mpvLines(status) {
  const exit = "Press q to exit.";
  if (!status) return [MPV_CHECK_FAILED, exit];
  return status.problem ? [status.problem, status.hint, exit] : [status.install_hint, exit];
}

// The sentences, one p each, ahead of Look again's line and button if they
// show. The button stays where it is, so it keeps the focus.
function writeMpvLines(lines) {
  for (const old of mpvMissingEl.querySelectorAll("p:not([data-role])")) old.remove();
  mpvMissingEl.prepend(...lines.map((line) => {
    const p = document.createElement("p");
    p.textContent = line;
    return p;
  }));
}

// Full-screen message when nothing can be played: mpv missing, an
// mpv_command that can't work, or a failed check. Each line is a sentence.
function showMpvMissing(lines) {
  writeMpvLines(lines);
  mpvMissingEl.hidden = false;
  libraryEl.hidden = true;
  showActionBar(false);
  showTabStrip(false);
}

// --- Look again on the "mpv not found" screen (the mpv missing screen) ---

// As onboarding's "Looking for your videos": only for a slow check.
const CHECKING_AFTER_MS = 1000;
const CHECKING_AGAIN = "Checking again…";
// Same words on all three messages, so the press never seems to do nothing.
const SAME_ANSWER = "Tried again. Same answer.";
// Screen 1's keys stay off this long at least, so a second press aimed at
// the button that has just gone never chooses a folder.
const KEYS_SETTLE_MS = 500;
let mpvChecking = false; // a check is running: one at a time

// On first launch only, the screen gets one primary button, focused. Up and
// Down still scroll it (as on "No videos found yet"), so in a short window
// every word can be read.
function offerMpvLookAgain(keyboard) {
  const note = document.createElement("p");
  note.className = "status";
  note.dataset.role = "note";
  note.setAttribute("role", "status");
  note.hidden = true;
  const button = actionButton("mpv-look-again", "mpv-look-again", "Look again", true);
  // Enamel's button shows focus on data-focused; the app moves the focus itself.
  button.addEventListener("focusin", () => { button.dataset.focused = "true"; });
  button.addEventListener("focusout", () => { delete button.dataset.focused; });
  button.addEventListener("click", () => {
    if (document.activeElement !== button) button.focus({ preventScroll: true });
    lookForMpvAgain(keyboard);
  });
  mpvMissingEl.append(note, button);
  mpvLookAgain = button;
  updateHints();
  keyboard.setRows([button], { scrollPage: true });
  keyboard.focusFirst();
}

function showMpvNote(text) {
  const note = mpvMissingEl.querySelector('[data-role="note"]');
  note.textContent = text;
  note.hidden = !text;
}

// B still quits and Up and Down still scroll while this runs, so a check that
// stalls (the page gives up after 30 seconds) leaves no key dead but A.
async function lookForMpvAgain(keyboard) {
  if (mpvChecking) return;
  mpvChecking = true;
  showMpvNote("");
  // A pressed with the button scrolled away brings it back into view.
  keyboard.refocus();
  const slow = setTimeout(() => {
    showMpvNote(CHECKING_AGAIN);
    keyboard.refocus(); // the line above it can push the button out of a short window
  }, CHECKING_AFTER_MS);
  let status = null;
  try {
    status = await api.lookForMpvAgain();
  } catch (err) {
    // Said on screen, as at launch.
  }
  clearTimeout(slow);
  mpvChecking = false;
  if (status && status.available) {
    continueToFolders(keyboard);
    return;
  }
  const before = [...mpvMissingEl.querySelectorAll("p:not([data-role])")].map((p) => p.textContent);
  const lines = mpvLines(status);
  writeMpvLines(lines);
  showMpvNote(before.join("\n") === lines.join("\n") ? SAME_ANSWER : "");
  keyboard.refocus();
}

// mpv is there now: the screen goes and the flow carries on at screen 1.
function continueToFolders(keyboard) {
  mpvLookAgain = null;
  keyboard.setRows([]);
  mpvMissingEl.replaceChildren();
  mpvMissingEl.hidden = true;
  // The wait holds for a failed search too: screen 1 then has a row to land on.
  const searching = Promise.allSettled([api.findFolders(), sleep(KEYS_SETTLE_MS)]).then(([found]) => {
    if (found.status === "rejected") throw found.reason;
    return found.value;
  });
  showOnboarding(searching);
}

async function main() {
  showPresses();
  // Keys work from the start, so q quits while the loading screen shows.
  // Until the list arrives there are no rows, so only quit does anything.
  const keyboard = createKeyboardController({
    onPlay: (row) => {
      if (row === mpvLookAgain) lookForMpvAgain(keyboard);
      else if (onboarding.isOpen()) onboarding.select(row);
      else if (settingsScreen.isOpen()) settingsScreen.select(row);
      else if (mode === "parsed") handleSelect(keyboard, row);
      else handlePlay(keyboard, row);
    },
    // On onboarding's second screen B goes back to the first; on the first
    // it quits, as on every screen without a menu. Just after Open my library,
    // with Home not ready yet, it does nothing: B there was meant for the old screen.
    onQuit: () => {
      if (ignoringBack) return;
      if (onboarding.isOpen() && onboarding.back()) return;
      if (settingsScreen.isOpen()) settingsScreen.back();
      else handleBack(keyboard);
    },
    onLookAgain: () => {
      if (onboarding.isOpen()) onboarding.lookAgain();
    },
    onDetails: toggleDetails,
    onRescan: () => handleRescan(keyboard),
    getTab: selectedTab,
    onSwitchTab: (step) => stepTab(keyboard, step),
    onSideStep: (step) => jumpLetter(keyboard, step),
    getTiles: () => (continueEl.hidden ? [] : continueTiles),
    onRemove: (tile) => removeTile(keyboard, tile),
    getBarButtons: () => (actionBarEl.hidden ? [] : [menuButtonEl]),
    onBarSelect: () => openMenu(false),
    onMenu: () => {
      if (homeShown()) openMenu(false);
    },
  });
  // Onboarding (the folder choice screens): once both folders are saved, the scan and its
  // result follow (the first scan screen), and Open my library opens Home as at any launch.
  onboarding = createOnboarding({
    keyboard,
    onHints: updateHints,
    scan: runScan,
    scanWords: progressText,
    onDone: () => {
      if (window.location.hash === ONBOARDING_ADDRESS) history.replaceState(null, "", window.location.pathname);
      return openHomeAfterOnboarding(keyboard);
    },
  });
  // Settings (issue 100): B goes back to Home, on the Menu button.
  settingsScreen = createSettings({
    keyboard,
    onboarding,
    onHints: updateHints,
    onClose: () => leaveSettings(keyboard),
    onFolderChanged: (saved) => rescanAfterChange(keyboard, saved.scan),
    toast: { show: showToast, update: updateToast },
  });
  // Home actions (the Home actions work): a tap on Menu opens the menu; a choice in it acts.
  menuButtonEl.addEventListener("click", () => {
    if (homeShown() && !keyboard.isBusy()) openMenu(false, menuButtonEl);
  });
  // Registered first, so the choice below starts from a focused element.
  for (const dialog of [menuEl, confirmEl, confirmUpdateEl]) {
    for (const type of ["en-select", "en-cancel"]) {
      dialog.addEventListener(type, () => keepFocusAfterPicker(keyboard));
    }
    // A short window can't show the whole picker (Enamel's dialog scrolls),
    // so the row Enamel moves the focus to is brought into view (the Enamel 0.8.0 upgrade:
    // Enamel 0.8.0's rows are taller).
    dialog.addEventListener("focusin", (event) => {
      if (event.target.matches(".en-picker__row")) event.target.scrollIntoView({ block: "nearest", inline: "nearest" });
    });
  }
  menuEl.addEventListener("en-select", (event) => handleMenuChoice(keyboard, event.detail.value));
  actionBarEl.addEventListener("focusin", markBarFocus);
  actionBarEl.addEventListener("focusout", markBarFocus);
  // Continue watching (the Continue watching work): a tap on a tile resumes it; a swipe
  // scrolls the row. No remove by touch.
  tilesEl.addEventListener("click", (event) => {
    const tile = event.target.closest(".continue-tile");
    if (tile && mode === "parsed" && !keyboard.isBusy()) handleSelect(keyboard, tile);
  });
  // Movies list (the Movies list work): a tap on a film plays it, a tap on the letter
  // strip jumps there, and the strip marks the focused film's letter.
  sections.movies.addEventListener("click", (event) => {
    const row = event.target.closest('.parsed-row[data-kind="movie"]');
    if (row && mode === "parsed" && !keyboard.isBusy()) handleSelect(keyboard, row);
  });
  // The strip never takes the focus, so the row keeps it while tapping.
  letterStripEl.addEventListener("mousedown", (event) => event.preventDefault());
  // A shorter window can leave the marked letter out of a strip that scrolls
  // (the letter strip fix). This also runs on coming back to the Movies tab, but Firefox has
  // kept the strip's place by then, so it only moves the strip if a swipe had
  // already taken the letter out of view.
  new ResizeObserver(keepCurrentLetterInView).observe(letterStripEl);
  letterStripEl.addEventListener("click", (event) => {
    const item = event.target.closest(".letter-strip-letter");
    const start = item && movieLetters.find((s) => s.letter === item.dataset.letter);
    if (start && !keyboard.isBusy()) focusLetter(keyboard, start);
  });
  document.addEventListener("focusin", (event) => {
    const letter = event.target.dataset && event.target.dataset.letter;
    if (letter && event.target.dataset.kind === "movie") markLetter(letter);
    updateHints(); // A Resume and X Remove on a tile
  });
  // The remove question (the picker confirm work): Yes, remove removes. Cancel and B
  // only close it, which Enamel does itself.
  confirmEl.addEventListener("en-select", (event) => {
    if (event.detail.value === "remove") confirmRemove(keyboard);
  });
  // A tap on a tab selects it; touch in the lists stays as it is.
  for (const name of TAB_ORDER) {
    tabs[name].addEventListener("click", () => {
      if (!keyboard.isBusy()) switchTab(keyboard, name);
    });
  }
  watchTabStripHeight(keyboard);
  // A window made smaller doesn't leave the focused button out of view (the mpv missing screen).
  window.addEventListener("resize", () => {
    if (mpvLookAgain) keyboard.refocus();
  });
  showLoading(keyboard);
  showDevInfo();
  showUpdateNote();

  let mpvStatus = null;
  try {
    mpvStatus = await api.getMpvStatus();
  } catch (err) {
    // Said on screen below; mpvLines has the sentence.
  }
  // Onboarding (the folder choice screens): with neither folder set, or at the page
  // address ending in #onboarding, the folders are chosen first.
  const firstLaunch = window.location.hash === ONBOARDING_ADDRESS || (await onboardingNeeded());
  if (!mpvStatus || !mpvStatus.available) {
    await hideLoading(keyboard);
    showMpvMissing(mpvLines(mpvStatus));
    // Later launches keep the message on its own (the mpv missing screen).
    if (firstLaunch) offerMpvLookAgain(keyboard);
    return;
  }

  // The search starts while the loading screen shows.
  if (firstLaunch) {
    const searching = api.findFolders();
    searching.catch(() => {});
    await hideLoading(keyboard);
    showOnboarding(searching);
    return;
  }
  await openHome(keyboard, true);
}

// --- Settings (issue 100) ---

// Home hides while Settings shows, as for onboarding.
function openSettings(keyboard) {
  if (keyboard.isBusy()) return;
  clearError();
  showOnboardingShell();
  settingsScreen.open();
}

// Back on Home with the focus on Menu. After a folder change Home is read
// again, as after a rescan; it may then have nothing to show (the result
// screen's scan takes over, as at launch).
async function leaveSettings(keyboard) {
  if (homeStale) {
    homeStale = false;
    keyboard.setBusy(true);
    await reloadLibrary(keyboard, null);
    keyboard.setBusy(false);
  } else {
    showLibraryView(keyboard, null, activeTab);
  }
  if (homeShown()) keyboard.focusBar(0);
}

// The rescan a folder change started: Enamel's toast counts it and says what
// it found, as for Rescan library. Home is read again once it ends, now if it
// shows, else on the way back from Settings.
async function rescanAfterChange(keyboard, started) {
  homeStale = true;
  if (!started) return;
  if (started.busy) {
    showToast(scanResultText({ busy: true }));
    return;
  }
  rescanning = true;
  showToast(scanProgressText(started));
  const result = await followScan((status) => window.EnamelUI.toast.update(scanProgressText(status)), started);
  rescanning = false;
  if (result.ok && homeShown()) {
    homeStale = false;
    await reloadLibrary(keyboard, focusedKey(keyboard));
  }
  showToast(scanResultText(result));
}

// --- Onboarding (the folder choice screens) ---

// The flow's own address, so Settings can open it later.
const ONBOARDING_ADDRESS = "#onboarding";

// Any problem asking just starts the app as it does today.
async function onboardingNeeded() {
  try {
    return (await api.getOnboarding()).needed === true;
  } catch (err) {
    return false;
  }
}

function showOnboardingShell() {
  libraryEl.hidden = true;
  episodesEl.hidden = true;
  openShow = null;
  showActionBar(false);
  showTabStrip(false);
}

function showOnboarding(searching) {
  showOnboardingShell();
  onboarding.open(searching);
}

// B does nothing just after Open my library (the second onboarding review fixes, moved by the first scan screen). If Home is still not ready
// when the loading screen would say it is still working, that screen shows and
// B quits again, as it does at launch, so a stalled card is never a dead end.
async function openHomeAfterOnboarding(keyboard) {
  ignoringBack = true;
  const stalled = setTimeout(() => {
    ignoringBack = false;
    loadingEl.querySelector('[data-role="slow"]').hidden = false;
    loadingEl.hidden = false;
  }, STILL_WORKING_MS);
  try {
    await openHome(keyboard, false);
  } finally {
    clearTimeout(stalled);
    ignoringBack = false;
    loadingEl.hidden = true;
  }
}

// Home, as at any launch: the saved library, or with none, the result screen's
// scan.
// launching: the loading screen is still up, and goes once Home is ready.
async function openHome(keyboard, launching) {
  const done = () => (launching ? hideLoading(keyboard) : undefined);
  // The carousel is asked for alongside the library (the Continue watching work).
  const continuing = fetchContinue();
  let answer;
  try {
    answer = await api.getParsedLibrary(fixtureCount);
  } catch (err) {
    answer = { ok: false, error: "Couldn't read the library." };
  }
  if (answer.ok) {
    if (hasLibrary(answer)) {
      renderContinue(await continuing);
      await showParsedLibrary(keyboard, answer);
      // At launch the focus starts on the first tile when the carousel shows.
      keyboard.focusTile(0);
      logTiming("Home: ready", 0, performance.now(), `with ${continueTiles.length} tiles`);
      await done();
      return;
    }
    await done();
    showFirstScan();
    return;
  }

  // Fallback: today's plain file list, unchanged.
  mode = "plain";
  showError(answer.error);
  let library;
  try {
    library = await api.getLibrary();
  } catch (err) {
    await done();
    showError("Couldn't read the library.");
    return;
  }
  await done();
  showLibrary(keyboard, library);
}

main();
