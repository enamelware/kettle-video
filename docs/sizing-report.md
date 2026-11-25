<!--
SPDX-License-Identifier: GPL-3.0-or-later
Copyright (C) 2026 Mario Carabotta
-->

# Sizing report: Kettle Video next to Steam's Gaming Mode (the sizing spike)

**Question:** Kettle Video's interface looks smaller than Steam's in Gaming Mode. How much of that comes from Enamel's own sizes (the same on every device), and how much from how each screen scales the page (different per device)? And what should Enamel's new baseline be?

**Short answer:** almost all of it is Enamel's sizes. On the Steam Deck, Kettle Video and Steam draw at exactly the same scale, so the whole difference is Enamel being smaller than Steam: rows about 12% shorter, body text about 17% smaller, buttons about a quarter shorter. On the Nova, Steam draws itself about 4% bigger than on the Deck while Kettle Video stays the same, so about a fifth of the gap there comes from scaling and the rest, again, from Enamel's sizes.

## How it was measured

- **Captures:** taken by the designer with Steam + R1 in Gaming Mode, on 29 October 2026. On each device: Steam's Settings > System, the Library grid, the Quick Access menu (the Quick Settings page), and Kettle Video's Home with a row focused and with its Menu open. On the Nova, Steam's Power menu too, which gives a picker row to compare with Kettle Video's.
  - Deck: read in place from Steam's screenshots folder. Nothing moved, copied into the repo or deleted.
  - Nova: the designer posted them on this issue. They were downloaded to a temporary folder outside the repo, only to be measured.
- **Tools:** `djpeg` (already on the Deck) turns each capture into plain pixels, and a short Python script (standard library only, kept outside the repo) finds edges by colour: where a row's background starts and stops, where a bar begins. Text heights were measured by brightness: the tallest run of pixels brighter than the background in a word with capitals and tall letters but no letters that hang below the line (so, the height from the top of a tall letter to the baseline). Every number below is in capture pixels.
- **Capture size:** the Deck's captures are 1280 by 800 pixels, the Nova's 1280 by 960. Both apps are in the same captures, so the ratios between them don't depend on how the capture itself was scaled.
- **No titles:** the captures show film and game titles. None are in this report; elements are named by what they are.

## How each device scales the page

Kettle Video's sizes in the captures are exactly Enamel's tokens at 16 pixels per rem, on both devices: a list row 56 (3.5rem), a picker row 72 (4.5rem), the hint bar 60 (3.75rem), the Menu button 44 (the touch target), the gutter 36 (2.25rem). So on both devices Firefox draws one CSS pixel as one capture pixel: a device pixel ratio of 1 and no zoom.

The size readout (`"debug_size_readout": true`, `docs/device-setup.md` section 6) writes these numbers to the launch log at start, to confirm them directly. Firefox doesn't tell a page its zoom: it folds it into the device pixel ratio, so a ratio of 1 also means no zoom. The readout's line from a Gaming Mode start on the Deck is still to be collected (see the issue).

## Steam Deck

Steam and Kettle Video both draw at one CSS pixel per capture pixel here, so every difference below is Enamel's sizes.

| What | Steam | Kettle Video | Steam ÷ Kettle |
|---|---|---|---|
| List row height | 64 (Quick Settings rows; Settings menu rows 63) | 56 | 1.14 |
| Row with a control (Settings) | 96 | none of its own | – |
| Text height, a row's main text | 18 | 15 | 1.20 |
| Text height, caps labels in the hint bar | 13 | 10 | 1.30 |
| Button height | 60 | 44 | 1.36 |
| Hint bar height | 60 | 60 | 1.00 |
| Tile width | 200 (portrait cover, Library) | 256 (small landscape tile; large 448) | 0.78 |
| Side gutter | 48 (Library) and 35 (Settings) | 36 | 1.33 and 0.97 |

Kettle Video's picker rows (72, with text 18 high) aren't in the table: the Deck's captures have no Steam picker to set them against. On the Nova, Steam's Power menu rows are 75, the same within Steam's own scaling there.

## Nova

| What | Steam | Kettle Video | Steam ÷ Kettle |
|---|---|---|---|
| List row height | 66 (Quick Settings rows; Settings menu rows 66) | 56 | 1.18 |
| Row with a control (Settings) | 99 | none of its own | – |
| Picker row (Power menu) | 75 | 72 | 1.04 |
| Text height, a row's main text | 19 | 15 | 1.27 |
| Text height, caps labels in the hint bar | 13 | 10 | 1.30 |
| Button height | 63 | 44 | 1.43 |
| Hint bar height | 63 | 60 | 1.05 |
| Tile width | 172 (portrait cover, Library) | 256 (small landscape tile; large 448) | 0.67 |
| Side gutter | 48 (Library) and 35 (Settings) | 36 | 1.33 and 0.97 |

## Where the difference comes from

- **Kettle Video is identical on both devices**, to the pixel: same rows, bars, buttons, tiles and gutter. Nothing in it scales per device, which is what CLAUDE.md asks.
- **Steam is about 4% bigger on the Nova than on the Deck** for heights: rows 66 against 64, buttons and the hint bar 63 against 60, rows with a control 99 against 96, text 19 against 18. Its gutters don't change (48 and 35), and its Library covers get narrower (172 against 200) because Steam fits six columns instead of five: their width comes from the grid, not from scaling. Steam's rule isn't visible from two devices; it isn't simply the screen's height, which would have made it 20% bigger.
- **So, the split:**
  - **Enamel's sizes, the same on every device:** all of the difference on the Deck: rows ×1.14, text ×1.20 (×1.30 for caps), buttons ×1.36. This is the part to fix, in Enamel.
  - **Scaling, different per device:** none on the Deck; about ×1.04 on the Nova, which is roughly a fifth of the gap there (rows ×1.18 = ×1.14 from Enamel × ×1.03 from scaling; buttons ×1.43 = ×1.36 × ×1.05).

## Recommended reference

**Measuring point: 1280 by 800 CSS pixels, at 16 pixels per rem.** This is only a measuring point for Enamel's baseline: the size at which Steam's numbers below were taken and Enamel's base values are set. It is not a size the layout is built for, and nothing in the layout targets it. The numbers say to keep it: it is where Steam and Kettle Video both draw one to one.

**How the interface should scale to every other screen:** the way it already does, on any screen.

- Every size stays in rem, so it follows the browser's font size, and Enamel's text and gutters keep growing on wide pages as they do now (from 100rem wide, a fifth bigger by 160rem).
- A screen that the system scales up shows up as a bigger device pixel ratio, and Firefox applies it to the whole page by itself. The app doesn't read the screen's size to choose sizes (CLAUDE.md's hard rule), so Steam's extra 4% on the Nova isn't copied: it would need exactly that. If Armada ever offers a display scale that Firefox picks up, it reaches the page on its own.

## Steam's sizes as Enamel's new baseline

At the measuring point, from the Deck's captures (the Nova's for the picker row, taken back to the Deck's scale). Sizes are rounded up to a multiple of 4; text sizes are not rounded. Text sizes are worked out from the measured text heights against Enamel's own, since both fonts put the tall letters at about three quarters of the font size (Kettle Video's picker text, 24 pixels, is 18 high, the same as Steam's main text).

| What | Steam's size (new baseline) | Enamel now |
|---|---|---|
| List row, minimum height | 64 (4rem) | 56 (3.5rem, `--en-size-row`) |
| Row with a control, minimum height | 96 (6rem) | no separate size |
| Picker row, minimum height | 72 (4.5rem), unchanged | 72 (4.5rem) |
| Main text | about 24 (1.5rem) | 20 (1.25rem, `--en-text-body` at its base) |
| Caps labels | about 17 (1.0625rem) | 13 (0.8125rem, `--en-text-caps` at its base) |
| Button, minimum height | 60 (3.75rem) | 44 (the touch target, `--en-size-target`) |
| Hint bar, minimum height | 60 (3.75rem), unchanged | 60 (3.75rem, `--en-size-bar`) |
| Side gutter, grids and shelves | 48 (3rem) | 36 (2.25rem, `--en-space-gutter` at its base) |
| Side gutter, lists | 36 (2.25rem), unchanged | 36 (2.25rem) |
| Tile width, portrait cover | 200 (12.5rem) | no portrait tile; landscape tiles 256 and 448 are already wider than Steam's covers |
| Text inset, list row | 20 (1.25rem) | 18 (1.125rem, `--en-space-inset` at its base); Steam is within a pixel of it, rounding alone moves it |
| Text inset, picker row | 24 (1.5rem) | 21 (1.3125rem, `--en-c-picker-inset`); Steam's is the same, rounding alone moves it |
| Side padding, button | 36 (2.25rem), unchanged | 36 (2.25rem, `--en-c-button-padding`) |
| Side padding, tab | 28 (1.75rem) | 24 (1.5rem, `--en-c-tab-padding`); Steam is within a pixel of it, rounding alone moves it |
| Gap between list rows | 12 (0.75rem) | 12 (0.75rem, `--en-space-gap`); Kettle Video's list rows use 4 (`--en-space-tight`) |
| Gap between an icon and its text | 16 (1rem) | 4 (0.25rem, `--en-space-tight`) |
| Gap between hints | 28 (1.75rem), unchanged | 28 (1.75rem, `--en-c-hint-gap`) |
| Side menu item, minimum height | 72 (4.5rem) | 62 (3.875rem, `--en-c-menu-item-height`) |
| Side menu focus bar, width | 8 (0.5rem) | 4 (`--en-c-menu-bar`) |
| Side menu, width | 360 (22.5rem) | no width of its own |
| Side menu, icon from the screen edge | 40 (2.5rem) | no icon; text starts at the gutter, 36 |
| Tile width, landscape tile on a shelf | 452 (28.25rem) | 448 (28rem, `--en-c-tile-large-max`, the large tile's widest) |
| Gap between tiles | 20 (1.25rem) | 12 (0.75rem, `--en-space-gap`) |
| Tile height, portrait cover | 300 (18.75rem) | no portrait tile |
| Page title text | about 33 (2.0625rem) | 30 (1.875rem, `--en-text-title` at its base) |
| Section heading text | 24 (1.5rem), unchanged | 24 (1.5rem, `--en-text-heading` at its base) |
| Small text | about 18.7 (1.1667rem) | 15 (0.9375rem, `--en-text-small` at its base) |
| Row description text | about 18.7 (1.1667rem) | about 17 (`--en-c-text-detail`) |

The rows from "Text inset, list row" down come from the second pass (below), from the Deck's captures.

Changing Enamel's sizes is a later step, made in Enamel and then brought in with a "Bring in Enamel" issue. Nothing in Kettle Video changes because of this report.

## Second pass

The second sizing spike: the parts the first pass skipped. Same method, tools and rules as above; every number is in capture pixels.

- **Captures:** on the Deck, 9 new ones taken by the designer on 29 October 2026, read in place from Steam's screenshots folder: Home with its shelves, the main side menu (opened with the Steam button), the Settings pages Display, Controller, Keyboard and Customization (section headings, rows with a description, buttons), a drop-down picker and a confirm dialog. Kettle Video's side: its two Deck captures from the first pass (Home with a row focused, and with its Menu open).
- **Nova:** the 6 captures from the first pass, downloaded again to a temporary folder outside the repo, only to be measured: Settings > System (page title, section headings, rows with a description, a button), the Library (tabs and covers), Quick Settings, the Power menu (a picker), and Kettle Video's Home with its Menu open and closed. By the designer's choice no new Nova captures were taken, so what those 6 don't show is marked as not measurable on the Nova. Where the Nova shows a part on a different screen from the Deck, the Deck was measured again on the same screen as the Nova (Library tabs, Quick Settings), and the table says so.
- **Where text starts** is measured to the first lit pixel of the first letter, in both apps, so the letter's own side room counts the same on each side and cancels out in the comparison. Steam's padding is then Enamel's value plus the difference. A difference of one pixel is within what the captures can show (soft letter edges and image compression), so "the same within a pixel" means no real difference.
- **Text sizes** are worked out from text heights as in the first pass (tall letters are about three quarters of the font size). Each height is taken on a word with a capital or a tall letter and no letter hanging below the line.
- **Baseline** is Steam's size at the measuring point, rounded up to a multiple of 4; text is not rounded. Where Steam is the same as Enamel within a pixel, the rounding alone moves the baseline, and the table says so.

### Padding

| What | Deck | Nova | Steam ÷ Kettle Video | Baseline | Enamel 0.7.0 |
|---|---|---|---|---|---|
| Where text starts in a list row | 19 (first letter 20 in; Kettle Video's 19) | 18 (Settings > System: first letter 19 in, on a round letter like Kettle Video's) | 1.06 (Deck), 1.00 (Nova) | 20 | 18 |
| Where text starts in a picker row | 21 (first letter 22 in; Kettle Video's 22) | 22 (Power menu: first letter 24 in; Kettle Video's on the same letter, 23) | 1.00 (Deck), 1.05 (Nova) | 24 | 21 |
| Side padding inside a button | 35 (text 37 in from each side; Kettle Video's Menu button 38) | not measurable: the only Steam button in the Nova's captures is stretched to the width of the controls beside it, so the space at its sides isn't padding | 0.97 (Deck) | 36 | 36 |
| Side padding inside a tab | 25 (Home tabs: first letter 25 in; Kettle Video's 24); Library tabs: first letter 24 in, on a round letter | 26 (Library tabs: first letter 27 in, on a straight letter; Kettle Video's on a straight letter, 25) | 1.04 (Deck), 1.08 (Nova) | 28 | 24 |

All four are the same as Enamel within a pixel on the Deck: Steam's paddings don't grow the way its rows and text do. Button text is bigger in Steam (its buttons are taller), but the space at the sides isn't. On the Nova the picker and tab paddings are a pixel or two bigger, about Steam's 4%; the list row's isn't.

### Gaps

| What | Deck | Nova | Steam ÷ Kettle Video | Baseline | Enamel 0.7.0 |
|---|---|---|---|---|---|
| Between rows in a list | 9 (Settings rows); 0 between picker rows and between side menu items | 10 (Settings rows); 0 between picker rows in a group | 2.25 (Deck), 2.50 (Nova) (Kettle Video's list rows are 4 apart) | 12 | 12 (`--en-space-gap`) |
| Smallest gap: an icon and its text | 16 (icon to text in a Settings row); 20 in Quick Settings; 13 to 15 from a button sign to its label in the hint bar | 19 in Quick Settings; 15 to 17 from a button sign to its label in the hint bar (the Nova's Settings rows have no icons) | 1.25 (Deck), 1.33 (Nova) (hint bar sign to label: Steam 15 and 16, Kettle Video 12) | 16 | 4 (`--en-space-tight`) |
| Between hints in the hint bar | 28 (27 to 28 from one label to the next sign) | 30 (29 to 30) | 0.97 (Deck), 1.03 (Nova) (Kettle Video's 29) | 28 | 28 |

Steam puts nothing as close as 4 between an icon and its text in these captures; its tightest is 13 in the hint bar. Steam's gap between list rows, 9, rounds up to Enamel's 12, but Kettle Video's own list rows sit 4 apart.

### Side menu

Kettle Video has no side menu, so there is no Steam ÷ Kettle Video column.

| What | Deck | Nova | Baseline | Enamel 0.7.0 |
|---|---|---|---|---|
| Item height | 72 (items follow each other with no gap) | not measurable: no capture of the main side menu | 72 | 62 |
| Focus bar width | 7 (solid for 7, then fades over 2); 38 tall, centred in its item, with round ends | not measurable: no capture of the main side menu | 8 | 4, the item's full height when focused |
| Menu width | 360 | not measurable: no capture of the main side menu | 360 | no width of its own |
| Padding from the screen edge | the menu touches the edge; icons start 38 in, text 90 in (95 on the focused item, which moves right) | not measurable: no capture of the main side menu | 40 (icon), 92 (text) | text starts at the gutter, 36; no icon |

### Landscape tiles

| What | Deck | Nova | Steam ÷ Kettle Video | Baseline | Enamel 0.7.0 |
|---|---|---|---|---|---|
| Small landscape tile, width and height | not measurable: Steam's Home shows no small landscape tile, only portrait covers (200 by 300) on its first shelf | not measurable: Steam's Home shows only blurred, behind a menu | – | – | 160 to 256 wide (Kettle Video's: 256 by 144) |
| Large landscape tile, width | 450 (the "what's new" shelf) | not measurable: Steam's Home shows only blurred, behind a menu | 1.00 (Kettle Video's large tile: 448) | 452 | 192 to 448 |
| Large landscape tile, height | not measurable: the hint bar covers the shelf's lower part in the capture | not measurable: Steam's Home shows only blurred, behind a menu | – | – | Kettle Video's: 252 |
| Gap between tiles | 18 (both shelves) | not measurable on a Home shelf (blurred); the Library's covers are 30 apart, against 45 on the Deck, because the Library fits columns | 1.50 (Kettle Video's: 12) | 20 | 12 |
| Portrait cover on Home, width and height | 200 by 300 | not measurable: Steam's Home shows only blurred, behind a menu | – | 200 by 300 | no portrait tile |

**Fixed size or columns:** on the Deck the landscape tiles look fixed: 450 wide with 18 between them doesn't fit a whole number of tiles in the shelf (two and two thirds show). The Nova can't confirm it: its captures show Steam's Home only blurred. The Library, by contrast, clearly fits columns: five on the Deck, six on the Nova, with narrower covers and smaller gaps on the Nova (first pass). The wide first tile on Steam's first shelf (300 tall) isn't measured: its left edge is off the screen.

### Text

| What | Deck: height | Deck: font size | Nova | Steam ÷ Kettle Video | Baseline | Enamel 0.7.0 |
|---|---|---|---|---|---|---|
| Page title | 25 | about 33 | capitals 25 high, against 23 on the Deck: about 36 | – (Kettle Video shows no page title) | about 33 | 30 |
| Section heading | 18 | 24 | capitals 18 high, against 17 on the Deck: about 25 | 1.20 (Kettle Video's shelf heading, 15 high, is at body size) | 24 | 24 |
| Small or secondary text | 14 | about 18.7 | 14 high: about 18.7 | 1.27 (Kettle Video's tile captions: 11 high) | about 18.7 | 15 |
| A row's description | 14 | about 18.7 | 14 high: about 18.7 | – (Kettle Video shows no row description) | about 18.7 | about 17 |

Steam's section heading is already Enamel's 24. Its small text and row descriptions are the same size as each other, and both bigger than Enamel's: small text by about a quarter, descriptions by about a tenth. The Nova's page title and section headings are on a different Settings page from the Deck's, and their words have no letter taller than a capital, so the Nova is compared on the height of capitals: the Deck's are 23 in the page title and 17 in the section heading (the "A" of the Controller page's heading; the Deck column's 18 is that word's tallest letter).

### Nova against the Deck

- **Text and headings grow on the Nova,** as in the first pass: section headings by about 6% (capitals 18 against 17), the page title by about 9% (25 against 23). Small text and descriptions measure the same, 14, but one pixel is 7% at that height, so a 4% change can't show.
- **Paddings mostly don't:** the list row's is the same; the picker's and the tab's are one or two pixels bigger (about 5%).
- **Gaps barely do:** list rows 10 against 9, hints 30 against 28, a hint's sign to its label 15 to 17 against 13 to 15, and an icon to its text in Quick Settings 19 against 20, the same within a pixel.
- **So it fits the roughly 4% found in the first pass for heights,** while paddings and gaps stay within a pixel or two, like the gutters did. That is a finding about how Steam scales, not a fault in either app.

### Not measured

- **Small landscape tile:** Steam's Home shows none on the Deck, and only blurred on the Nova.
- **Large landscape tile height:** the hint bar covers the shelf's lower part in the Deck's capture; the Nova's Home is blurred.
- **On the Nova, the main side menu, every landscape tile and the gap between Home tiles:** no Nova capture shows them (the designer chose to use the first pass's Nova captures only).
- **On the Nova, the side padding inside a button:** its only Steam button is stretched to the width of the controls beside it.
