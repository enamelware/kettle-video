# Kettle Video

The shared Enamelware rules come from the handbook plugin (`enamelware@enamelware`); this file holds only what is specific to Kettle Video.

Kettle Video is a small, controller-first browser for local movies and TV shows, a thin layer on mpv that must feel native in SteamOS Gaming Mode. The repository is `enamelware/kettle-video`; folders, file paths and ids say `kettle-video`. The owner is a product designer who knows HTML/CSS: explain in plain language, keep changes small enough to review.

## Devices

The Steam Deck (SteamOS, x86) is the dev and first-test device; the Retroid Pocket Nova (Armada, ARM) is tested less often, so flag ARM or Armada risks on the issue ("Nova risk"). Test in Gaming Mode, not just Desktop Mode. Window: Firefox in kiosk mode (`launch.sh`); keep the UI independent of the window layer.

## Hard rules

- **Never commit anything from my devices, library or accounts.** The privacy guard (`tools/privacy_guard.py`) must pass before any commit or push; never bypass it (no --no-verify). Test data uses invented names only.
- **Sample library.** Running the app, examples and public screenshots use only the Blender open movies (`docs/sample-library.md`), with the credit line "(CC) Blender Foundation | studio.blender.org".
- **Media folders are read-only**, to the app and to Claude Code (reading them to test is fine). Stay inside this directory otherwise; never touch `~/.ssh` or credentials.
- **Kettle Video never goes online by itself.** Any request to the internet happens only when the user chooses an action that clearly says it will go online. Any future feature that needs the network must be user-triggered and must update the README's privacy statement first (the kiosk Firefox profile included: `docs/spec.md`, "Updates: never online by itself").
- **Backend:** Python standard library, plus only the unmodified packages in `vendor/` (`THIRD_PARTY_LICENSES.md`). Never edit `vendor/`.
- **Enamel** is vendored in `vendor/enamel/`, which must match the tag in `ENAMEL_PIN`; update it only with `tools/update_enamel.py`, in its own "Bring in Enamel" issue. Read `vendor/enamel/DESIGN.md` before interface work. All styling comes from Enamel; never hardcode a size it provides (read its token or measure). A gap goes on this repo's issue with the label `needs enamel`; nothing is written to Enamel's repo.
- **Do not reimplement playback.** Launch mpv as an external process and return when it exits; resume comes from mpv's saved state. mpv may be missing (e.g. on Armada): detect the system mpv, then the Flatpak (`flatpak info io.mpv.Mpv`), and show `flatpak install flathub io.mpv.Mpv`.
- **No layout is tied to a screen size, a device or an aspect ratio.** Layouts adapt to the space they get. Breakpoints come from the content and are named by what they do, never by a device or a size. Nothing in the code, styles, tests or docs names a screen size, a device or an aspect ratio as a layout target. The Steam Deck and the Nova are test devices, never targets. Facts about a device that aren't about its screen stay (for example mpv being a Flatpak on the Nova, or Armada's settings).

## Design rules

- Input is keyboard keys from Steam Input, the keys mpv uses (arrows, Space/Enter, q/Esc); no Gamepad API, nothing hover-only. Button-to-key table: `docs/device-setup.md`.
- Check every UI change across window widths, from Enamel's smallest supported box to very wide (screenshots).
- Class names and `data-` hooks are internal, but `docs/spec.md`, "Theming hooks", lists them all: update it in the same commit.
- Settings live in one JSON file, read through the backend. The app writes it only when onboarding saves the two folders and when Settings changes one kind's folder.
- Brand v0.1: Enamel's colours and single accent (vendored at 0.13.1 since the Enamel 0.13.1 upgrade); the loading screen wordmark "Kettle" in bundled Rubik Mono One, the only Mustard left. Details: `docs/spec.md`, "Brand v0.1".

## Library and architecture

Two folders (Movies, TV Shows) in `settings.json`; TV is show > season > episode; titles come from filenames only. The scanner, parser, library store, settings and mpv launcher form one backend (`backend/`), independent of the UI (`ui/`), so a later Decky plugin can reuse it. The filename parser is pure logic, tested from sample filenames.

## Screens

Today the app has a loading screen, first-launch onboarding (an mpv check when it's missing, choosing the Movies and TV Shows folders, then the first scan and its result screen), and one library screen with a Continue watching row above Movies and TV Shows tabs, where a show opens its episodes, and a Settings screen (Folders and About) opened from Home's menu. This is the target design once the detail screens are built: a Movies detail screen per movie, and the full onboarding and roadmap in `docs/spec.md`, "Roadmap".

Open questions, never decided alone: a controller-friendly folder browser, SD card removal and re-insertion, Flatpak permissions for Firefox and the installer, exact filename patterns, and which window shows the UI.

## License

GPL-3.0-or-later. Every new source file starts with this header, in its comment syntax:

```
SPDX-License-Identifier: GPL-3.0-or-later
Copyright (C) 2026 Mario Carabotta
```

## How we work

- Issues live on the "Kettle" board (`.claude/board.json`), changed only through `scripts/board.sh`; tests run only through `scripts/test.sh` (quick: name the browser checks for the screens touched; `full` before an L merges and before any release, see `docs/dev-environment.md`, "Release check"). /draft, /next and /tidy are in `.claude/commands/`.
- Commits reference the issue (`Refs #N`). Do not push without asking (/next and the "failed" phrase count as asking). `main` only ever holds finished, tested work: the test devices are updated by hand from it.
- Record decisions in `docs/decisions.md`. **Decide yourself**, without asking or stopping, when all of these are true: the choice can be undone with a git revert; you would recommend one option; no hard stop applies. If two options seem equal, pick the smaller one that is easier to undo. Then comment on the issue: "Decided: <what>. Why: <one line>. To change it, reply on this issue." and add the `decided` label, so I can review all of these together on the board. Real decisions still go in `docs/decisions.md`. A theming hook change decided this way updates its docs in the same commit (Design rules).
- An extra hard stop here: the issue and this file contradicting each other.
- Files behind the handbook's size limits (`enamelware:operations`, "Sizes"): the data folder (anything the app saves there, or how it finds it), the format of `settings.json`, design system tokens (`ui/css/tokens.css`, or any token value the app sets), `launch.sh`, the local web server (`backend/server.py`), privacy, and licences (`LICENSE`, `THIRD_PARTY_LICENSES.md`, `vendor/`).
- Claude Code runs every test, including runs against the real library (read-only, the paths in this device's `settings.json`). Never ask the owner to run commands.
- One issue per session (except /next all and /next N). When asked to continue or change #N, read it and its comments with `gh` first.
- "#N failed: <what happened>" (several numbers allowed): comment the feedback on the issue and move it to More to do; don't start fixing it.
- Delete your own memory notes with `scripts/forget-note.sh`, never rm.

## Public writing

The repo is public, so everything a visitor reads (README, `docs/`, `CHANGELOG.md`, code comments, tests, `.claude/`, issues, comments, commit messages) makes sense to a stranger.

- **Project voice**: "Kettle Video uses…", never "I", "we" or "you", and "the designer", never "owner". Instructions to Claude Code (this file, `.claude/`) may say "you", and keep their wording until a workflow issue changes it. Text addressed to the app's users (README usage steps, `CHANGELOG.md`, on-screen words) may say "you".
- **Devices** are named only as reference hardware: Steam Deck (SteamOS) and Retroid Pocket Nova (Armada).
- **Nothing private**: no personal paths, machine or login names, personal media or real titles, other email addresses, or references to private chats, documents, canvases or the private board. Example content is always invented.
- **No old issue numbers or commit addresses in files**: name earlier work in words ("the onboarding work"). Commit messages still say `Refs #N`. Issues are public tickets with /draft's headings. Past commits are never rewritten.
- Workflow terms are explained in `docs/how-this-repo-is-built.md`. Dev tools work on another machine or say what they need (`docs/dev-environment.md`, "On another machine").
- Checked by `tools/public_text.py`, part of `tools/release_check.py`.

## How to talk to me

Plans start with: what I will do (5 bullets at most), what changes for the user, what could go wrong, files touched (one line); end with each rule marked "respected" or "not respected". A decision offers 3 options at most, with a recommendation and one sentence why. No code, and file-by-file detail only when asked.
