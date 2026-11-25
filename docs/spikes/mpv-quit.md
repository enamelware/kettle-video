<!--
SPDX-License-Identifier: GPL-3.0-or-later
Copyright (C) 2026 Mario Carabotta
-->

# Spike: position, duration and picture when mpv quits (the mpv quit spike)

Measured on 2026-10-06 on the Steam Deck (Desktop Mode, SteamOS, x86) with
the Flathub mpv Flatpak `io.mpv.Mpv` 0.41.0. The prototype is in
`spikes/mpv-quit/`; nothing in the app, the UI, `launch.sh`, the library
code or any Flatpak permission was changed.

## Short answer

**Option 1 works with the Flatpak mpv: a small mpv script, loaded the same
way as today's 5-second rewind script.** Options 2 and 3 were not needed.

When you press B, the script pauses, saves the frame on screen (video only),
writes a small record (file, position, duration, time of quit), then quits
exactly as before, so mpv's own resume save and the 5-second rewind are
unchanged. It adds about **0.03 seconds** to quitting. The picture is about
**40 to 65 KB** at 640 px wide.

**Recommended approach for the Continue watching work:** this script, with
two details that the spike found matter:

1. **mpv writes into a temporary folder under `/tmp`, and Kettle moves the
   files into its own data folder afterwards.** The Flatpak mpv can read the
   whole device but cannot write into Kettle's folder, and `/tmp` is the one
   place both can use without changing any permission.
2. **The 640 px picture is made after mpv has closed**, by running mpv once
   more on the saved frame (about 0.4 s, mostly starting the Flatpak). The
   viewer is already back in the list by then, so it never slows down
   quitting. Converting to plain RGB colours before shrinking is required:
   the first attempt without it came out washed out (blacks lifted by about
   10 out of 255).

## What the Flatpak mpv can read and write

From `flatpak info --show-permissions io.mpv.Mpv` (read-only, nothing
changed) and a check from inside the sandbox:

| Place | Read | Write |
|---|---|---|
| Whole device (`host:ro`), including the app folder and the SD card | yes | no |
| Kettle's folder (`data/`) | yes | **no** ("Read-only file system") |
| `/tmp` (shared with the rest of the device) | yes | **yes** |
| The Flatpak's own folder `~/.var/app/io.mpv.Mpv/` | yes | yes |
| Pictures and Videos folders (`xdg-pictures`, `xdg-videos`) | yes | yes |

So the script itself is read straight from Kettle's folder (as the rewind
script already is). Output goes to `/tmp`. The Flatpak's own folder would
also work, but Kettle would then have to read a folder outside the project,
and `/tmp` avoids that. (The write check created one empty test file in that
folder and deleted it straight away; nothing else there was read.)

**System mpv:** not installed on this Deck (`which mpv` finds nothing), so it
was not tested. A system mpv can write anywhere the user can, so the same
script works there, and the `/tmp` step is simply not needed.

## Results (Flatpak mpv 0.41, Steam Deck)

Test files, all read-only from the SD card (the names here are invented; the
real titles are left out):
- **10-bit HEVC film**: *Example Film*, 1920×1036, 10-bit HEVC, about 83
  minutes, with English subtitles.
- **Short file**: a short copy of *Example Show*'s "Sample (Opening)" clip
  (asked for 3 seconds; copying cuts at keyframes, so it is 13 seconds), made
  in `/tmp`.
- **No HDR file is in the library** (all 80 videos checked: 77 are 10-bit
  HEVC SDR, 3 are 8-bit H.264). HDR could not be tested; nothing was
  downloaded.

"Matches" below means the saved picture was compared with the same moment
decoded separately by ffmpeg (software decoding, no subtitles), and with the
frames one second before and after: it was closest to the same moment every
time, with an average difference of 1 to 4 out of 255 (JPEG noise).

| Case | Record | Picture | Resume save |
|---|---|---|---|
| B while playing (1080p 10-bit, software decoding) | position and duration right | matches | same position as the record |
| B while paused, hardware decoding on (VA-API) | right | matches, colours right | same |
| B while paused, software decoding | right | matches, colours right | same |
| Subtitle on screen and on-screen text shown, then B | right | **video only**: no subtitle, no text (checked by eye too) | same |
| Short file, B after 1 s | right | matches | same |
| Short file played to the end | **finished = true**, position = duration | none (by design) | **none**: mpv saves nothing at the end |
| Window closed (mpv's close button) | written, marked "other", no picture | none | saved |
| Playing the same file again after B | | | 5-second rewind still works: saved at 40.96 s, started again at 35.96 s |

**Colours / washed out:** with the fix above, the picture's average
brightness and colour strength are within about 1.5 out of 255 of the
reference for the 10-bit film, with hardware decoding on or off. Before the
fix they were about 10 brighter (washed out). HDR remains untested.

**Time added to quitting** (from pressing B until mpv has closed, three runs
each on the 1080p 10-bit film, while playing):

| | Runs | Average |
|---|---|---|
| Today (no script) | 0.068, 0.077, 0.088 s | about 0.08 s |
| With the script | 0.103, 0.120, 0.097 s | about 0.11 s |

The script's own work (pause, save frame, write record) took 33 to 72 ms.
Shrinking to 640 px afterwards took about 0.4 s of waiting (counted CPU time
was under 0.05 s; most of the wait is the Flatpak starting up), and happens
after the viewer is back in the list.

**Picture size:** 38 to 67 KB for 640×346 frames of the film, 14 KB for a
dark 640×480 frame. The full-size frame kept in `/tmp` until it is shrunk is
225 to 385 KB, and is deleted afterwards.

**Steam closing the app** (simulated with a stop signal, since the terminal
can't press Steam's button):

| What gets the stop signal | Result |
|---|---|
| Only the `flatpak run` wrapper | The wrapper ends, but **mpv keeps playing** inside the sandbox. Nothing saved. This confirms the README: the Flatpak doesn't pass the stop on. |
| Only mpv | mpv saves its resume position, and the script writes a record marked "other" (no picture). mpv ends with status 4, which today's Kettle would show as a failed playback. |
| Both at once | mpv saves its resume position, but the record is lost: the wrapper ends first, so the prototype tidies up before the script has written it. |

As expected, Steam closing the app gives no picture. Which of these Steam
actually does in Gaming Mode was not checked (it needs the device).

## Options 2 and 3

- **Option 2** (Flatpak can't read the script or write the output): not
  needed. It can read the script; writing works through `/tmp`. Using the
  Flatpak's own folder instead would mean Kettle reading outside its project
  folder, which the designer would need to agree to.
- **Option 3** (grab the frame afterwards by playing the file again from the
  saved position): not needed and not built. The shrink step already shows
  what a second mpv run costs on the Deck (about 0.4 s to start the Flatpak
  for a single picture); decoding a 10-bit film from a seek point would add
  to that, and on the Nova (ARM) it would be slower again.

## Risks for the real feature

- **Nova (to confirm):** everything above is Steam Deck only. Hardware
  decoding on ARM and the Flatpak sandbox on Armada may behave differently,
  especially the frame save with hardware decoding and the time taken to
  start mpv for the shrink step. `/tmp` sharing is part of the Flatpak's own
  permissions, so it should be the same, but it is unchecked there.
- **`/tmp` is emptied on restart.** Kettle must move the files out right
  after mpv closes. If Kettle itself is stopped at that moment, the picture
  is lost (the resume position is not: mpv keeps that itself).
- **A user's own `q` key setting wins.** The script's B binding is not
  forced, so someone who changed `q` in their own mpv settings gets no
  picture. Forcing it would override their choice.
- **"Finished" comes only from the script.** mpv saves nothing when a film
  ends, so Kettle has to rely on the record's `finished` flag.
- **mpv ending from a stop signal reports status 4**, which today's Kettle
  shows as "playback failed". Worth handling when this is built.
- **HDR not tested**: no HDR file in the library.
- **Audio-only files** were not tested: there is no frame to save; the
  record notes `frame_saved: false`.

## How to run the prototype

From the project folder (it never writes next to the media; test resume saves
can be kept apart with `--watch-later-dir`):

```
python3 spikes/mpv-quit/run.py "<a video file>" --mpv flatpak
python3 spikes/mpv-quit/measure.py --mpv flatpak
```

`run.py` plays one file the way Kettle does today plus the script, and puts
the record and picture in `data/spikes/mpv-quit/`. If the 640 px step fails, it says so
(`picture_error`, and `picture_saved: false` in the record) and keeps the
full-size frame instead of losing it. `measure.py` repeats all
the cases above automatically (driving mpv through its control socket) and
prints the numbers (it stops with a short message naming any test file
that isn't on the card); its pictures are in `data/spikes/mpv-quit/measure-flatpak/`.
`measure.py` uses ffmpeg, already on SteamOS, only to check the pictures;
the prototype itself needs only mpv and Python's standard library.
