<!--
SPDX-License-Identifier: GPL-3.0-or-later
Copyright (C) 2026 Mario Carabotta
-->

# Spike: can Kettle Video open the system's own folder dialog and get back a real folder path? (the folder dialog spike)

**Status: done (2026-10-29).** Steam Deck: terminal part (2026-10-26), then
the designer's hand checks in Desktop and Gaming Mode (2026-10-29). The designer
then decided to stop testing (the folder dialog spike): no controller retry on the Deck
and no Nova run. The Nova is assumed to behave like the Deck, and the
recommendation below lists that as a risk.

Looked at on the Steam Deck (SteamOS 3.9.5, x86, Desktop Mode, KDE Plasma
on Wayland, one SD card in). Nothing was installed, nothing was written to
the card or any media folder, no sudo, no Flatpak permission changed. Each
dialog was only asked to *choose* a folder. The scripts are in
`spikes/folder-dialog/` (Python standard library only). In this report and
in the scripts' output, a folder is never named: it is described as
"SD card, 2 levels down" and the like.

## Why

Onboarding will list the folders with videos that it finds. Where that
list misses a folder, a "Browse somewhere else" row could open the system's
own folder dialog. Firefox's own folder picker can't do this: a web page
never learns the real path. A dialog opened by the app's Python side can
return it, and the server then hands it to the page.

## Short answer (Steam Deck)

- **Four folder dialogs are there without installing anything:** the
  desktop portal's file chooser (KDE's, in folder mode), KDE's own dialog
  (`kdialog`), the GTK dialog (`zenity`) and Python's built-in Tk dialog.
- **Each one opens from a process started like the app's server** and stays
  open until it is answered. **The server keeps answering while a dialog
  is open** (every ping answered, slowest 3 ms), because each request runs
  on its own thread, as in the app's server.
- **The desktop portal needs a held-open connection.** It answers later,
  with a signal, to the connection that asked. The command-line tools
  (`gdbus`, `busctl`) exit as soon as they have asked, and the portal then
  drops the request (tried: the answer never comes). Python's standard
  library has no D-Bus support, so the spike talks to the session bus
  through a small client written with the standard library only
  (`spikes/folder-dialog/dbus_session.py`, about 250 lines). The system's
  Python D-Bus libraries (`dbus-python` 1.4.0, PyGObject 3.56.3) are on
  the Deck, but using them would be a new dependency for the app.
- **By hand on the Deck (2026-10-29):** in Desktop Mode all four dialogs
  returned a real folder, cancel worked (tried on the portal), and the
  page got the focus back at once every time. In **Gaming Mode the portal
  is not available**; kdialog, zenity and Tk all showed in front of the
  page, returned a real folder with **touch**, and handed the focus back
  at once.
- **The controller and trackpads were not confirmed:** in Gaming Mode
  nothing reached even the spike's own page, most likely because its Steam
  entry didn't have Kettle Video's layout (see "Question 3").
- **mpv** (the Flatpak, `host:ro`) can play from anywhere on the SD card
  and internal storage on both devices (the storage spike), so any folder these dialogs
  return there is playable.

## Steam Deck table

From the spike's logs of the designer's runs (2026-10-29). "Not confirmed"
means no controller input reached the spike at all, so the dialogs
themselves were never tried with it.

| Dialog | Works in Desktop Mode | Works in Gaming Mode | Controller | Touch | Returns a path | mpv can play |
|---|---|---|---|---|---|---|
| Desktop portal (KDE) | yes: path and cancel, focus back | **no: not available** | not confirmed | yes (Desktop Mode) | yes, as a `file://` address | yes (the storage spike) |
| kdialog (KDE) | yes, focus back | yes: in front, focus back | not confirmed | yes | yes | yes (the storage spike) |
| zenity (GTK) | yes, focus back | yes: in front, focus back | not confirmed | yes | yes | yes (the storage spike) |
| Tk (Python) | yes, focus back | yes: in front, focus back | not confirmed | yes | yes | yes (the storage spike) |

Time from opening a dialog to a folder chosen, in Gaming Mode with
touch: kdialog 4 to 14 s, zenity 10 to 15 s, Tk 4 s. All the folders
picked were on internal storage (1 to 4 levels down); the SD card wasn't
tried by hand, but every dialog lists it, and mpv plays from it (the storage spike).
Cancel was tried by hand only on the portal. On the others it wasn't
tried (the automatic run closes each dialog itself rather than
cancelling it); the spike reads cancel from the exit code or empty output
shown below, as each tool documents it.

## Question 1: what is there (Steam Deck)

Run: `python3 spikes/folder-dialog/dialogs.py`

| Dialog | The check | Result on the Deck |
|---|---|---|
| Desktop portal | read the property `version` of `org.freedesktop.portal.FileChooser` on the session bus; then list the portal back ends that offer a file chooser (`/usr/share/xdg-desktop-portal/portals/`) | version 4; back ends `kde.portal` (KDE) and `gtk.portal` (GNOME). On KDE the KDE one answers. |
| kdialog | look for `kdialog` on the PATH, then `kdialog --version` | kdialog 26.04.3 |
| zenity | look for `zenity` on the PATH, then `zenity --version` | zenity 3.44.5 |
| Tk | `python3 -c 'import tkinter'`, and an X display in `DISPLAY` | tkinter 8.6; X display there (Tk runs through XWayland under Wayland) |

Not looked at: GTK or Qt dialogs through PyGObject or PyQt (new
dependencies for the app).

## Question 2: does it work (Steam Deck, Desktop Mode, from the terminal)

Run: `python3 spikes/folder-dialog/auto_check.py`. It starts
`spikes/folder-dialog/server.py` the way `launch.sh` starts the app's
server (`python3 -u`, from the project folder, in the background, output
to a log), asks it to open each dialog in folder mode, asks it for a ping
every 0.2 s while the dialog is open, and closes the dialog after 4
seconds (nobody picks a folder in this run).

| Dialog | Opened and stayed open | Server answered while open | Slowest answer | Closed |
|---|---|---|---|---|
| Desktop portal | yes | 20 of 20 | 2 ms | by the script (the portal's own Close) |
| kdialog | yes | 21 of 21 | 2 ms | by the script (stopped) |
| zenity | yes | 20 of 20 | 2 ms | by the script (stopped) |
| Tk | yes | 20 of 20 | 3 ms | by the script (stopped) |

Nothing was left running afterwards.

**How each one is opened**, starting in the home folder
(`spikes/folder-dialog/dialogs.py`, `open_dialog`):

- **Desktop portal:** on the session bus, `org.freedesktop.portal.Desktop`,
  `/org/freedesktop/portal/desktop`, `org.freedesktop.portal.FileChooser`,
  method `OpenFile("", title, {handle_token, directory: true, modal: true})`.
  The answer is the `Response` signal on the request path: code 0 with
  `uris` (a `file://` address), 1 for cancel. No parent window is given:
  the page can't name Firefox's window to the portal, so the dialog may not
  be tied to Kettle's window. In Desktop Mode it still showed in front.
- **kdialog:** `kdialog --title TITLE --getexistingdirectory START`. The
  path on standard output; exit 1 on cancel.
- **zenity:** `zenity --file-selection --directory --title=TITLE
  --filename=START/`. The path on standard output; exit 1 on cancel.
- **Tk:** a second Python process runs `tkinter.filedialog.askdirectory`
  and prints the path (empty on cancel). It needs its own process: Tk must
  run on a program's main thread, and the server's is busy.

Checked by hand on the Deck (2026-10-29), with the test page recording
each result and the focus: see "Steam Deck table" above.

### Gaming Mode: what to look out for

In Gaming Mode, Steam shows the windows of the game it started. kdialog,
zenity and the Tk dialog are started by the spike's server, so they belong
to that game. The desktop portal's dialog is drawn by the portal's own
program, which Steam didn't start, so it may not show at all in Gaming
Mode. **Confirmed by hand:** in Gaming Mode the page found no portal file
chooser to open (marked "not available"), while kdialog, zenity and Tk
showed in front of the page.

## Question 3: is it usable

- **Touch: yes.** kdialog, zenity and Tk could each pick a folder by
  touching the screen, in Gaming Mode, in 4 to 15 seconds.
- **Controller and trackpads: not confirmed.** In Gaming Mode no button
  worked, not even on the spike's own page, which reads the same keys as
  Kettle. The likeliest reason is that the spike's Steam entry used
  Steam's default gamepad layout (no keys) instead of the Kettle Video
  template. Kettle's layout gives the trackpads no job either
  (`docs/device-setup.md`, section 3). The designer chose not to test again.
  None of these dialogs is made for a controller, so even with the right
  layout, picking a folder with the D-pad may be slow or not fully
  possible.
- **"New folder":** the KDE and GTK dialogs offer a button to create a
  folder. Kettle never uses it, but a person could.

## Question 4: can mpv play from it

Answered by the storage spike (`docs/spikes/storage.md`, "Question 4"): on both devices
mpv is the Flatpak `io.mpv.Mpv` v0.41.0 with `host:ro`, so it can read the
whole system read-only, and it played a real video from the SD card and a
test clip from internal storage. Any folder these dialogs return on the SD
card or internal storage is playable. No new mpv check was needed.

## Recommendation

**Use a system dialog for "Browse somewhere else": kdialog first, then
zenity, then Tk**, whichever is found first on the device. Don't use the
desktop portal.

Why:
- kdialog, zenity and Tk work in **both** Desktop and Gaming Mode on the
  Deck, return the real path and hand the focus back. The portal doesn't
  show in Gaming Mode, and it needs the session-bus client above.
- They need nothing new: a program start and its output.
- kdialog first because it matches the system's own (KDE) dialogs and was
  among the quickest. zenity is next. Tk comes last because it looks the
  least like the system, and the part of Python it needs (`tkinter`) is
  missing on some systems.

**Risks:**
- **The controller may not fully work in these dialogs** (not confirmed,
  see "Question 3"). Touching the screen is enough to pick a folder, and
  the designer accepts that. Onboarding should still list the folders it
  finds as normal rows the controller can reach, so the dialog is only
  needed for the rare folder the list misses.
- **The Nova wasn't tested** (the designer's decision): it is assumed to behave
  like the Deck. Armada may lack kdialog or zenity, or may treat the
  second window differently in Gaming Mode. The fallback order and
  hiding the row when nothing is found cover a missing dialog; a dialog
  that opens behind Kettle would only show up in use.
- **The dialogs offer "New folder".** Kettle never creates folders, but a
  person could from inside the dialog.

**What onboarding part 1 needs to call it** (from `dialogs.py`,
`open_dialog`):
1. At start, look for `kdialog`, then `zenity` on the PATH, then check
   that `import tkinter` works and `DISPLAY` is set. No dialog found:
   don't show the "Browse somewhere else" row.
2. On the row, the server starts the dialog as its own program, in the
   request's own thread so the server keeps answering:
   - kdialog: `kdialog --title TITLE --getexistingdirectory START`
   - zenity: `zenity --file-selection --directory --title=TITLE --filename=START/`
   - Tk: a second `python3` process running
     `tkinter.filedialog.askdirectory` and printing the result (Tk must
     run on a program's main thread).
3. Read the path from its output (trimmed); exit code 1 or empty output
   means cancel. Check that the path is a folder before using it.
4. No time limit while it is open: the person may take a while. The
   page's focus comes back by itself when the dialog closes.
5. Use the home folder as START. Log only "picked" or "cancelled", never
   the path (privacy).

## Privacy check

The report and the spike's files were checked with the storage spike's
privacy check (`spikes/storage/privacy_check.py`): no card label, user name
or film, show or folder name from this Deck appears in them.

## Retroid Pocket Nova

**Not tested.** The designer decided on 2026-10-29 not to test the Nova and
to assume it behaves like the Deck (the folder dialog spike). The prompt for a Nova
Claude Code session is still on the folder dialog spike, if it is ever needed. Its
table would follow the Deck's above, and the recommendation stands unless
it shows otherwise.
