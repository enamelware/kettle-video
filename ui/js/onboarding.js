// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Mario Carabotta

// Onboarding (the folder choice screens): on first launch, choose the Movies folder (screen
// 1), then the TV Shows folder (screen 2), from the folders the backend
// found with videos (the folder finder). When no folder is found anywhere, "No videos
// found yet" shows in place of screen 1 (the No videos found screen). Built only from Enamel
// 0.9.0's parts: the step label, group bands, list rows with their meta line,
// the badge, the message in a row, numbered steps and the button. The page
// only ever sees ids, names and counts; the backend checks the choice and
// saves it in settings.json.
//
// Screen 3 (the first scan screen), Enamel 0.10.0's stat pair and notes: the scan, then
// what it found. It also opens on its own when folders are set and there is no
// saved library, with no search and no choice behind it.

import * as api from "./api.js";
import { actionButton, addSpan } from "./dom.js";
import { plural, SCAN_FAILED } from "./home_menu.js";
import { STILL_WORKING, STILL_WORKING_MS } from "./still_working.js";

// "Looking for your videos" shows only when a search takes longer than this.
const LOOKING_AFTER_MS = 1000;
const LOOKING = "Looking for your videos";
const SEARCH_FAILED = "Couldn't look for your folders. Press Y to look again.";
const CHOICE_FAILED = "Couldn't save your folders. Your settings are unchanged.";
const SKIP = "skip";
const LOOK_AGAIN = "look-again";
// The Browse somewhere else work: the row and the button that open the system's folder dialog.
const BROWSE = "browse";
const BROWSE_WORDS = "Browse somewhere else";
const BROWSE_FAILED = "Couldn't open the folder window. Choose a folder from the list instead.";
// What can take the focus on a screen: a row, or a button.
const CHOICES = ".folder-row, .no-videos-action, .result-action";

// Screen 3's two buttons. Its scan's words say it is still working after the
// loading screen's wait, in the loading screen's words (still_working.js).
const OPEN_LIBRARY = "open-library";
const CHANGE_FOLDERS = "change-folders";

// While the first search runs, nothing is known yet: no title that a moment
// later could turn out to be the wrong one.
const SEARCHING = { step: "", title: "", intro: "", select: "Select", back: "Quit" };

// The No videos found screen. Its first sentence, where it looked, comes from the backend.
const NO_VIDEOS = {
  step: "",
  title: "No videos found yet",
  intro: "It plays videos you already have and doesn't create folders for you.",
  steps: [
    "Make one folder for movies and one for TV shows, on this device or on an SD card.",
    "Copy your videos in. Give each TV show its own folder.",
    "If they are on a card, put it in. Then choose Look again.",
  ],
  select: "Look again",
  back: "Quit",
};

// Screen 3's states. No words for A and B while the scan runs: neither does
// anything. A's words follow the focused button.
const STEP_3 = "Step 3 of 3";
const READING = { step: STEP_3, title: "Reading your folders", intro: "", select: null, back: null };
const READY = {
  step: STEP_3,
  title: "Your library is ready",
  intro: "Titles come from your file and folder names. Nothing was changed in your folders.",
  back: "Back",
};
const NOTHING_FOUND = { step: STEP_3, title: "Nothing found in these folders", intro: "", back: "Back" };
const SCAN_TROUBLE = { step: STEP_3, title: "Couldn't read your folders", intro: "", back: "Back" };

const SCREENS = {
  1: {
    step: "Step 1 of 3",
    title: "Which folder has your movies?",
    intro: "Folders with videos, grouped by where they are. Kettle only reads them: it never moves, renames or creates anything.",
    skip: "I don't have movies",
    select: "This is my movies folder",
    back: "Quit",
  },
  2: {
    step: "Step 2 of 3",
    title: "Which folder has your TV shows?",
    intro: "It can be in a different place from your movies. Inside it, each show should have its own folder.",
    skip: "I don't have TV shows",
    select: "This is my TV shows folder",
    back: "Back",
  },
};

// Settings (issue 100): one kind's folder screen, reused from screens 1 and
// 2 with no step label, "Stop using ..." in place of "I don't have ...", and
// B back to Settings.
const CHANGE = {
  movies: { ...SCREENS[1], step: "", skip: "Stop using a movies folder", back: "Back" },
  tv: { ...SCREENS[2], step: "", skip: "Stop using a TV shows folder", back: "Back" },
};

// Enamel's own icons, drawn as on its Components page: a drive for storage
// on the device, a card for storage you can take out, and the error mark.
const DRIVE_ICON =
  '<svg class="en-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true"><rect x="3" y="6" width="18" height="12" rx="2"/><path d="M3 13h18"/><path d="M16.5 15.5h1"/></svg>';
const CARD_ICON =
  '<svg class="en-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true"><path d="M9 3h8a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V7z"/><path d="M10 7v3M13 7v3M16 7v3"/></svg>';
const ERROR_ICON =
  '<svg class="en-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true"><circle cx="12" cy="12" r="10" fill="currentColor" stroke="none"/><path d="M12 7v6"/><path d="M12 16.5v.5"/></svg>';

function icon(markup) {
  const template = document.createElement("template");
  template.innerHTML = markup;
  return template.content.firstElementChild;
}

function folders(n) {
  return `${n} folder${n === 1 ? "" : "s"}`;
}

// keyboard: the app's keyboard controller (rows, focus, busy). scan runs the
// library's scan, reporting its progress, and answers with its result. onDone
// runs on Open my library, and answers once Home is ready; onHints when the
// hint bar's words change.
export function createOnboarding({ keyboard, scan, scanWords, onDone, onHints }) {
  const el = document.getElementById("onboarding");
  const stepEl = el.querySelector('[data-role="step"]');
  const titleEl = el.querySelector('[data-role="title"]');
  const introEl = el.querySelector('[data-role="intro"]');
  const lookingEl = el.querySelector('[data-role="looking"]');
  const groupsEl = el.querySelector('[data-role="groups"]');
  let open = false;
  let step = 1;
  let answer = null; // the last search's answer, or null
  let failed = false; // the last search failed
  let movies = null; // the Movies folder's id, or null for "I don't have movies"
  let moviesRow = null; // the row chosen on screen 1: an id or SKIP
  let tvRow = null; // the row chosen on screen 2: an id or SKIP
  let result = null; // screen 3: what the scan found, or { failed, message }
  let scanning = false; // screen 3: the scan is running
  let noChoices = false; // screen 3 opened on its own, with nothing chosen first
  let scans = 0;
  let rows = [];
  let searches = 0;
  let picks = []; // folders chosen in the dialog: { folder, kind }, kept through Look again
  let browsing = false; // the dialog is open
  // Settings (issue 100): { kind, ids: { movies, tv }, onSaved, onBack } while
  // one kind's folder is being changed from Settings, else null (onboarding).
  let change = null;

  // The message inside a row: Enamel's error style with its mark. Empty
  // while there is nothing to say, so it takes no space.
  function showMessage(row, text) {
    const message = row.querySelector(".en-row__message");
    message.replaceChildren(icon(ERROR_ICON), document.createTextNode(text));
    // The row grew: the message itself is brought into view (in a short
    // window a tall row can't be wholly on screen).
    message.scrollIntoView({ block: "nearest" });
  }

  function folderRow(folder) {
    const row = document.createElement("li");
    row.className = "folder-row en-row";
    row.tabIndex = -1;
    row.dataset.kind = "folder";
    row.dataset.id = folder.id;
    // Why it can't be chosen, from the backend (the first onboarding review fixes): A says it in the row.
    if (folder.problem) row.dataset.problem = folder.problem;
    const line = addSpan(row, "row-line", "");
    // "SD card › Media › Films", the folder's own name in bold.
    const trail = [folder.place, ...folder.trail];
    const path = addSpan(line, "folder-path", "");
    path.textContent = trail.slice(0, -1).map((part) => `${part} › `).join("");
    const name = document.createElement("strong");
    name.className = "folder-name";
    name.textContent = trail[trail.length - 1];
    path.appendChild(name);
    if (change) {
      // From Settings: each kind's folder as it is now, either may be chosen.
      if (folder.id === change.ids.movies) addSpan(line, "en-badge", "Movies");
      if (folder.id === change.ids.tv) addSpan(line, "en-badge", "TV shows");
    } else if (step === 2 && folder.id === movies) addSpan(line, "en-badge", "Movies");
    const meta = [folder.count_text, folder.examples.join(", ")].filter(Boolean).join(" · ");
    addSpan(row, "en-row__meta", meta);
    addMessage(row);
    return row;
  }

  function addMessage(row) {
    const message = addSpan(row, "en-row__message", "");
    message.setAttribute("role", "status");
    message.setAttribute("aria-live", "polite");
  }

  // "I don't have ..." or "Browse somewhere else".
  function actionRow(kind, text) {
    const row = document.createElement("li");
    row.className = "folder-row en-row";
    row.tabIndex = -1;
    row.dataset.kind = kind;
    addSpan(row, "row-line", text);
    addMessage(row);
    return row;
  }

  // The dialog can't open, or gave no folder: in the row, or, as a button has
  // no room for it, in the line above the buttons.
  function showBrowseProblem(row, text) {
    if (row.querySelector(".en-row__message")) {
      showMessage(row, text);
      return;
    }
    lookingEl.textContent = text;
    lookingEl.dataset.state = "error";
    lookingEl.hidden = false;
    lookingEl.scrollIntoView({ block: "nearest" });
  }

  function clearBrowseProblem() {
    if (failed || lookingEl.dataset.state !== "error") return;
    lookingEl.textContent = "";
    delete lookingEl.dataset.state;
    lookingEl.hidden = true;
  }

  function band(place) {
    const heading = document.createElement("h2");
    // Filled with a drive for storage on the device; outlined with a card
    // for a card or a drive you can take out.
    const removable = place.kind !== "internal";
    heading.className = removable ? "folder-band en-band en-band--outline" : "folder-band en-band";
    const name = addSpan(heading, "en-band__name", "");
    name.append(icon(removable ? CARD_ICON : DRIVE_ICON), document.createTextNode(place.name));
    addSpan(heading, "en-band__count", folders(place.folders.length));
    return heading;
  }

  // The search's folders, each folder from the dialog added to its place
  // (a place of its own if the search had none) unless the search found it too.
  function placesWithFolders() {
    const places = answer ? answer.places.map((place) => ({ ...place, folders: [...place.folders] })) : [];
    for (const { folder, kind } of picks) {
      if (places.some((place) => place.folders.some((listed) => listed.id === folder.id))) continue;
      const home = places.find((place) => place.name === folder.place);
      if (home) home.folders.push(folder);
      else places.push({ name: folder.place, kind, folders: [folder] });
    }
    return places.filter((place) => place.folders.length > 0);
  }

  // Which screen shows now. Screen 2 stays when a Look again there finds
  // nothing, so the choice made on screen 1 isn't lost.
  function currentScreen() {
    if (step === 3) {
      if (scanning) return READING;
      if (result.failed) return SCAN_TROUBLE;
      return result.nothing_found ? NOTHING_FOUND : READY;
    }
    // From Settings there is no "No videos found yet": the list stays, with its
    // line saying nothing was found, so "Stop using ..." can still be chosen.
    if (change) return !answer && !failed ? SEARCHING : CHANGE[change.kind];
    if (step === 1 && !answer) return failed ? SCREENS[1] : SEARCHING;
    if (step === 1 && placesWithFolders().length === 0) return NO_VIDEOS;
    return SCREENS[step];
  }

  function noVideosButton(kind, words, primary) {
    return actionButton("no-videos-action", kind, words, primary);
  }

  // The steps and the button, or two. The app moves the focus to a button like
  // a row.
  function showNoVideos() {
    const steps = document.createElement("ol");
    steps.className = "no-videos-steps en-steps";
    for (const text of NO_VIDEOS.steps) {
      const item = document.createElement("li");
      item.textContent = text;
      steps.appendChild(item);
    }
    rows = [noVideosButton(LOOK_AGAIN, NO_VIDEOS.select, true)];
    if (answer.browse) rows.push(noVideosButton(BROWSE, BROWSE_WORDS, false));
    groupsEl.replaceChildren(steps, ...rows);
    groupsEl.hidden = false;
    // The buttons are at the page's end, so Up and Down also scroll it: in a
    // short window the words above them can still be read.
    keyboard.setRows(rows, { scrollPage: true });
    onHints();
  }

  // --- Screen 3 (the first scan screen) ---

  // One count: a large number with its word.
  function statCount(count, word) {
    const box = document.createElement("span");
    box.className = "en-statpanel__count";
    addSpan(box, "en-statpanel__number", String(count));
    box.append(` ${word}`);
    return box;
  }

  // counts: [number, word] pairs. The panel's whole text is in its label. A
  // kind that was skipped says "Not set", and its second line says which kind.
  function statPanel(kind, panel, counts) {
    const box = document.createElement("div");
    box.className = "en-statpanel";
    box.dataset.kind = kind.key;
    box.setAttribute("role", "img");
    if (!panel.set) {
      box.setAttribute("aria-label", `${kind.name}, not set`);
      addSpan(box, "en-statpanel__notset", "Not set");
      addSpan(box, "en-statpanel__path", kind.name);
      return box;
    }
    const words = counts.map(([n, one]) => plural(n, one));
    box.setAttribute("aria-label", [...words, panel.path].join(", "));
    const countsEl = addSpan(box, "en-statpanel__counts", "");
    countsEl.append(...counts.map(([n, one]) => statCount(n, n === 1 ? one : `${one}s`)));
    addSpan(box, "en-statpanel__path", panel.path);
    return box;
  }

  function resultButton(kind, words, primary) {
    return actionButton("result-action", kind, words, primary);
  }

  function showScanProgress(status) {
    const words = groupsEl.querySelector('[data-role="scan-words"]');
    const bar = groupsEl.querySelector(".en-progress");
    if (!words || !bar) return;
    const text = scanWords(status);
    const share = status.files_total > 0 ? Math.round((status.files_done / status.files_total) * 100) : 0;
    words.textContent = text;
    bar.style.setProperty("--value", `${share}%`);
    bar.setAttribute("aria-valuenow", String(share));
  }

  // The head line says where the scan is; Enamel's second place on it says
  // when it has been a while since that changed.
  function showReading() {
    const box = document.createElement("div");
    box.className = "scan-progress";
    const head = document.createElement("div");
    head.className = "en-progress__head";
    addSpan(head, "", scanWords(null)).dataset.role = "scan-words";
    const slow = addSpan(head, "", "");
    slow.dataset.role = "scan-slow";
    const bar = document.createElement("div");
    bar.className = "en-progress";
    bar.setAttribute("role", "progressbar");
    bar.setAttribute("aria-label", READING.title);
    bar.setAttribute("aria-valuenow", "0");
    bar.style.setProperty("--value", "0%");
    addSpan(bar, "en-progress__fill", "");
    box.append(head, bar);
    groupsEl.replaceChildren(box);
    groupsEl.hidden = false;
    rows = [];
    keyboard.setRows([], { scrollPage: true });
    onHints();
  }

  function showResult(screen) {
    const parts = [];
    if (screen !== SCAN_TROUBLE) {
      const pair = document.createElement("div");
      pair.className = "en-statpair";
      pair.append(
        statPanel({ key: "movies", name: "Movies" }, result.movies, [[result.movies.count, "movie"]]),
        statPanel({ key: "tv", name: "TV shows" }, result.tv, [[result.tv.shows, "TV show"], [result.tv.episodes, "episode"]]),
      );
      parts.push(pair);
      if (result.notes.length > 0) {
        const notes = document.createElement("div");
        notes.className = "result-notes";
        for (const text of result.notes) {
          const note = document.createElement("p");
          note.className = "en-note";
          note.textContent = text;
          notes.appendChild(note);
        }
        parts.push(notes);
      }
    }
    // The screen's one primary button, focused first. With nothing to open,
    // Change folders is the only way on.
    rows = [resultButton(CHANGE_FOLDERS, "Change folders", screen !== READY)];
    if (screen === READY) rows.unshift(resultButton(OPEN_LIBRARY, "Open my library", true));
    groupsEl.replaceChildren(...parts, ...rows);
    groupsEl.hidden = false;
    keyboard.setRows(rows, { scrollPage: true });
    onHints();
  }

  function render() {
    const screen = currentScreen();
    el.dataset.step = screen === NO_VIDEOS ? "no-videos" : String(step);
    if (step === 3) el.dataset.result = screen === READING ? "reading" : screen === READY ? "ready" : screen === NOTHING_FOUND ? "nothing" : "failed";
    else delete el.dataset.result;
    stepEl.textContent = screen.step;
    stepEl.hidden = !screen.step;
    titleEl.textContent = screen.title;
    titleEl.parentElement.hidden = !screen.title;
    introEl.textContent = screen === NO_VIDEOS ? `${answer.looked} ${screen.intro}` : screen.intro;
    introEl.hidden = !screen.intro;
    if (step === 3) {
      lookingEl.textContent = screen === SCAN_TROUBLE ? result.message : "";
      if (screen === SCAN_TROUBLE) lookingEl.dataset.state = "error";
      else delete lookingEl.dataset.state;
      lookingEl.hidden = screen !== SCAN_TROUBLE;
      if (screen === READING) showReading();
      else showResult(screen);
      return;
    }
    const places = placesWithFolders();
    // Above a list: what the search couldn't see (the first onboarding review fixes). "No videos found
    // yet" and an empty screen 2 say it in their own sentences.
    const line = failed ? SEARCH_FAILED : (answer && places.length > 0 && answer.gaps) || "";
    lookingEl.textContent = line;
    if (failed) lookingEl.dataset.state = "error";
    else delete lookingEl.dataset.state;
    lookingEl.hidden = !line;
    if (screen === NO_VIDEOS) {
      showNoVideos();
      return;
    }
    rows = [];
    const parts = [];
    for (const place of places) {
      const list = document.createElement("ul");
      list.className = "folder-list en-rows";
      for (const folder of place.folders) {
        const row = folderRow(folder);
        list.appendChild(row);
        rows.push(row);
      }
      parts.push(band(place), list);
    }
    if (answer && places.length === 0) {
      const none = document.createElement("p");
      none.className = "status";
      none.textContent = `No folders with videos found. Looked in: ${answer.checked}.`;
      parts.push(none);
    }
    const last = document.createElement("ul");
    last.className = "folder-list en-rows";
    const endRows = [actionRow(SKIP, (change ? CHANGE[change.kind] : SCREENS[step]).skip)];
    if (answer && answer.browse) endRows.unshift(actionRow(BROWSE, BROWSE_WORDS));
    last.append(...endRows);
    rows.push(...endRows);
    parts.push(last);
    groupsEl.replaceChildren(...parts);
    groupsEl.hidden = false;
    keyboard.setRows(rows, { readAboveFirst: true });
    onHints();
  }

  // The row with this id (or kind: SKIP, BROWSE), else the first folder; the
  // first row also brings the top of the screen back into view.
  function focusRow(id) {
    let index = rows.findIndex((row) => row.dataset.id === id || row.dataset.kind === id);
    if (index < 0) index = 0;
    if (index === 0) window.scrollTo(0, 0);
    keyboard.focusAt(index);
  }

  // Screens with their buttons at the end, where Up and Down scroll the words.
  function scrollsPage() {
    return el.dataset.step === "no-videos" || el.dataset.step === "3";
  }

  function hasFolderRows() {
    return rows.some((row) => row.dataset.kind === "folder");
  }

  // Runs the scan and shows what it found. B and A do nothing meanwhile: there
  // are no rows, and B is answered in back(). Up and Down scroll the page, so
  // every word can be read in a short window.
  async function runScan() {
    const mine = ++scans;
    step = 3;
    result = null;
    scanning = true;
    render();
    window.scrollTo(0, 0);
    keyboard.setBusy(false);
    let lastWords = "";
    let slowTimer = null;
    const slowEl = () => groupsEl.querySelector('[data-role="scan-slow"]');
    const waitForChange = () => {
      clearTimeout(slowTimer);
      if (slowEl()) slowEl().textContent = "";
      slowTimer = setTimeout(() => {
        if (mine === scans && slowEl()) slowEl().textContent = STILL_WORKING;
      }, STILL_WORKING_MS);
    };
    waitForChange();
    let outcome;
    try {
      const done = await scan((status) => {
        if (mine !== scans || !open) return;
        showScanProgress(status);
        const words = scanWords(status);
        if (words !== lastWords) {
          lastWords = words;
          waitForChange();
        }
      });
      if (!done.ok) throw new Error("scan failed");
      outcome = await api.getScanResult();
    } catch (err) {
      outcome = { failed: true };
    }
    clearTimeout(slowTimer);
    if (mine !== scans || !open) return;
    scanning = false;
    result = outcome.failed ? { failed: true, message: SCAN_FAILED } : outcome;
    render();
    window.scrollTo(0, 0);
    keyboard.focusFirst();
  }

  // Back from screen 3. With nothing chosen first, no search has run yet, and
  // screen 2 can't stand: a folder chosen there would clear the Movies folder
  // already set, so B goes to screen 1 as Change folders does.
  function leaveResult(to) {
    step = noChoices ? 1 : to;
    result = null;
    noChoices = false;
    if (!answer) {
      failed = false;
      render();
      groupsEl.hidden = true;
      search(null, null);
      return;
    }
    render();
    focusRow(step === 1 ? moviesRow : tvRow);
  }

  // focusId: the row to keep the focus on. Coming from a screen with no folder
  // list to one with a list, the focus starts on the first folder (the first onboarding review fixes).
  async function search(pending, focusId) {
    const hadFolders = hasFolderRows();
    const mine = ++searches;
    keyboard.setBusy(true);
    const timer = setTimeout(() => {
      if (mine !== searches) return;
      lookingEl.textContent = LOOKING;
      delete lookingEl.dataset.state;
      lookingEl.hidden = false;
      groupsEl.hidden = true;
    }, LOOKING_AFTER_MS);
    let found;
    try {
      found = await (pending || api.findFolders());
    } catch (err) {
      found = null;
    }
    clearTimeout(timer);
    if (mine !== searches || !open) return;
    keyboard.setBusy(false);
    answer = found && Array.isArray(found.places) ? found : null;
    failed = answer === null;
    render();
    // From Settings the list first opens on the folder this kind uses now.
    const first = change && !hadFolders ? change.ids[change.kind] || null : null;
    focusRow(!hadFolders && hasFolderRows() ? first : focusId);
  }

  // The Browse somewhere else work. The page waits, however long the dialog stays open, and the
  // focus comes back to where it was. A folder gets a row like a listed one,
  // focused; the backend has checked it, and a problem shows in that row.
  async function browse(row) {
    browsing = true;
    keyboard.setBusy(true);
    onHints();
    let result;
    try {
      result = change ? await api.browseFolder(null, change.kind) : await api.browseFolder(step === 2 ? movies : null);
    } catch (err) {
      result = { ok: false, message: BROWSE_FAILED };
    }
    browsing = false;
    keyboard.setBusy(false);
    if (!open) return;
    onHints();
    if (!result.ok || !result.picked) {
      keyboard.refocus();
      if (!result.ok) showBrowseProblem(row, result.message || BROWSE_FAILED);
      return;
    }
    // A folder picked again takes the place of its old row: it may read differently now.
    picks = picks.filter((pick) => pick.folder.id !== result.folder.id);
    picks.push({ folder: result.folder, kind: result.place_kind });
    render();
    focusRow(result.folder.id);
    if (result.message) showMessage(document.activeElement, result.message);
  }

  async function choose(row) {
    if (row.dataset.kind === OPEN_LIBRARY) {
      // The keys stay off until Home is ready, as after any step that removes
      // its own buttons, so a second press never acts on what has just gone.
      keyboard.setBusy(true);
      close();
      keyboard.setRows([]);
      try {
        await onDone();
      } finally {
        keyboard.setBusy(false);
      }
      return;
    }
    if (row.dataset.kind === CHANGE_FOLDERS) {
      leaveResult(1);
      return;
    }
    if (row.dataset.kind === LOOK_AGAIN) {
      search(null, null);
      return;
    }
    if (row.dataset.kind === BROWSE) {
      browse(row);
      return;
    }
    if (row.dataset.problem) {
      showMessage(row, row.dataset.problem);
      return;
    }
    const id = row.dataset.kind === "folder" ? row.dataset.id : null;
    if (change) {
      saveChange(row, id);
      return;
    }
    if (step === 1) {
      movies = id;
      moviesRow = id || SKIP;
      step = 2;
      render();
      // The choice made here before Change folders, if there was one.
      focusRow(tvRow);
      return;
    }
    keyboard.setBusy(true);
    let saved;
    try {
      saved = await api.chooseFolders(movies, id);
    } catch (err) {
      saved = { ok: false, message: CHOICE_FAILED };
    }
    if (open && saved.ok) {
      // The scan starts at once. The rows go first, so a second press never
      // acts on the ones just removed (the second onboarding review fixes).
      tvRow = id || SKIP;
      keyboard.setRows([]);
      runScan();
      return;
    }
    keyboard.setBusy(false);
    if (!open) return;
    // The message shows in the row, while the focus stays on it.
    if (document.activeElement === row) showMessage(row, saved.message || CHOICE_FAILED);
  }

  // Settings (issue 100): the backend checks the one folder against the other
  // kind's, saves it and starts the rescan; the screen then goes back to
  // Settings. A refusal shows in the row, as in onboarding.
  async function saveChange(row, id) {
    keyboard.setBusy(true);
    let saved;
    try {
      saved = await api.chooseSettingsFolder(change.kind, id);
    } catch (err) {
      saved = { ok: false, message: CHOICE_FAILED };
    }
    keyboard.setBusy(false);
    if (!open || !change) return;
    if (saved.ok) {
      leaveChange().onSaved(saved);
      return;
    }
    if (document.activeElement === row) showMessage(row, saved.message || CHOICE_FAILED);
  }

  // Closes the screen opened from Settings; answers its handlers.
  function leaveChange() {
    const done = change;
    change = null;
    keyboard.setRows([]);
    close();
    delete el.dataset.change;
    return done;
  }

  function close() {
    open = false;
    el.hidden = true;
    groupsEl.replaceChildren();
    rows = [];
    onHints();
  }

  // Enamel styles a focused row on data-focused (the app moves the real
  // focus itself). A row's message goes away when the focus leaves it.
  groupsEl.addEventListener("focusin", (event) => {
    const row = event.target.closest(CHOICES);
    if (row) row.dataset.focused = "true";
  });
  groupsEl.addEventListener("focusout", (event) => {
    const row = event.target.closest(CHOICES);
    if (!row) return;
    delete row.dataset.focused;
    const message = row.querySelector(".en-row__message");
    if (message) message.replaceChildren();
    clearBrowseProblem();
  });
  // A tap chooses the row, as A does.
  groupsEl.addEventListener("click", (event) => {
    const row = event.target.closest(CHOICES);
    if (!row || !open || keyboard.isBusy()) return;
    if (document.activeElement !== row) row.focus({ preventScroll: true });
    choose(row);
  });

  return {
    // pending: a search already started (at launch, while the loading
    // screen shows), else the search starts now.
    open(pending) {
      open = true;
      change = null;
      delete el.dataset.change;
      step = 1;
      answer = null;
      failed = false;
      movies = null;
      moviesRow = null;
      tvRow = null;
      result = null;
      scanning = false;
      noChoices = false;
      picks = [];
      el.hidden = false;
      render();
      groupsEl.hidden = true;
      search(pending, null);
    },
    // Screen 3 on its own: folders are set and there is no saved library (the
    // designer's answer on the first scan screen), so it scans those and shows what it found.
    openScan() {
      open = true;
      change = null;
      delete el.dataset.change;
      answer = null;
      failed = false;
      movies = null;
      moviesRow = null;
      tvRow = null;
      picks = [];
      noChoices = true;
      el.hidden = false;
      keyboard.setRows([]);
      runScan();
    },
    // Settings (issue 100): the folder screen for one kind ("movies" or
    // "tv"). ids: each kind's folder id now (or undefined), for the badges and
    // the first focus. onSaved(answer) runs once the change is saved, or found
    // to change nothing; onBack() on B. Either way the screen has closed.
    openChange(kind, ids, { onSaved, onBack }) {
      open = true;
      change = { kind, ids, onSaved, onBack };
      el.dataset.change = kind;
      step = kind === "movies" ? 1 : 2;
      answer = null;
      failed = false;
      movies = null;
      moviesRow = null;
      tvRow = null;
      result = null;
      scanning = false;
      noChoices = false;
      picks = [];
      el.hidden = false;
      window.scrollTo(0, 0);
      render();
      groupsEl.hidden = true;
      search(null, null);
    },
    isOpen: () => open,
    // A on a row scrolled out of view (Up reads the words above the list) only
    // brings it back: nothing is ever chosen unseen (the first onboarding review fixes).
    select(row) {
      if (!open || !rows.includes(row)) return;
      if (!scrollsPage() && !keyboard.rowInView(row)) {
        keyboard.showRow(row);
        return;
      }
      choose(row);
    },
    // B: screen 2 goes back to screen 1, keeping the choice made there, and
    // screen 3's result to screen 2; during the scan it does nothing.
    // False on screen 1, where B quits as on every screen without a menu.
    // While the dialog is open, B closes it: should it open behind Kettle,
    // the controller can still get out.
    back() {
      if (open && browsing) {
        api.closeBrowse().catch(() => {});
        return true;
      }
      // From Settings: back to Settings, on the row it was opened from.
      if (open && change) {
        if (!keyboard.isBusy()) leaveChange().onBack();
        return true;
      }
      if (open && step === 3) {
        if (!scanning) leaveResult(2);
        return true;
      }
      if (!open || step !== 2) return false;
      if (keyboard.isBusy()) return true;
      step = 1;
      render();
      focusRow(moviesRow);
      return true;
    },
    lookAgain() {
      if (!open || step === 3) return;
      const current = rows.find((row) => row === document.activeElement);
      const onRow = current && current.dataset.kind !== LOOK_AGAIN;
      search(null, onRow ? current.dataset.id || current.dataset.kind : null);
    },
    // Not on "No videos found yet", where Up and Down scroll away from the
    // focused button on purpose.
    keepFocusInView() {
      if (!scrollsPage() && rows.includes(document.activeElement)) {
        keyboard.showRow(document.activeElement);
      }
    },
    // The hint bar's words while it is open, else null. Y's hint shows only
    // where A does something else.
    hints() {
      if (!open) return null;
      const screen = currentScreen();
      const focused = rows.includes(document.activeElement) ? document.activeElement : null;
      const onBrowse = focused && focused.dataset.kind === BROWSE;
      const selectWords = step === 3 && focused ? focused.textContent : screen.select;
      return {
        select: onBrowse ? "Browse" : selectWords,
        back: browsing ? "Cancel" : screen.back,
        lookAgain: screen === SCREENS[step] || (change !== null && screen === CHANGE[change.kind]),
      };
    },
  };
}
