<!--
SPDX-License-Identifier: GPL-3.0-or-later
Copyright (C) 2026 Mario Carabotta
-->

# Spike: can the controller layout be set up automatically? (the controller layout spike)

Looked at on 2026-10-07 on the Steam Deck (Desktop Mode, SteamOS 3.8.16,
build 20260716.1, x86). Read-only, as the designer agreed on the issue: only
Steam's controller-layout folder and the non-Steam shortcuts list were
opened. Nothing in Steam, the system or the app was changed. The Steam
client's own version number was not read, because it lives outside the two
folders the designer allowed; the layout files say "version 3" for their own
format. Valve changes these internals without notice, so every finding below
is dated to this day.

Other versions seen: Firefox Flatpak 153.0.3, mpv Flatpak (Flathub
`io.mpv.Mpv`) 0.41.0.

## Short answer

**Yes, partly. An installer could write Kettle's layout straight into
Steam's files, but only while Steam is closed, and only for controller types
it knows about.** It is the only option that keeps the current design (keys
from Steam Input) and also works while a film plays. Reading the gamepad in
the browser instead would not help during playback, because the Flathub mpv
cannot read a gamepad at all.

**Recommendation:** keep the hand-made layout as the documented way for
v0.1, and plan the installer (already on the roadmap) to also place a Kettle
layout for the Steam Deck and the Nova, with a backup and a clear "close
Steam first" step. Do not switch to gamepad input. Details per option below.

## What was found on this Deck

### 1. Where Steam keeps a non-Steam game's layout, and how its ID is made

- **Layouts are filed by the shortcut's name, not its ID.** Steam keeps one
  folder per game in its controller-layout folder for this account
  (`~/.local/share/Steam/steamapps/common/Steam Controller Configs/<account>/config/`).
  For a non-Steam shortcut the folder is the shortcut's name in lower case
  with punctuation removed: the Deck's shortcut is called `launch.sh`, so its
  layout is in the folder `launchsh`; the Nova's is called "Media Player", so
  its layout is in `media player`.
- Inside, there is one file per controller type, for example
  `controller_neptune.vdf` (the Steam Deck's own controls),
  `controller_steamos_handheld.vdf` and `controller_xboxone.vdf`.
- Next to the folders, one small list per controller type
  (`configset_controller_<type>.vdf`) says which layout each game uses. For
  Kettle each entry just says "use the automatically saved layout"
  (`"media player" { "autosave" "1" }`).
- **The layouts travel between devices through Steam Cloud.** The two
  "media player" files on this Deck were made on the Nova (their saved path
  starts with `/var/home/<user>/`, the Nova's home folder). Because the Nova saved them under other
  controller types, they don't clash with the Deck's `launchsh` layout.
- **The game ID:** the shortcuts list holds 115 non-Steam shortcuts. For 95
  of them (the ones added by an emulator tool) the ID follows the well-known
  recipe (a checksum of the program path plus the name). Kettle's own entry,
  added through Steam's "Add a Non-Steam Game", does **not** follow it
  (stored ID 3306155764; the recipe gives 2977849140). So an installer cannot
  reliably predict the ID, but it does not need to: the layout is found by
  name.
- **Could an installer provide a layout file?** Yes, in principle: write a
  layout file into the folder named after the shortcut, and add the matching
  line to each `configset_controller_<type>.vdf`. The open tool Steam ROM
  Manager does exactly this for emulator shortcuts (it keys by lower-cased
  title and writes one list per controller type, making backups first;
  source below). Steam rewrites these lists while it runs, so the files must
  be changed while Steam is closed, or Steam may overwrite them.
- **The Deck's layout today** only changes six buttons from Steam's default:
  D-pad to the four arrow keys, A to Space, B to Q. Everything else is
  Steam's default.

### 2. No layout set

- **What Steam gives a new non-Steam game:** a copy of the template
  "Gamepad With Joystick Trackpad" (Steam Deck controls) or "Gamepad"
  (Xbox-style controllers). Every button is a gamepad button; there are no
  keys. Seen in the layout files, which name their starting point as
  `default://<game name>`.
- **The browser:** Steam always presents the controller to the game as a
  virtual "Microsoft X-Box 360 pad" (seen in the system's device list). The
  Firefox Flatpak has access to all devices (`devices=all`), so Firefox's
  Gamepad API could see that pad. But Kettle only listens for keys, so with
  no layout the list does not move. (Not tried in Gaming Mode; see "To try
  on the device".)
- **mpv:** **the Flathub mpv 0.41.0 cannot read a gamepad.** Its option list
  has no gamepad option at all (`--input-gamepad` exists only when mpv is
  built with SDL2 gamepad support). So with no layout, playback cannot be
  paused or stopped from the controller. A system mpv might have the option,
  but none is installed here to check, and Armada uses the Flatpak.

### 3. The Nova (all to confirm on the Nova)

- The Nova's saved layouts show it reaches Steam as
  `controller_steamos_handheld` (a generic SteamOS handheld type), and once
  as `controller_xboxone`, probably from switching Armada's emulated
  controller type. Each emulated type (Steam Deck, Xbox 360, DualSense) gets
  **its own layout file**, which is why the layout has to be set again after
  switching: Steam does not copy a layout across controller types.
  To confirm on the Nova: which type name each Armada setting gives.
- **Side finding:** on the Nova's handheld layout, **A is bound to Enter, not
  Space** (the Xbox-type one uses Space). Enter plays a row in Kettle's list,
  but in mpv Enter means "next file", so A would not pause during playback.
  To confirm on the Nova.
- An installer would need one file per type: neptune (Deck),
  steamos_handheld, xbox360, xboxone and ps5 (DualSense).

### 4. What would change in Kettle with gamepad input

- The UI would need a small new module that polls the Gamepad API about 60
  times a second and turns buttons into the same actions as the keys (move,
  play, back). Small: one file, plus tests, plus a decision because the design
  rules say "No Gamepad API".
- It would only cover the list. During playback, mpv still needs keys (the
  Flathub mpv has no gamepad input), so a Steam layout would still be
  needed. Kettle cannot add gamepad input to mpv without building its own mpv,
  which the rules rule out.
- Desktop Mode and Gaming Mode would then behave differently (Steam's
  desktop layout already sends arrow keys), adding another path to test.

### 5. How fragile each option is when Steam updates

- **Installer writes the layout:** depends on undocumented Valve file
  formats and folder names. They have been stable for years (Steam ROM
  Manager relies on them), but could change without notice. If they do, the
  worst case is that the layout is ignored and the user sets it by hand as
  today; nothing breaks in Kettle.
- **Hand-made layout (today):** unaffected by format changes; only the menu
  wording may move.
- **Gamepad API:** independent of Steam's files, but depends on how Steam
  presents its virtual pad, and doesn't solve playback.

## Options

| Option | Needs | Reliability | Work | Verdict |
|---|---|---|---|---|
| A. Keep the hand-made layout (today) | The steps in `docs/device-setup.md`, once per device and controller type (Steam Cloud carries it to other devices on the same account when the type matches) | High | None | Keep as the fallback, always documented |
| B. Installer writes Kettle's layout | Steam closed during install; the shortcut's name known (the installer creates it); one layout file per controller type; backups of Steam's lists; editing files outside the project, which needs the designer's approval | Medium: undocumented formats, Steam may overwrite while running | Medium: part of the planned installer, plus tests on both devices | **Recommended**, as part of the installer |
| C. Gamepad API in the browser | A new UI module; a decision against the "No Gamepad API" rule | Low as a whole: the list works, playback does not | Small for the list, impossible for mpv with the Flathub build | Not recommended |
| D. Ship a layout file the user imports | A layout file in the project the user picks in Steam | Unclear: Steam's import of a personal file for a non-Steam game was not confirmed | Small | Only if B proves too fragile; to research |

## To try on the device

Only if the designer wants to confirm point 2 by eye, in Gaming Mode: open
Kettle's controller settings, choose a different layout so that the default
"Gamepad" one is in use (or make a second Kettle shortcut that has no layout),
open Kettle and press the D-pad and A. Expected: the highlight does not move
and nothing plays. Then set the layout back.

## Sources

- This Deck's Steam controller-layout folder and shortcuts list, read on
  2026-10-07 (read-only).
- `flatpak info --show-permissions org.mozilla.firefox`, and
  `flatpak run io.mpv.Mpv --list-options` (no gamepad option), 2026-10-07.
- Steam ROM Manager, controller layout code:
  <https://github.com/SteamGridDB/steam-rom-manager/blob/master/src/lib/controller-manager.ts>
- mpv default key list (Enter is "next file", Space is pause):
  <https://github.com/mpv-player/mpv/blob/master/etc/input.conf>
- mpv `--input-gamepad` (SDL2 builds only):
  <https://mpv.io/manual/stable/#options-input-gamepad>
- Gamepad API: <https://developer.mozilla.org/en-US/docs/Web/API/Gamepad_API>
