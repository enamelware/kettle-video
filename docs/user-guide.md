# User guide

The details behind the [README](../README.md): how Kettle Video resumes films, keeps the screen on, saves its library, and where it keeps everything. A development copy (a git folder) keeps `settings.json`, `data/` and `logs/` in its own folder; an installed copy keeps them in the places listed under [Where everything lives](#where-everything-lives).

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

The controller's **X** button sends **Backspace**: add it to your controller layout (see [`device-setup.md`](device-setup.md)). During a film, X steps through the subtitles instead (see "Playback controls").

**About the pictures:** each tile's picture is a frame from your own video, saved when you stop it with B. The pictures stay on the device, in `data/thumbnails/` inside the app folder (or under your `data_dir`), never next to your media, never in the project's files on GitHub (that folder is excluded), and never in any log. One picture per tile, about 480 pixels wide; it's deleted when the film finishes, when you remove the tile, when it drops off the end of the row, or when the film is removed from the library. Deleting the folder is safe: the tiles then show the title on a plain surface until you next stop each film.

With `"resume": false` there is no Continue watching row. Closing the player in another way (the window's close button, Steam closing the app) saves no picture.

## Watching movies

While a film is open, Kettle asks the system to keep the device awake: the screen shouldn't dim or turn off by itself. It uses the system's own "stay awake" lock (`systemd-inhibit`), labelled **Kettle / Playing a video**, which asks only for "don't go idle". It never stops a sleep you ask for: the power button always puts the device to sleep. Kettle pauses the film just before, so on waking it is paused at the same point; press A to play on. The lock is tied to the player: it ends when you quit, when the player crashes, or when the app is closed. mpv's own "stop the screensaver" option stays on as well.

In Gaming Mode, Steam runs its own dim and screen-off timers, which don't look at that lock. So while a film plays, Kettle's screen also asks the browser to keep the screen on (the standard "Screen Wake Lock"). Steam has delayed its timers for that kind of request since its 13 October 2026 update. The request ends when the film closes, however it closes. Each change is noted in the launch log (`screen wake lock: held`, `released`, and so on).

**If the screen still dims or the device still sleeps in Gaming Mode,** Steam's own timers may be overriding both. Turn them off or make them longer: press the Steam button, then **Settings → Power** (on older SteamOS versions some of these are under **Settings → Display**), and change **Dim screen after** and **Sleep after**, for battery and for plugged in.

**To turn it off**, set `"keep_awake": false` in `settings.json`; that turns off both the lock and the browser's request. A `settings.json` without the `keep_awake` line behaves as `true`.

**Limits:**

- The device stays awake for as long as the player is open, **including while a film is paused**. A paused film left overnight will drain the battery. Staying awake only while a film is actually playing needs a live link to mpv, planned for later.
- If the lock tool is missing or the system refuses the lock (possible on some Armada devices), the film plays normally without it and the mpv log says so.
- For now, each mpv log also lists the system's stay-awake locks a few seconds after the film starts and then every minute (lines starting `kettle-video: locks:`), to check afterwards that the lock was held. This will be removed once it's confirmed on both devices.

## Playback controls

While a film plays, mpv's own control bar is off and only these buttons do something (your controller layout must send the keys shown; see [`device-setup.md`](device-setup.md)):

- **A** (Space): play or pause. A tap on the screen does the same.
- **B** (q): stop and go back to Kettle, keeping your place.
- **D-pad Left / Right** and the **left stick** (Left / Right arrow): back / forward 10 seconds.
- **L1 / R1** (j / l): back / forward 1 minute.
- **X** (Backspace): next subtitle track, then Off.
- **Y** (a): next audio track.
- **D-pad Up** (Up arrow): show the title, the time and the progress bar.
- **D-pad Down, L2, R2, the right stick, Start and Select**: nothing (in the list, Start opens the menu). Volume is the device's own buttons.

On a keyboard, Space, Left, Right and Esc do the same as A, D-pad Left, D-pad Right and B; every other key does nothing during a film (no fullscreen toggle, screenshots or volume keys). Kettle gives mpv these settings each time it starts it and never changes mpv's own settings folder. Your own mpv `input.conf` isn't used while Kettle plays a film; your `mpv.conf` and mpv scripts still are. Full details: [`spec.md`](spec.md), "Playback controls".

## Saved library

The app remembers your library in `data/library.json` inside the app folder, so it opens at once without reading your folders. The first time, it reads your folders once and shows what it found; after that, open the menu (the **Menu** button at the top, or Start) and choose **Rescan library** (or press r) when you've added or removed files. To keep the file somewhere else, set `"data_dir"` in `settings.json` (a relative path is inside the app folder).

- Deleting `data/library.json` is safe: at the next launch the app reads your folders again and shows what it found.
- **Don't share this file or attach it to issues.** It lists the names of your files. The logs never include it.

## Settings

Open the menu (the **Menu** button at the top, or Start) and choose **Settings**. B goes back to Home.

- **Folders:** the **Movies** and **TV shows** rows show where each folder is ("SD card › Films"), or "Not set". Choose one to pick a different folder from the same list as on the first launch, or **Stop using** that kind (one of the two must stay set). The change is saved in `settings.json` and the library is read again at once; films and episodes from the old folder show as **Missing** until you choose **Remove N missing items** in the menu. Your video folders are only ever read.
- **About:** the app's version (from the `VERSION` file), its licence, and every third-party credit in `THIRD_PARTY_LICENSES.md`; choose one to read its licence text (Up and Down scroll it). mpv is used but not bundled: Kettle launches the copy already on your device.

## Logs

Each run writes three logs, all timestamped, under `logs/` in a development copy or `~/.local/state/kettle-video/logs` in an installed one (see [Where everything lives](#where-everything-lives)): `launch-<timestamp>.log` (the launcher itself), `firefox-<timestamp>.log` (Firefox's own output, kept separate so the launch log stays readable), and one `mpv-<timestamp>.log` per file played (starts with the `mpv_args` in use and whether the stay-awake lock is on, then mpv's own info-level messages, including which video decoder was used and whether hardware decoding was on — no per-frame progress spam). The app writes the mpv log itself from mpv's output, so it works the same for a system mpv and the Flatpak, with no extra permissions. A log is normally a few kilobytes. Attach the relevant one(s) to a GitHub issue if something goes wrong.

If Kettle can't start (Firefox isn't installed, `settings.json` has a mistake, or the app doesn't get ready in time), it says so on screen instead of just closing: what went wrong, what to do, and the name of the launch log to attach. Close the message with A or B. Without Firefox the message is a system dialog (press A for OK).

## Testing as a brand-new user

For testing only: two launch options open Kettle Video as a new user would see it, without touching your real setup. Both go in a Steam shortcut's **Launch Options**; nothing else needs changing.

- `KETTLE_FRESH_START=1 %command%`: **fresh start**. The app starts as it does for someone new: it asks for your Movies and TV Shows folders, whatever `settings.json` says, then opens Home with "No library yet." It starts with a new, empty data folder in a temporary place, and the folders you choose are kept there too, for that session only: `settings.json` is only read, for your other settings, and never changed. Your saved library, your Continue watching row and mpv's resume positions are neither read nor changed: mpv gets its own empty resume folder for the session. A "FRESH START" marker shows in the bottom-left corner of every screen. When the app quits, the temporary folder is deleted, so the next fresh start asks again; if it's left behind (after Steam's "Exit game" or a crash), the next fresh start deletes it. The search for folders reads your real folders, and only reads them, as always.
- `KETTLE_PRETEND_NO_MPV=1 %command%`: the app behaves as if mpv were not installed, to see the "mpv not found" screen. Nothing is uninstalled.
- Both together: `KETTLE_FRESH_START=1 KETTLE_PRETEND_NO_MPV=1 %command%`.

Only one copy of the app opens at a time, so close the normal one before starting the fresh-start one (and the other way round).

**A second Steam shortcut, "Kettle Video (fresh start)"**, in Desktop Mode (the same steps on the Steam Deck and the Nova; they never need the Browse button, which doesn't work on the Nova):

1. Open your existing **Kettle Video** shortcut's **Properties** (right-click it in My Library, or the cog, then Properties) and copy its **Target** and **Start In** somewhere, or keep the window open.
2. **Games → Add a Non-Steam Game to My Library**. Tick **Kettle Video** (on the Nova a development copy is listed as **Kettle Video (dev)**, thanks to `install-shortcut.sh`, see [`dev-environment.md`](dev-environment.md#adding-a-development-copy-to-steam)) and choose **Add Selected Programs**. If Kettle Video isn't offered a second time, tick any program in the list instead: the next step points the shortcut at Kettle Video.
3. Open the new shortcut's **Properties**: set its name to **Kettle Video (fresh start)**, paste the same **Target** and **Start In** as the first one, and set **Launch Options** to `KETTLE_FRESH_START=1 %command%`.
4. Give it the same controller layout as the first one: [`device-setup.md`](device-setup.md), "Controller layout", says how to save the first one's layout as a template and reuse it.

To test the "mpv not found" screen, change that shortcut's Launch Options to `KETTLE_FRESH_START=1 KETTLE_PRETEND_NO_MPV=1 %command%` (or make a third shortcut the same way). Launching the normal Kettle Video shortcut afterwards shows your library, resume positions and Continue watching exactly as before.

## Where everything lives

| What | Where |
|---|---|
| The app files (replaced by an update) | `~/.local/share/kettle-video/app`, a shortcut to the current version's folder in `~/.local/share/kettle-video/versions` |
| Your saved library | `~/.local/share/kettle-video/data` |
| Settings | `~/.config/kettle-video/settings.json` (made on the first launch) |
| Logs (attach them to a GitHub issue) | `~/.local/state/kettle-video/logs` |
| The app menu entry | `~/.local/share/applications/kettle-video.desktop` (a development copy's is `kettle-video-dev.desktop`) |
| The app window's Firefox profile (rebuilt at every launch) | `~/.mozilla/kettle-video-profile`, or `~/.var/app/org.mozilla.firefox/data/kettle-video-profile` with Flatpak Firefox |

A development copy (a git folder) keeps `settings.json`, `data/` and `logs/` in its own folder. An installed copy is told apart by a small mark file the installer leaves in its app folder.

## Uninstalling

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
