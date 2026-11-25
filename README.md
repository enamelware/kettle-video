# Kettle Video

A lightweight browser for local movies and TV shows, built as a thin layer over mpv, for handheld Linux (Steam Deck / SteamOS and Retroid Pocket Nova / Armada). See `CLAUDE.md` for the full project brief and `docs/spec.md` for the current milestone's exact scope.

Kettle Video is built with Claude Code from a designer's specs; [How this repo is built](docs/how-this-repo-is-built.md) explains the workflow, the checks and where decisions are recorded. Developing it on another machine: see `docs/dev-environment.md`, "On another machine".

## Requirements

- Python 3.10+. No pip packages: the backend uses the standard library plus a few pure-Python libraries bundled in `vendor/` (see [Third-party code](#third-party-code)). *Confirmed on the Steam Deck (Python 3.13) and the Nova (Python 3.14).*
- Firefox, either a system install or the Flatpak (`org.mozilla.firefox`) — auto-detected by `launch.sh`.
- **mpv — not bundled.** Detected in this order: a system `mpv` on PATH, then the Flatpak (`io.mpv.Mpv`). If neither is found, the app shows an on-screen message with install instructions (the Bazaar app store, or `flatpak install flathub io.mpv.Mpv`) and waits for you to press `q` to exit. On the first launch the same screen also has a **Look again** button, so once you've installed mpv you can carry on without restarting the app.

## Setup

Setting up a new device, step by step (tools, getting the code, adding to Steam, controller layout, troubleshooting): see [`docs/device-setup.md`](docs/device-setup.md). The short version:

Run the app: on first launch it asks for your Movies and TV Shows folders and saves them in `settings.json`, creating the file if there is none. To change them later, open the menu (the **Menu** button at the top, or Start) and choose **Settings** (see [Settings](#settings)). To set things by hand instead:

```
cp settings.example.json settings.json
```

Edit `settings.json` and fill in your real `movies_path` and `tv_path` (with both left empty, the app asks at launch). Leave `mpv_command` as `"auto"` unless you need to point at a specific mpv binary. `mpv_args` is an optional list of extra flags passed straight to mpv, e.g. `["--hwdec=auto"]`, for testing decode settings without editing code — leave it as `[]` normally. `resume` (`true` by default) controls whether films continue where you stopped them; see [Resume](#resume). `keep_awake` (`true` by default) keeps the device awake while a film is open; see [Watching movies](#watching-movies).

## Running

```
./launch.sh
```

This starts the backend, opens Firefox in kiosk mode pointed at it, and closes everything down again when you choose **Quit** in the menu (`q` or B opens it with Quit chosen; press Enter or A) (or when either the backend or Firefox is closed by any other means — whichever goes first takes the other down with it).

For day-to-day development without the kiosk wrapper, see `docs/dev-environment.md`.

## Installing

Kettle Video installs into your home folder with one command in Desktop Mode. It needs no password, never uses `sudo` and never changes the system or Steam's own files.

1. From the release, download three files into the same folder (for example Downloads): `install.sh`, `kettle-video-<version>.tar.gz` and `kettle-video-<version>.tar.gz.sha256`. (Until the repository is public, the developer makes them with `tools/release.py`.)
2. Open a terminal (Konsole) in that folder and run:

   ```
   bash install.sh
   ```

   It checks the archive against its checksum first (if they don't match, nothing is installed), puts the app files in place, adds **Kettle Video** to the app menu with its icon (unless that entry is already there and opens something else, such as a development copy: then it leaves it alone and says so, see [Adding a development copy to Steam](#adding-a-development-copy-to-steam)), and checks for mpv. If mpv is missing it says why it's needed, shows the one Flathub command (`flatpak install flathub io.mpv.Mpv`) and asks before running it. Say no and the install still finishes; the app then opens on its "mpv not found" screen until mpv is installed. If the Flathub command asks for a password you don't have, or can't find flathub, install mpv for your user only: `flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo`, then `flatpak install --user flathub io.mpv.Mpv`.
3. Add it to Steam: open the app menu, find **Kettle Video** (under Multimedia), right-click it and choose **Add to Steam**. This works on the Steam Deck and on the Nova (where Steam's own Browse button doesn't).
4. In Gaming Mode, set the controller layout for the new shortcut (Library, Kettle Video, the controller icon). Steam keeps a layout for each shortcut, so a new shortcut needs it again. The buttons send these keys: D-pad = arrows, A = Space, B = q, X = Backspace, Y = a, L1 = j, R1 = l, Start = m, and the left stick left and right = arrows; the full table and the steps are in [`docs/device-setup.md`](docs/device-setup.md), "Controller layout".

### Updating

**From inside the app:** Settings › About › Check for updates. When a newer version is out, choose **Update and restart** and say yes: Kettle Video downloads it (B cancels while it downloads), installs it and restarts by itself, without leaving Gaming Mode. Your library, settings, resume positions and Continue watching stay as they are. This is the only time it goes online, and only because you chose it; it never updates by itself.

**Or run the installer again**, which always works, also when Update and restart isn't offered: put the newer release's `install.sh`, archive and `.sha256` file in one folder and run `bash install.sh` there. Both ways use the same steps:

- It finds the installed copy, prints the version you have and the one in the archive, and replaces only the app files. Your library, settings, resume positions, Continue watching and logs are never touched.
- The archive is checked against its checksum before anything changes.
- An older archive than the version you have gets a warning and a question first; anything but yes changes nothing.
- The version you have is kept until the new one has **started cleanly**: its server starts, its page and every file the page needs load, and it answers. If that or any install step fails, the previous version is put back and the installer says so. Nothing to do on your side: Kettle Video opens as before.
- If the device loses power during an update, Kettle Video is either the old version or the new one, never a mix; the next run of the installer tidies up what was left.

**Where everything lives** in an installed copy (Linux's standard places; `XDG_DATA_HOME`, `XDG_CONFIG_HOME` and `XDG_STATE_HOME` move them if you have set them):

| What | Where |
|---|---|
| The app files (replaced by an update) | `~/.local/share/kettle-video/app`, a shortcut to the current version's folder in `~/.local/share/kettle-video/versions` |
| Your saved library | `~/.local/share/kettle-video/data` |
| Settings | `~/.config/kettle-video/settings.json` (made on the first launch) |
| Logs (attach them to a GitHub issue) | `~/.local/state/kettle-video/logs` |
| The app menu entry | `~/.local/share/applications/kettle-video.desktop` (a development copy's is `kettle-video-dev.desktop`) |
| The app window's Firefox profile (rebuilt at every launch) | `~/.mozilla/kettle-video-profile`, or `~/.var/app/org.mozilla.firefox/data/kettle-video-profile` with Flatpak Firefox |

A development copy (this git folder, as on the Deck and the Nova) keeps `settings.json`, `data/` and `logs/` in its own folder, as before; the rest of this README describes that copy. An installed copy is told apart by a small mark file the installer leaves in its app folder.

### Uninstalling

In Desktop Mode, open a terminal (Konsole) and run:

```
bash ~/.local/share/kettle-video/app/installer/uninstall.sh
```

It first lists what it will remove and what it keeps, then asks before doing anything.

- It removes the app files, **Kettle Video** in the app menu and the app window's own Firefox profile (`kettle-video-profile`, which holds nothing personal). A menu entry that doesn't open the installed copy, such as a development copy's, is left as it is.
- It **keeps your data**: your saved library and Continue watching, your settings and the logs. Install Kettle Video again later and it finds them. It asks whether to delete them too, and if you say yes, asks once more to confirm, because that can't be undone.
- It never touches your movies and TV shows, mpv (it stays installed, with its own resume positions) or Steam's files.
- If anything looks unexpected (Kettle Video isn't installed there, a folder isn't one the installer made, a place outside your home folder, or Kettle Video is still open), it stops and says why, with nothing removed.
- One step is yours: remove Kettle Video from Steam by hand. In Desktop Mode, right-click it in your Steam Library and choose **Manage**, then **Remove non-Steam game from your library**.

## Adding a development copy to Steam

On the Steam Deck, Steam's own "Browse" button (**My Library → Add a Non-Steam Game → Browse**) works fine — just point it at `launch.sh`.

On the Nova, that same "Browse" button doesn't work, so instead:

```
./install-shortcut.sh
```

This writes a `kettle-video-dev.desktop` entry to `~/.local/share/applications/`, named **Kettle Video (dev)**. Restart Steam (or just reopen the dialog), go to **My Library → Add a Non-Steam Game**, and "Kettle Video (dev)" will already be listed — no Browse needed.

**A development copy and an installed copy on one device** each have their own app menu entry: **Kettle Video (dev)** (`kettle-video-dev.desktop`) opens the development copy and **Kettle Video** (`kettle-video.desktop`) the installed one. Neither script changes or removes the other's entry, and Steam shortcuts you already made keep working. Earlier versions of `install-shortcut.sh` wrote `kettle-video.desktop` themselves; running it again moves that entry to its own name (only if it opens this copy). Until then, the installer leaves that entry as it is, says so and doesn't add its own (run `install-shortcut.sh` again, then the installer); the uninstaller leaves it as it is too. `install-shortcut.sh` refuses to run in an installed copy, which already has its entry.

## Testing as a brand-new user

For testing only: two launch options open Kettle Video as a new user would see it, without touching your real setup. Both go in a Steam shortcut's **Launch Options**; nothing else needs changing.

- `KETTLE_FRESH_START=1 %command%`: **fresh start**. The app starts as it does for someone new: it asks for your Movies and TV Shows folders, whatever `settings.json` says, then opens Home with "No library yet." It starts with a new, empty data folder in a temporary place, and the folders you choose are kept there too, for that session only: `settings.json` is only read, for your other settings, and never changed. Your saved library, your Continue watching row and mpv's resume positions are neither read nor changed: mpv gets its own empty resume folder for the session. A "FRESH START" marker shows in the bottom-left corner of every screen. When the app quits, the temporary folder is deleted, so the next fresh start asks again; if it's left behind (after Steam's "Exit game" or a crash), the next fresh start deletes it. The search for folders reads your real folders, and only reads them, as always.
- `KETTLE_PRETEND_NO_MPV=1 %command%`: the app behaves as if mpv were not installed, to see the "mpv not found" screen. Nothing is uninstalled.
- Both together: `KETTLE_FRESH_START=1 KETTLE_PRETEND_NO_MPV=1 %command%`.

Only one copy of the app opens at a time, so close the normal one before starting the fresh-start one (and the other way round).

**A second Steam shortcut, "Kettle Video (fresh start)"**, in Desktop Mode (the same steps on the Steam Deck and the Nova; they never need the Browse button, which doesn't work on the Nova):

1. Open your existing **Kettle Video** shortcut's **Properties** (right-click it in My Library, or the cog, then Properties) and copy its **Target** and **Start In** somewhere, or keep the window open.
2. **Games → Add a Non-Steam Game to My Library**. Tick **Kettle Video** (on the Nova a development copy is listed as **Kettle Video (dev)**, thanks to `install-shortcut.sh`, above) and choose **Add Selected Programs**. If Kettle Video isn't offered a second time, tick any program in the list instead: the next step points the shortcut at Kettle Video.
3. Open the new shortcut's **Properties**: set its name to **Kettle Video (fresh start)**, paste the same **Target** and **Start In** as the first one, and set **Launch Options** to `KETTLE_FRESH_START=1 %command%`.
4. Give it the same controller layout as the first one: `docs/device-setup.md`, "Controller layout", says how to save the first one's layout as a template and reuse it.

To test the "mpv not found" screen, change that shortcut's Launch Options to `KETTLE_FRESH_START=1 KETTLE_PRETEND_NO_MPV=1 %command%` (or make a third shortcut the same way). Launching the normal Kettle Video shortcut afterwards shows your library, resume positions and Continue watching exactly as before.

## Resume

When you close a video and play the same file again, it continues 5 seconds before where you stopped, so you can pick up the thread. This is mpv's own feature: Kettle switches it on, and mpv saves and restores the positions. A small mpv script that ships with Kettle (`backend/mpv_scripts/resume_rewind.lua`) moves the start back by those 5 seconds; if you stopped in the first 5 seconds, it starts from the beginning.

**What saves the position** (checked on the Nova with the Flatpak mpv 0.41):

- Closing the video with `q` (the controller's B), Esc, or the window's close button: saved.
- Playing to the very end: nothing is saved, so the next time starts from the beginning.
- The player being told to stop from outside (for example Steam closing the app): saved with a normal mpv install; **not saved with the Flatpak**, because the Flatpak wrapper doesn't pass the stop message on to mpv.
- The player being force-closed: never saved.

**Where positions are kept:** in mpv's own folder, one small file per video (plus small "redirect" files for its parent folders). Nothing is written next to your media.

- Flatpak mpv: `~/.var/app/io.mpv.Mpv/.local/state/mpv/watch_later/` (confirmed on the Nova).
- Normal mpv install: `~/.local/state/mpv/watch_later/` (mpv's default; not checked on a device yet).

**To clear them**, delete the files in that folder. Every video then starts from the beginning.

**To turn resume off**, set `"resume": false` in `settings.json`. Films then always start from the beginning, and no new positions are saved. A `settings.json` without the `resume` line behaves as `true`.

**Limits:**

- Positions follow the file's full path. If the SD card is mounted under a different path, or a file is moved or renamed, it starts from the beginning.
- mpv also remembers the audio and subtitle track you chose for that file.
- There is no "start from the beginning" button yet.
- Every resume steps back 5 seconds, so opening and closing a film without watching moves its saved spot 5 seconds earlier each time.
- A start position you set yourself (`--start` in `mpv_args` or in mpv's own config) is used as it is, without stepping back.
- If you add `--save-position-on-quit` or `--resume-playback` (or their `--no-` forms) to `mpv_args`, your setting wins over the `resume` setting.

## Continue watching

Whatever you're partway through sits at the top of the list under **Continue watching**: one tile per film or show, showing the frame where you stopped, newest first, at most 6. Press A on a tile to resume. Press X to take a tile away; the film still resumes from the list, and it comes back the next time you play it and stop. A film shows up once you've stopped it at least a minute in, and leaves once you've watched 95% of it or played it to the end.

The controller's **X** button sends **Backspace**: add it to your controller layout (see `docs/device-setup.md`). During a film, X steps through the subtitles instead (see "Playback controls").

**About the pictures:** each tile's picture is a frame from your own video, saved when you stop it with B. The pictures stay on the device, in `data/thumbnails/` inside the app folder (or under your `data_dir`), never next to your media, never in the project's files on GitHub (that folder is excluded), and never in any log. One picture per tile, about 480 pixels wide; it's deleted when the film finishes, when you remove the tile, when it drops off the end of the row, or when the film is removed from the library. Deleting the folder is safe: the tiles then show the title on a plain surface until you next stop each film.

With `"resume": false` there is no Continue watching row. Closing the player in another way (the window's close button, Steam closing the app) saves no picture.

## Watching movies

While a film is open, Kettle asks the system to keep the device awake: the screen shouldn't dim or turn off by itself. It uses the system's own "stay awake" lock (`systemd-inhibit`), labelled **Kettle / Playing a video**, which asks only for "don't go idle". It never stops a sleep you ask for: the power button always puts the device to sleep, and on waking the film is at the same point. The lock is tied to the player: it ends when you quit, when the player crashes, or when the app is closed. mpv's own "stop the screensaver" option stays on as well.

In Gaming Mode, Steam runs its own dim and screen-off timers, which don't look at that lock. So while a film plays, Kettle's screen also asks the browser to keep the screen on (the standard "Screen Wake Lock"). Steam has delayed its timers for that kind of request since its 13 October 2026 update. The request ends when the film closes, however it closes. Each change is noted in the launch log (`screen wake lock: held`, `released`, and so on).

**If the screen still dims or the device still sleeps in Gaming Mode,** Steam's own timers may be overriding both. Turn them off or make them longer: press the Steam button, then **Settings → Power** (on older SteamOS versions some of these are under **Settings → Display**), and change **Dim screen after** and **Sleep after**, for battery and for plugged in.

**To turn it off**, set `"keep_awake": false` in `settings.json`; that turns off both the lock and the browser's request. A `settings.json` without the `keep_awake` line behaves as `true`.

**Limits:**

- The device stays awake for as long as the player is open, **including while a film is paused**. A paused film left overnight will drain the battery. Staying awake only while a film is actually playing needs a live link to mpv, planned for later.
- If the lock tool is missing or the system refuses the lock (possible on some Armada devices), the film plays normally without it and the mpv log says so.
- For now, each mpv log also lists the system's stay-awake locks a few seconds after the film starts and then every minute (lines starting `kettle-video: locks:`), to check afterwards that the lock was held. This will be removed once it's confirmed on both devices.

## Playback controls

While a film plays, mpv's own control bar is off and only these buttons do something (your controller layout must send the keys shown; see `docs/device-setup.md`):

- **A** (Space): play or pause. A tap on the screen does the same.
- **B** (q): stop and go back to Kettle, keeping your place.
- **D-pad Left / Right** and the **left stick** (Left / Right arrow): back / forward 10 seconds.
- **L1 / R1** (j / l): back / forward 1 minute.
- **X** (Backspace): next subtitle track, then Off.
- **Y** (a): next audio track.
- **D-pad Up** (Up arrow): show the title, the time and the progress bar.
- **D-pad Down, L2, R2, the right stick, Start and Select**: nothing (in the list, Start opens the menu). Volume is the device's own buttons.

On a keyboard, Space, Left, Right and Esc do the same as A, D-pad Left, D-pad Right and B; every other key does nothing during a film (no fullscreen toggle, screenshots or volume keys). Kettle gives mpv these settings each time it starts it and never changes mpv's own settings folder. Your own mpv `input.conf` isn't used while Kettle plays a film; your `mpv.conf` and mpv scripts still are. Full details: `docs/spec.md`, "Playback controls".

## Saved library

The app remembers your library in `data/library.json` inside the app folder, so it opens at once without reading your folders. The first time, it reads your folders once and shows what it found; after that, open the menu (the **Menu** button at the top, or Start) and choose **Rescan library** (or press r) when you've added or removed files. To keep the file somewhere else, set `"data_dir"` in `settings.json` (a relative path is inside the app folder).

- Deleting `data/library.json` is safe: at the next launch the app reads your folders again and shows what it found.
- **Don't share this file or attach it to issues.** It lists the names of your files. The logs never include it.

## Settings

Open the menu (the **Menu** button at the top, or Start) and choose **Settings**. B goes back to Home.

- **Folders:** the **Movies** and **TV shows** rows show where each folder is ("SD card › Films"), or "Not set". Choose one to pick a different folder from the same list as on the first launch, or **Stop using** that kind (one of the two must stay set). The change is saved in `settings.json` and the library is read again at once; films and episodes from the old folder show as **Missing** until you choose **Remove N missing items** in the menu. Your video folders are only ever read.
- **About:** the app's version (from the `VERSION` file), its licence, and every third-party credit in `THIRD_PARTY_LICENSES.md`; choose one to read its licence text (Up and Down scroll it). mpv is used but not bundled: Kettle launches the copy already on your device.

## Privacy

Kettle Video collects nothing and never goes online by itself. The only time it connects is when you choose **Check for updates** in Settings › About: it then asks GitHub for the latest version, which shows GitHub your IP address and the app's version, and, if you then choose **Update and restart**, downloads the new version from GitHub. It sends nothing about you or your library. Your library, settings and watch history stay on your device.

- On a development copy (a git folder), the same two actions ask that copy's own git remote instead: **Check for updates** reads its latest version and **Pull the latest version** downloads it. git connects with its own settings, including any sign-in you have set up for that remote, so the remote can see which account is asking.
- The window Kettle Video opens in has a Firefox profile of its own, with Firefox's own updates, telemetry and other online features switched off.
- The installer goes online only if mpv is missing and you say yes to installing it from Flathub.

Any future feature that needs the network will only run when you choose it, and this section will say so first.

## Reporting a bug

Open a new issue on GitHub and choose **Bug report**. It asks for your device, its system and version, Desktop or Gaming Mode, the Kettle Video version (Settings › About shows it) and what happened. Please leave out personal file and folder names.

## Logs

Each run writes three logs, all timestamped, under `logs/` in a development copy or `~/.local/state/kettle-video/logs` in an installed one (see [Installing](#installing)): `launch-<timestamp>.log` (the launcher itself), `firefox-<timestamp>.log` (Firefox's own output, kept separate so the launch log stays readable), and one `mpv-<timestamp>.log` per file played (starts with the `mpv_args` in use and whether the stay-awake lock is on, then mpv's own info-level messages, including which video decoder was used and whether hardware decoding was on — no per-frame progress spam). The app writes the mpv log itself from mpv's output, so it works the same for a system mpv and the Flatpak, with no extra permissions. A log is normally a few kilobytes. Attach the relevant one(s) to a GitHub issue if something goes wrong.

If Kettle can't start (Firefox isn't installed, `settings.json` has a mistake, or the app doesn't get ready in time), it says so on screen instead of just closing: what went wrong, what to do, and the name of the launch log to attach. Close the message with A or B. Without Firefox the message is a system dialog (press A for OK).

## Current limitations (by design, for now)

Films are listed by the title and year read from their file names, and TV shows by show, season and episode. **TV shows are in beta** (the tab says "TV Shows (beta)"): today the tab lists your shows, and choosing one opens one list of its episodes (with season headings when it has more than one season), where any episode plays; separate show, season and episode screens come later. Playing a video again resumes where you stopped (see [Resume](#resume)), and a [Continue watching](#continue-watching) row shows what you're partway through. With neither folder set in `settings.json`, the first launch walks you through onboarding: it checks for mpv, asks you to choose the folders, then scans them and shows what it found (see `docs/spec.md`, "Onboarding: choosing the folders"). Not built yet: thumbnails in the lists, settings beyond the two folders (they are set in `settings.json` by hand), theming snippets, and the full installer (`install-shortcut.sh` only adds the shortcut). See `docs/spec.md`, "Roadmap", for the full roadmap.

## Third-party code

The filename parser uses [guessit](https://github.com/guessit-io/guessit) and its dependencies. They are bundled, unmodified, in `vendor/`, so nothing needs to be installed with pip. `THIRD_PARTY_LICENSES.md` lists each one with its version, license and source, and mpv, which is used but not bundled. The Settings screen's About section shows the same list.

The Kettle wordmark on the loading screen uses the Rubik Mono One font (SIL Open Font License 1.1). It is bundled, unmodified, in `ui/fonts/` with its license file and is never loaded online; it's listed in `THIRD_PARTY_LICENSES.md` too.

The design system (Enamel, MIT) is vendored in `vendor/enamel/`; see [Design system](#design-system).

## Design system

The app's styling comes from the design system for the Kettle apps, **Enamel** (MIT licence, the designer's own project, [github.com/enamelware/enamel](https://github.com/enamelware/enamel)). Its two stylesheets, its behaviour script, its `DESIGN.md`, `VERSION`, `LICENSE`, `NOTICE.md` and `MIGRATION.md` are copied, unchanged, into `vendor/enamel/`, and the page loads both stylesheets before the app's own. Nothing is loaded online.

The Enamel release the app has adopted is pinned in one place, `ENAMEL_PIN` at the repo's root (its release tag, such as `v0.7.0`). The copy in `vendor/enamel/` must match that tag exactly, and the design system check compares with that tag only, never with Enamel's main branch or its latest release, so a new Enamel release can't fail an unrelated issue. Upgrades are their own issue: when Enamel publishes a newer release, `/next all` drafts one "Bring in Enamel <version>" issue.

To take a newer Enamel (in that issue only), check its `CHANGELOG.md` for the version Kettle Video should adopt, then run `python3 tools/update_enamel.py 0.7.0` (with that version) on a device that has Enamel at `~/Development/enamel` (or still under its old folder name; or give another folder as a second argument). It reads the files from that version's release tag (`v0.7.0`), never from Enamel's folder as it happens to be, so work in progress there can't come in by mistake. It copies only the files that changed, prints the old and new version, moves the pin in `ENAMEL_PIN` to the new tag, and never changes Enamel itself. The tests compare the app's copy with the pinned tag, and are skipped with a plain reason where Enamel or that tag isn't on the device. Never edit the copies in `vendor/enamel/` by hand; then update the version in `THIRD_PARTY_LICENSES.md` and run the tests.

## License

This project is licensed under the GNU General Public License v3.0 or later (GPL-3.0-or-later) — see `LICENSE`. mpv is a separate program launched as an external process; it is not bundled and is not covered by this project's license. Outside code contributions aren't being accepted for now, but issues (bug reports, feedback) are welcome.
