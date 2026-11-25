<!--
SPDX-License-Identifier: GPL-3.0-or-later
Copyright (C) 2026 Mario Carabotta
-->

# Spike: where videos live on each device and what mpv can read (the storage spike)

**Status: done on both devices** (Steam Deck 2026-10-08/09, Nova
2026-10-09), including card out / card back in. Only the optional USB drive
check was not done. The Nova results and the differences between the
devices are in "Retroid Pocket Nova" and "Differences between the devices"
below.

Looked at on the Steam Deck (SteamOS 3.9.2, x86, Desktop Mode, one SD card
in, no USB drive) and on the Retroid Pocket Nova (Armada, ARM, Desktop
Mode, one SD card in, no USB drive). Everything was read-only: nothing was written to the card
or any media folder, no sudo, nothing installed, no Flatpak permission
changed. The scripts are in `spikes/storage/` (Python standard library
only). In this report, card labels and the user name are placeholders
(`<card-1>`, `<user>`) and folder names are counts or invented names.

## Short answer (Steam Deck)

- **Where cards are:** an SD card appears at `/run/media/<user>/<card label>`
  (SteamOS also adds a shortcut `/run/media/<card label>` pointing there).
  Internal storage worth searching is the home folder, `/home/<user>`.
- **How to find them:** Python can read the system's list of mounted drives
  and, for each, what hardware it sits on. That tells an SD card from a USB
  drive or internal storage reliably, with no extra tools.
- **Which folders to suggest:** walk each place up to 6 levels deep, skip
  hidden, Steam, emulator and junk folders, and suggest the folder that
  *holds* the films or shows ("Films"), never each film's own folder. On the
  real card this finds exactly the two folders already in `settings.json`.
- **Speed:** a few milliseconds per place. No progress message is needed on
  the Deck.
- **mpv:** the Flatpak mpv (v0.41) can read the whole system read-only, so it
  plays from the SD card and from the home folder. Nothing the app can read
  is out of mpv's reach.
- **Card out / back in:** the card's folder disappears at once when the card
  is pulled and comes back at the same place, with the same name, about
  2.7 s after it goes in. A search running at that moment ends at once with
  "nothing found"; it never hangs or crashes.
- **Nothing found that blocks an onboarding that lists found folders**, on
  the Deck. Open points are below.

## Steam Deck table

| Place | How it is found | Display name | App can read | mpv can play |
|---|---|---|---|---|
| Home folder, `/home/<user>` (ext4) | the user's home folder | Internal storage | yes | yes (test clip copied there) |
| `/run/media/<user>/<card-1>` (ext4) | list of mounted drives, under `/run/media/`; hardware says SD | SD card | yes | yes (a real video from the card) |
| Second card or USB drive | same, hardware says USB | USB drive (or "SD card 2") | not tested: none plugged in | not tested |

Also present: two empty USB card-reader slots (size 0). They are not drives
and the script leaves them out.

## Question 1: where storage is

- **Listing drives with built-in tools only.** `/proc/self/mountinfo` lists
  every mounted drive and where it is mounted. Only mounts under
  `/run/media/`, `/media/` or `/mnt/` are offered (where Linux desktops put
  cards and USB drives); system mounts are ignored. Internal storage is
  offered as the home folder, not as the whole disk.
- **Telling them apart.** For each mounted drive, `/sys/dev/block/…` shows
  the hardware path. An SD card hangs off an MMC controller and reports type
  `SD`; built-in eMMC storage (some handhelds) also hangs off an MMC
  controller but reports `MMC`; a USB stick or reader has `usb` in its path;
  NVMe or SATA is internal. **The "removable" flag is useless:** the Deck's
  SD slot says it is *not* removable.
- **Display names:** "Internal storage", "SD card", "USB drive"; a second
  of the same kind gets a number ("USB drive 2"). The card's own label could
  be shown next to it, but it is user data and may be empty or meaningless.
- **The `/run/media/<card label>` shortcut** is a link, not a second mount,
  so the card is listed once.
- **Card out / back in** (2026-10-09, `card_watch.py`, which checks the card
  four times a second and searches it without the skip rule the whole time):
  - **Card pulled:** within a quarter of a second the folder
    `/run/media/<user>/<card-1>` and the `/run/media/<card-1>` shortcut are
    both gone. The card was pulled while mounted (pressing the card in
    ejects it physically, not through the system), which is how users will
    do it.
  - **A search while the card is pulled** ends at once with 0 videos and
    one unreadable folder. No hang, no error, no partial result kept. (The
    app's rescan already keeps the saved library in this case, the pulled card fix.)
  - **Card back in:** SteamOS's own card script first checks the card's
    file system (and repairs its journal, since the card was pulled while
    in use), then mounts it, about **2.7 s** after the card goes in. It
    comes back at the **same place with the same name**, the shortcut comes
    back, and the same videos are found.
  - **For about a quarter of a second before the card is ready**, its folder
    already exists but cannot be read (permission denied). A search or a
    library load must treat "exists but unreadable" under `/run/media/` as
    "card not ready yet", and look again a moment later, not as an error.
  - **First search after the card goes in: 0.41 s** (no skip rule, nothing
    in memory yet). See the timings below.

## Question 2: where to look on internal storage (proposed rule)

Search the **home folder only**, and inside every place never walk into:

- **hidden folders** (name starts with a dot). This alone skips Steam's own
  install (196 GB on this Deck, under a hidden folder), Flatpak app data and
  caches;
- **Steam folders** on any drive: `steamapps`, `SteamLibrary`, `Steam`,
  `compatdata`, `shadercache` (a card used for games has a Steam library on
  it);
- **emulator folders**: `Emulation`, `EmuDeck`, `ES-DE`, `RetroArch`, `roms`,
  `downloaded_media` (scraped video previews), `Applications`, `homebrew`
  (Decky plugins);
- **junk the scanner already ignores**: `Sample`/`Samples`, macOS `._` files,
  and `lost+found`.

Compared ignoring capitals. On this Deck the home folder holds no library
videos but does hold several hundred short videos in theme, plugin and app
folders; with the rule, none are found and only 79 folders are read instead
of 504. On the card, the rule skips its Steam library: 7 folders read instead
of 414, and 115 game videos never seen.

## Question 3: finding folders with videos (proposed rule)

- **How deep:** up to 6 levels below the place's top.
- **Which folder to suggest:** start from each top-level folder that has
  videos somewhere below. Go down while there is only one way down, but never
  into a single film's or show's own folder. A folder that holds two or more
  titles is a *collection* and is suggested ("Films", not "Films/Some
  Film"). If a folder holds two or more collections (`Media/Films`,
  `Media/TV`), each collection is suggested instead of the parent.
  Season-like names (`Season 1`, `S02`, `Specials`, `Disc 1`, `Part 2`) count
  as parts of one title, so a show's folder is never split into seasons.
- **Videos at the top of a card:** the place itself is suggested ("the whole
  card"), alongside any collection folders.
- **Clips are not libraries:** a folder whose videos are all under 20 MB
  (trailers, previews, game intros) is not suggested.
- Checked on invented layouts (`find_video_folders.py --selftest`, and
  `tests/test_storage_spike.py`): a tidy card, a nested `Media/` folder, loose
  videos at the top, a single long chain, one show with seasons, one film,
  Steam and hidden folders, clips only. All give the expected suggestions.
- **On the real card:** exactly two folders suggested, the Movies folder
  (4 videos) and the TV Shows folder (75 videos), the same two already set
  in `settings.json`.

### Timings (Steam Deck, three runs each)

| Place | Folders read | Run 1 | Run 2 | Run 3 |
|---|---|---|---|---|
| SD card, with the rule | 7 | 0.001 s | 0.001 s | 0.001 s |
| Home folder, with the rule | 79 | 0.003 s | 0.002 s | 0.002 s |
| SD card, no skip rule (for comparison) | 414 | 0.065 s | 0.063 s | 0.063 s |
| Home folder, no skip rule (for comparison) | 504 | 0.017 s | 0.016 s | 0.017 s |

All runs had the folder list already in memory (the card had just been read).
The first search right after the card went back in, with nothing in memory
and no skip rule (414 folders), took **0.41 s**: the realistic worst case on
the Deck for this card. With the skip rule it reads far fewer folders. Even
so, well under a second, so **no progress message is needed on the Deck**; a short
"Looking for videos…" is still worth designing for slower cards and the Nova.

## Question 4: what mpv can open

- **mpv on the Deck:** the Flatpak `io.mpv.Mpv`, v0.41.0, system install, no
  local overrides. No system mpv.
- **Its Flatpak permissions** (`flatpak info --show-permissions io.mpv.Mpv`):

  ```
  [Context]
  shared=ipc;network;
  sockets=pulseaudio;wayland;x11;
  devices=all;
  filesystems=xdg-run/pipewire-0:ro;xdg-pictures;/tmp;xdg-videos;host:ro;~/.var/app/io.mpv.Mpv/config/mpv/scripts:create;
  ```

  `host:ro` means it can read the whole system, including `/run/media`,
  `/media` and `/mnt`, but write only to `/tmp`, Pictures and Videos.
- **Test:** mpv, found exactly as the app finds it, decoded a few frames
  with no window, no sound and no saved position: a real video from the SD
  card (the smallest one in the suggested folders) and a 2-second test clip
  copied into the home folder (it holds no real videos). Both played. The
  clip and its folder were deleted afterwards.
- **Places the app can read but mpv cannot:** none on the Deck.

## Read-only check

`snapshot.py` fingerprinted the whole card (every file's and folder's path,
size and modified time) before and after all the runs above: 27,581 files,
425 folders, the same fingerprint both times. Nothing changed.

After card out / card in (2026-10-09) the counts were the same, but the
fingerprint was not. One entry differed: the card's **top folder**, whose
"last changed" time moved to the exact second the card was mounted again.
No file and no media folder changed (every entry newer than the day before
was listed: only the top folder). The system log shows why: SteamOS's card
script checks the file system and repairs its journal on every insertion
after the card was pulled while in use. That is the system, not Kettle: the
spike scripts only read. Worth knowing for later tests: comparing a card
before and after a re-insertion must ignore the top folder's own time.

`privacy_check.py` compared this report and the spike scripts against every
private word on the Deck (card label, user paths, and every film, show and
episode name in the suggested folders): clean.

## What would stop onboarding

**On the Deck nothing blocks it. On the Nova one thing needs a decision:**
a card that was taken out and put back is not opened by Armada, and there
is no file manager in Gaming Mode to open it from. Until the user opens it
(in Desktop Mode, or by restarting the Nova), Kettle cannot see the card at
all. Options for the onboarding and "SD card not available" design, not
decided here (it touches the open question "SD card removal and
re-insertion handling" in `CLAUDE.md`):

- show a plain message ("Your SD card isn't open. Restart the Nova, or open
  it in Desktop Mode") and look again when asked;
- have Kettle ask the system to open the card itself (the same request the
  file manager makes, no sudo). That changes system state and needs testing
  and a decision first;
- leave it to the installer or the device's own settings.

On the Nova, also: **"the card's folder exists" does not mean "the card is
there".** An empty folder stays behind after the card is pulled. Kettle
should check that the folder is an actual mounted drive (it is in the
system's list of mounts), not just that it exists, before calling a card
empty.

Points for the design, both devices:

- On the Deck, the card needs about 2.7 s after it goes in before it can be read, and
  for a short moment its folder is there but unreadable. Onboarding (and
  the library at launch) should show "SD card not ready" and look again,
  not "no videos found".
- The card label is not a good display name; use "SD card" / "USB drive".
- The home folder normally holds no library on a Deck (games and apps fill
  it with short videos), so expect "Internal storage" to find nothing unless
  the user copied films there.
- If the Flatpak mpv ever loses `host:ro` (a user override), cards stop
  playing; the existing "mpv could not play" message would show.

## Retroid Pocket Nova

Run with Claude Code on the Nova itself (Armada, ARM, Desktop Mode,
2026-10-09), with the same scripts and the same placeholders.

### Short answer (Nova)

- **Where cards are:** the same place as on the Deck,
  `/run/media/<user>/<card label>`. Armada does **not** add the
  `/run/media/<card label>` shortcut. Internal storage is the home folder,
  `/var/home/<user>` (Armada keeps home folders under `/var/home`).
- **Which folders to suggest:** the same rules find exactly the two folders
  in `settings.json` (Movies, 9 videos; TV Shows, 102 videos). The card also
  holds a ROM folder, which the skip rule leaves out.
- **Speed:** a few milliseconds with the skip rule; the first search after
  the card came back, with no skip rule, took **0.92 s**.
- **mpv:** the same Flatpak mpv as on the Deck (v0.41.0, ARM build, system
  install, no local overrides), same permissions (`host:ro`). It plays from
  the card and the home folder. No system mpv.
- **Card back in: Armada does not open (mount) it by itself.** The card is
  seen by the system but stays closed until the user opens it by hand
  (designer: "it's recognised but not automounted. i need to mount it
  manually"). Once opened it comes back at the same place with the same
  name. This is the main difference from the Deck, and it matters for
  onboarding and for the library (see "What would stop onboarding").

### Nova table

| Place | How it is found | Display name | App can read | mpv can play |
|---|---|---|---|---|
| Home folder, `/var/home/<user>` (btrfs, on UFS chips) | the user's home folder | Internal storage | yes | yes (test clip copied there) |
| `/run/media/<user>/<card-1>` (exFAT) | list of mounted drives, under `/run/media/`; hardware says SD | SD card | yes | yes (a real video from the card) |
| Second card or USB drive | same, hardware says USB | USB drive | not tested: none plugged in | not tested |

Also present, as on the Deck: two empty USB slots (size 0), left out.

### Question 1 (Nova): where storage is

- **Internal storage is UFS, formatted btrfs.** btrfs gives its mounts a
  placeholder device number, so the first version of `drives.py` could not
  find the hardware behind them and called internal storage "Other drive".
  Fixed in the spike: for a placeholder number it now looks up the named
  device instead, and it recognises the Nova's UFS controller. Internal
  storage and the SD card are now told apart correctly. (A btrfs-formatted
  card or USB drive would have been misnamed the same way.)
- **The SD card** sits on the Nova's MMC controller and reports type `SD`,
  exactly like the Deck's. The card is exFAT here (the Deck's is ext4).
- **Card out / back in** (`card_watch.py`, as on the Deck):
  - **Card pulled:** the card is gone at once. A search running at that
    moment ends with 0 videos: no hang, no error.
  - **An empty folder stays behind.** Unlike the Deck, the card's folder
    `/run/media/<user>/<card-1>` is not removed: an empty folder owned by
    the system stays where the card was. Anything that only checks "does
    the folder exist" sees an empty card, not a missing one.
  - **Card back in:** the system sees the card (its full size, its
    partition) but **does not open it**. It stayed closed until the designer
    opened it by hand, a little over two minutes later. It came back at the
    **same place with the same name**, despite the leftover folder, and the
    same 113 videos were found.
  - **First search after opening: 0.92 s** (no skip rule, nothing in
    memory, 432 folders).

### Question 2 and 3 (Nova): the rules

Same rules, same results:

- **Card:** with the rule, 17 folders read and two suggested, the Movies
  folder and the TV Shows folder (the two in `settings.json`). Without the
  rule, 409 folders (a ROM folder makes up most of them), same suggestions.
- **Home folder:** 84 folders read with the rule, one short video found, so
  nothing suggested; without the rule, 170 folders and 59 short videos
  (app and theme files), none suggested.
- `find_video_folders.py --selftest`: all invented layouts pass on the Nova.

### Timings (Nova, three runs each)

| Place | Folders read | Run 1 | Run 2 | Run 3 |
|---|---|---|---|---|
| SD card, with the rule | 17 | 0.003 s | 0.004 s | 0.003 s |
| Home folder, with the rule | 84 | 0.014 s | 0.004 s | 0.005 s |
| SD card, no skip rule (for comparison) | 409 | 0.034 s | 0.040 s | 0.045 s |
| Home folder, no skip rule (for comparison) | 170 | 0.010 s | 0.007 s | 0.006 s |

As on the Deck, these runs had the folder list in memory. The first search
right after the card was opened again, with nothing in memory and no skip
rule, took **0.92 s**: the realistic worst case on the Nova for this card,
about twice the Deck's 0.41 s. **No progress message is strictly needed**;
a short "Looking for videos…" is still cheap insurance for bigger cards.

### Question 4 (Nova): what mpv can open

- **mpv on the Nova:** the Flatpak `io.mpv.Mpv`, v0.41.0, ARM build,
  system install, from Flathub, no local overrides. No system mpv.
- **Its Flatpak permissions:** identical to the Deck's (the same
  `[Context]` block as above, including `host:ro`).
- **Test:** the same check as on the Deck. A real video from the card and
  a 2-second test clip copied into the home folder both played; the clip
  was deleted afterwards.
- **Places the app can read but mpv cannot:** none on the Nova.

### Read-only check (Nova)

`snapshot.py` before all the runs and after card out / card in: 2,093
files and 432 folders both times. As on the Deck, the fingerprint differed
in one entry only: the card's **top folder**, whose time was set to the
exact second the card was opened again (09:30:46, matching the watcher's
log). No file and no media folder changed. That is the system opening the
card, not Kettle.

`privacy_check.py` compared this report and the spike scripts against every
private word on the Nova (user paths and every film, show and episode name
in the suggested folders): clean. The card's own label is the device's name,
which the report uses throughout, so it was checked separately: it appears
only as the device name, never as part of a path.

## Differences between the devices

| | Steam Deck | Nova |
|---|---|---|
| Card place | `/run/media/<user>/<label>` | same |
| `/run/media/<label>` shortcut | yes | no |
| Home folder | `/home/<user>` | `/var/home/<user>` |
| Internal storage | NVMe, ext4 | UFS, btrfs (needed a fix in the spike) |
| Card file system (these cards) | ext4 | exFAT |
| Card pulled | folder removed | **empty folder left behind** |
| Card back in | opened by itself, about 2.7 s | **not opened; the user opens it by hand** |
| First search after card back | 0.41 s | 0.92 s |
| mpv | Flatpak v0.41.0, `host:ro` | same (ARM build) |
| Suggested folders on the real card | Movies, TV Shows | same |

## Still to do

- **Optional, not done:** a USB drive with a video, to confirm "USB drive"
  detection on either device (none was plugged in).

## How to run the scripts

From the project folder (all read-only; `--real` shows real names on screen
only, never paste that output):

```
python3 spikes/storage/drives.py
python3 spikes/storage/find_video_folders.py <place> --runs 3
python3 spikes/storage/find_video_folders.py --selftest
python3 spikes/storage/mpv_check.py
python3 spikes/storage/card_watch.py
python3 spikes/storage/snapshot.py <place>
python3 spikes/storage/privacy_check.py docs/spikes/storage.md [--allow <card label>]
```
