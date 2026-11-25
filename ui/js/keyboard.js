// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Mario Carabotta

const PLAY_KEYS = new Set(["Enter", " ", "Spacebar"]);
const QUIT_KEYS = new Set(["q", "Q", "Escape"]);
// Interim parsed library view (the parsed library view): d shows paths, r rescans.
const DETAILS_KEYS = new Set(["d", "D"]);
const RESCAN_KEYS = new Set(["r", "R"]);
// The controller's X sends Backspace (the Continue watching work, docs/decisions.md).
const REMOVE_KEYS = new Set(["Backspace"]);
// The controller's Start sends m: it opens Home's menu (the Home actions work).
const MENU_KEYS = new Set(["m", "M"]);
// The controller's Y sends a: Look again in onboarding (the folder choice screens).
const LOOK_KEYS = new Set(["a", "A"]);

// A held key sends itself again and again (event.repeat). For A, B and X
// that counts as one press (the held button fix): otherwise holding A on a show opens
// it and plays the first episode, and holding B goes back and then quits.
// The arrows keep repeating, so holding the D-pad still scrolls.
function isHeldRepeat(event) {
  return event.repeat && (PLAY_KEYS.has(event.key) || QUIT_KEYS.has(event.key) || REMOVE_KEYS.has(event.key)
    || MENU_KEYS.has(event.key) || LOOK_KEYS.has(event.key));
}

// The room a row keeps above itself when it is scrolled to.
function marginAbove(row) {
  return parseFloat(getComputedStyle(row).scrollMarginTop) || 0;
}

// Enamel 0.11.0 (the Enamel 0.11.0 upgrade): a focused button or picker row drops while A is
// held, but a stylesheet can't see a controller's press, so the app marks it
// with data-pressed="true" until A comes up or the focus moves on (A on Menu
// opens the menu, and its first row must not look pressed). It only changes
// how things look: what A does is still decided on the press, below.
const PRESSABLE = ".en-button, .en-picker__row";

export function showPresses() {
  function release() {
    for (const element of document.querySelectorAll('[data-pressed="true"]')) delete element.dataset.pressed;
  }
  window.addEventListener("keydown", (event) => {
    if (!PLAY_KEYS.has(event.key) || event.repeat) return;
    const target = document.activeElement;
    if (target && target.matches(PRESSABLE) && !target.disabled) target.dataset.pressed = "true";
  }, true);
  window.addEventListener("keyup", (event) => {
    if (PLAY_KEYS.has(event.key)) release();
  }, true);
  document.addEventListener("focusout", release);
  window.addEventListener("blur", release);
}

// Whether an Enamel picker (the remove question, the picker confirm work, or Home's
// menu, the Home actions work) is open.
export function pickerOpen() {
  return Boolean(window.EnamelUI && window.EnamelUI.picker.isOpen());
}

// While a picker is open, Enamel answers Up, Down, Enter, Escape and Tab
// itself and they never get here. The app acts on nothing else, except the
// controller's A (Space) and B (q), which go to the picker: A chooses the
// focused row, B is Cancel. So one press is never acted on twice: B that
// closes the menu never quits, and Start does nothing while it is open.
function handlePickerKey(event) {
  event.preventDefault();
  if (isHeldRepeat(event)) return;
  if (PLAY_KEYS.has(event.key)) window.EnamelUI.picker.select();
  else if (QUIT_KEYS.has(event.key)) window.EnamelUI.picker.cancel();
}

// Home shell (the Home shell work): getTab returns the selected tab while the tab
// strip shows (else null), and onSwitchTab(-1 | 1) is Left or Right on it.
// onSideStep(-1 | 1) is Left or Right inside a list (letter jumps, the Movies list work).
// Continue watching (the Continue watching work): getTiles returns the carousel's tiles while
// it shows (else []); A on a tile is onPlay(tile), X is onRemove(tile).
// Home actions (the Home actions work): getBarButtons returns the action bar's buttons
// while it shows (else []); A on one is onBarSelect(button), and Start (m)
// is onMenu(). Onboarding (the folder choice screens): Y (a) is onLookAgain().
export function createKeyboardController({
  onPlay, onQuit, onDetails, onRescan, getTab, onSwitchTab, onSideStep, getTiles, onRemove,
  getBarButtons, onBarSelect, onMenu, onLookAgain,
}) {
  let rows = [];
  let currentIndex = -1;
  let busy = false;
  let onTabs = false; // the focus is on the tab strip, not in the list
  let onCarousel = false; // the focus is on a Continue watching tile
  let tileIndex = 0; // the tile focused last, for Up from the tabs
  // The focus is on the action bar. onTabs and onCarousel keep saying where
  // it came from, so Down goes back there.
  let onBar = false;
  let barIndex = 0;
  let upDownScroll = false; // see setRows
  let wordsAboveFirst = false; // see setRows

  function tiles() {
    return getTiles ? getTiles() : [];
  }

  function barButtons() {
    return getBarButtons ? getBarButtons() : [];
  }

  // Focuses a button on the action bar (stopping at the ends). Since the Home polish
  // the bar isn't docked: its buttons sit at the top of the page, so the
  // page goes to the top. False when the bar isn't shown.
  function focusBar(index = barIndex) {
    const list = barButtons();
    if (list.length === 0) return false;
    onBar = true;
    barIndex = Math.max(0, Math.min(index, list.length - 1));
    list[barIndex].focus({ preventScroll: true });
    window.scrollTo(0, 0);
    return true;
  }

  // Down from the bar: back to the tile, tab or row it came from.
  function leaveBar() {
    onBar = false;
    refocus();
  }

  // Focuses a tile (stopping at the ends) with the top of the page in view,
  // and scrolls the row sideways to show it. False when there are none.
  function focusTile(index) {
    const list = tiles();
    if (list.length === 0) return false;
    onBar = false;
    onTabs = false;
    onCarousel = true;
    tileIndex = Math.max(0, Math.min(index, list.length - 1));
    const tile = list[tileIndex];
    tile.focus({ preventScroll: true });
    window.scrollTo(0, 0);
    tile.scrollIntoView({ block: "nearest", inline: "nearest" });
    return true;
  }

  function focusRow(index) {
    if (rows.length === 0) return;
    onBar = false;
    onTabs = false;
    onCarousel = false;
    currentIndex = Math.max(0, Math.min(index, rows.length - 1));
    const row = rows[currentIndex];
    // A row can change height when it takes or loses the focus (a long film
    // title shows in full, the Movies list work). Keep the new row where it was, so
    // the list doesn't jump, then make sure it is wholly on screen.
    const before = row.getBoundingClientRect().top;
    row.focus({ preventScroll: true });
    // The page's end, which holds the one focusable thing. Not
    // scrollIntoView: Firefox then keeps pulling the page back to the focused
    // element, so Up and Down couldn't scroll away from it.
    if (upDownScroll) {
      window.scrollTo(0, document.documentElement.scrollHeight);
      // With a second button under it (the Browse somewhere else work), the first may now start
      // above the window: back up just enough, keeping its focus ring in view.
      const above = row.getBoundingClientRect().top - marginAbove(row);
      if (above < 0) window.scrollBy(0, above);
      return;
    }
    const shift = row.getBoundingClientRect().top - before;
    if (shift) window.scrollBy(0, shift);
    row.scrollIntoView({ block: "nearest" });
    // A row that only just fits, with no room left for its margins, is placed
    // exactly; one taller than the room shows from its start, where its name is.
    if (wordsAboveFirst && !rowInView(row)) {
      const box = row.getBoundingClientRect();
      if (box.height > roomBottom()) window.scrollBy(0, box.top - marginAbove(row));
      else window.scrollBy(0, box.top < 0 ? box.top : box.bottom - roomBottom());
    }
  }

  // scrollPage: Up and Down scroll the page instead of moving the focus, for
  // a screen with one thing to focus and words to read around it (the No videos found screen).
  // readAboveFirst: words above the first row may not fit with it in a short
  // window (the first onboarding review fixes), so on that row Up scrolls up to them and Down comes back.
  function setRows(newRows, { scrollPage: scrolls = false, readAboveFirst = false } = {}) {
    rows = newRows;
    currentIndex = rows.length > 0 ? 0 : -1;
    upDownScroll = scrolls;
    wordsAboveFirst = readAboveFirst;
  }

  // Focuses the selected tab and shows the top of the page. False when the
  // tab strip isn't shown.
  function focusTabs() {
    const tab = getTab ? getTab() : null;
    if (!tab) return false;
    onBar = false;
    onTabs = true;
    onCarousel = false;
    tab.focus({ preventScroll: true });
    window.scrollTo(0, 0);
    return true;
  }

  function focusFirst() {
    focusRow(0);
  }

  function focusAt(index) {
    focusRow(index);
  }

  function refocus() {
    if (onBar && focusBar(barIndex)) return;
    if (onCarousel && focusTile(tileIndex)) return;
    if (onTabs && focusTabs()) return;
    focusRow(currentIndex);
  }

  // The row the list is on; null while the focus is on the bar, the tabs or
  // a tile.
  function currentRow() {
    return !onBar && !onTabs && !onCarousel && currentIndex >= 0 ? rows[currentIndex] : null;
  }

  // The tile's place in the carousel while one has the focus, else -1.
  function currentTileIndex() {
    return onCarousel && !onBar ? tileIndex : -1;
  }

  function isOnBar() {
    return onBar;
  }

  // A message on its own ("mpv not found", the responsive layout work) has nothing to focus.
  // Up and Down then scroll the page, so a message taller than a short
  // window can still be read to the end with the controller.
  function nothingToFocus() {
    return upDownScroll || (rows.length === 0 && tiles().length === 0 && !(getTab && getTab()));
  }

  // The room above the hint bar. Bottom padding: the page keeps that much clear.
  function roomBottom() {
    const padding = parseFloat(getComputedStyle(document.documentElement).scrollPaddingBottom) || 0;
    return window.innerHeight - padding;
  }

  // How far one press scrolls: never more than the room, with some of it left
  // on screen, so whole lines of words stay readable from one view to the next.
  function scrollStep() {
    return Math.min(window.innerHeight / 2, (roomBottom() * 3) / 4);
  }

  function scrollPage(step) {
    window.scrollBy(0, step * scrollStep());
  }

  // Wholly in the room above the hint bar; a row taller than the room, once it
  // starts on screen.
  function rowInView(row) {
    const box = row.getBoundingClientRect();
    if (box.top < -1) return false;
    return box.bottom <= roomBottom() + 1 || (box.height > roomBottom() && box.top < roomBottom());
  }

  // Brings the focused row back into view.
  function showRow(row) {
    focusRow(rows.indexOf(row));
  }

  // A screen that scrolls with Up and Down can have a second button under the
  // first (the Browse somewhere else work). Down scrolls until the focused button is in view, never
  // past it, so no words are skipped, and only then moves on; Up moves back,
  // and then scrolls.
  function hasNextButton() {
    return upDownScroll && currentIndex < rows.length - 1;
  }

  function stepToNextButton() {
    const row = rows[currentIndex];
    const room = row.getBoundingClientRect().top - marginAbove(row);
    const atEnd = window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 2;
    if (atEnd || room < 1) focusRow(currentIndex + 1);
    else window.scrollBy(0, Math.min(scrollStep(), room));
  }

  // Down on the first row while it is still below the room above the hint bar:
  // scrolls towards it, a step at a time so no words are skipped. False once
  // it is in view, and Down then moves on as usual.
  function scrollDownToFirstRow() {
    if (!wordsAboveFirst || currentIndex !== 0) return false;
    const row = rows[0];
    const box = row.getBoundingClientRect();
    // A row taller than the room is in view once it starts at the top.
    const needed = Math.min(box.bottom - roomBottom(), box.top - marginAbove(row));
    if (needed < 1) return false;
    window.scrollBy(0, Math.min(scrollStep(), needed));
    return true;
  }

  function previousButton() {
    return upDownScroll && currentIndex > 0;
  }

  function isBusy() {
    return busy;
  }

  function setBusy(value) {
    busy = value;
  }

  function handleKeydown(event) {
    if (pickerOpen()) {
      handlePickerKey(event);
      return;
    }
    if (isHeldRepeat(event)) {
      event.preventDefault();
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (busy) return;
      if (onBar) {
        leaveBar();
        return;
      }
      if (hasNextButton()) {
        stepToNextButton();
        return;
      }
      if (nothingToFocus()) {
        scrollPage(1);
        return;
      }
      // From the carousel, Down goes to the tabs.
      if (onCarousel) {
        focusTabs();
        return;
      }
      if (scrollDownToFirstRow()) return;
      // From the tabs, Down goes into the list, onto the row it was on.
      focusRow(onTabs ? currentIndex : currentIndex + 1);
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      if (busy || onBar) return;
      // Up from the top row of content (a tile, or the tabs without the
      // carousel) goes to the action bar.
      if (onCarousel) {
        focusBar(0);
        return;
      }
      if (previousButton()) {
        focusRow(currentIndex - 1);
        return;
      }
      if (nothingToFocus()) {
        scrollPage(-1);
        return;
      }
      // Up from the tabs goes to the tile focused last, if the carousel shows.
      if (onTabs) {
        if (!focusTile(tileIndex)) focusBar(0);
        return;
      }
      // At the page's top too: moving the focus to this row again would scroll
      // the words back out of view.
      if (wordsAboveFirst && currentIndex === 0) {
        scrollPage(-1);
        return;
      }
      // Up from the first row goes back to the tabs.
      if (currentIndex <= 0 && focusTabs()) return;
      focusRow(currentIndex - 1);
      return;
    }
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      if (busy) return;
      const step = event.key === "ArrowLeft" ? -1 : 1;
      // On the bar: the next button, stopping at the ends.
      if (onBar) focusBar(barIndex + step);
      // On the carousel: the next tile, stopping at the ends (no letter jumps).
      else if (onCarousel) focusTile(tileIndex + step);
      else if (onTabs && onSwitchTab) onSwitchTab(step);
      else if (!onTabs && currentIndex >= 0 && onSideStep) onSideStep(step);
      return;
    }
    if (PLAY_KEYS.has(event.key)) {
      event.preventDefault();
      if (busy) return;
      if (onBar) {
        const button = barButtons()[barIndex];
        if (button && onBarSelect) onBarSelect(button);
      } else if (onCarousel) {
        const tile = tiles()[tileIndex];
        if (tile) onPlay(tile);
      } else if (!onTabs && currentIndex >= 0 && rows[currentIndex]) {
        onPlay(rows[currentIndex]);
      }
      return;
    }
    if (REMOVE_KEYS.has(event.key)) {
      event.preventDefault();
      const tile = onCarousel && !onBar ? tiles()[tileIndex] : null;
      if (!busy && tile && onRemove) onRemove(tile);
      return;
    }
    if (QUIT_KEYS.has(event.key)) {
      event.preventDefault();
      onQuit();
      return;
    }
    if (MENU_KEYS.has(event.key)) {
      event.preventDefault();
      if (!busy && onMenu) onMenu();
      return;
    }
    if (LOOK_KEYS.has(event.key) && onLookAgain) {
      event.preventDefault();
      if (!busy) onLookAgain();
      return;
    }
    if (DETAILS_KEYS.has(event.key) && onDetails) {
      event.preventDefault();
      onDetails();
      return;
    }
    if (RESCAN_KEYS.has(event.key) && onRescan) {
      event.preventDefault();
      if (!busy) onRescan();
    }
  }

  // A click or tap focuses a row through the browser (the click-then-Enter fix). Follow it,
  // so Enter and A play the row that looks selected and the arrows carry on
  // from there. While busy (loading screen, "Playing…"), a press must not
  // move the focus at all, so the browser's default is cancelled.
  function handleMousedown(event) {
    if (busy) event.preventDefault();
  }

  function handleFocusin(event) {
    const button = barButtons().indexOf(event.target);
    if (button >= 0) {
      if (busy && !(onBar && button === barIndex)) refocus();
      else if (!busy) {
        onBar = true;
        barIndex = button;
      }
      return;
    }
    const tab = getTab ? getTab() : null;
    if (tab && event.target === tab) {
      if (busy && (onBar || !onTabs)) refocus();
      else {
        onBar = false;
        onTabs = true;
        onCarousel = false;
      }
      return;
    }
    const tile = tiles().indexOf(event.target);
    if (tile >= 0) {
      if (busy && (onBar || !(onCarousel && tile === tileIndex))) refocus();
      else if (!busy) {
        onBar = false;
        onTabs = false;
        onCarousel = true;
        tileIndex = tile;
      }
      return;
    }
    const index = rows.indexOf(event.target);
    if (index < 0) return;
    if (busy) {
      if (onBar || onTabs || onCarousel || index !== currentIndex) refocus();
      return;
    }
    onBar = false;
    onTabs = false;
    onCarousel = false;
    currentIndex = index;
  }

  window.addEventListener("keydown", handleKeydown);
  window.addEventListener("mousedown", handleMousedown, true);
  document.addEventListener("focusin", handleFocusin);

  return {
    setRows, rowInView, showRow, focusFirst, focusAt, focusTabs, focusTile, focusBar, isOnBar, refocus, currentRow, currentTileIndex,
    setBusy, isBusy,
  };
}

export function createMinimalQuitController({ onQuit }) {
  function handleKeydown(event) {
    if (isHeldRepeat(event)) {
      event.preventDefault();
      return;
    }
    if (QUIT_KEYS.has(event.key)) {
      event.preventDefault();
      onQuit();
    }
  }
  window.addEventListener("keydown", handleKeydown);
}
