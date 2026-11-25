# Device setup

How to set up the app on a Steam Deck or another SteamOS-like device (such as a Retroid Pocket Nova running Armada), add it to Steam, and map the controller.

## 1. Set up the device

Do this in Desktop Mode, in Konsole.

1. **Check the tools.** Python must be 3.10 or newer.

   ```
   git --version
   ```

   ```
   python3 --version
   ```

   ```
   flatpak list --app | grep -i -E "firefox|mpv"
   ```

2. **Install Firefox and mpv if missing.** The easiest way is the device's app store (Discover on the Steam Deck). From the command line:

   ```
   flatpak install flathub io.mpv.Mpv
   ```

   If it says "No remote refs found for 'flathub'", use the app store, or add the Flathub remote and install with `--user`.

3. **Get the code.** The repo is public, so no key is needed:

   ```
   mkdir -p ~/Development && cd ~/Development && git clone https://github.com/enamelware/kettle-video.git kettle-video
   ```

   Without a network, copy the folder over on a USB drive. To update later, run `git pull` inside the folder.

4. **Point it at your media.** Nothing to do here if you like: on first launch the app asks for your folders and saves them in `settings.json`. To set them by hand instead, inside the `kettle-video` folder:

   ```
   cp settings.example.json settings.json
   ```

   Then set `movies_path` and `tv_path` in `settings.json`. Copy the SD card path from the file manager's address bar (it's usually under `/run/media`). Plain paths are best, but a pasted `file:///` address or a `~` also works. Paths differ from device to device, which is why each device has its own `settings.json`.

5. **Run it by hand first.**

   ```
   chmod +x launch.sh && ./launch.sh
   ```

   Firefox opens full screen with the list (on a first launch, choose your folders and scan them first). Play a file, then press Q and then Enter to quit (Q opens the menu with Quit chosen). The newest `launch-….log` in `logs/` says which Firefox was found (system or Flatpak). If the file played, mpv was found too.

6. **If mpv can't open your files:** the app shows a hint, and the error is in the newest `mpv-….log` in `logs/`. The Flatpak mpv can already read the whole device, SD card included (its standard read-only access, `host:ro`), so no Flatpak permission change is needed (checked on the Steam Deck; see `docs/decisions.md`, "mpv Flatpak already reads the SD card").

## 2. Add it to Steam

- **Steam Deck:** in Desktop Mode, open the Steam client, then Games, Add a Non-Steam Game to My Library, Browse. Pick `launch.sh`; if it's hidden, set the file filter to All files.
- **If Browse doesn't work** (it doesn't on the Nova): run `./install-shortcut.sh` in the `kettle-video` folder. It creates `kettle-video-dev.desktop` in `~/.local/share/applications/` (a development copy's own entry, so it never clashes with an installed copy's; the installer review fixes). Restart Steam, then pick "Kettle Video (dev)" from the Add a Game list.

Then choose Return to Gaming Mode.

## 3. Controller layout (Gaming Mode)

Steam Input turns buttons into keyboard keys. The same keys work in the list and in mpv.

| Button | Bind to | In the list | While mpv plays |
| --- | --- | --- | --- |
| D-pad up / down | Up / Down arrow | Move the highlight | Up: show where I am. Down: nothing |
| D-pad left / right | Left / Right arrow | Switch tabs, jump by letter in the Movies list, move between Continue watching tiles | Back / forward 10 seconds |
| Left stick left / right | Left / Right arrow | Same as the D-pad | Back / forward 10 seconds |
| A (bottom face button) | Space | Play the selected file | Play or pause |
| B (right face button) | Q | Open the menu with Quit chosen (B again backs out); Back inside a show | Stop and return to the list |
| X (left face button) | Backspace | Remove a Continue watching tile | Next subtitle track, then Off |
| Y (top face button) | A | Nothing | Next audio track |
| L1 | J | Nothing | Back 1 minute |
| R1 | L | Nothing | Forward 1 minute |
| Start | M | Open the menu (Rescan library, Quit) | Nothing |

Leave L2, R2, the right stick and Select as they are: they send no key, so they do nothing in the list or in mpv. The left stick's up and down are not needed. Enter also plays and Esc works like B in the list. The table needs the ten keys above (Y, L1 and R1 are new with the playback controls work, Start with the Home actions work: add them to an existing layout). For the left stick, set it to act as a directional pad (Steam calls this mode "Directional Pad") and bind only its left and right.

On the Nova, check that A sends Space, not Enter: one saved layout was seen with A on Enter (`docs/spikes/controls.md`), and in mpv Enter does nothing.

Steps: Library, Non-Steam, Kettle Video, controller icon. Choose Edit Layout and pick an input. Switch its action type to Keyboard (R1 cycles through Gamepad, Mouse, Keyboard and Numpad), bind the key from the table, and save. To reuse the layout on another entry: the cog beside Edit Layout, Export Layout, Save New Layout, then a "New Template" named Kettle Video.

## 4. If something fails

- Test the layout in Gaming Mode. Steam may ignore layouts for non-Steam apps in Desktop Mode.
- Check that the saved layout is the one applied to Kettle Video.
- Check that each binding is on the Keyboard tab, not Gamepad.
- On Armada, if you change the emulated controller type in Armada Control, check the layout again.
- Steam's "A" means the bottom face button by position. If the labels on your device differ, go by position.
- Menu wording differs slightly between the Steam Deck's and Armada's Steam builds; the flow is the same.

## 5. Updating a test device

Kettle Video never goes online by itself (the never-online work), so a test device no longer updates at every launch: the old developer option `"dev_auto_update"` is gone, and a line for it left in `settings.json` is simply ignored.

To see whether there is something newer, open Settings › About › Check for updates. On a git copy it compares with GitHub's `main` and says whether a newer version is there. When it is, a **Pull the latest version** row appears under it (the Update and restart work): A, then yes in the question, fetches `main` and restarts the app on it in place, without closing the window or leaving Gaming Mode. It pulls only when the copy is on `main` with no changes of its own to tracked files (`settings.json`, `data/` and `logs/` don't count), and otherwise says why and changes nothing. `git pull` in the copy's folder, in Desktop Mode, still works too.

## 6. Developer option: size readout (test devices only)

To see how big the app's page is and how the screen scales it, the app can write one line to its launch log when it starts. It's for developers, it changes nothing on screen, and it's off unless you turn it on.

1. Add this line to that device's `settings.json`, inside the braces:

   ```
   "debug_size_readout": true,
   ```

2. Start Kettle Video from Steam in Gaming Mode. The newest `launch-….log` in `logs/` then has one line starting `size readout:`, with the page's size in CSS pixels (the units the page lays out in), the device pixel ratio (how many screen pixels make one CSS pixel), the screen's size, and a note on Firefox's zoom: Firefox doesn't tell a page its zoom, it folds it into the device pixel ratio.

The line holds sizes only, never a title or a folder. To turn it off, remove the line or set it to `false`. What it was used for: `docs/sizing-report.md`.

## 7. What to note when something goes wrong

- The device and mode (Desktop or Gaming).
- Which check failed and what you saw.
- The newest `launch-….log` in `logs/`, and the newest `mpv-….log`.
- Whether Firefox and mpv are a system install or a Flatpak on that device.
