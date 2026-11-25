# Changelog

What changes in each release of Kettle Video, newest first. The release
script (`tools/release.py`) takes a release's notes from its entry here: a
line `## <version>`, matching `VERSION` and the release tag `v<version>`,
and everything under it up to the next `## ` line.

This file starts at 0.1.0-dev (the release script work). Earlier history is in
`docs/decisions.md` and git's log.

## 1.0.0

The first public release.

- Browse the movies and TV shows on your device with the controller, in Gaming Mode, and play them in mpv.
- Films continue where you stopped them, and a Continue watching row shows what you're partway through, with the frame where you stopped.
- The first launch checks for mpv, asks for your Movies and TV Shows folders, and reads them.
- TV shows are in beta: each show opens one list of its episodes.
- Settings: change either folder, see the version and every third-party credit, and check for updates.
- Install, update and uninstall: `install.sh` installs in your home folder with no password, Check for updates then Update and restart updates from inside the app, and `installer/uninstall.sh` removes it and keeps your data unless you ask.
- Never online by itself: only Check for updates and Update and restart go online, when you choose them.
- A README for people using the app, a user guide, and screenshots.

## 0.1.0-dev

The first version built for installing, still in development.

- Browse local movies and TV shows with a controller, in Steam's Gaming Mode.
- First launch: checks for mpv, asks for the Movies and TV Shows folders, then scans them.
- Titles come from file names only; TV shows are grouped by show, season and episode.
- Films play in mpv and resume where they stopped; a Continue watching row lists what is in progress.
- Settings screen to change either folder.
- Release archive, checksum and release notes built by `tools/release.py` (for developers).
- A release check (`tools/release_check.py`, for developers) that fails if anything personal or private is in the repo or a release.
- Install with one command in Desktop Mode (`install.sh`, no password): app files, settings, data and logs in the home folder's standard places, an app menu entry with its icon, and an offer to install mpv from Flathub.
- Update by running the installer again with a newer archive: the previous version is kept until the new one starts cleanly, and comes back if it doesn't.
- Uninstall with `installer/uninstall.sh`: removes the app files, its menu entry and the app window's Firefox profile, and keeps your library, settings and logs unless you ask and confirm.
- Kettle Video never goes online by itself. Settings › About › Check for updates asks GitHub only when you choose it.
- Update and restart from Settings: downloads the newer version, installs it with the installer's own checks and rollback, and restarts in place without leaving Gaming Mode. A development copy gets Pull the latest version instead.
- A Privacy section in the README says exactly what goes online and when, and a bug report form on GitHub asks for what's needed to look into a problem.
- The repo is written for strangers: no old issue numbers or private links, a public-text check in the release check (for developers), and a "How this repo is built" page.
- A development copy (`install-shortcut.sh`) has its own app menu entry, "Kettle Video (dev)", so it and an installed copy never take over each other's.
