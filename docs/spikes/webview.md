<!--
SPDX-License-Identifier: GPL-3.0-or-later
Copyright (C) 2026 Mario Carabotta
-->

# Spike: can a Python-opened webview window replace Firefox kiosk mode? (the webview spike)

Looked at on 2026-10-08 on the Steam Deck (Desktop Mode, x86) only: the
designer dropped the Nova part (see "Nova" below). Nothing in the app, the system or
Flatpak was changed and no sudo was used. As the issue allows (pip only
inside a throwaway venv in `spikes/webview/`), and with the designer's go-ahead
in the Claude Code session on 2026-10-08, pywebview and Qt were downloaded
from PyPI (Python's public package index) into throwaway folders there.

A *web view* is a bare browser pane with no browser around it: the app's
pages would show in a window that Python opens itself, instead of in
Firefox.

## Short answer

**Recommendation: switch only when the app is packaged as a Flatpak.**
**The designer's decision (2026-10-08): accepted. Kettle keeps Firefox kiosk mode;
a web view is reconsidered only with the Flatpak work** (see
`docs/decisions.md`).

- On the Deck the only route that works today (Route C) means **downloading
  about 212 MB and using 546 MB of disk on top of Kettle's 6.8 MB**, all of
  it compiled, processor-specific code, which CLAUDE.md rules out for the
  app.
- It is faster and lighter than Firefox (Home ready in 0.8 s instead of
  about 2.3 s, 370 MB of memory instead of 570 MB), but those gains don't
  outweigh the download, the licence catch and the Nova risk.
- Inside a Flatpak the web view comes with the runtime and works the same
  on every device and processor, so that is when switching becomes cheap.

## What users would download on top of Kettle

The designer's question: would people need big libraries on top of Kettle for
it to work? Measured on the Steam Deck; sizes are disk space after install.

| | Today (Firefox kiosk) | Route C (Qt web view) | Route A (system web view) | Route D (Kettle as a Flatpak) |
|---|---|---|---|---|
| Kettle itself | 6.8 MB | 6.8 MB | 6.8 MB | to measure |
| Window | Firefox Flatpak, 328 MB | pywebview + Qt: **546 MB** (212 MB download), inside the app folder | nothing, if the system has WebKitGTK: **SteamOS doesn't** | a Flatpak runtime that has a web view (the GNOME one has WebKitGTK); shared with other apps that use it; size to measure |
| Shared Flatpak runtime (org.freedesktop.Platform 25.08) | 669 MB, also needed by mpv | still needed by mpv | still needed by mpv | replaced or joined by the app's own runtime |
| mpv Flatpak | 245 MB | 245 MB | 245 MB | 245 MB (or bundled; not decided) |

So **yes: every route needs big downloads on top of Kettle**, and today's
already does. Firefox plus its shared runtime is about 1 GB on a device that
has neither, though many Decks already have the runtime from other Flatpaks
(this one has it twice over). Route C would replace the 328 MB of Firefox
with 546 MB of its own, which nothing else on the device can share, and mpv
would still need its runtime. Only Route A costs nothing extra, and only on
a system that ships WebKitGTK: SteamOS does not; Armada is still to check.

## Question 1: what is already there

Checked with `python3 spikes/webview/probe.py`, which prints each exact check
next to its result.

| | Steam Deck (SteamOS, x86) | Nova (Armada, ARM) |
|---|---|---|
| Python | 3.14.6 | not tested |
| pip | no (`No module named 'pip'`) | not tested |
| venv | yes | not tested |
| ensurepip (puts pip into a venv) | yes, pip 26.1.2 | not tested |
| GTK bindings for Python (`gi`) | yes, 3.56.3 | not tested |
| GTK 3 / GTK 4 | 3.24.52 / 4.22.4 | not tested |
| WebKitGTK (any version) | **no**: no library and no Python typelib | not tested |
| Qt web engine library | yes, Qt 6.11.1 (`libQt6WebEngineCore`), for the KDE desktop | not tested |
| Qt Python bindings (PyQt5, PyQt6, PySide6) | **no** | not tested |
| glibc (decides which pip builds can run) | 2.43 | not tested (ARM builds need 2.39 or newer) |

## Question 2: routes

### Steam Deck (x86)

| Route | Works? | What it needs | Size |
|---|---|---|---|
| A: system GTK + WebKit, no new package | **No: would need a system change** (installing WebKitGTK with pacman after `steamos-readonly disable`, which SteamOS updates wipe). Not tried, as the issue requires. | nothing new, if WebKit were there | 0 |
| B: pywebview in a venv, reusing system GTK or Qt | **No.** pywebview installs, then stops with "You must have either QT or GTK with Python extensions installed": GTK finds no WebKit, and there are no Qt bindings. | pywebview, bottle, proxy_tools | 0.7 MB of packages (the venv with its own pip is 17 MB) |
| C: pywebview + Qt from pip, own web engine | **Yes.** Home opens full screen with no frame, with the library and the Continue watching pictures. | pywebview, QtPy, PyQt6, PyQt6-WebEngine, and Qt with its web engine (PyQt6-Qt6, PyQt6-WebEngine-Qt6) | 212 MB download, **546 MB on disk** (Qt's libraries 368 MB, translations 54 MB, resources 25 MB) |
| D: Flatpak of the app | on paper, below | | |

Exact commands (from the repo root):

```
python3 spikes/webview/probe.py                              # Question 1
python3 spikes/webview/window_gtk.py                         # Route A
python3 -m venv --system-site-packages spikes/webview/.venv-b
spikes/webview/.venv-b/bin/pip install pywebview             # Route B
spikes/webview/.venv-b/bin/python spikes/webview/window_pywebview.py
python3 -m venv spikes/webview/.venv-c
spikes/webview/.venv-c/bin/pip install --no-cache-dir "pywebview[qt]"   # Route C
spikes/webview/.venv-c/bin/python spikes/webview/window_pywebview.py
python3 spikes/webview/quit_check.py                         # quitting
python3 spikes/webview/measure.py webview 3                  # speed, memory
python3 spikes/webview/measure.py firefox 3
spikes/webview/.venv-c/bin/python spikes/webview/screenshots.py OUT_DIR
```

Route A on the Deck stops with "WebKit2GTK is not installed (would need a
system change)" before starting the server, so nothing is left running.

### Nova (ARM)

Not tested. Claude Code works on the Deck and cannot reach the Nova, and
the designer dropped this part (2026-10-08): the Nova will be tested as part of
the Flatpak work, if a web view comes up again then. From the package
listings only: pip has ARM builds of Qt and its web engine, but they need
glibc 2.39 or newer; if Armada's is older, Route C cannot run on the Nova at
all. The same commands as above would fill in this column.

### Route D: a Flatpak of the app (on paper)

A Flatpak brings its own *runtime* (a shared set of libraries). The GNOME
runtime includes WebKitGTK, so inside a Flatpak, Route A (no extra package)
would work the same on every device and processor, with no system change.
The KDE runtime has Qt, and its web engine comes as a separate add-on
(*BaseApp*). So the Flatpak question and the webview question are linked:
once Kettle is a Flatpak, a webview costs almost nothing extra; before that,
it means either a large download into the app folder or a system change.
Flatpak packaging is a "later, not now" milestone in CLAUDE.md. To confirm
when packaging starts: the exact runtime contents and sizes at that time.

## Question 3: the real app in the web view (Steam Deck, Route C)

| Check | Result | Notes |
|---|---|---|
| Server starts as today, Home opens | **pass** | same server command as `launch.sh` |
| Full screen, no frame (Desktop Mode) | not tested: spike closed as answered | the window asks for both; screenshots used a plain window, so not seen yet |
| Full screen, no frame (Gaming Mode) | not tested: spike closed as answered | steps below |
| Controller | not tested: spike closed as answered | The page gets the controller as keyboard keys from Steam Input, as in Firefox, so nothing in the page changes. But the new shortcut needs the keyboard layout applied (steps below) |
| Touch | not tested: spike closed as answered | |
| Playback, and coming back after mpv quits | not tested: spike closed as answered | **the key check**, see "Focus" below |
| Resume | unchanged in principle | saved by mpv and the server, not the window |
| Keep-awake | unchanged | the server runs mpv under the system's stay-awake lock (`systemd-inhibit`); the window plays no part |
| Looks | **different**, see below | screenshots at 16:10 and 4:3 |
| Quitting | **pass** | `spikes/webview/quit_check.py` starts the spike as the Steam shortcut does, then stops it politely (what Steam's "Exit game" sends) and kills it hard (as if it crashed): nothing left behind either way (process list checked). See "Quitting" below |
| Speed and memory | **faster and lighter** | table below |

### Speed and memory (Steam Deck, 3 runs each)

Measured with `python3 spikes/webview/measure.py webview|firefox 3`: from
starting the server to the app's own "page loaded" signal, then the memory
of every process the window started (PSS: each process's own memory plus its
fair share of what it shares), 5 seconds after load. The server is not
counted in either.

| | Run 1 | Run 2 | Run 3 |
|---|---|---|---|
| Web view, Home ready | 0.8 s | 0.9 s | 0.8 s |
| Firefox kiosk, Home ready | 1.9 s | 2.5 s | 2.6 s |
| Web view, memory | 369 MB (5 processes) | 367 MB | 367 MB |
| Firefox kiosk, memory | 553 MB (14 processes) | 577 MB | 573 MB |

### Looks (Steam Deck, 16:10 and 4:3)

Taken with `spikes/webview/screenshots.py`, same library in both.

1. **Font.** The web view uses the Deck's own system font; the Firefox
   Flatpak uses the one in its runtime. Text is slightly wider in the web
   view, so the first Continue watching tile and the captions come out a
   little bigger and wrap differently.
2. **Scrollbar.** The web view shows a permanent grey scrollbar down the
   right edge; Firefox's hides itself. A one-line style change would hide it
   if the app switched.
3. **Focus ring.** The ring only shows while the window is the *active*
   window. In the screenshot run, the desktop didn't make the web view
   active, so no ring was drawn, although focus was on the first tile.
   Firefox draws it regardless.
4. Colours, hint bar, tabs and list layout: the same.

### Focus: the key check for Gaming Mode

Because the ring and the keys both need the web view to be the active
window, the check that matters is whether **gamescope (Gaming Mode's window
manager) makes the web view active again after mpv quits**. If it doesn't,
the controller's keys would go nowhere and no ring would show, until a tap
on the screen.

### Quitting

In the first version of the spike, Qt once crashed on start-up and the
server it had started kept running: the script only stopped the server when
its window closed normally. The spike's scripts now ask Linux to stop the
server as soon as the script that started it ends, however it ends (a
standard Linux feature, called from plain Python). `launch.sh` does the same
job today by watching both processes; a switch would need one of the two.
The orphaned server from that crash was stopped by hand.

## Licences

| Package | Route | Licence (from PyPI, 2026-10-08) | Works with GPL-3.0-or-later? |
|---|---|---|---|
| pywebview 6.2.1 | B, C | BSD 3-Clause | yes |
| bottle 0.13.4 (pywebview helper) | B, C | MIT | yes |
| proxy_tools 0.1.0 (pywebview helper) | B, C | MIT | yes |
| typing_extensions 4.16.0 (pywebview helper) | B, C | PSF-2.0 | yes |
| QtPy 2.4.3 | C | MIT | yes |
| packaging 26.3 (QtPy helper) | C | Apache-2.0 or BSD-2-Clause | yes |
| PyQt6-sip 13.13.0 (PyQt6 helper) | C | BSD-2-Clause | yes |
| PyQt6 6.11.0 | C | GPL-3.0-only | yes, but the combined app could then only be shared under GPL **version 3**, not "or later" |
| PyQt6-WebEngine 6.11.0 | C | GPL-3.0-only | same as PyQt6 |
| PyQt6-Qt6, PyQt6-WebEngine-Qt6 6.11.2 (Qt itself) | C | LGPL-3 | yes |
| PySide6-Addons 6.11.2 (alternative to PyQt6, not tried) | C | LGPL-3.0 or GPL-2.0 or GPL-3.0 | yes, with no "version 3 only" catch |
| GTK 3.24.52 (system) | A | LGPL-2.1-or-later (`pacman -Qi gtk3` on the Deck) | yes |
| PyGObject 3.56.3 (system) | A | LGPL-2.1-or-later (`pacman -Qi python-gobject` on the Deck) | yes |
| WebKitGTK 2.54 (not on the Deck) | A | a mix including LGPL, BSD, Apache-2.0, MIT, GPL-3.0-or-later and MPL (Arch Linux package page, 2.54.1) | yes in practice: it is a system library the app would only talk to, never ship |

**Chromium inside Qt's web engine** (from Qt's licensing page): Qt's own
parts are LGPL-3 or GPL-2/3; the Chromium code brings BSD, Apache-2.0, MIT,
ISC, LGPL 2.1 (including FFmpeg) and a few MPL-1.1 parts. Qt states it does
not link to or ship GPL binary code. All of these work with GPL-3.0-or-later,
except that MPL-1.1 on its own does not; such parts are usually also offered
under GPL or LGPL. Qt ships the whole web engine under LGPL-3, which is what
pip's Qt packages use. If Kettle ever adopted Route C, those few MPL-1.1
parts would need a closer look first.

## If Kettle switches later (with the Flatpak)

- **What would change in the app:** `launch.sh` would open the web view
  instead of Firefox, and watch it the same way; the pages stay as they are,
  except hiding the scrollbar. Firefox could stay as the fallback when no web
  view is found.
- **What a user would install:** with Route C, nothing by hand, but the
  installer would download 212 MB into the app folder. In a Flatpak, the
  runtime comes with it.
- **Rules it touches:** Route C is a new dependency and compiled code, both
  designer decisions under CLAUDE.md.
- **Size:** M (launcher, watchdog, fallback, installer step, tests on both
  devices).

## Surprises

- SteamOS already ships Qt 6.11's web engine (for KDE), about the same
  version pip downloads, but with no way to reach it from Python.
- The Deck has no pip for the system Python, but `ensurepip` works, so a
  venv can get pip without a system change.
- The Firefox Flatpak doesn't use the Deck's system font; the web view does.
- Qt can't draw off screen on the Deck (it can't use the graphics chip that
  way), so web view screenshots need a real, briefly visible window.

## For later: adding the web view to Gaming Mode (Steam Deck)

Not done in this spike (closed as answered); kept for the Flatpak work.

In Desktop Mode:

1. Open Steam, then **Games → Add a Non-Steam Game to My Library → Browse**.
2. Go to the app folder, then `spikes/webview/`, set the file type filter to
   **All files**, choose `run-webview.sh`, then **Add Selected Programs**.
3. In the library, right-click the new entry, **Properties**, and rename it
   "Kettle webview spike".
4. Return to Gaming Mode. Open the new entry, press the controller icon and
   choose the same keyboard layout as the real app (Your Layouts), or set
   the five keys from `docs/device-setup.md` section 3 by hand. Steam files
   layouts by shortcut name, so the new shortcut starts with none.
5. Launch it. Quit it from the Steam menu (**Exit game**).

The window writes its messages to `logs/webview-spike.log`.

## Removing everything

1. Delete the `spikes/webview/` folder: it holds the scripts and both
   throwaway venvs (`.venv-b` 17 MB, `.venv-c` 546 MB).
2. Remove the test shortcut from the Steam library (Manage, Remove non-Steam
   game from your library).
3. Delete `logs/webview-spike.log`, if you like.
4. Route B's install left one 3 KB file outside the app folder, in pip's
   shared cache, before the Route C install switched the cache off. pip
   never deletes it by itself. To remove it in Desktop Mode, open the file
   manager, turn on **Show Hidden Files**, and delete this folder from your
   home folder:
   `.cache/pip/wheels/54/b4/ac/2b81b90ec2895608a2d68ceca60a4476b409bdfe16398a4251`
   (it holds only `proxy_tools-0.1.0-py3-none-any.whl`). It does nothing
   if left there.
