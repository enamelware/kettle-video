# Decisions

## 2026-09-29 — Cut onboarding, filename parsing, and TV hierarchy from the MVP

**Decision:** MVP is scan a configured folder on launch, list video files as plain text, play the selected file in mpv, return to the list. The media folder path comes from the settings JSON file. Onboarding, filename parsing, and the TV show > season > episode hierarchy move to post-MVP.

**Reason:** Testing is happening with pre-set SD card folders on the Nova and Steam Deck, so there's no need yet for a folder-picker onboarding flow, parsed titles, or a TV hierarchy — a flat file list is enough to validate the mpv launch/return loop on both devices.

## 2026-09-29 — MVP scans two folders grouped by folder; Continue watching moves to post-MVP

**Decision:** MVP now scans two configured folders (not one) and lists files grouped by folder. Continue watching joins onboarding, filename parsing, and the TV hierarchy as post-MVP.

**Reason:** Testing with pre-set SD card folders — the test setup has two folders to distinguish, and there's no resume/session tracking needed yet to validate the scan → list → play → return loop.

## 2026-09-29 — Milestone 2 implementation decisions

**Decision:** Settings live in `settings.json` (gitignored) with `movies_path`, `tv_path`, `mpv_command` (default `"auto"`); `settings.example.json` is committed with placeholders. Video extensions matched: mp4, mkv, avi, mov, webm, m4v, wmv, flv, mpg, mpeg, ts, m2ts. `backend/` is split into `settings.py`, `scanner.py`, and `mpv.py` — all pure logic with no HTTP awareness — plus `server.py` as the only module that touches sockets, so a future Decky plugin can reuse the core directly. mpv detection order: system PATH, then Flatpak `io.mpv.Mpv`; missing mpv shows an on-screen install hint instead of failing.

**Reason:** Matches the architecture note in `CLAUDE.md` (keep the core reusable/portable) and keeps the settings format simple enough to hand-edit for SD-card-based testing.

**Decision:** The dedicated Firefox kiosk profile is stored *outside* the project — `~/.mozilla/media-player-profile` for a system Firefox, or `~/.var/app/org.mozilla.firefox/data/media-player-profile` for a Flatpak Firefox (its own writable data dir). The launcher log stays inside the project, under `logs/`.

**Reason:** Per the designer's explicit rule to ask before writing anything outside the project folder or changing Flatpak permissions: keeping the profile inside the project would require a `flatpak override --filesystem=...` grant when Firefox is a Flatpak install, which the designer asked to avoid doing automatically. Using Firefox's own data directory needs no permission change at all. The designer confirmed this default when asked directly during planning.

## 2026-09-29 — Review round: non-blocking playback, request hygiene, dynamic port, Flatpak Firefox shutdown

**Decision:** `POST /api/play` no longer blocks for the whole film — it validates the request, starts mpv in a background thread, and returns immediately; a new `GET /api/status` reports `idle`/`playing` plus the last run's result, and the frontend polls it while showing a plain "Playing…" state.

**Reason:** A request held open for an entire film's runtime risks timing out in Firefox. Polling a small status endpoint avoids that regardless of film length.

**Decision:** The server now rejects any request whose `Host` header isn't `127.0.0.1:<port>`, and any `POST` whose `Content-Type` isn't `application/json`, both with `403`.

**Reason:** Basic hygiene for a server that's loopback-only but still reachable by anything running as the same user; costs nothing since the real client (Firefox navigating to `127.0.0.1:<port>`) already satisfies both.

**Decision:** `launch.sh` picks a free port automatically (asking Python for an OS-assigned one) if its preferred port is already in use, instead of failing to bind.

**Reason:** Avoids a stuck process from a previous run (or anything else on the device) silently preventing the app from starting.

**Decision:** When Firefox is the Flatpak build, `launch.sh` stops it with `flatpak kill org.mozilla.firefox` rather than killing the `flatpak run` wrapper's PID, and `launch.sh` now watches both the backend and Firefox (`wait -n`) so either one exiting stops the other.

**Reason:** Killing the wrapper PID doesn't reliably propagate into the Flatpak sandbox. **Caveat:** `flatpak kill org.mozilla.firefox` closes *any* running Flatpak Firefox on the device, not just this kiosk window — if the designer's everyday browser is also the Flatpak build and happens to be open at the same time, it would close that too. Documented rather than solved; not worth the complexity of isolating it further for a kiosk launcher.

**Decision:** (Logging part replaced on 2026-10-01, the mpv log fix: see "mpv logs" below.) mpv now runs with `--log-file=<path> --msg-level=all=info --really-quiet`, writing one log per playback to `logs/mpv-<timestamp>.log` (its own dedicated file, not mixed into the launcher's log), with the configured `mpv_args` prepended as a header line. Error responses from `/api/play` now carry a `log`/`log_tail` field instead of raw `stderr`.

**Reason:** `--log-file` captures mpv's own info-level messages (like which hardware decoder it picked) without the constantly-redrawn progress status line, which isn't part of mpv's logging pipeline at all — so the file stays small and readable by construction, and doubles as the source for error detail now that the terminal output itself is silenced. The new optional `mpv_args` setting lets the designer test flags like `--hwdec=auto` by editing `settings.json`, without touching code.

## 2026-09-29 — Forgiving settings paths, three-way "not found" reason

**Decision:** `movies_path`/`tv_path` in `settings.json` are cleaned up once on load (`backend/settings.py`): surrounding whitespace stripped, a `file://` prefix removed with `%20`-style escapes decoded, and a leading `~` expanded. Everything downstream — the scanner, playback, on-screen errors — sees only the cleaned path, and the UI always shows that cleaned path back, not the raw string from the file.

**Reason:** SD-card paths are easy to get wrong by hand or by pasting from a file manager (which may hand you a `file://` URI). Cleaning up once at the settings boundary, rather than in every consumer, keeps `scanner.py` and `mpv.py` simple and matches the "core stays reusable" architecture note.

**Decision:** `scanner.scan_source` distinguishes *why* a folder wasn't usable instead of a single generic "not found": `"does not exist"`, `"is not a folder"`, or `"permission denied"`, returned as a `reason` field on `ScanResult` (only present when `status` is `"not_found"`). Detecting permission denial needed an explicit `os.stat`/`os.listdir` check, since `pathlib.Path.exists()`/`is_dir()` silently swallow `PermissionError` and just report `False`.

**Reason:** A flat "folder not found" message doesn't tell the designer whether to check the SD card is inserted, fix a typo, or fix permissions — three different fixes needing three different messages, especially useful for testing on removable SD cards where "not mounted yet" and "wrong path" look identical otherwise.

## 2026-09-29 — License: GPL-3.0-or-later

**Decision:** The project is licensed under GPL-3.0-or-later (full text in `LICENSE`).

**Reason:** Resolves the open license question in `CLAUDE.md` (MIT vs GPL-3.0); the designer chose GPL-3.0. Keeping it open source and copyleft protects against closed forks — anyone who distributes a modified version has to keep it open too. Going with "or-later" rather than "-only" keeps the option open to dual-license the project while the designer remains the sole author, without needing to track down every contributor's permission later.

## 2026-09-30 — Name and brand direction: Kettle (v0.1)

**Decision:** The project is named Kettle. Wordmark: Rubik Mono One, plain one-line text (no stacking, shadow or line). Palette: Mustard & Sage. The font file will be bundled with the app, not loaded from Google Fonts. For now this is recorded as the target only: the code, README and `.desktop` entry keep "Media Player" and the current tokens until a later task applies the brand.

**Reason:** Gives the project an identity for the v0.1 release while keeping this change docs-only and easy to review. Bundling the font keeps the app fully offline, in line with the no-online rule. Rubik Mono One is under the SIL Open Font License, so it can be bundled in a GPL project. The brand is v0.1 and may still change.

## 2026-09-30 — Filename parser uses guessit, bundled in vendor/

**Decision:** The filename parser will use [guessit](https://github.com/guessit-io/guessit) 4.4.0, with our own rules added on top later. guessit and its dependencies (rebulk 6.0.1, babelfish 0.6.1, python-dateutil 2.9.0.post0, six 1.17.0) are shipped as an unmodified copy in `vendor/` at the repo root. `backend/vendor_path.use_vendor()` puts `vendor/` first on `sys.path`, so the bundled copy is used even when a different version is installed on the system. Nothing is installed with pip, at install time or at runtime. The versions, licenses and sources are listed in `THIRD_PARTY_LICENSES.md`. The `CLAUDE.md` "standard library only" rule now has an exception for these packages only. Any new dependency still needs the designer's approval.

**Reason:** In the parser spike (`~/Development/parser-spike/findings.md`), guessit handled the real Nova SD card files and the synthetic cases best. The alternatives were ruled out:
- **anitopy:** built for anime only, and it misses scene-style names (`Show.Name.S02E05...`).
- **parse-torrent-title (PTN):** cuts off episode titles.

Bundling instead of pip keeps the "no terminal in Gaming Mode" and "no install step" goals. All five packages are pure Python, so x86/ARM parity holds. Keeping the copies unmodified means anyone can check them against PyPI, or swap in a newer release.

**Licenses:** guessit is LGPL-3.0-or-later, rebulk MIT, babelfish BSD-3-Clause, six MIT, and python-dateutil Apache-2.0 / BSD-3-Clause (dual). All are compatible with this project's GPL-3.0-or-later. Each license file ships next to its package in `vendor/`.

**Python minimum raised to 3.10:** guessit 4.4.0 and rebulk 6.0.1 both declare `Requires-Python >=3.10`, so the README, `docs/dev-environment.md` and the `launch.sh` warning now say 3.10+ (it was 3.9+). The designer chose this during planning. It is still a warning in `launch.sh`, not a hard stop. The version on each device still needs confirming.

## 2026-09-30 — Single-name normaliser (parser chunk 2)

**Decision:** `backend/parser.py` has one function, `parse_name(name, kind)`, that turns one file or folder name into a `ParsedName` (title, year, season, episode, episodes, episode_title, raw, flags). The caller passes `kind` ("movie" or "episode", from the root the file is in) and it goes to guessit as its `type` option, so guessit never decides by itself. Rules on top of guessit:
- Only known video extensions (the scanner's list) are stripped, so folder names like `Example.Movie.1995.1080p` keep their last part.
- A name that is only `Season N` / `SNN` returns that season, an empty title and the flag `season-only`.
- Several episode numbers are kept only with an explicit multi-episode marker (`S01E01E02`, `S01E01-E02`, `1x01-02`). Otherwise the first is kept and the flag `extra-numbers-ignored` is added (same for a season range such as `S01-S03`).
- guessit's title is kept as is, case included. If it is empty or guessit fails, the title falls back to the name with dots and underscores as spaces and `[...]`/`{...}` tags removed, with the flag `fallback`. Parentheses are kept, since they usually hold a year or part of the name.
- A bad name never raises; a wrong `kind` raises `ValueError`, because that is a bug in the caller.
- guessit is imported on the first call, so importing the module stays fast.

**Reason:** The later folder-walking chunk needs one small, predictable result per name, and flags let it (and the designer) see which names need a look instead of hiding guesses. Known gaps are recorded as expected-failure tests in `tests/test_parser.py` and left for the next chunk: a number inside an episode title is lost (`Room 511` → `Room`, `The 100 Doors` → `The` plus an invented season 1), and `Dr.` loses its full stop.

## 2026-09-30 — Titles are rebuilt from the original text (parser chunk 3)

**Decision:** `parse_name` now calls guessit once in advanced mode, which gives the position of each match in the name. The episode title is rebuilt from the original text at that position, so full stops come back (`Meet Dr. Example`) and an episode number dropped by the extra-numbers rule comes back when it sits inside the title or right after it (`Room 511`). The main title uses the same rebuild but can only get its full stops back (`Dr. Example and the Thing`), and only in names with spaces. In dotted or underscored names, dots and underscores stay separators. A safety check keeps guessit's own value unless the rebuilt text has the same words once its full stops and recovered numbers are removed. So the rebuild can never produce a different title. `Room 511` keeps its `extra-numbers-ignored` flag, because putting `511` in the title is still a guess.

**Reason:** guessit strips full stops and reads numbers inside episode titles as extra episodes. The original text is the only reliable source, and positions let us use it without writing our own title parser. Advanced mode costs the same as normal mode on the Nova, and its values match normal mode for every fixture name.

**Year-in-title probes:** `Quillmoor 2051 (2017)`, `2003 Fernhollow Voyage 1971`, `1923 Brackenfold (2019)` and `Example.Show.2010.S01E03` all come out right from guessit as it is. They are recorded as tests, and no year rules were added. Still open: `Example Show - 03 - The 100 Doors` (episode title `The` and an invented season 1), kept as an expected-failure test.

## 2026-09-30 — Movie grouping rules (parser 4a, the movies parser work)

**Decision:** The Movies folder is grouped into movies by folder: a folder that directly holds videos is a movie (or holds several), and a folder with no videos is a container. When a folder holds one movie, its name gives the title and year; otherwise each file uses its own name. Several files become one movie with parts **only when every file has a clear part marker** (`Part 2`, `pt2`, `CD2`, `Disc 2`, ` - 01` at the end) and they share a title and year. Dot files, `._` files, `Sample` folders and non-video files are ignored. Links are followed only inside the root, each real path counts once, and unreadable folders are skipped and listed. The full rules are in `docs/spec.md` ("Movie grouping").

**Reason:** The issue's first rule, "same title once a trailing number is removed", would merge a movie and its sequel lying loose in a genre folder (`Example Movie` and `Example Movie 2`). The designer chose the stricter clear-marker rule during planning. guessit already drops these markers from the title (`Two Part Example - 01` → `Two Part Example`), but it doesn't give us the part number, so the number is read from the file name.

**Known limit:** a genre folder holding just one movie can't be told apart from a movie's own folder, so the movie takes the folder's name. It is recorded in a test and not guessed around.

## 2026-09-30 — Delivery workflow: /item, project permissions, push to main

**Decision:** `.claude/commands/item.md` adds a `/item <spec or sentence>` command. It creates a GitHub issue (writing the What / Watch for / Done when spec itself when given a single sentence), builds the item without asking for plan approval unless a stop trigger in `CLAUDE.md` applies, runs the tests, commits `Refs #N:` on `main`, pushes `main`, and reports in plain language. It never closes the issue; the designer does that after the device test. `.claude/settings.json` (committed) accepts file edits inside the repo, and allows the test command, everyday git commands (status, diff, add, commit, pull, push) and `gh issue` / `gh label` without prompting. It asks before force-pushing and before deleting files, issues or labels. It denies `sudo` and anything under `~/.ssh`. Reads and edits outside the repo still ask, which is Claude Code's default. `.gitignore` now ignores only the top-level `/settings.json` (the app's settings), so `.claude/settings.json` can be committed.

**Reason:** Fewer approval prompts for routine work. The designer chose to push straight to `main` so the Nova only has to pull `main` before testing. The tests run before every push, and the stop triggers still bring real decisions back to the designer.

## 2026-09-30 — Review board: /draft and /next replace /item

**Decision:** Work items now go through a GitHub Projects board named "Kettle", with Status columns Drafted, Approved, Building, Test on device, Done. `/draft <text>` writes one or more issues (anything bigger than `size:M` is split) and puts them in Drafted without building anything. The designer reviews them, leaves notes as comments and moves the ones to build into Approved. `/next [#N]` builds only an Approved issue: Building → test → commit `Refs #N:` on `main` → push → Test on device. "#N passed" moves it to Done and closes it; "#N failed: ..." moves it back to Building for a fix. The board's IDs are saved in `.claude/board.json` so the commands don't look them up each time. `.claude/settings.json` allows `gh project` commands but asks before deleting a project, item or field, or unlinking the repo. `/item` is removed.

**Reason:** `/item` wrote the spec and built it in one go, so the designer only saw the spec after the work was done. Splitting drafting from building puts the designer's review before any code changes, and the board shows at a glance what's waiting for review, for building and for a device test.

## 2026-10-01 — Staged device testing; automated tests owned by Claude Code

**Decision:** The board's Status columns are now Drafted, Approved, Building, Ready for testing, Tested on ND, Tested on NG, Done ("Test on device" was renamed to "Ready for testing", keeping its ID). ND is Nova Desktop Mode, NG is Nova Gaming Mode, and Done means also checked on the Steam Deck (Desktop and Gaming Mode). Claude Code owns all automated and command-line testing: unit tests, scripts and their output, read-only runs against the real library on the SD card, and timings, all before a card reaches Ready for testing. The designer only does exploratory testing on the devices (UI, controller, playback, Gaming Mode) and is never asked to run commands. `/draft` splits "Done when" into what Claude checks automatically and what the designer checks by eye; `/next` ends in Ready for testing with a comment listing what was verified and short exploratory checks per device. Phrases "ND ok #N", "NG ok #N", "Deck ok #N" (several numbers allowed) move cards along; "#N failed on ND|NG|Deck: ..." sends it back to Building and, after the fix, to Ready for testing. `.claude/settings.json` now allows running `backend` and `tests` modules, `ls`, `git log`/`show`, and reading (never editing) `/run/media`.

**Reason:** Device testing happens in stages, and the board should show which stage each item has passed. Anything a terminal can check is faster and more reliable when Claude does it, which leaves the designer's time for what only a person with a controller can judge.

## 2026-10-01 — TV grouping rules (parser 4b-1, the TV parser work)

**Decision:** The TV Shows folder is grouped as the issue describes: a folder with videos or season folders is a show, other folders are containers, loose root files are grouped by parsed title, the show title comes from the folder name (else the most common file title), the file name's season beats the folder's (flagged `season-mismatch`), shows with no season info are one flat list, multi-episode files are one entry, and unnumbered files are kept, flagged and listed last. Three details the issue left open: a season folder is one whose *whole* name is a season marker (`Season 2`, `S02`), using the name reader's existing `season-only` result; other folders inside a show are scanned like any folder, so a `Specials` folder becomes its own show until 4b-2; and files without a season in a show that has seasons go in a "no season" group after the numbered seasons. The movie scan's folder-listing code is now a shared `read_folder` function, so both scans use exactly the same ignore rules. The full rules are in `docs/spec.md` ("TV grouping").

**Reason:** Each detail is the most literal reading of the issue's rules, which keeps behaviour predictable and leaves specials to 4b-2 as planned. Sharing `read_folder` instead of copying it means a change to the ignore rules can't make the two scans drift apart.

**Known gap found on the real folder:** a number at the *start* of an episode title is lost by the name reader (`11 - 511 Example Place` gives `Example Place`). The episode number and position are right; only the title text is short. It is recorded as an expected-failure test and not fixed here, because this issue reuses the name reader unchanged.

## 2026-10-01 — Specials, duplicates and odd names (parser 4b-2, the specials and odd names parser work)

**Decision:** Specials folders (`Specials`, `Special`, `Season 0`, `S00`) become season 0, labelled "Specials" and listed after everything else in a show. A flat (absolute-numbered) show stays flat, with Specials as a separate section after it. A specials folder wins over a season in the file name, and the file is flagged `season-mismatch`; for normal season folders the file name still wins. Files in the same season sharing an episode number are all kept, flagged `duplicate` and listed by file name. Titles are joined to Unicode NFC (one letter per accent) for display, grouping and sorting; paths are never changed. Sorting stays a simple case-insensitive sort.

**Reason:** These were the planned readings written in the issue, and the designer approved it without changing them. Putting a file in a Specials folder is a deliberate act, while a season number in a downloaded file name often isn't. Keeping every duplicate means no file can disappear from the list. NFC fixes the macOS case without touching anything on disk. A language-aware sort (so `É` sorts with `E`) would need the system's locale data, which differs between devices, so it's left out for now.

**Found while building:** guessit handles Japanese, Korean and Cyrillic names and 255-character names fine. Two name-reader quirks were found and recorded as expected-failure tests, not fixed here because this issue reuses the name reader unchanged: a dot before the episode marker in a spaced name stays in the title (`Plain Example.S01E02` → `Plain Example.`), and some symbols are lost in a symbols-only name (`@#$%^&()` → `@ $%^&`).

## 2026-10-01 — Resume uses mpv's built-in saved positions (the resume work)

**Decision:** Kettle starts mpv with `--save-position-on-quit` by default, and with `--no-resume-playback --no-save-position-on-quit` when `"resume": false` is set in `settings.json` (a missing `resume` means `true`). Kettle stores no positions of its own and doesn't change mpv's save folder or any Flatpak permission. The mpv command is now built by one pure function, `build_command` in `backend/mpv.py`. An option the user already put in `mpv_args` is never added a second time, and the user's value wins.

**Reason:** CLAUDE.md says resume positions come from mpv's own saved state, and mpv already does this reliably for both the normal and the Flatpak install. Building our own storage would duplicate it and could drift out of sync with mpv. When resume is off, `--no-save-position-on-quit` is passed as well as `--no-resume-playback`, so a user's own mpv config can't save positions behind the setting's back.

**Checked on the Nova (Flatpak mpv 0.41):** quitting with `q` and closing the window both save; playing to the end saves nothing; a stop signal sent to the `flatpak run` wrapper is not passed on to mpv, so nothing is saved, while the same signal sent to mpv itself does save. A forced kill never saves. Positions live in `~/.var/app/io.mpv.Mpv/.local/state/mpv/watch_later/`, with "redirect" entries for the parent folders.

**Open question, not built now:** how to start a film from the beginning on purpose. It needs a second action in the list (for example a "Play from start" button), which is a UI decision for the designer.

## 2026-10-01 — "More to do" column; Approved renamed to Ready for dev

**Decision:** The board's Status columns are now Drafted, Ready for dev (was Approved, same ID), Building, More to do, Ready for testing, Tested on ND, Tested on NG, Done. "#N failed on ND|NG|Deck: ..." now only comments the designer's feedback on the issue and moves it to More to do; nothing is fixed straight away. `/next` always takes the top More to do issue first, addressing every point of the designer's latest feedback and saying in its comment what changed for each, and only then the top Ready for dev issue. `/next #N` works for issues in either column. Building only ever starts from those two columns.

**Reason:** The designer wants to collect feedback from device testing and decide when rework happens, rather than having a fix start the moment a failure is reported. Clearing sent-back work first keeps half-finished issues from piling up behind new ones.

## 2026-10-01 — Resume starts 5 seconds early (the resume work, designer feedback)

**Decision:** A resumed film starts 5 seconds before its saved position (never before 0). This is done by a small Lua script shipped with Kettle, `backend/mpv_scripts/resume_rewind.lua`, passed to mpv with `--script` only when resume is on. At mpv's `on_load` step, after mpv has applied the saved position but before playback starts, it moves the start back. A start set on the command line or in mpv's config is not a resume and is left alone. The 5 seconds is fixed for now, not a setting.

**Reason:** The designer asked for it after testing on the device. mpv has no option for this. Doing it inside mpv keeps Kettle out of mpv's save files (no need to know where they live or how they are named), works the same for the normal and Flatpak mpv, and causes no visible jump because the position is changed before the first frame. The Flatpak mpv can read the script because it has read-only access to the whole device (`host:ro`). Lua is not a new dependency: it is built into mpv (checked in the Flatpak 0.41 build).

**Trade-off:** opening and closing a film without watching moves its saved spot 5 seconds earlier each time. Accepted as harmless; noted in the README.

## 2026-10-01 — Brand v0.1 colours in the app (the Brand v0.1 work)

**Decision:** The ten Mustard & Sage colours are added as tokens, and the existing colour names now point to them, so existing snippets keep working. The usage rules are in `docs/spec.md` ("Brand v0.1"). Summary: Ink page, Surface rows, focus is a Raised fill plus a 3px Sage ring with a 2px Ink gap, Snow text, Fog secondary text, errors in Cream on Brick (never Brick text), Line for decoration only, and Mustard and Sage never used alone to tell two states apart. The focused row is lifted above its neighbours so the ring is never covered, and rows keep a small scroll margin so the ring isn't cut off at the edge of the screen. Neither changes the layout.

**System font, not DM Sans:** the brand checkpoint names DM Sans for text, but the app keeps the device's system font. Bundling a second font adds weight and a licence file for little gain on small screens, and loading it online is against the no-online rule. Only the wordmark font (Rubik Mono One) is planned to be bundled, in a later issue.

**"Folder not found" is an error:** the issue asked for no JavaScript change, but that message shared one plain status line with "no video files found", so styles alone couldn't tell them apart. The designer chose a one-line change: the status line gets `data-state="error"` when a folder can't be read, and it is styled Cream on Brick. This is a new, documented snippet hook; no existing hook changed.

**Measured contrast** (all pass): Snow 13.1 to 16.1, Fog 6.4 to 7.8, Ink on Sage 10.7, Ink on Mustard 8.8 (the brief said 8.9, a rounding difference), Sage ring 8.7 to 10.7, Cream on Brick 4.8. Line against Raised is 1.2 to 1, not 1.4 as in the brief; it is decoration only, so nothing changes.

## 2026-10-01 — Changes go to main before device testing, until v0.1

**Decision:** `/next` keeps pushing to `main` once the automated tests pass, before the designer tests on the devices. `main` is the working copy, not a "tested only" branch. From the v0.1 release, users get marked release versions that contain only changes that passed device testing.

**Reason:** The Steam Deck gets new code by updating from `main`, so testing there needs the change on `main` first. One branch per issue would mean switching branches on the devices, by command, in Desktop Mode, and gets messy when several issues are in testing at once. The repo is private and has no users yet, so an untested change on `main` only affects the designer. Considered and rejected for now: a branch per issue merged after "Deck ok", or after "NG ok".

## 2026-10-01 — The browser must check for newer UI files (the Brand v0.1 work, designer feedback)

**Decision:** The backend sends `Cache-Control: no-cache` with every answer, so Firefox asks the app on every load whether a page, style or script file has changed. Unchanged files still answer "not modified", so loading stays fast. This is a one-line backend change, approved by the designer as an exception to the Brand v0.1 work's "no backend change" rule.

**Reason:** After the Brand v0.1 work was pushed, the designer saw no colours on the Nova. The launch logs showed why: since 29 September the kiosk Firefox had mostly not asked for the page or its styles at all, and reused its cached copies. Python's file server sends only a "last modified" date, so Firefox guesses how long a file stays fresh (a share of its age) and skips asking until then. Every future look change would hit the same problem.

**Catch:** copies Firefox cached before this change carry no such instruction, so they can still be reused until Firefox's own guess runs out (a few hours at most here), or until a forced reload. After the first fresh load, the problem does not come back.

## 2026-10-01 — One copy at a time, and Firefox gets time to close (the start-up fix)

**Decision:** `launch.sh` holds a lock (`logs/launch.lock`, through `flock`) for as long as it runs. A second launch while one is open or starting writes one log line and stops; it doesn't start Firefox or bring the open window forward. On quit, Firefox is asked to close and gets up to 15 seconds before it is forced (was 1 second). The backend logs `page loaded N s after launch` the first time the page talks to it, and if Firefox closes without that line ever appearing, the launcher logs that the app's Firefox profile may be damaged. It only detects and logs; it doesn't reset the profile itself (open question).

**Reason:** On 2026-10-01 the designer hit "Firefox is already running, but is not responding" and "Firefox closed unexpectedly while starting", and then the app wouldn't open until its profile was moved aside by hand. The logs showed several copies started within seconds of each other on the same profile. The 1-second limit was also suspected, but a headless Firefox closes in about 0.4 s, so it's not proven; 15 seconds is a cheap safety margin for a real window on a slow device. `flock` is part of util-linux, a base system package on SteamOS and Armada, and the lock is released by the system however the launcher ends, so there's never a stale lock to clean up.

**Not changed:** the Flatpak Firefox path still stops Firefox with `flatpak kill`, which closes every Flatpak Firefox window and doesn't give it time to close. The Nova has no Flatpak Firefox to test a change on. The designer chose to leave it as is and watch the Steam Deck tests; it becomes its own issue only if it causes problems there.

## 2026-10-01 — mpv logs: the app writes them from mpv's output (the mpv log fix)

**Decision:** mpv no longer writes its own log file (`--log-file`). It prints its messages (`--quiet --msg-level=all=info,vd=v --msg-module`), and the backend copies them line by line into the same `logs/mpv-<timestamp>.log`, after the same first line naming the `mpv_args`. Progress-line output is dropped, and a log stops growing at about 1 MB as a safety limit. `vd=v` adds detail for the video decoder only: about 15–40 lines when a video opens, saying which decoder ran and whether hardware decoding worked.

**Reason:** On the Nova the logs were empty apart from their first line. The Flatpak mpv can read the home folder but not write to it, and mpv fails quietly when it can't open its log file. Copying mpv's output works the same for a system mpv and the Flatpak, needs no permission changes, and the failed-playback hint (which quotes the end of the log) gets real text to quote. On the Nova, a 3-second and a 20-second test clip both gave a 3 KB log, so it doesn't grow during playback.

**Rejected:** giving the mpv Flatpak permission to write into the app's folder (it changes a setting outside the app, on every device); leaving it as is (it blocked the skeleton hardening round's hardware-decoding question and made bug-report logs useless).

## 2026-10-01 — Loading screen and the bundled wordmark font (the loading screen work)

**Decision:** The app opens on a loading screen with the Kettle wordmark until the library arrives. The wordmark font, Rubik Mono One, is bundled unmodified in `ui/fonts/` with its licence file, and loaded only from there. The designer approved the download at build time.

**Licence check:** Before downloading, the licence file in the official Google Fonts repository (`google/fonts`, `ofl/rubikmonoone/OFL.txt`) was read: SIL Open Font License 1.1, Copyright 2015 The Rubik Project Authors. The OFL allows the font to ship with a GPL app as long as it keeps its own licence, which ships next to it. The font is not trimmed or changed, so the Reserved Font Name rule (which covers modified versions) doesn't apply. Both files are byte-for-byte the copies in that repository (checked against the repository's own file fingerprints); `tests/test_loading_screen.py` checks the font's fingerprint.

**Choices inside the brief:**
- **No minimum display time.** On a small library the screen may only flash; a minimum would slow every launch.
- **A failed library read** now shows the existing error banner with "Couldn't read the library." Before, the page stayed empty with no message.
- **Keys work from the start.** The key handler is set up before the mpv check, so q quits during the loading screen and on the "mpv not found" screen. Before the list arrives there are no rows, so only quit does anything. That made the separate quit-only handler for the "mpv not found" screen unnecessary; it's still in `keyboard.js`, unused, because this item doesn't change key handling.
- **The font file is served as-is.** Python's file server on SteamOS doesn't know the `.ttf` type and sends it as generic data. Firefox doesn't need the type for fonts, so the backend isn't changed.

**Reason:** Before, the page showed "Movies" and "TV Shows" headings with nothing under them until the list arrived, and nothing at all if reading the library failed.

## 2026-10-01 — Interim parsed library view (the parsed library view)

**Decision:** The app now shows the library the way the parser reads it (films and shows, with an episode list per show) instead of the plain file list, through a new `/api/library/parsed` answer that the backend builds once per app run and keeps in memory. It's a temporary bridge, replaced by the library index and API items. Details: `docs/spec.md`, "Parsed library view (interim)".

**Reason:** The designer needs to check the movie and TV grouping (the movies parser work, the TV parser work, the specials and odd names parser work) on the devices, in the real app, before the index is built on top of it.

**Choices inside the brief:**
- **The loading screen from the loading screen work is the "Loading library…" state.** The brief predates the loading screen work; showing a second, plain loading message would be a step back. The screen stays up until the first scan is done.
- **The answer holds no device paths,** so for a missing folder the page asks the old `/api/library` for the path to keep today's "folder not found" message word for word. That only happens when a folder is missing.
- **After playing, no rescan.** The list is remembered (that's the point of scanning once); the focus goes back to the row just played. The plain fallback list still rescans after each playback, as before.
- **Rescan keeps your place:** the same show stays open and the same row stays focused, if they still exist. Playing is paused for the few seconds a rescan takes, so the list can't change under a film that's starting.
- **Show counts add specials** ("2 seasons, 24 episodes, 1 special"), so the counts match the folders when compared by eye. Episode labels: "S02E05", "S01E01-E02" for a double episode, "73" with no season, "Special", and "?" when there's no number (with the "unnumbered" note).
- **The parser is imported only when the library is first asked for,** so an old Python or a broken `vendor/` gives the fallback sentence instead of stopping the app. `use_vendor()` runs at server start, as asked.

**Rejected:** building the display strings in the page (the later API and a Decky plugin would have to repeat them); scanning on every page load (slow on a big card, and the page reloads after nothing else).

## 2026-10-01 — Development moves to the Steam Deck

**Decision:** The Steam Deck (x86, SteamOS, 16:10) is now the dev and first-test device; the Retroid Nova (ARM, Armada, 4:3) is tested less often. Board columns after Ready for testing: Tested on DD (Steam Deck Desktop Mode), Tested on DG (Steam Deck Gaming Mode), Done (also checked on the Nova, Desktop and Gaming together). Phrases: "DD ok", "DG ok", "Nova ok", "#N failed on DD|DG|Nova". The two Status options were renamed in place (same option IDs), so no card lost its column; the loading screen work, which had passed Nova Desktop Mode, went back to Ready for testing with a comment saying so.

**Reason:** Development now happens on the Deck. Testing there first is quicker, but ARM-, Armada- and 4:3-specific problems will surface later, so /next adds a "Nova risk" line to an issue whenever a change might behave differently on the Nova, and Claude Code checks UI changes at 4:3 itself (browser window sizes, screenshots).

*Replaced on 2026-10-22 by "No layout is tied to a screen size, a device or an aspect ratio" (the responsive layout work) for the screen: the devices are no longer layout targets, UI changes are checked across a range of window widths, and "Nova risk" keeps only its non-screen parts.*

## 2026-10-01 — Loading screen stays at least 2 seconds (the loading screen work)

**Decision:** The loading screen stays up for at least 2 seconds at launch, even when the library is ready sooner. Until it goes, the list underneath ignores the arrow and play keys; q still quits.

**Reason:** The designer couldn't see the screen: on the real library it only flashed. The issue offered a minimum time as an option, and the designer asked for 2 seconds. Blocking the other keys stops a film from starting behind the screen.

## 2026-10-01 — Saved library (the saved library work)

**Decision:** The library is saved to `data/library.json` after a full scan and loaded at launch. **The app never scans at launch; it scans only when asked** (Scan my folders, the Rescan library row, or r). Quick rescans of only what changed and handling of files that have disappeared come in the next item. Details: `docs/spec.md`, "Saved library".

**Reason:** Launching becomes instant on big libraries (the real library on the Deck's card: 1.3 s to scan, about 1 ms to load), and the saved file is the base for quick rescans and missing-file handling.

**Choices inside the brief:**
- **IDs:** the first 16 hex characters of the SHA-1 of `<source>:<relative key>`. A film's key is its folder, **except when that folder holds several films, or the film sits loose in the Movies folder**: then it's the film's first file, so two films never share an ID. A show's key is its folder, or its title for loose files. Renaming or moving a file makes a new item; accepted for now, it matters for "Continue watching" later.
- **The file stores grouping results, not display strings,** so wording changes (labels, counts) don't need a rescan.
- **A folder that isn't there during a scan keeps its saved items** (if they were saved for the same folder path), so a rescan with the card out removes nothing.
- **Progress moves in two steps** (films done, then shows done). Finer progress would need changes to the grouping code, which this item doesn't touch.
- **At launch the first film has the focus**, not the Rescan row above it, so A still plays straight away.
- **A section never scanned, or whose folder path changed, says "Not scanned yet".** The brief only covers the case where nothing at all is saved; without a line, an empty section would look like an empty folder.
- **Log lines name the kind of error only,** never its text, since that can hold a full path.

**Rejected:** scanning at launch in the background (it is what makes big libraries slow to open, and the brief asks for scans only when asked); saving the page's display strings (a wording change would need a rescan).

## 2026-10-02 — The launcher follows only its own Flatpak Firefox (the saved library work, the Firefox crash fix)

**Decision:** With the Flatpak Firefox, `launch.sh` now asks Flatpak for the ID of the sandbox it starts (`--instance-id-fd`) and watches that sandbox, not the `flatpak run` command. To quit, it asks Firefox inside that sandbox to close and gives it up to 15 seconds; only then does it force that one sandbox shut (`flatpak kill <instance>`). It never runs `flatpak kill org.mozilla.firefox` any more. With a system Firefox, if the Firefox it started has gone but another one is open on the app's profile (Firefox restarted itself), it follows that one. This replaces the "Not changed" note under the start-up fix.

**Reason:** Both bugs had the same cause. `flatpak kill org.mozilla.firefox` closed every Firefox window on the Deck, including the designer's own browser (the Firefox crash fix), and it forced the app's Firefox shut without letting it save. After such a forced close, Firefox restarts itself once at the next start: the first copy ends and a new one takes over inside the same sandbox. The `flatpak run` command ends with the first copy, so the launcher thought Firefox had closed after 1 second, stopped the app and force-closed everything again. That loop is why the app wouldn't open after the first library load (the saved library work). Seen in the launch logs of 2026-10-01 22:56 and reproduced with the real profile.

**Rejected:** resetting the Firefox profile (it treats the symptom, and the next forced close brings it back); stopping the `flatpak run` command's process (a stop signal isn't passed into the sandbox, see the start-up fix).

## 2026-10-02 — Developer auto-update at launch (the developer auto-update)

**Decision:** With `"dev_auto_update": true` in a device's `settings.json`, `launch.sh` runs `backend/dev_update.py` before starting the app. It fast-forwards the git copy to its upstream branch and gives up after 5 seconds without an answer. After an update, the launcher starts again (`exec`) from the new `launch.sh`, keeping the same log file and launch start time. The page shows the result for 8 seconds and the build id for the whole session, in a corner box that takes no focus. The option is left out of `settings.example.json` and documented in `docs/device-setup.md`.

**Reason:** The Nova is tested less often, and it should always run the latest push without a terminal. Fast-forward only means a device with local edits or a different history is never changed: it says "Couldn't update" and runs what it has. Starting again from the new script avoids running half-old, half-new launcher code. The quick text check for the setting in `launch.sh` means nothing extra runs when it's off: launches were timed the same (median 0.40 s to page loaded, before and after). The update step runs with the launcher's lock file closed, so an `ssh` left behind by a timeout can't hold the lock (on a timeout, git's whole process group is stopped anyway).

**Choices inside the brief:** the note shows for 8 seconds, so it is still readable after the 2-second loading screen. The box sits in the bottom-right corner, with the page keeping that strip free so a focused row never scrolls under it. Git asks no questions (`GIT_TERMINAL_PROMPT=0`, ssh `BatchMode`), because no one can answer them in Gaming Mode.

**Rejected:** `git pull` (it can merge and stop on conflicts); downloading builds without git (more code, and the test devices are git copies anyway).

## 2026-10-02 — The app's Firefox never asks about Safe Mode (the saved library work, designer feedback)

**Decision:** the app's Firefox profile gets `toolkit.startup.max_resumed_crashes = -1`, which switches off Firefox's "Firefox closed unexpectedly while starting" question. `launch.sh` now writes the profile's `user.js` at every launch, not only when it is missing, so settings added later reach existing profiles. `user.js` belongs to the app; changes made to it by hand are overwritten.

**Reason:** the designer hit the message again after the saved library work and the Firefox crash fix. Firefox counts starts it considers unfinished and asks about Safe Mode once the count passes 3. The app's starts kept adding to it: hard closes did, and so did a clean open and quit with Firefox hidden (seen going from 3 to 4 on the real profile). The message waits for an answer that can't be given with a controller, and the app never opens. A damaged profile is still noticed: the launcher logs when Firefox closes without opening the app.

**Not verified:** a hidden Firefox never shows this message, so the tests check that the setting is in place rather than that the message stays away.

## 2026-10-02 — /next has every build checked by two agents before it reaches the designer

**Decision:** after building and testing an issue, /next hands the uncommitted change to two project agents (`.claude/agents/`): **test-checker**, then **reviewer**. Each returns PASS or FAIL with a numbered list. On a FAIL the builder fixes the problems and both run again, at most two fix rounds. Only two PASS verdicts let the issue be committed and moved to Ready for testing, and both verdicts go into the issue comment. Still failing after that, or a problem only the designer can decide, makes the issue Blocked.

- test-checker may only write inside `tests/` and run the tests; reviewer may only read (plus read-only `git` and `gh issue view`). A small guard, `.claude/hooks/agent_guard.py`, enforces this on every tool call they make, not just the instructions.
- The checks run before the commit, so a failing change never lands on `main`.

**Reason:** the builder checking its own work misses things a fresh look catches: an acceptance point quietly left out, a test that would still pass if the feature broke, something visible beyond the spec. Fresh agents with narrow permissions give a second opinion without being able to "fix" by changing the app themselves.

**Note:** reviewer also needs `git status` and `gh issue view` (to see new files and read the issue), not just `git diff`; both are read-only.

## 2026-10-02 — /next is safe to interrupt: one branch per issue, a progress comment, resume first

**Decision:** /next and /next all can now stop at any moment (usage limit, closed session, the Deck turned off) and carry on later. Each issue is built on its own branch `issue-N` from the latest `main`. Work in progress is committed and pushed there at checkpoints: after the plan, after the main code change, and after fixes from each round of checks. Only when test-checker and reviewer both pass and the full suite passes on the final code is the branch squashed into a single `Refs #N` commit on `main`, pushed, and deleted. Each issue has one progress comment, edited in place at every checkpoint. Every run starts by looking for unfinished work (Building cards, `issue-N` branches, uncommitted changes, unpushed commits) and continues it from the progress comment, always re-running both checking agents and all tests before merging. Each step first checks whether it already happened, so a resume never duplicates a comment, commit, merge or board move. In /next all, each issue is built by its own fresh helper agent; the main session keeps only the queue, the agents' verdicts and the summary. The full procedure is in `.claude/commands/next.md`.

- **Squash, not a merge commit:** `main` keeps one commit per issue, as before, and never shows the half-done steps.
- **Work-in-progress commits are named `WIP issue-N: ...`, without `#N`,** so they don't flood the issue's timeline with references.
- **The plan checkpoint is an empty commit;** the plan itself lives in the progress comment, where both the designer and a resumed run can read it.
- **A blocked issue keeps its work** on its parked branch instead of throwing it away; /next continues from it once the label is removed.
- **The checking agents can't start agents themselves**, so in /next all the main session runs them and passes their verdicts to the builder.
- **Unclear state is never "repaired":** the branch is left exactly as it is, the issue is blocked with a plain explanation, and the run moves on. Uncommitted changes that don't belong to an issue branch stop the whole run.
- `.claude/settings.json` allows the branch commands this needs (switching, merging and deleting `issue-*` branches, fetching, editing issue comments through `gh api`) and asks before any `gh api` delete.

**Reason:** long batches can be cut off by a usage limit, a closed session or the Deck turning off. Before this, an interruption could leave half-done work in the project folder, with nothing to say where it stopped. The Nova's auto-update pulls `main`, so unfinished code there reaches a test device. This keeps the 2026-10-01 rule that changes go to `main` before device testing: the branch only lives until the automated checks pass, so no device ever has to switch branches.

## 2026-10-02 — Clicks and taps select the row that A plays (the click-then-Enter fix)

**Decision:** the app's note of the selected row now follows the browser's focus, whatever moved it (arrow keys, a click, a tap). While the app is busy (loading screen, "Playing…"), a press is cancelled before the browser can move the focus, and if the focus moves anyway it is put back.

**Reason:** before, only the arrow keys updated the note, so a click highlighted one row while A played another. Following the focus, instead of handling clicks separately, keeps one rule for every way a row can be selected; the keys and controller work exactly as before.

## 2026-10-02 — Home shell colours: slate base, Sage focus, Mustard for progress (the Home shell work)

**Decision:** the dark olive backgrounds of Brand v0.1 give way to slate greys: black bars, a flat #343843 page, #3F4553 rows, #4A5163 for the focused row, #585D69 for the selected tab, #22252E for progress tracks, and a lighter Fog (#BCC0C9) for secondary text. Snow, Mustard, Sage, Cream and Brick stay, plus white for text on the selected tab.

- **Token names (the designer's answer on the issue):** the current `--color-*` names stay and the slate ones are added next to them; nothing is renamed or removed. `--color-surface`, `--color-raised` and `--color-line` now point to the slate shade that replaced each olive one, so existing snippets keep working, while the app's own styles use the new names. The issue's "`--kettle-` names" were not used, because the tokens have always been `--color-…`.
- **Ink stays (the designer's answer)** as the one dark text colour, for text on Sage buttons (10.7 to 1).
- **Sage focus ring:** 3px with a 2px gap on anything focused, rows and tabs alike; it stays at least 4.6 to 1 against every background it sits on.
- **Mustard for progress only,** on the dark track. **Exception (the designer's answer):** the KETTLE wordmark on the loading screen stays Mustard.
- **Focused-row text rule:** on a focused row every line is Snow, never Fog, because Fog on the focused-row shade is only 4.35 to 1, under the 4.5 needed for text.

**Reason:** a navigation layout inspired by Steam reads best in neutral slate, which also lets Sage and Mustard stand out as accents. Every pair is checked by `tests/test_brand_colours.py`. Only colour and layout ideas are taken from Steam: no logo, icons or artwork, and nothing suggests Valve endorses Kettle.

## 2026-10-02 — Home shell layout: tabs and focus (the Home shell work)

**Decision:** the focus starts on the selected tab, and the Rescan row heads both tabs' lists, so Down from the tabs lands on it first. The tab strip stays on screen inside a show (with TV Shows selected), so Up from the first episode reaches the tabs too. Each list's own heading is hidden on screen (kept for screen readers and snippets), since the tab names the list. The developer box moved up to sit above the hint bar.

**Reason:** the spec puts the focus on the tabs and keeps the Rescan row where it was in the list; one place for the tabs on every library screen keeps the keys the same everywhere. A visible "Movies" heading under a "MOVIES" tab repeats itself and costs rows at 4:3.

## 2026-10-02 — Name reader fixes: numbers in titles, stray dots, symbols, accent sorting (the name reader fixes)

**Decision:** the five known gaps are fixed in `backend/parser.py`, and their expected-failure tests are now normal tests.
- **Numbers in episode titles:** a number guessit reads as an extra episode, or as a season after the kept episode, joins the episode title when it sits inside it or touches it (`511 Example Place`, `The 100 Doors`). When guessit split a number (`100` read as season `1`), the whole run of digits is taken. When such a number cut the title short, the plain words after it come back too, but only plain words: anything with brackets or tags keeps guessit's own title. A number that joins the title no longer counts as a season, so `The 100 Doors` stays in a flat show. The existing safety check still applies: the rebuilt title must have guessit's words once its numbers and full stops are removed.
- **Stray dot:** in a name with spaces, a dot glued to what follows (`Plain Example.S01E02`) is a separator; a dot followed by a space (`Example Inc. S01E02`) is still a full stop.
- **Symbols-only names:** when guessit's title has no letters or digits, the name itself is kept (spaces tidied).
- **Accent sorting:** `title_sort_key` sorts by the title with accents removed (Unicode NFKD), ignoring case, then by the title itself, so the order is stable. Movies and shows use it; titles keep their accents for display. Grouping of loose files and episode file-name order still ignore case only.

**Reason:** each fix uses positions guessit already reports, so no new title parser is written and the safety check limits what can change. On the real TV folder only episode 11 changed (`Example Place` → `511 Example Place`, names invented); the Movies folder is unchanged. Accent sorting uses only Python's own Unicode data, because the device's language settings differ between the Nova and the Steam Deck: close enough, not right for every language (`ß`, Scandinavian letters).

## 2026-10-02 — Quick rescans, missing items and Remove (the quick rescan and Remove work)

**Decision:** a rescan reads again only the names of files that are new or changed (by size or modified time); every other name reuses what the saved library says. **A scan never removes anything:** a file that has gone while its folder is still there is kept, marked missing, until the designer confirms "Remove them". A folder that isn't there at all (SD card out) is **not available**, which is different from missing: that section is skipped, nothing in it is marked missing, and its saved items stay as they were. Scans are refused while mpv plays. Details: `docs/spec.md`, "Saved library".

**Reason:** reading one name takes about 8 ms on the Nova, so big libraries need the reuse. Keeping missing items until a confirmed Remove means a slow or half-mounted card can never quietly empty the library. Scanning while a film plays takes processing power the Nova needs for smooth video.

**Choices inside the brief:**
- **Small change to the grouping code:** `scan_movies(root, parse=None)` and `scan_tv(root, parse=None)` take one optional name reader. Without it they behave exactly as before, and their tests are unchanged. The saved library passes a reader that hands back saved results for names it may reuse and calls the real parser for the rest. Results are saved per name (`"movie:<name>"`, `"episode:<name>"`), folder names included, since the grouping reads folder names too; a name is read again whenever a file with that name is new or changed.
- **One order rule:** films and shows are put in order by one shared rule (`library_order` in `backend/parser.py`, title then year), used by the Movies and TV grouping and by the saved library, so a missing film sits where a fresh scan would put it. The grouping's results don't change.
- **Which files the scan sees** is listed before grouping with the same folder-reading function as the grouping, so the two always agree.
- **A folder inside the library that can't be read** (as opposed to the whole Movies or TV Shows folder): its films and episodes are kept as they were, not marked missing. This counts the folder listing before grouping and the grouping's own listing, since the card can go between the two.
- **The whole Movies or TV Shows folder can't be listed** (any read error, not only "permission denied", at the start, while listing, or while grouping): that section is "not available" for this scan, exactly like a card that is out. Never everything missing. Keeping the saved library safe in every other card-pulled case is the pulled card fix.
- **A single film whose file is gone keeps its ID.** If a new file appears in the same folder (a rename), it shows as a new film keyed by its file, so the two never share an ID; once the missing one is removed, the next scan keys it by its folder again. A film with several parts where some are gone stays one film: "1 of 2 parts missing", and A plays its first part that is still there.
- **What "N missing items" counts:** a whole missing film or show is one item; otherwise each missing part or episode is one.
- **The question "Remove N missing items?"** replaces the library on screen, with Cancel focused first; B is Cancel too. Afterwards the focus goes to the Rescan row.
- **Pressing A on a missing show** shows the same "File not found. Rescan or remove it." sentence as a missing film, as the brief says for any missing item.
- **The summary line stays** under the Rescan row until the next scan (it is saved with the library), and resets its missing count after Remove.
- **Saved names follow the name reader (the designer's answer, option 1):** each source saves `names_version`, a short code worked out from `backend/parser.py` and the bundled guessit and rebulk version files. When it differs from the running app's, the rescan reuses no saved names and reads every name again once (about 1 second on the Deck's card), then reuses them as usual. The code is worked out from the files rather than a number someone has to remember to raise, so no name reader change can be missed; a change that doesn't affect results (a comment, say) only costs one slower rescan. Rejected: a separate "Full rescan" row (another row, and you'd have to remember it) and leaving it as it is (seeing fixes would need deleting `library.json`, impossible in Gaming Mode). Films and episodes already marked missing keep the titles they had, since their files can't be read.
- **The saved file keeps format version 1:** the new fields are optional, so a library saved by the previous version loads, and its first rescan reads every name once.

**Rejected:** reusing a name's result regardless of whether its file changed (the brief asks for changed files to be read again); marking a whole section missing when its folder can't be read (that is exactly the card-out case to avoid); a Remove per item (not in this item).

## 2026-10-02 — Names that can't be read as text are skipped, never renamed (the unreadable name fix)

**Decision:** while listing a folder, the scan checks that each video's or folder's name can be written as plain text (UTF-8). If not, that entry is skipped and listed with "name can't be read", with each unreadable character shown as a replacement mark (�), and the scan goes on. Other files with such names are ignored like any other non-video. The check lives in the folder reader the Movies and TV scans share (`backend/library_movies.py`). Every skipped path is stored in that safe form.

**Reason:** one such name used to stop the whole rescan, because the item ID and the saved library both need plain text (audit finding H8). Renaming the file would fix the name but media is read-only. Guessing the old encoding (often Latin-1) could show the right letters, but the guess is often wrong and the play path would still need the raw name; skipping keeps the rest of the library working and tells the user which file to fix. A skipped folder takes its contents with it, the same as a folder that can't be read.

## 2026-10-05 — Held A and B count as one press (the held button fix)

**Decision:** the page ignores the automatic repeats of a held key (the browser marks them as repeats) for A (Enter, Space) and B (q, Esc) only, both in the library and on the "mpv not found" screen. The arrows still repeat. d and r are left as they were, since the issue only covers A and B.

**Reason:** acting on every repeat made a held A open a show and then play its first episode, and a held B go back and then quit (audit finding H5). Ignoring repeats in the one place keys are read keeps the fix small. It relies on Steam Input sending a held button as one key held down; if a controller type sends separate presses instead, they can't be told apart from real presses (a Nova risk to check by hand).

## 2026-10-05 — Plain messages for settings mistakes (the settings mistakes work)

**Decision:** a broken `movies_path` or `tv_path` (not text, or empty), a settings file that can't be read or isn't UTF-8 text, or one that isn't a `{ … }` list of settings stops the backend with one plain sentence naming the setting. A broken `mpv_command` (not text, a quote that isn't closed, or a program that can't be found on the PATH or at its full path) doesn't stop the app: the mpv check reports it, and the page shows it on the "mpv not found" screen with a hint to fix it or set it to `"auto"`. If the mpv check itself fails or doesn't answer within 30 seconds, the loading screen gives way to a plain message on that same screen. `null`, an empty or blank `mpv_command` and `"auto"` all still mean "find mpv". A UTF-8 file with the invisible start marker some Windows editors add is accepted.

**Reason:** these mistakes used to give a raw Python error, or leave the loading screen spinning, or (an empty folder path) quietly scan the app's own folder (audit finding H4). Folder paths are needed before anything can be shown, so they stop the app, as other bad settings already did; the message reaches the screen once the start-up problem screen is built. The mpv command only matters when playing, so the library app can still start and say what's wrong. Checking the program up front means a wrong command is caught before Play instead of after; the play-time message from the stuck Playing fix stays for a program that disappears or can't start after the check.

## 2026-10-05 — The checking agents' guard: what it can and can't enforce (the agent guard fixes)

**Decision:** the guard (`.claude/hooks/agent_guard.py`) now lets the checking agents use `git status`, `git diff`, `git log` and `git show` only with a list of known display options (such as `--stat`, `--name-only`, `--oneline`, `--format=…`), instead of allowing anything after the command name. Every other option is refused, including `--output` (writes a file), its short spelling `--out`, `--ext-diff` and `--textconv` (run other programs) and `--no-index`. Options git reads before the command name (`git -c …`, `git -C …`) are refused too, as are `$` variables, braces, wildcards and backslashes, which the shell could turn into a refused option after the guard has looked. For the issue itself, only `gh issue view N`, `gh issue view N --comments` and `gh issue view N --json <fields>` (title, body, comments, labels, state) are allowed; both agents are now told to use `--json body,comments`, because `--comments` alone prints nothing in this setup, so they had only been seeing the comments, never the "Done when". The guard has its own tests (`tests/test_agent_guard.py`).

**What it can enforce:** which shell commands the two agents run, one at a time with nothing chained, piped or redirected; that reviewer changes no files; that test-checker writes only inside `tests/` (links that point out of `tests/` count as outside).

**What it can't enforce:**
- **test-checker can run code it wrote.** It may write a script in `tests/` and then run it as a test, and that script could change app code or anything else the user can change. This is a limit of the approach, not a bug: running tests is test-checker's job, and a test is code. The safety net is that the builder only commits files it checked (`git status` before every commit), and the reviewer sees every change on the branch.
- **Reading is not limited.** Read, Grep and Glob can open any file the user can; the guard only watches commands and file writes. "Stay inside the project" for reading remains an instruction in the agent definitions.
- **git's own settings.** A diff or text-conversion program set in the repository's git settings or `.gitattributes` would still run on `git diff`. The agents can't change those settings, but a change on the branch to `.gitattributes` could; the reviewer would see it in the diff.
- **The allow-list may be too narrow.** An agent asking for a harmless option that isn't listed gets a refusal naming what is allowed, and carries on without it. Add an option only after checking in git's manual that it can't write a file or run a program.

**Reason:** the old guard checked only the start of each command, so `git diff --output=<file>` could overwrite any file and `--ext-diff` could run another program (audit finding H9). Listing the safe options is shorter and safer than chasing every risky one, since git keeps adding options and accepts abbreviations.

## 2026-10-05 — mpv Flatpak already reads the SD card; no permission change needed (the docs catch-up)

**Finding:** checked on the Steam Deck from the terminal, read-only (no setting changed), with the Flathub mpv Flatpak `io.mpv.Mpv` 0.41.0 (x86_64, stable):
- `flatpak info --show-permissions io.mpv.Mpv` lists `filesystems=…;host:ro;…`: read-only access to the whole device, which includes `/run/media`, where SteamOS mounts the SD card.
- `flatpak override --show io.mpv.Mpv` and `flatpak override --user --show io.mpv.Mpv` are both empty: no one added a permission on this Deck, so this is the Flatpak's standard setup.
- Inside the Flatpak's sandbox, the Movies folder on the card could be listed and a TV episode's first bytes read (`flatpak run --command=…`).

**Decision:** the 2026-10-01 entry above ("Resume starts 5 seconds early") was right: the mpv Flatpak can read the whole device. `docs/device-setup.md` no longer tells users to add a `flatpak override --filesystem=…` permission. The on-screen hint after a failed Flatpak playback ("may not have filesystem permission … Check Flatpak permissions") was misleading for the same reason. With the designer's OK (the docs catch-up, 2026-10-06), a failed Flatpak playback now shows the same hint as a system mpv: "Check that the file isn't corrupted or in an unsupported format."

**Reason:** a doc that asks users to change a permission they already have sends them on a needless fix in Desktop Mode, and away from the real cause (usually a damaged or unsupported file, shown in the mpv log).

**Nova risk:** not checked on the Nova here. The Flathub build is the same for ARM, so `host:ro` should be there too, but Armada might mount cards somewhere other than `/run/media`; `host` covers `/media` and `/mnt` as well. A user who removed the permission themselves would still need it back.

## 2026-10-06 — Fewer approval prompts: narrow allow rules and wrapper scripts

- **What:** the repeated /next operations go through three small scripts: `scripts/test.sh` (all tests and browser checks), `scripts/board.sh` (board moves, labels, progress comments, adding a card; only this repo and the Kettle project, IDs from `.claude/board.json`) and `scripts/branch-done.sh` (deletes a finished `issue-N` branch only when `main` on GitHub holds the same files). `.claude/settings.json` allows those scripts, read-only git, the git steps /next uses (named branches only, never force), and `gh issue view/list/create/edit/comment`.
- **Why:** most prompts came from chained commands (`cd … && export … && …`), pipes and loops, and from raw `gh api` / `gh project` calls that need broad rules to cover. A wrapper validates its own arguments, so one narrow rule is safe.
- **Still asks:** force push, pushing to another branch name (`a:b`) or deleting with push, `git reset --hard`, `git branch -D`, deleting files, installing anything, any `gh` call naming another repo, raw `gh api`/`gh project`/`gh label`, and edits to the settings files.
- **Denied:** `sudo`, reading SSH keys, gh or Claude credentials and other secret files, and file-tool edits under `/run/media` (the SD card).
- **Limits:** permission rules match command text, not what a program does. A shell command can still write under `/run/media` if it is allowed for another reason; the app's own code never does (see the audit's media safety notes). `git branch -d` can't be used: /next squashes branches, so git never sees them as merged; that is why `branch-done.sh` checks the files instead.
- Shared rules are in `.claude/settings.json` (committed, both devices). `.claude/settings.local.json` is for device-only rules and is empty for now; its old `rm` allow was removed so deleting always asks.

## 2026-10-06 — Keep the device awake during playback (the keep-awake work)

- **What:** mpv is started under `systemd-inhibit --what=idle --who=Kettle --why="Playing a video" --mode=block` (`backend/keep_awake.py`; it asked for `idle:sleep` until the power button fix, see below). The tool holds the system's stay-awake lock for exactly as long as the command it starts. mpv is also always given `--stop-screensaver=yes`, so its own screensaver blocking stays on even if mpv.conf turns it off (an option the user sets in `mpv_args` still wins, as for every other default). A new `keep_awake` setting (default `true`; a file without it behaves as `true`) turns the lock off.
- **Why this tool:** it ships with systemd on SteamOS (and most Linux systems, likely Armada too), needs no new dependency and no permission, and ties the lock's life to the player's process, so there is no "release" step that a crash could skip.
- **Lock always ends** (checked on this Deck with the Flatpak mpv 0.41, 2026-10-06): normal quit or end of file, mpv killed (crash), and the lock tool itself stopped (as when Steam closes the app) all leave no Kettle lock in `systemd-inhibit --list`. In the last case the Flatpak mpv keeps playing until it ends, because the Flatpak wrapper doesn't pass the stop message on (see the README's Resume section), but without the lock, so the device is never left unable to sleep.
- **Tool missing or not working:** before each film the tool takes the same lock around `true` (a few milliseconds), so a lock the system refuses (a session or permission rule, possible on Armada) is caught before it could stop mpv from starting; if the tool is missing or that test lock fails, mpv runs unwrapped and the mpv log (and the launch log) says so. A missing mpv is still checked before wrapping, so the screen keeps its plain "mpv could not be run" message (the stuck Playing fix).
- **Limits:** version 1 keeps the device awake for as long as mpv is open, including while paused (a paused film overnight drains the battery). Knowing play vs pause needs the live mpv connection planned for Continue watching. Steam's own Gaming Mode dim and sleep timers may ignore the system lock; the README tells users where to change them (Settings → Power). Not done: a Decky plugin, changing Steam settings from code.
- **Step 0 diagnostics (temporary):** each mpv log lists `systemd-inhibit --list` a few seconds after start and every 60 seconds (`media-player: locks:` lines). **Remove** the marked section in `backend/keep_awake.py`, the two "Step 0" lines in `mpv.play()`, their test and the README bullet once the designer has confirmed on the Deck and the Nova, in Gaming Mode, that the lock is held and the device stays awake.
- **Nova risk:** Armada may lack `systemd-inhibit` or handle the lock differently; the "tool missing" path then applies, and its Gaming Mode timers are untested.

## 2026-10-06 — Three-digit anime numbers (the three-digit episode fix)

- **Decision:** after guessit reads a name, a bare three-digit number that follows a dash (`Show - 112`, `Show_-_098`) and that guessit split into a season and an episode is read whole, as one absolute episode with no season (`backend/parser.py`, `_absolute_numbers`). Leading zeros are fine (`- 007` is episode 7). Names where guessit already reads it right (a tag after the number, as in `- 124 [720p]`) are untouched.
- **Why only after a dash:** "space dash space number" is how anime releases write absolute numbers, while scene-style names pack season and episode without a dash (`Show.Name.112.HDTV`, `Show Name 112`). Those keep guessit's season 1, episode 12, and are now tests too. A show that really means S01E12 and writes `Show - 112` would now read as episode 112; no such name was found in the samples or the real library, and the issue asks for the anime reading.
- **Checked:** the real TV folder on the SD card gives exactly the same shows, seasons and episodes before and after (it has no three-digit names). Parser timing is unchanged (about 8.3 ms per name on this Deck, before and after).
- **Still open:** four-digit numbers (`- 1012` stays season 10, episode 12), and `- 112 - The 100 Doors` (unchanged: guessit reads the title's `100` as the season and episode). Both are listed in `docs/spec.md`.

## 2026-10-06 — SD card pulled out during a rescan (the pulled card fix)

- **What:** nothing new in the app. The protection was already built with the quick rescan and Remove work: a Movies or TV Shows folder that can't be listed at any point of a rescan (card out before, pulled while its files are being listed, or pulled before they are grouped) is "not available", its saved list is kept exactly as it was, and the other folder is still scanned as usual. A folder *inside* a working card that can't be read is listed as skipped and its items stay as they were. The pulled card fix adds tests that prove each of these (`tests/test_library_rescan.py`).
- **Empty folder left behind:** on SteamOS the card is mounted by the system at `/run/media/<user>/<card name>`, and the settings point at folders *inside* it (`…/Movies`, `…/TV Shows`). Even if an unmount left an empty mount folder behind, `Movies` inside it would not exist, so the section reads as "not available", never as "available but empty". Only a source set to the card's top folder itself could look empty; then its items would be marked missing (kept, with "Missing"), never removed, since only a confirmed Remove deletes ("A scan never removes anything", above).
- **Nova risk:** not checked on the Nova. Armada may mount cards elsewhere (`/media`, `/mnt`) or leave a folder behind differently; with the source folders inside the card, the outcome is the same. Worth a look: pull the card mid-rescan on the Nova and check the list keeps its items with "Folder not available".

## 2026-10-07 — Movies list: letter jumps, letter strip, every row drawn (the Movies list work)

- **Left and Right jump by letter inside the Movies list.** They did nothing inside a list before, so nothing is lost; on the tab strip they still switch tabs. Right goes to the first film of the next letter that has films, Left to the first film of the previous one; empty letters are skipped and there is no wrapping round, so a press at either end does nothing rather than throwing you to the other end of a long list. From the Rescan or Remove row, Right goes to the first letter. The TV Shows tab and the episode list keep Left and Right as they were (other issues will change them).
- **The letter strip is touch only.** It shows which letters have films and lets a finger jump there, but the controller never lands on it: Left and Right already jump by letter, and a strip that took the focus would need its own way in and out. It is marked with bold text and a snow bar beside the current letter, not Mustard (Mustard is kept for progress bars) and not colour alone.
- **Every row is drawn, no "draw only what's visible".** Drawing only the rows on screen is much more code (scrolling, focus and touch all get harder). It is only worth it if measured to be needed: the rule was to stop and report if 2,000 rows took over 300 ms on the Steam Deck. Measured times are in the issue and in `docs/spec.md` ("Movies list").
- **Order and groups in the back end** (`backend/library_order.py`), so they can be tested without a browser and a future Decky plugin gets the same order. Groups come first (#, A to Z, other), then the title ignoring capitals and accents, then year, then ID. A title starting with a symbol that would otherwise sort between letters (such as `~`) sits under #, so every group is in one piece. Plain alphabetical order, with no special handling for a leading "The", "A" or "An" (*replaced by the title sorting work, see below*).
- **Ø, Ł, Æ, Đ count as their nearest plain letter** (the designer's choice on the issue). Ø, Ł, Æ, Đ, ß, Œ and Þ are Latin letters but not "accented letters" to Unicode, so they first landed in "other" after Z. Now they count as O, L, A, D, S, O and T, both for the letter group and for the order inside it, because someone looking for "Ørsted" looks under O, the same way É already counts as E. One letter each (Æ as A, not "AE"), so the group and the order always agree. Rejected: keeping them in "other" (they look out of place at the end), and Danish/Norwegian-style groups for Æ, Ø, Å after Z (more complex, and their order would differ from other languages). Only the Movies list uses this; it lives in `backend/library_order.py`.
- **The page's library answer is a contract.** It gained two fields per film, `sort_index` and `letter`, and nothing else; the page takes the year off the end of `display_title` instead of asking for a new field.
- **Films play by ID.** The page sends the film's ID and the back end finds the file (its first part that is there), so the list never needs a file location to play. Episodes and the plain-list fallback still play by relative path. Nothing about how mpv starts changed.
- **Focus doesn't jump.** A focused film shows its whole title, so rows change height as the focus moves; the keyboard code keeps the newly focused row where it was on screen, then makes sure it is wholly visible.

## 2026-10-07 — Sorting ignores a leading The, A or An (the title sorting work)

Replaces the "plain alphabetical order" part of the Movies list work entry above (kept there, marked as replaced).

- **A leading "The", "A" or "An" is ignored for sorting and for the letter group**, so "The Mossbrook" sits under M and the T group no longer swells. The title on screen never changes. Only one article is dropped, once ("The The" stays under T), only when it is followed by a space (so "A.I." stays under A) and only when a letter or digit follows ("The" alone stays under T). Titles are folded first (capitals and accents), so "THE MOSSBROOK" counts too.
- **English only.** Le, La, El, Der, Die, Il and so on are not dropped: they clash with words in other languages ("Die Fernhollow" could be English, "La" is French and Spanish), and a wrong guess hides a film under a letter nobody would look under.
- **One rule, in the name reader** (`title_without_article` in `backend/parser.py`). The Movies list (`backend/library_order.py`) and the order of films and shows (`library_order` in the name reader) both use it, so "The Oakhollow" sits under O on the TV Shows tab too. Equal titles then go by the full title with its article ("The Thistlecombe" before "Thistlecombe", always), then year, then ID.
- **Shows are put in order again when the page asks for the library**, as films already were, so a library saved before this change shows the new order straight away, without a rescan. Shows still have no letter groups, and the Ø, Ł, Æ rule from the Movies list work stays Movies-list only.


## 2026-10-07 — Continue watching (the Continue watching work)

- **6 items**, the most recently stopped first. A seventh pushes the oldest off (its picture is deleted); it comes back only the next time it is stopped, so a tile never reappears with an old picture when another leaves.
- **Remove has no question and keeps the resume position.** X takes the tile away at once and deletes its picture. Resume positions are mpv's own (see "Resume uses mpv's built-in saved positions"), and nothing in Continue watching ever touches them, so the film still resumes from the list and comes back to the carousel the next time it is stopped.
- **Missing items stay and are labelled.** A tile whose file is marked missing, or whose folder isn't there right now (card out), keeps its place with a dark grey frame and "Missing"; A shows the same sentence as a missing row. Removing missing items from the library also removes their tiles and pictures.
- **The finished rule: 95% watched, or played to the end.** Resume has no rule of its own (mpv saves nothing at the very end and knows nothing else), so this is Kettle's. "Watched at least 60 seconds" is read as "stopped at 60 seconds or later": Kettle only knows where you stopped, not how long you watched.
- **Where the pictures live:** `<data_dir>/thumbnails/` (`data/thumbnails/` by default, excluded from git with the rest of `data/`), one JPEG per tile, about 480 px wide, named after the item's ID. Never inside a media folder: if `data_dir` is set inside one, no pictures are saved or deleted there. Picture names and contents never go into a log; mpv's own "Screenshot: '<file>'" lines are left out when the app copies mpv's messages into the mpv log. The README says so.
- **How the frame is taken:** option 1 of the mpv quit spike: a small mpv script on B (`backend/mpv_scripts/quit_capture.lua`), writing into a fresh folder under `/tmp` because the Flatpak mpv can't write into the app's folder. The full-size frame is shown straight away and replaced in the background by the small picture, which mpv makes after it has closed, so the return to the list is never slowed by it. Only files of the saved library, and only with `resume` on: with resume off there is no carousel.
- **The controller's X sends Backspace** (the designer's choice). In mpv, Backspace only resets the playback speed to normal, so a stray press during a film changes nothing visible; Delete would toggle mpv's on-screen controls and `x` would shift subtitle timing. Added to `docs/device-setup.md`.
- **Focus after a film depends on where it was started** (the designer's choice). From a tile: back to the carousel, on the item just watched (now first), else the first tile, else the tabs. From a list row: back to that row, as before (the Home shell work, the Movies list work), so you keep your place in the list.
- **The carousel shows only above the library lists**, not inside a show's episodes, so Up from the tabs there does nothing, as before. A film's tile shows its title without the year.

## 2026-10-08 — Firefox stays; a web view only with a Flatpak (the webview spike)

- **Kettle keeps Firefox kiosk mode.** A Python-opened web view is reconsidered only if Kettle is packaged as a Flatpak (the designer's choice, on the spike report `docs/spikes/webview.md`). Inside a Flatpak the web view comes with the runtime and works the same on every device; before that, the only route that worked on the Steam Deck (pywebview with Qt from pip) adds 546 MB of compiled, processor-specific code on top of Kettle's 6.8 MB, and its PyQt licence would tie Kettle to GPL version 3 only.
- **Deck-only report.** The Nova half of the spike was dropped (the designer's choice): the Nova will be tested as part of the Flatpak work. No follow-up issue.
- What the web view would gain, for when the Flatpak work starts: Home ready in 0.8 s instead of about 2.3 s, and about 370 MB of memory instead of 570 MB, on the Deck. What to watch: the focus ring and the keys only work while the web view is the active window, so it must become active again after mpv quits in Gaming Mode.

## 2026-10-08 — Where videos live, Steam Deck half (the storage spike, spike)

Report: `docs/spikes/storage.md`. These are proposals for the onboarding design, not final; the Nova half (entry of 2026-10-09 below) confirms them and adds what differs on the Nova.

- **Find cards and drives from the system's own list of mounts** (`/proc/self/mountinfo`), and tell an SD card from a USB drive or internal storage from the hardware path in `/sys`. Standard library only. The "removable" flag is not used: the Deck's SD slot reports itself as not removable.
- **Show "SD card", "USB drive", "Internal storage"**, not the card's label, which is user data and often meaningless.
- **Internal storage means the home folder.** Never walk into hidden folders, Steam, emulator, Decky or junk folders (list in the report). On the Deck this skips Steam's 196 GB install and a card's Steam library, and the search takes milliseconds.
- **Suggest the folder that holds the films or shows** ("Films"), never each film's folder; split a parent holding two collections; suggest the card itself when videos sit at its top; drop folders of short clips; look 6 levels deep at most. On the real card it finds exactly the two folders in `settings.json`.
- **No progress message needed on the Deck**; worth designing a short one anyway for the Nova and slow cards.
- **mpv:** the Deck's Flatpak mpv has read access to the whole system (`host:ro`), so it plays from the card and the home folder; nothing needs changing.
- **A card that is "there but unreadable" means "not ready yet", not "empty"** (card out / card in, 2026-10-09). On the Deck the card comes back at the same place with the same name about 2.7 s after insertion, and for a moment before that its folder exists but cannot be read. Onboarding and the library should wait and look again rather than report no videos. A search running when the card is pulled ends at once with nothing found; it never hangs.

## 2026-10-09 — Where videos live, Nova half (the storage spike, spike)

Report: `docs/spikes/storage.md` ("Retroid Pocket Nova", "Differences between the devices"). The Deck entry above holds on the Nova too: same card place, same rules, same two suggested folders, same Flatpak mpv with `host:ro`, a search never hangs when the card is pulled.

- **Armada does not open a card that is put back in.** The system sees it, but it stays closed until the user opens it by hand; there is no file manager in Gaming Mode. How Kettle should handle this is **not decided**: it belongs to the open question "SD card removal and re-insertion handling" (options in the report: a plain message, Kettle asking the system to open the card, or leaving it to the installer).
- **A card's folder existing does not mean the card is there.** On the Nova an empty folder stays where the card was. Kettle should treat a card as present only when its folder is in the system's list of mounts.
- **Find hardware through the named device when the number is a placeholder.** The Nova's internal storage (UFS, btrfs) hides its device number; the spike now looks up the named device instead, so internal storage, cards and USB drives are told apart on both devices.
- **No progress message strictly needed on either device** (worst case 0.92 s on the Nova for a 432-folder card with nothing in memory); a short one is still cheap insurance.

## 2026-10-09 — Closing the app while a film plays (the server shutdown check)

Results of every way of closing: the server shutdown check (Steam Deck, Desktop Mode by Claude Code, Gaming Mode by the designer).

- **A playing film stops and keeps its place** (option A, the designer's choice). Before the server stops, it asks mpv to quit normally, as B does, so mpv saves its resume position and the Continue watching frame, and the server keeps the stop before it goes. Before this, closing the window or the app's own Quit left mpv playing full screen with no app behind it. It waits at most 2 seconds for mpv, so the server is still gone within about 2 seconds.
- **The app asks through mpv's control socket**, not a stop signal: a signal sent to the Flatpak's `flatpak run` wrapper never reaches mpv (the start-up fix, the mpv quit spike), while the socket works the same for the system and the Flatpak mpv. The socket lives in a fresh folder under `/tmp`, the one place the Flatpak mpv can write.
- **The frame is taken however mpv closes**, not just on B (the designer's Gaming Mode feedback: no picture after "Exit game"). The quit script now also takes the frame just before mpv lets go of the film, which happens on a stop signal, the window closing and the app's quit request alike. Checked with the real Flatpak mpv: a stop signal still gives the frame, and mpv closes in about 0.1 s. Only a forced kill saves nothing.
- **When closing, the full-size frame stays the picture**: the small one takes about 0.4 s to make, which would eat into the 2 seconds. It is replaced the next time the film is stopped.
- **`launch.sh` is unchanged.** The rare case where the launcher itself is killed (server and window stay, Kettle won't start again until they are closed) stays as it is (the designer's choice; option B would have changed `launch.sh`).

## 2026-10-09 — Playback controls (the playback controls work)

What each button does: `docs/spec.md`, "Playback controls".

- **mpv's built-in control bar is off.** It is crowded and made for a mouse; Kettle shows only mpv's own on-screen text and progress bar when a button is pressed.
- **Everything is given to mpv at launch** (options, Kettle's key file, a wording script), never written into mpv's settings folder, so Kettle can't break the designer's own mpv. The designer's `input.conf` is replaced while Kettle plays; `mpv.conf` and mpv scripts are still read (reported on the issue, not decided).
- **Every default mpv key is off**, so a stray press does nothing. That includes keys people may expect from mpv (fullscreen, screenshot, volume); listed in the spec.
- **The button layout:** A play/pause, B stop, D-pad and left stick 10 s, L1/R1 1 minute, X subtitles, Y audio, D-pad Up where am I, everything else nothing. Buttons follow Steam's names, which go by position (A = bottom face button), because the layout lives in Steam, which names buttons the same way on the Deck and the Nova whatever is printed on them.
- **New keys for the layout: Y = a, L1 = j, R1 = l.** Letters, because they do nothing in Kettle's list or in Firefox (Page Up / Page Down would scroll the page), and are easy to find in Steam's key picker. X keeps Backspace: Remove in the list, next subtitle in mpv.
- **The Continue watching script takes q and Esc with forced bindings.** With mpv's default keys off, a normal script binding is switched off too; forced ones are not. The key file also binds q and Esc to a plain quit for when that script isn't passed.
- **One tap to play or pause is the only touch control for now.** Double clicks are switched off, so two quick taps never toggle fullscreen.
- **A small script of Kettle's writes the wording** ("Paused", track names, "No subtitles in this file", "Only one audio track"), because key bindings alone can't check what the file holds. No third-party control layers (such as replacement control bars) are adopted yet.
- **On-screen text size 40** in mpv's scale (about 44 px on the Deck, 5.5% of the screen height): mpv 0.41's default of 30 is small at arm's length on a 7-inch screen.
- **D-pad Up shows Kettle's own title** (the designer's choice A, 2026-10-09), not the file name, which is often unreadable (`Some.Movie.2019.1080p…`). Kettle passes the title to mpv at launch (`--force-media-title`), with the year as in the Movies list and the part or episode as on the Continue watching tiles. A `--force-media-title` in the designer's `mpv_args` still wins. Files outside the saved library keep what mpv shows on its own.

## 2026-10-09 — The app takes its styling from kettle-ui, vendored (the first design system step)

- **The app's styling comes from kettle-ui**, the designer's own design system, vendored at **version 0.3.1**: both stylesheets, `DESIGN.md`, `VERSION`, `LICENSE` and `NOTICE.md`, copied unchanged into `vendor/kettle-ui/`. The reasons for restyling every screen with it come with part 4 (the last design system step).
- **Licence: MIT** (the designer's answer on the first design system step). It fits with GPL-3.0-or-later and is listed in `THIRD_PARTY_LICENSES.md`. Its notice covers the values that match Valve's Steam client styles.
- **Same folder layout as kettle-ui** (`tokens/`, `components/`), so paths in `DESIGN.md` stay true and the update script copies each file to the same place.
- **Updated only by `tools/update_kettle_ui.py`**, which copies just the files that changed and prints the old and new version. It reads `~/Development/kettle-ui` and never writes there. The copies are never edited by hand (rule in CLAUDE.md).
- **The server sends the two stylesheets at `/vendor/kettle-ui/…`**, and nothing else under `vendor/`: the page is served from `ui/`, and moving the copies into `ui/` would mix vendored and own files. Only those two exact paths are answered.
- **Loaded before the app's own stylesheets.** Every kettle-ui name starts with `kt-` / `--kt-`, and the app uses none, so nothing looks different yet (checked by screenshots at 16:10 and 4:3).


## 2026-10-09 — The frame and simple screens move to kettle-ui (the second design system step)

- **kettle-ui's classes sit next to the app's own** (`tab kt-tab`, `hint-bar kt-hintbar`…), so the documented snippet hooks keep working; nothing was renamed.
- **The rows are left for the third design system step**, including the Rescan row: they are the same list row everywhere, and restyling some of them here would give the app two row looks at once. Until the third design system step the rows keep the Sage ring and their own text colour and size, while the tabs have kettle-ui's accent ring.
- **Scan my folders, Cancel and Yes, remove stay as they are for now** (the designer's choice on the second design system step, 2026-10-09), with their old look and the Sage ring. The remove question's two buttons get their own issue, the picker confirm work.
- **The page colour role `--color-bg` now points to `--kt-surface-page`**, so the page-coloured gap in the rings the app still draws matches the new page.
- **Errors are strong text on the raised surface with a red bar at the start**: kettle-ui has no message component, and neither white nor dark text reaches 4.5:1 on its red. Plain messages ("Playing…", "Rescanning…") use the same surface without the bar.
- **The tabs' ring shows on any focus**, not only keyboard focus as in kettle-ui, because the D-pad moves the focus onto the tabs (L1 and R1 don't switch tabs). Their gap is `--kt-space-gap`, wider than kettle-ui's, so the ring isn't covered by the other tab.
- **The hint bar and top bar keep the shell's height** (6% of the screen, at least 40px) rather than kettle-ui's 60px bar, so the lists keep their room.
- **The wordmark keeps Mustard, its size and PLAYER's spacing**: kettle-ui has no brand tokens, and the issue asks that only the colours around it change.
- **Spacing moved to the nearest kettle-ui token** (for example the side gutter is 36px instead of 24px, so the rows are a little narrower), since the issue asks for no spacing or type size outside the tokens on these screens.
- The gaps found are listed in `docs/spec.md` ("Design system: frame and simple screens") and on the issue.


## 2026-10-09 — Continue watching tiles share a bottom edge (the tile alignment work)

- **The tiles stand on one bottom line, like Steam's Recent games row**, so the row reads as one shelf and the large tile rises above the rest.
- **Built with a two-line grid** (frames, then captions), each tile spanning both lines (a CSS "subgrid"), so the tiles' class names and the page's structure stay exactly as they were; only the stylesheet changed. Firefox has supported this since 2019, on both devices.
- **Small tiles keep their name where it was, under the frame**, now on the same line as the large tile's caption. The issue says small tiles "keep their title"; putting the name over the picture would change their look, which the issue rules out (layout only), and the third design system step restyles the tiles anyway.
- **Built before the third design system step** (the designer's batch order): the third design system step restyles the tiles and must keep this layout; the browser check `tests/continue_row_layout_check.py` measures it, so a change that loses it fails.


## 2026-10-09 — Lists and Continue watching move to kettle-ui (the third design system step)

- **Every library row becomes kettle-ui's list row** (`kt-row`, added next to `file-row`): the Movies and TV Shows lists, a show's episodes, the Rescan and Remove rows and the plain-list fallback, so the app has one row look. The focused row lifts to the control surface with no ring, as kettle-ui's rules say; the rows had a Sage ring until now.
- **Scan my folders, Cancel and Yes, remove are left alone** (the designer's choice on the second design system step): they keep the app's own row look and the Sage ring. The remove question's buttons are the picker confirm work. In the stylesheet the old row look now applies only to rows without `kt-row`; no class was renamed.
- **The focus look repeats on `:focus`**: kettle-ui shows it on keyboard focus or `data-focused`, but the app moves the real focus itself (as the second design system step did for the tabs).
- **Rows keep room above and below** (`--kt-space-gap`): kettle-ui's row is one centred line, and these rows can have two or three (subtitle, paths). A one-line row stays at kettle-ui's 56px, about the height it had.
- **On a focused row the muted lines step up to soft grey, not white**, following kettle-ui's rule; the title is strong white. The brand test that asked for white secondary text on a focused row now asks for this instead.
- **The tile alignment work's Continue watching layout stays**: frames on one bottom edge, captions on the line below. kettle-ui's tile expects one size of tile on a top-aligned shelf, with the progress track on its own line and the ring drawn over frame and track; here the thin bar stays inside the frame and the app puts kettle-ui's ring over the frame alone. The row keeps kettle-ui's ring room (`--kt-focus-affordance`), so `--continue-ring-room` now points to it. *Replaced on 2026-10-22 by "No layout is tied to a screen size, a device or an aspect ratio" (the responsive layout work): the row now uses kettle-ui's shelf room and tile sizes directly.*
- **A tile without a picture takes kettle-ui's plain frame**, with the name in the frame's small capitals; "Missing" takes the same capitals on a black label. A missing tile without a picture no longer turns darker: kettle-ui has no darker surface for it, and "Missing" says it in words.
- **Old tokens stay for snippets** (`--continue-progress-height` and the colour roles), unused by the app now; the last design system step tidies them, as with the second design system step.
- The gaps found are listed in `docs/spec.md` ("Design system: lists and Continue watching") and on the issue.


## 2026-10-10 — The app takes all its styling from kettle-ui (the last design system step)

- **Every colour, type size, spacing and radius now comes from kettle-ui**, the designer's design system, vendored unchanged at **version 0.3.1** (the first design system step). The app's own stylesheet holds layout only. Why: Kettle should feel like the rest of SteamOS Gaming Mode and like the designer's other Kettle tools, and one source of values means a change to the design system reaches every screen, instead of two sets of values drifting apart.
- **The Sage focus ring and the Mustard progress bar are replaced by kettle-ui's single accent** (coral by default, the same colour for rings and bars). kettle-ui's rule is one accent per app, and Sage and Mustard were nearly the same lightness, so they couldn't tell states apart anyway.
- **The old colour variables are removed**: the Mustard & Sage palette, the older names kept since the Home shell work, every colour role, and the spacing, type size, radius, focus-ring, row padding and progress-height tokens. Each one and its replacement is listed in `docs/spec.md` ("Tokens removed in the last design system step"), so a snippet can be moved over. No class name, id or `data-` marker changed.
- **The wordmark keeps Mustard** (`--color-wordmark`), its font and size, and PLAYER its wide spacing: the designer's choice on the Brand v0.1 work, and kettle-ui has no brand tokens. It is the one colour value left in the app's own styles.
- **Scan my folders, Cancel and Yes, remove keep their old look for now** (the designer's option B on the last design system step, 2026-10-09): their old values sit in one labelled block in `ui/css/tokens.css` (`--own-look-*`), used by those three rows only, and the automated "no old values" test allows that block alone. The picker confirm work restyles the remove buttons and a later issue Scan my folders; then the block goes. Removing the values outright would have changed how the three buttons look, which the issue doesn't ask for.
- **The brand rules in `docs/spec.md` and CLAUDE.md are updated** to match: Mustard & Sage is no longer the app's palette.
- The gaps found across the second design system step and the third design system step are gathered in `docs/spec.md` ("Design system: the switch finished") and on the issue.

## 2026-10-14 — /next all never stops to ask; idle work with test-writer and refactor-scout

**Decision:**
- **Only a single-issue /next stops to ask.** /next all (and /tidy) turn every question or blocker into one plain-language question in the issue's comments plus the `blocked` label, keep the branch, and go on with the next issue. The one early end left is uncommitted or unpushed work on `main` that belongs to no issue: nothing can be built safely on top of it, so the run ends with a report instead of guessing.
- **Idle work.** When /next all has nothing left that isn't blocked, it runs the same routine as the new `/tidy` command (`.claude/commands/tidy.md`):
  - **test-writer** (`.claude/agents/test-writer.md`, Sonnet) first proposes, changing nothing; only if it finds something does the run create one `tests` issue, straight into Ready for testing (nothing for the designer to approve first). Then it makes up to 2 improvements, one at a time, each on `issue-T` from the latest `main`, checked by test-checker and reviewer, merged and the branch deleted before the next. The results go in one comment on that issue, with a quick DD smoke check only. Bugs a new test uncovers are reported, not fixed.
  - **refactor-scout** (`.claude/agents/refactor-scout.md`, Opus) proposes up to 3 refactors, each with what it would change, why, what could break and how the tests cover it. The run double-checks them against existing `refactor` issues and open or blocked issues, and files the rest in Drafted, labelled `refactor` and with a size.
- **Refactors come last.** In Ready for dev, `refactor` issues are built only after every other issue there. The full suite must pass before the refactor starts (otherwise Blocked) and after; no existing test may be loosened or removed; behaviour stays the same.

**Why these shapes:**
- **refactor-scout can't create issues itself.** It is read-only like reviewer, and the run files its drafts. Letting it create issues would mean letting it write files (issue bodies can't go through the guard's one-line commands) or run `gh issue create`; keeping it read-only means a bad proposal can never change anything, and the run checks for duplicates a second time before filing.
- **test-writer proposes before making,** so a run that finds nothing creates no empty issue, and the checking agents get each improvement's "Done when" in the issue body, like any other issue.
- **Branches reuse `issue-T`,** one improvement at a time, so the existing permissions, `branch-done.sh` and the resume rules work unchanged.

**Guard:** `.claude/hooks/agent_guard.py` now knows four roles. test-writer may write only in `tests/`, `docs/` and `README.md`, run the tests, and list issues (`gh issue list` with a few safe options); refactor-scout may only read (git, `gh issue view`, `gh issue list`). Neither may create or edit issues. The same limits as test-checker apply (see "The checking agents' guard"): test-writer can run a test it wrote, so the run checks `git status` before every commit and only commits `tests/`, `docs/` and `README.md`.

**Reason:** the designer wants long batches to finish unattended and to use idle time well, without the helpers ever changing what the app does or building anything the designer hasn't approved.

## 2026-10-14 — Permission rules: reading never asks, only changing does

**Decision:** the broad "ask" rules in `.claude/settings.json` that also caught read-only commands are replaced by rules that name the changing commands. Reading is allowed; changing or deleting still asks.
- **Labels:** `gh label list` and `gh label create` are allowed (the workflow creates `blocked`, `refactor` and `tests`); `gh label edit`, `delete` and `clone` ask.
- **Another repository:** any `gh` call naming another repository used to ask. Now only creating, editing or commenting on issues, and creating labels, there asks; viewing and listing don't.
- **`gh api`:** plain reads are allowed; a call that sets a method (`-X`, `--method`) or sends data (`-f`, `-F`, `--field`, `--raw-field`, `--input`) asks. GraphQL changes need `-f` or `--input`, so they ask too.
- **`gh project`:** `list`, `view`, `item-list` and `field-list` are allowed; every command that creates, edits, links, archives or deletes asks. Board moves still go through `scripts/board.sh`.
- **pip and npm:** `list`, `show`, `ls` and `view` are allowed; installing, removing, downloading and running packages ask (`npx` still always asks).
- **Unchanged:** force pushes, deleting branches or files, `git reset --hard`, `gh issue close/delete`, `flatpak install`, `curl`, `wget` and edits to the settings files still ask. `curl` and `wget` stay: even a "read" sends a request out and can save files.

**Limits:** rules match the command's text. A write flag spelled in a way not listed (or glued oddly) would slip through the `gh api` allow; anything not listed in "allow" still asks by default. A rule that matches by mistake only asks, it never allows.

**Reason:** read-only checks (listing labels, viewing the board) were stopping unattended runs for approval, while protecting nothing.

## 2026-10-14 — The board is shared with kettle-ui; this repo acts only on its own issues

**Decision:** the Kettle board now also holds kettle-ui issues. `scripts/board.sh list` shows only cards whose issue lives in this repository (GitHub's own Repository field on the issue, not a field someone fills in), and leaves out other repositories' cards and draft cards; moving a card already matched on both number and repository, so a kettle-ui issue with the same number is never moved by mistake. /next, /next all, /tidy and /draft say the same in words: only this repository's issues are read, built, moved, labelled or created, and a dependency on another repository's issue is not followed. The list now fetches up to 1000 cards, since the shared board grows faster. Tests in `tests/test_board_script.py` run the script against a stand-in board with mixed cards.

**Reason:** a kettle-ui card in More to do or Ready for dev would otherwise be picked by /next and built here, in the wrong project.

## 2026-10-19 — kettle-ui 0.5.0 comes in with its motion, taken as it is (the Enamel 0.5.0 upgrade)

- **The vendored design system moves from 0.3.1 to 0.5.0**, through `tools/update_kettle_ui.py` only (never by hand). The tool now also copies 0.5.0's small behaviour script (`components/kettle-components.js`), but the server doesn't send it and the page doesn't load it yet: the picker confirm work does that, when something uses it.
- **0.5.0's motion is accepted unchanged** (the designer's option 1 on the Enamel 0.5.0 upgrade, 2026-10-14). kettle-ui 0.4.0 and 0.4.1 added motion measured from Gaming Mode: a focused Continue watching tile grows a little, its accent ring starts thick, narrows, breathes four times and rests; a newly focused list row fades its lift in. kettle-ui's reduced-motion setting is not switched on. The designer judges the motion on the Deck. Why: the motion is the design system's intended look, and taking it unchanged is the reason it is vendored. The alternatives were switching motion off for now, or holding the update until kettle-ui changed.
- **The app's browser checks wait for movement to finish before measuring** (`settle()` in the shared Marionette helper waits until no animation or transition is running, apart from the ring's slow breathing, which changes only its opacity). The Continue watching layout check measures the shared bottom line on the tiles as laid out, before the focused tile's growth, and the ring on the tile as drawn.
- **The Continue watching row's ring room (`--continue-ring-room`) is now kettle-ui's own shelf room**: the ring at its thickest, grown with the tile, plus half the large tile's growth (about 22px at 1280x800, was 10px). With the old room, the grown tile's ring was cut by about 2px at the row's left and top edges, and the thick starting ring much more. Tiles stay where they were (the room is padding cancelled by a negative margin); only when the row has scrolled sideways does the focused tile sit a little further from the edge. *Replaced on 2026-10-22 by "No layout is tied to a screen size, a device or an aspect ratio" (the responsive layout work): the row now uses kettle-ui's own `--kt-c-shelf-room`.*

## 2026-10-19 — The remove question becomes a kettle-ui picker (the picker confirm work)

- **The question is kettle-ui 0.5.0's picker dialog, confirm use, and replaces the old question completely** (the designer's instruction on the picker confirm work, 2026-10-14): no old block, key handling or "question open" flag is kept beside it. The app asks kettle-ui (`KettleUI.picker.isOpen()`) wherever it used its own flag.
- **The server sends kettle-ui's behaviour script, and the page loads it with a plain script tag** after the stylesheets and before the app's module, so `window.KettleUI` always exists when the app starts. Still nothing else under `vendor/` is sent.
- **The list stays behind the question** instead of being hidden, because the picker is drawn as a darkened, blurred layer over the page. Cancel and B put the focus back on the Remove row (kettle-ui returns it there); Yes, remove reloads the list with the focus on Rescan, as before.
- **A (Space) and B (q) are handed to the picker by the app.** kettle-ui only answers Up, Down, Enter, Escape and Tab; the controller sends Space for A and q for B, so while a picker is open the app's key handler sends those two to `picker.select()` and `picker.cancel()` and acts on nothing else. This is what kettle-ui's DESIGN.md asks of apps with their own key handling, and it means one press is never acted on twice (Escape cancels and never quits).
- **Hook changes** are listed in `docs/spec.md` ("Design system: the remove question as a kettle-ui picker"): the names that still make sense are kept on the dialog; `[data-role="choices"]` goes; the two rows stop being `.file-row.parsed-row`.

**Reason:** the designer asked for kettle-ui 0.5.0 to be used wherever it fits and for old styling to go; the picker is kettle-ui's answer to this question, and doing it by halves would leave two ways of drawing and handling the same question.

## 2026-10-19 — kettle-ui 0.5.0 finished: Scan my folders is a primary button, the old look goes (the design system finish)

- **Scan my folders is kettle-ui's primary button**, not a row (the designer's instruction on the design system finish, 2026-10-14). It is the first-launch screen's one main action, which is what kettle-ui's primary button is for (at most one per screen). It sits at its own width under "No library yet." and, since it always has the focus there, shows kettle-ui's primary focus: the accent fill with dark text. The app repeats that focus look on `:focus`, as it already does for rows and tiles, because the app moves the real focus itself and kettle-ui shows it on keyboard focus only. The alternative, a kettle-ui list row, would have kept a full-width row for a single action, which kettle-ui's rows are not meant for ("any vertical list").
- **The old look goes entirely**: the `--own-look-*` block, the `.file-row:not(.kt-row)` rules and the app's list of rows that wore it. The "no colour or loose size values" test loses its exception for it. Hooks on the action changed as the issue allows; they are listed in `docs/spec.md` ("Design system: kettle-ui 0.5.0 finished").
- **Everything else the app draws itself stays as it is**, compared one by one with kettle-ui 0.5.0 (the table in the spec): kettle-ui still has no message, error or empty-state component. The toast is kettle-ui's only new component that could carry a message, but it is out of scope here and it leaves after three seconds, while the app's messages stay until something changes. kettle-ui's progress bar was not used for "Scanning… N of M", because the count moves in two jumps (films, then shows) and a bar would suggest a precision it doesn't have.
- **A test now finds unused styling**: every class, id, marker and custom property in the app's own stylesheets must be used by the page or its scripts. After removing the old look nothing else was unused.

**Reason:** the designer asked for kettle-ui 0.5.0 everywhere it fits and for old styling that has no job to go.

## 2026-10-19 — The app is called Kettle Video

**Decision:** The app is named **Kettle Video** (it was briefly to be called Kettle Watch, a name that never reached the code). Kettle apps are named Kettle plus their medium, with no verbs; Kettle Audio is next. "Kettle Video" replaces the "Media Player" working title in the window title, the README, the Steam shortcut that `install-shortcut.sh` creates, the device setup guide and CLAUDE.md. The loading-screen wordmark stays "Kettle", the family name. The repository, folders and file paths (`media-player`, `media-player.desktop`) are not renamed yet: that waits for the name checks. Past entries in this file keep the names they used at the time.

**Reason:** the designer set the naming rule for the Kettle family, so each app's name says what it plays.

## 2026-10-19 — kettle-ui gaps are fixed in kettle-ui

**Decision:** All styling and components come from kettle-ui (a hard rule in CLAUDE.md). When an issue needs something kettle-ui lacks or that doesn't fit, the app doesn't style it itself: the builder stops, writes the gap as a question on this repo's issue and adds the label `needs kettle-ui`. The designer (or a kettle-ui session) carries it to kettle-ui's open "Gaps found by the apps" issue; /next never writes to another repository.

**Reason:** the designer wants one design system for every Kettle app, with its gaps fixed at the source and all of them findable under one label.

## 2026-10-19 — The design-system check compares with kettle-ui's finished version (the finished-version check)

*Replaced on 2026-10-22 by "The app takes kettle-ui by released version" (the Enamel 0.6.0 upgrade): the check and the update tool now read the release tag, never `main`.*

**Decision:** The test that the app's copy of kettle-ui matches kettle-ui now reads kettle-ui's files from its `main` branch (`git show main:<file>`), not from the folder as it is. It only reads: it never switches kettle-ui's branch or touches its files. Work in progress in kettle-ui (uncommitted, or committed on another branch) no longer fails Kettle's tests; a finished new version on kettle-ui's `main` still does, until the app brings it in with the update tool. Where the folder is missing, isn't a git folder or has no `main` branch, the test is skipped with a plain reason. The update tool still copies the folder as it is (unchanged here; raised on the issue).

**Reason:** on 2026-10-19 a kettle-ui session started building its 0.5.1, and from that minute every Kettle branch failed this test, so nothing could be merged (the designer's choice on the board script fix).

## 2026-10-19 — The board script finds a just-added card through the issue (the board script fix)

**Decision:** When the board's card list doesn't include an issue yet, `scripts/board.sh` asks GitHub through this repo's issue which board cards it has, and uses the Kettle board's card. That answer is up to date at once, while the board's list took from 30 seconds to a few minutes to include a new card. Waiting and retrying was the alternative; it would have slowed every miss and still failed when GitHub was slower than the wait. Keeping the card ID that GitHub returns on adding was not built either: the lookup through the issue already covers the move right after adding, and it also covers a card added some other way (by hand on the board, or by an earlier run). The lookup goes through this repo's issue only, so another repository's card can't be found or moved, and an issue on no board still gets the plain "not on the board" message. `scripts/board.sh list` still reads the board's list, so a card added a moment ago can be missing from it for a minute or two.

**Reason:** /draft and /tidy move a new issue to its column straight after adding it, and that step failed every time.

## 2026-10-21 — The page keeps the screen on in Gaming Mode with Firefox's Screen Wake Lock (the screen wake lock fix)

**Decision:** While a film plays (from the moment mpv starts until the page sees it has closed), the page asks Firefox for a Screen Wake Lock, asks again if Firefox lets go while the film is still on (for example after the page was hidden), and releases it when mpv closes, however it closes, including when the backend stops answering. Only with `keep_awake` on: the play answer now carries that setting. Each change goes to the launch log in fixed words (`screen wake lock: held`, `lost`, `refused`, `unsupported`, `released`), through `POST /api/wake-lock`, which refuses anything else. The system lock from the keep-awake work stays as it is.

**Why:** in Gaming Mode, Steam's own dim and screen-off timers decide idleness from input and don't look at the system lock, so the screen still went off during films (the Nova). Since its 13 October 2026 update, Steam delays those timers when "web browsers or other apps request to disable monitor sleep … while playing video". The Flathub mpv's own request can't reach Steam (its plugin only talks to GNOME's session manager, the one service its sandbox allows), but Kettle's screen is a Firefox page, and a page asks with the standard Screen Wake Lock. Checked on the Deck: Firefox 153 offers it to Kettle's local page and grants it. Chosen by the designer over two heavier options: the server asking the screensaver service itself, or changing how mpv is started.

**Limits:** whether Steam honours Firefox's request in Gaming Mode, and whether Firefox keeps it while mpv covers the page, can only be seen on the devices (the launch log shows held or lost). Like the system lock, it covers pauses too. A page reloaded during a film doesn't ask again until the next film. If it doesn't keep the screen on, the next step is the server asking the screensaver service itself (option 2 on the issue). The "can't wake" half of the screen wake lock fix is separate and not fixed by this.

## 2026-10-22 — The app takes kettle-ui by released version; 0.6.0 comes in (the Enamel 0.6.0 upgrade)

**Decision:**
- **The update tool copies a named version**, read from kettle-ui's release tag (`python3 tools/update_kettle_ui.py 0.6.0` reads `v0.6.0`), never from the folder as it happens to be. It refuses, copying nothing, when the tag is missing, a file isn't in it, or the tag's `VERSION` says another version. It only reads kettle-ui: no branch is switched, no file touched.
- **The design-system check compares the app's copy with the tag for the version the app records** (`vendor/kettle-ui/VERSION`), never with kettle-ui's `main`. A newer version on `main`, or work in progress, never fails it; any difference from the recorded release still does, file by file. Skipped with a plain reason where kettle-ui isn't on the device, isn't a git folder, or has no tag for that version. This replaces the finished-version check's comparison with `main`.
- **No stand-in for missing tags.** The issue planned one (the commit that changed `VERSION`), but kettle-ui now tags every release (v0.3.0 to v0.6.0), so tags only.
- **0.6.0, not 0.5.1** (the designer's answer on the Enamel 0.6.0 upgrade, 2026-10-21): kettle-ui's changelog says Kettle Video skips 0.5.1 and takes 0.6.0, which includes it, now that its responsive series is finished. The app's own responsive work stays in the responsive layout work.
- **The hint bar takes kettle-ui's height** (the designer's answer on the Enamel 0.6.0 upgrade, 2026-10-22). In 0.6.0 the bar's height became a minimum (`--kt-size-bar`, 60px at the normal font size), so it no longer gave way to the app's own `--shell-bar-height` (6% of the screen: 48px on the Deck, 46px on the Nova). The bar is now 12 to 14px taller; nothing else on screen changed. The page's bottom room, the list's scroll room, the letter strip and the dev box follow kettle-ui's `--kt-c-hintbar-height` (kept at the bar's real height by kettle-ui's script), and the app's own rule placing the remove question's layer is gone: kettle-ui's picker meets the bar by itself. `--shell-bar-height` is now the top bar's height only.

**Reason:** comparing with `main` broke every Kettle branch whenever kettle-ui started a new version (it blocked the board script fix and the screen wake lock fix); a release tag is a fixed, finished version, so kettle-ui can work ahead without blocking the app and nobody can bring in half-done work. For the hint bar, keeping the old height would have meant overriding a kettle-ui size inside the app, against the rule that all styling comes from kettle-ui.

## 2026-10-22 — Decide more, stop less

**Decision:** /next and /tidy never stop a run on a question and never use the interactive question prompt, in any mode (single /next included). A choice that a git revert can undo, where one option can be recommended and no hard stop applies, is decided by Claude and recorded on the issue ("Decided: … Why: … To change it, reply on this issue.") with the `decided` label. The only hard stops are: a new dependency or licence question; anything that could change, move or delete media or other files outside the repo; anything a git revert can't undo; a product change nobody asked for that doesn't come from the issue or the design system; security or privacy; the issue contradicting CLAUDE.md. A hard stop, or one problem stuck for about 30 minutes, becomes one question in the issue and the `blocked` label, and the run moves on. Changes that come from a new design system version (Enamel, formerly kettle-ui) are in scope: the app follows them, never hardcodes a size the design system provides, and only treats them as a problem if something can no longer be reached, read or used. The old stop triggers "a theming hook would change" and "the spec is ambiguous" are now decided (a hook change still updates its docs in the same commit). Rules in CLAUDE.md ("Decide, don't stall"), `.claude/commands/next.md` ("Decide or block") and the reviewer agent.

**Reason:** the designer wants faster decisions and runs that never stall: most questions had a clear recommended answer and could be undone, and the `decided` label lets the designer review them all together on the board instead of answering each one before work can continue.

## 2026-10-22 — No layout is tied to a screen size, a device or an aspect ratio (the responsive layout work)

Replaces every earlier decision that named 16:10 or 4:3 as a target (marked above where they appear).

**Decision:**
- **The rule** (the designer's wording, agreed on the responsive layout work): no layout is tied to a screen size, a device or an aspect ratio. Layouts adapt to the space they get; breakpoints come from the content and are named by what they do. The Steam Deck and the Nova are test devices, never targets; device facts that aren't about the screen stay. In CLAUDE.md (Hard rules, Target devices, Design rules), and "Nova risk" in `.claude/commands/next.md` no longer lists the screen.
- **The smallest supported size is kettle-ui's**: 20rem wide by 15rem tall (320 by 240 at the browser's normal font size), set by its content. Text doesn't scale with width beyond kettle-ui's own sizes.
- **Continue watching takes kettle-ui's tile widths** from the width its row gets (the row is kettle-ui's shelf, a size container): a small tile is two fifths of the row, between 10rem and 16rem, the large one three quarters, between 12rem and 28rem. Before, the tiles were sized by the screen height, the large one exactly twice a small one. Now the large one is about 1.75 times a small one where both are at their widest, and a wider row shows more tiles. The row's ring room is kettle-ui's `--kt-c-shelf-room`. `--continue-tile-height`, `--continue-small-tile-height` and `--continue-ring-room` are gone (theming tokens; the spec says so).
- **Kept as they are, because they follow the space and not a device:** the top bar's height (6% of the window's height, at least 40px; the Home actions work turns it into kettle-ui's action bar), the letter strip's letters (fitted to the space between the bars) and the wordmark (fitted to the page's width so KETTLE stays on one line; it is the brand mark, not text).
- **Tabs that wrap make the tab strip taller.** kettle-ui's tabs wrap onto another line when they don't fit (at 320 wide, MOVIES and TV SHOWS sit on two lines). The strip had a fixed one-line height; it now has that as a minimum, and the app keeps `--tab-strip-height` at the strip's real height (measured, as kettle-ui's script does for the hint bar), so the scroll room and the letter strip follow it.
- **Short windows: the top bar and the tabs scroll with the page.** Where the window can't keep the top bar, two lines of tabs and the hint bar pinned with two rows between them (about 21rem tall, worked out from those sizes), they stop being pinned. Otherwise, at kettle-ui's smallest box the pinned bars took 224 of 240 pixels and no row fitted. Named by what it does; no device's screen comes near it.
- **Up and Down scroll a screen with nothing to focus.** The "mpv not found" messages have nothing to focus, and the arrows did nothing there; in kettle-ui's smallest box the longer ones run past the hint bar. Up and Down now scroll the page by half a window on such a screen, so the controller can reach the end. Nothing changes where there is something to focus.
- **A message keeps the focus in view.** When "Playing…", "Rescanning…" or an error appears above the lists it pushes them down; in a short window that could put the focused tab or row under the hint bar, so the app scrolls it back into view.
- **kettle-ui gap: the picker in kettle-ui's smallest box.** The remove question's panel (kettle-ui's picker) is taller than the room above the hint bar at 320 by 240, so its top is cut off. That is kettle-ui's component, so it isn't restyled here: raised on the responsive layout work with the label `needs kettle-ui`, and the lists check notes it at that size instead of failing.
- **The browser checks run at six window sizes, labelled by width only** (`tests/window_sizes.py`): 320 by 240 (kettle-ui's smallest box), then 640, 1024, 1280, 1920 and 2560 wide. A check that only needs a window uses the 1280-wide one. Headless Firefox won't make a window narrower than 500 CSS pixels, so below that the checks zoom the page in (the browser's own zoom, as Ctrl and + does): it then lays out at 320 CSS pixels wide, what a screen that narrow shows. Firefox is started with `--remote-allow-system-access` for that. `tests/test_no_layout_targets.py` fails if the interface files, the docs that describe the app, the /next instructions or the browser checks name a screen's aspect ratio, or tie a device to a screen size. The decisions log, the spikes and the audit are history and aren't checked.

**Reason:** the app should work the same on any handheld, a desktop window or a TV; laying out for two screens made every other size an accident. kettle-ui 0.6.0 (the Enamel 0.6.0 upgrade) is responsive, so the app takes its sizes rather than keeping its own.

## 2026-10-22 — Home actions: a docked bar, a menu, scan progress as a toast (the Home actions work)

**Decision:**
- **Actions live on a docked bar.** Home gets kettle-ui's action bar across the top, with its buttons on the right; it replaces the black top bar and its clock. It stays docked while the page scrolls, and Up from the top row of content reaches it. Its height is kettle-ui's (`--shell-bar-height` now follows the bar's real height). In windows too short to keep the bar, two lines of tabs, the hint bar and two rows (about 22.25rem, the responsive layout work's 21rem plus the bar's extra height), the bar scrolls with the page as the top bar did (the responsive layout work); Start opens the menu from anywhere, so nothing becomes unreachable.
- **Menu is a word and opens a picker.** One button, "Menu" (a word, not an icon), opens kettle-ui's picker as an action list: Rescan library, Remove N missing items (only when there are some), Quit, Cancel. The Rescan and Remove rows at the top of the lists, and their "Last scanned" and "Last scan" lines, are gone.
- **Start sends m.** Start opens the menu from anywhere on Home. Steam doesn't keep Start for itself in a non-Steam game's layout (only the Steam and Quick Access buttons are reserved), so it is bound to a keyboard key like the other buttons: m, which nothing else in the list uses, and which Kettle's mpv key file sets to do nothing.
- **B on Home opens the menu on Quit, replacing B quitting at once.** B then A quits, B then B backs out, so a stray B never closes the app. Inside a show B still goes back. Where there is no menu (loading, first launch, mpv messages, the plain-list fallback) B quits as before, so it never leaves you stuck.
- **Scan progress is a toast.** kettle-ui's toast, bottom right above the hint bar, replaces "Rescanning…" and the Rescan row's progress line. It counts the files the scan reports (in two steps, the Movies folder then the TV Shows folder, since the scan reports progress per folder and the scan itself is out of this issue's scope), then shows what changed for three seconds. The words come from the backend (`last_result.message`, "3 added, 1 missing" or "No changes"), so they are unit-tested and never hold a path or a name. "Missing" counts items that went missing in this scan, not everything still missing, so a rescan with nothing new says "No changes".
- **Quit stops the server, and the launcher closes the window.** The page can't close its own kiosk window; the server stopping is what ends `launch.sh`, which then closes Firefox (the start-up fix, the server shutdown check). No "are you sure".
- **The short-window rules now really reach the letter strip.** The responsive layout work's rule moving the letter strip to the top of a short window sat before the strip's own rule in the stylesheet, so it never applied; with the taller bar the strip had no room left at kettle-ui's smallest box (320 by 240) and its letters couldn't be tapped. The short-window rules now come last, and the letters in a short window fit the height from the top of the window to the hint bar (`--font-size-letter-strip-short`).
- **kettle-ui gaps are fixed in kettle-ui.** Everything here is kettle-ui 0.6.0's (action bar, button, picker, toast). The app adds only placement: the bar reaches out to the page edges past the body's gutter, and in dev mode the toast sits above the developer box. No gap was found.
- **The plain-list fallback's answer still names the configured folders.** "No absolute paths in anything the server answers" is checked on every answer Home uses; `GET /api/library`, used only by the fallback when the saved library can't load, still puts the configured folder in its "folder not found" line, because changing it means changing the scanner, which this issue leaves alone.

**Reason:** quitting with a single B was too easy to do by accident, and a list row was an odd place for app actions; Steam puts them in a bar and a menu. A toast reports a rescan without moving the list or taking the focus.

## 2026-10-27 — git rm allowed in the repo; no chained commands in /next

**Decision:**
- **`git rm` runs without asking** for files git tracks inside this repo (`.claude/settings.json` allow list). Git itself refuses untracked files and paths outside the repo, and without `-f` it refuses a file with uncommitted changes, so what it deletes is always in git and can be brought back. Still asked: plain `rm` and `rmdir`, `git rm` with an absolute, home (`~`) or parent (`..`) path, `git rm -f`/`-rf`/`--force`, `git -C` (it can point git at another folder), `git clean`, and `find -delete`.
- **During /next and /next all, one simple command at a time:** no `&&`, `;` or pipes, so each command can match the allow list on its own. Output is filtered in a separate step or with the built-in tools.

**Reason:** both cut approval prompts without letting anything delete work that git can't restore.

## 2026-10-27 — The GitHub account is renamed from steamostools to enamelware (the account rename)

**Decision:**
- **Everything in the repo uses the new name.** The board settings (`.claude/board.json`: owner, repo and board address) changed first, because the rename had broken the board script; the board test now takes the designer from those settings. The development copy on the Steam Deck fetches and pushes from `git@github.com:enamelware/media-player.git`.
- **The board's address kept its shape.** It is still the account's board number 1, now under the new account name; its internal IDs didn't change, so `scripts/board.sh` needed nothing but the settings.
- **A check keeps the old name out** (`tests/test_account_name.py`). It reads every file git tracks and fails if `steamostools` appears, in any capitals. Not checked: `vendor/` (unmodified third-party copies, never edited here), the check's own file, and entries in this log or a changelog dated on or before 2026-10-27, which are history.
- **Outside the repo, listed, not changed:** the Nova's copy of the app still fetches from the old address (steps in the Nova account update), as does any other copy, such as the kettle-ui folder on the Steam Deck. The Steam shortcut and the desktop entry point at `launch.sh` in the app folder, not at GitHub, so they don't use the account name.

**Reason:** GitHub forwards the old addresses only until someone else takes the name `steamostools` and creates a repository with the same name; after that, anything still using it would quietly reach someone else's repository.

## 2026-10-27 — The design system is now Enamel; the app takes 0.7.0 (the Enamel rename)

**Decision:**
- **Enamel 0.7.0 comes in under its new name.** `tools/update_enamel.py` copies it into `vendor/enamel/`, which replaces the folder under the old name. It copies the same files as before by their new names, plus `MIGRATION.md`. The server sends the three files the page needs from `vendor/enamel/`, and the page loads them from there.
- **Only names changed.** Every token, class, state attribute, animation and script name the app uses is renamed exactly as `vendor/enamel/MIGRATION.md` lists (the `kt` prefix became `en`, the script's global is `EnamelUI`). Every name the app used is in that list, and with the old names mapped to the new ones, 0.6.0's three files and 0.7.0's are the same outside comments, so nothing looks or moves differently. Browser screenshots at every checked width were compared before and after.
- **Theming hooks:** the `en-` classes listed in `docs/spec.md` ("Theming hooks") are Enamel's; the app's own names, the ones snippets select on, didn't change.
- **The update script looks for `~/Development/enamel` first**, then the design system's folder under its old name, because the issue asks for that fallback while the folder on the Steam Deck still has its old name. That one line is the only old name left outside `vendor/` and older entries in this log.
- **A check keeps the old names out** (`tests/test_design_system_name.py`): it reads every file git tracks and fails on any old name, except in `vendor/`, its own file, that one fallback line, and entries in this log dated on or before 2026-10-27 other than this one.
- **GitHub:** the label for design system gaps is now `needs enamel`; the issues that had it keep it.

**Reason:** the design system was renamed in its own 0.7.0 (a breaking change by name only), and its changelog asks Kettle Video to switch through this issue. Older entries in this log keep the old name: they are history.

## 2026-10-28 — Fewer approval prompts: peek.sh reads Enamel, helpers are told the command rules

**Decision:**
- **`scripts/peek.sh` reads the other Kettle repo** (Enamel, found next to this one at `../enamel`) and runs only `git log`, `show`, `status`, `diff`, `tag` (listing only), `rev-parse` and `ls-files` there. Options that write a file (`--output` and its abbreviations), run another program (`--ext-diff`, `--textconv`) or read outside that repo (`--no-index`) are refused, and `status` takes no lock on its index. It is allowed in the shared settings; `git -C` itself still asks, because it can point git at any folder. The agents' guard lets every helper use it with the same display options as plain git.
- **Every helper is told the command rules in its own instructions** (reviewer, test-checker, test-writer, refactor-scout) and in the builder's prompt: one plain command at a time, git from this repo's folder without `-C`, `scripts/peek.sh` for Enamel. Helpers don't always pick up CLAUDE.md, so it is written where each one reads it; `tests/test_agent_guard.py` checks it is there.
- **A new ask or deny rule must never catch a read-only command.** `tests/test_agent_guard.py` checks every ask and deny rule in `.claude/settings.json` against a list of read-only commands (git log, show, status, diff; gh issue view and list; ls, cat, grep; `scripts/board.sh list`; `scripts/peek.sh`). No existing rule caught one, so none was narrowed.
- `scripts/forget-note.sh` was already there and allowed; nothing changed for it.

**Reason:** reading Enamel's history came up as a `git -C` approval prompt each time, and a rule that asks on a read-only command costs a prompt for nothing.

## 2026-10-28 — Quick checks on every issue, the full check before a release

**Decision:**
- **Quick** (`scripts/test.sh`, the default) runs on every issue and aims to finish in under 2 minutes: the unit suite without the timing tests and, alongside it, the browser checks for the screens the change touches (the ones named, plus any `tests/*_check.py` the change adds or edits). Both mostly wait on servers and Firefox rather than the processor, so running them side by side roughly halves the time: the unit suite and one browser check took 1 min 34 s together, against about 4 minutes one after the other.
- **Faster without checking less.** The Quit test waited out a 30-second connection timeout after the server had already stopped; it now probes with a 1-second timeout, which checks the same thing. The four timing tests (parser, movies, TV, rescan), which only print how long a large invented library takes, are marked `@full_only` (`tests/full_only.py`) and run in the full check; what the rescan one also asserts, that unchanged files aren't read again, is covered by a smaller test that stays in quick. The unit suite went from 2 min 37 s to about 1 min 30 s.
- **Full** (`scripts/test.sh full`, or `all`) runs everything: the whole unit suite, timings included, then every browser check. It runs before any `VERSION` bump or release, and once at the end of `/next all` if anything was merged. If it fails, the run finds from the commits which merged issue caused it, moves that issue to More to do with a plain-language comment, and nothing is released until it passes.
- **Never the same check twice on the same code.** `scripts/test.sh` remembers each pass (the unit suite, each browser check, full) against the exact code: the tree git would commit with every change added, uncommitted files included, worked out with a separate index so nothing is staged. The results live in git's own folder (`.git/kettle-test-results/`), never in the repo. A full pass counts for everything; `--again` runs it anyway.
- The agents' guard lets test-checker and test-writer run the new modes.

**Reason:** the unit suite alone had grown past 2½ minutes and every issue ran it several times (builder, test-checker, merge), while a single release-time run of everything is enough to catch what the quick check leaves out.

## 2026-10-28 — Pin the Enamel version

**Decision:**
- **One pin.** The Enamel release Kettle Video has adopted is recorded in one place, `ENAMEL_PIN` at the repo's root: its release tag (`v0.7.0`). Until now the version came from `vendor/enamel/VERSION`, which is Enamel's own file and moves with whatever was copied, and a test also named 0.7.0 by hand; both now agree with the pin, and the hand-written number is gone. `tools/update_enamel.py` moves the pin with the copies, and only when the update succeeds.
- **Checked against the pin only.** The design system check compares `vendor/enamel/` with Enamel's files at the pinned tag (it already read the tag, never Enamel's main or its folder as it is, since the finished-version check and the Enamel 0.6.0 upgrade). Nothing compares with Enamel's main branch or its latest release, so a new Enamel release can't fail an unrelated issue's checks. Where Enamel's folder or the tag isn't on the device (the Nova), that one comparison is skipped with a plain reason, as before.
- **Upgrades are their own issue.** At the start of `/next all`, the run reads Enamel's release tags with `scripts/peek.sh` and, if there is one newer than the pin and no issue for it yet, drafts one "Bring in Enamel <version>" issue with a plain summary of the changelog. It never upgrades there and then, nor inside another issue: the reviewer fails any other issue that changes `ENAMEL_PIN` or `vendor/enamel/`, and an issue that needs a newer Enamel is linked to the upgrade issue and waits for it.

**Reason:** a retro found Enamel changes had held up about 10 of the last 15 issues: finished issues couldn't merge while the design system check was failing over an Enamel change nobody had adopted yet. The finished-version check and the Enamel 0.6.0 upgrade had already moved the comparison to release tags; the pin and the separate upgrade issue close what was left.

## 2026-10-28 — Checks scale with the issue's size

**Decision:**
- **Three sizes, defined once** in CLAUDE.md ("Sizes") and used by /draft: S is one small change of about 3 files or fewer, with no new screen and no change to data, launch, privacy or licences; M is one feature or one screen; L is several screens, or a change across the app or the design system. When unsure, the bigger one. The "about 3 files" doesn't count the tests written for the change or `docs/decisions.md`, since every issue adds those.
- **The path follows the size.** The builder always writes the tests the change needs. S and M go to the reviewer alone, which also checks the tests would fail if the feature broke; L adds test-checker and `scripts/test.sh full` before merging. Every size keeps its branch, the merge only when checks pass, the progress comment, the testing comment and the board moves.
- **The reviewer fixes tidy-ups itself.** Unused lines or imports, repeated set-up, a missing licence header, wording: it fixes them in one `WIP issue-N: reviewer tidy-ups` commit and lists them, and fails only for real problems (wrong behaviour, a broken layout, something the spec asks for that's missing, tests included, a gap not reported to the designer, a broken hard rule, security or privacy). The guard lets it edit `tests/`, `backend/`, `ui/`, `tools/`, `scripts/`, the workflow's commands and agents, `docs/` and `README.md`, run the quick check, and commit only on an issue branch; never `vendor/`, `ENAMEL_PIN`, `launch.sh`, the installer, the settings files, `CLAUDE.md` or the guard itself, and it never pushes. Tidy-ups outside its folders come back as "Tidy-ups left" for the builder.
- **Upgrades are automatic.** An S that touches more than about 3 files, or the data folder, `launch.sh`, privacy, licences, `settings.json`'s format or design system tokens, becomes M; an M that grows past one screen or feature becomes L. The label changes and one line on the issue says why.
- **Small neighbours are bundled.** S issues next to each other in Ready for dev that touch the same area are built on one branch, one issue at a time with a marker commit after each, and reviewed once; the merge rebuilds `main` one issue at a time from those markers, so each still lands as its own `Refs #N:` commit, moves its own card and gets its own testing comment.
- **A series is reviewed as a whole.** /draft gives the issues it splits from one item a shared `series: <name>` label and links them. When the last one merges, one reviewer pass covers everything from the commit before the series' first issue: fit between the pieces, duplicated code, the feature as a whole. Until it passes the cards wait in Building; fixes go in a follow-up issue in the same series, which goes straight to Ready for dev because it only fixes what the designer already approved.
- **Housekeeping and resuming.** Every /next starts with `scripts/board.sh close-done`, which closes this repo's open issues whose cards are already in Done. A resume always re-runs the quick check, but the agents only if the code changed since they passed (the progress comment's new `Checks passed on:` line), replacing the rule to always re-run them before merging.
- **/tidy keeps both agents,** as Enamel decided: its changes are test-writer's tests, which is where test-checker earns its place.

**Reason:** a retro of the first 13 issues found test-checker never failed anything (its value was the tests it wrote), the reviewer's failures on medium issues were tidy-ups that cost a whole extra round, and the full check found nothing in four runs. Kettle Video's own retro agreed, and added that re-running the agents after a pause never found anything. Enamel made the same change the same day.

## 2026-10-28 — Single testing column

**Decision:**
- **One testing column.** The board's "Tested on DD" and "Tested on DG" columns are gone (both were empty, in both repos, so no card had to move); a built issue sits in Ready for testing until the designer moves it to Done. The two options were removed from the Status field with every other option's ID kept, so no card lost its column, and `.claude/board.json` lists the six that remain. The descriptions of Ready for testing and Done no longer name a device stage.
- **The designer tests on whatever device is to hand,** and moving a card to Done is the approval. The board housekeeping at the start of the next /next (`scripts/board.sh close-done`) closes the issue. The phrases "DD ok", "DG ok" and "Nova ok" are gone; "#N failed: <what happened>" stays (comment, then More to do).
- **The testing comment** has one short list of things to try, not grouped by device, and a "Nova risk" line only when a change might behave differently on ARM, Armada or a different screen shape.
- This replaces the column part of "Development moves to the Steam Deck" above; the Steam Deck stays the dev device.

**Reason:** the designer tests on whatever device is at hand, and a card passing through three device stages added board moves without catching more.

## 2026-10-28 — TV Shows marked as beta with plain text (the TV beta label)

**Decision:** the TV Shows tab reads "TV Shows (beta)": plain text inside the tab, in the tab's own Enamel style, so it shows in Enamel's caps as "TV SHOWS (BETA)" at the label's colour, not muted. A non-breaking space keeps "(beta)" with "Shows". Screen readers hear "TV shows, beta" through the tab's `aria-label`, which also means they no longer hear that tab's count. No badge, no new class or theming hook, no app styling.

**Reason:** the designer's comment on the issue ("just use text next to the TV SHOWS (beta)") replaces the badge, and Enamel 0.7.0 has no badge or tag component; a lowercase or muted "(beta)" would need styling inside the app, which CLAUDE.md does not allow.

## 2026-10-28 — Fresh start for testing (the fresh start mode)

**Decision:**
- **Launch options are environment variables**, `KETTLE_FRESH_START=1` and `KETTLE_PRETEND_NO_MPV=1`, set in a second Steam shortcut's Launch Options (`KETTLE_FRESH_START=1 %command%`). They pass through `launch.sh` unchanged, so `launch.sh` needs no change, and the same `settings.json` serves both shortcuts.
- **One place picks the data folder**, once at launch: `backend/launch_options.py`. Normal use is unchanged (`settings.json`'s `data_dir`, `data/` by default). There is no general "data folder" variable: nothing needs one yet, and fresh start is the only other folder.
- **Fresh start's folder is under `/tmp`** (`kettle-fresh-…`, this user only), with the app's data folder and **mpv's own empty resume folder** (`watch_later`, passed with `--watch-later-dir` after `mpv_args` so it always wins). The designer's choice on the fresh start mode ("1 is fine"), over turning resume off or sharing the real positions: it keeps the real positions untouched while resume and Continue watching can still be tested. `/tmp` because the Flatpak mpv can write only there.
- **Deleted when the server stops**, however it is stopped (Quit, the window closed, a stop signal); a leftover is deleted at the next fresh start. Only a folder that is directly in `/tmp`, named `kettle-fresh-…`, a real folder owned by this user, holding the app's own mark file, and not in use by a running copy is ever deleted.
- **`/api/status` no longer sends mpv's log location or its last lines**: they hold absolute paths (the film's among them), the issue asks for none in any answer, and the page never used them. They stay in the log file.
- **Logs stay in `logs/` and the Firefox profile is shared** in fresh start: the logs are what a bug report needs, and the page keeps nothing in the profile.
- **The marker is Enamel's hint (`.en-hint`) with no button glyph**, first in the hint bar (in the bottom-left corner, the hints keeping the right), plus one in the loading screen's corner, which covers the bar. Enamel 0.7.0 has no badge or marker component; that gap is reported on the fresh start mode with `needs enamel`.

**Reason:** testing onboarding and first-launch screens again and again must never put the designer's library or resume positions at risk, and must need no terminal and no change to `launch.sh`.

## 2026-10-29 — Folder dialog for "Browse somewhere else" (the folder dialog spike)

**Decision:** onboarding's "Browse somewhere else" row opens a system folder dialog started by the server: **kdialog first, then zenity, then Python's Tk dialog**, whichever the device has. The row is hidden when none is found. The desktop portal is not used. The designer decided to stop testing after the Steam Deck runs: the Nova is assumed to behave like the Deck, and a controller that doesn't fully work in the dialog is accepted, because touching the screen is enough.

**Reason:** on the Deck, kdialog, zenity and Tk return the real path and hand the focus back in both Desktop and Gaming Mode, with nothing new installed. The portal doesn't show in Gaming Mode and would need a hand-written session-bus client. Full findings and the risks are in `docs/spikes/folder-dialog.md`.

## 2026-10-29 — Sizing against Steam, and the size readout (the sizing spike)

**Decision:**
- **The reference screen is a measuring point, not a layout target.** `docs/sizing-report.md` takes Steam's sizes at 1280 by 800 CSS pixels as Enamel's new baseline, and says in those words that nothing is built for that size. This is the reading the issue suggested; the designer moved the issue to Ready for dev without asking for a target, so the hard rule "No layout is tied to a screen size" stands as it is.
- **The size readout is a developer setting, `"debug_size_readout": true`,** off when missing, like `dev_auto_update`. The page measures once at start and the backend writes one line from checked numbers only.
- **Firefox's zoom is reported as part of the device pixel ratio.** Firefox gives a page no zoom value of its own: in a test, 150% zoom made the ratio 1.5 and every CSS size (window, screen, outer window) shrank to match. Reading it from Firefox's profile instead would mean the app opening Firefox's own files while it runs. The line says so in words rather than inventing a number.
- **`ui/js/size_readout.js` is the one script allowed to read the screen's size.** The check from the responsive layout work still holds for every other script, and a new test checks that this file only returns the numbers: it changes nothing on the page, imports nothing, and only app.js uses it, to send them.
- **The captures the designer posted on the issue were used:** the Deck's read in place in Steam's screenshots folder (the same files), the Nova's downloaded to a temporary folder outside the repo. That settled the issue's question of how to reach the Nova's captures, so neither a drop folder on the Deck nor a session on the Nova was needed.

**Reason:** the captures answer the question on their own: Kettle Video draws Enamel's tokens one to one on both devices, so the difference from Steam is Enamel's sizes, plus about 4% that Steam adds for itself on the Nova. Full numbers in `docs/sizing-report.md`.

## 2026-10-29 — Enamel 0.8.0: Steam's sizes, from one root size (the Enamel 0.8.0 upgrade)

**Decision:**
- **Enamel 0.8.0 comes in through the sync script** (`tools/update_enamel.py 0.8.0`); `ENAMEL_PIN` is `v0.8.0`. The script needed no change.
- **The app's own sizes stay in rem or Enamel's tokens,** and a new unit test (`tests/test_no_fixed_pixels.py`) fails on any fixed size in `ui/css/` other than one-pixel hairlines. The app's stylesheets already met this; the test keeps it so.
- **The app never sets `--en-root-size`.** It stays at Enamel's 100%; a new browser check (`tests/enamel_sizes_check.py`) checks that, and that turning it up to 112.5% grows the app's own rows, bars and letter strip with Enamel's components.
- **`--shell-bar-height`, before the app measures the bar, is the action bar's new one-line height** (a button plus the tight space above and below, 68px at the normal font size), the same sum as Enamel's `.en-actionbar`, instead of `--en-size-bar` (60px), which no longer matches the bar.
- **The short-window breakpoint moves from 22.25rem to 24.25rem.** The same sum as before (action bar, two lines of tabs, the hint bar, two rows and the gap between them) with 0.8.0's sizes: the bar is 8px taller, each row 8px taller and the gap between rows 8px wider. A media query can't read a token, so the sum is written out.
- **In the smallest supported box one whole row is enough.** The responsive layout work kept room for two rows in a short window. With 0.8.0's text, a film title wraps onto two lines in a window 20rem wide, and such a row is taller than half the room between the bars in a 15rem-tall window, so only one fits. Enamel's own rule for that box (a list row with its title fits) still holds, and the row moved to is always wholly on screen; the shell check now asks for two rows wherever two fit, and one otherwise.
- **The Continue watching row's gap between tiles is Enamel's new shelf gap** (`--en-c-shelf-gap`, 20px), since the row is Enamel's shelf laid out as a grid.
- **The tab strip's side padding is Enamel's gap (`--en-space-gap`) instead of the gutter.** With 0.8.0's larger tab text, the beta tab no longer fit in the smallest supported box and Enamel's tabs now break a too-long label anywhere, which split "(BETA)" from "SHOWS" (the TV beta label). The tabs are centred, so this changes nothing wherever there is room.
- **The Continue watching check lays the row out again after each resize.** Headless Firefox draws a classic page scrollbar, and when a resize makes it appear Firefox kept the tiles' widths from before it (12px of extra row width) until the row was laid out again. Firefox on Linux normally floats its scrollbars over the page, so the devices are less likely to see it (a stale width only makes the tiles a little wider); the check measures Enamel's widths, not that leftover.
- **A focused picker row is brought into view.** In a window too short for the whole menu or remove question, Enamel's dialog scrolls, but the row Enamel moved the focus to could stay out of sight (Down onto "Remove 2 missing items" in the smallest supported box). The app now scrolls that row into view inside Enamel's dialog whenever it gets the focus; nothing else about the picker changes.
- **The whole page keeps the list gutter** (`--en-space-gutter`). Enamel 0.8.0 adds a wider gutter for grids and shelves (`--en-space-gutter-grid`), but Continue watching sits above the lists on the same page, and one left edge for both reads better than two; it can move to the wider gutter when Home gets real shelves.
- **The size readout stays** behind its developer setting (`debug_size_readout`), off unless set: keeping it costs nothing, and the sizing report update measures again with it.

**Reason:** Enamel 0.8.0 raises its sizes to Steam's Gaming Mode (the sizing report, the sizing spike and the second sizing spike), and its DESIGN.md asks apps to size their own layout on the same scale. App sizes built from the tokens follow by themselves; the two that copied an old meaning (the bar's fallback height and the short-window sum) are recomputed from 0.8.0's components.

## 2026-10-29 — Finding the folders with videos (the folder finder)

**Decision:**
- **The rules are the storage spike's, copied into `backend/folder_finder.py`;** the spike's scripts stay as they are. A place counts only if it is in the system's list of mounts, and a card whose folder exists but can't be read is "not ready", never "empty".
- **The page asks `GET /api/onboarding/folders`, which searches again on every call** (so "Look again" is the same call) and keeps every folder found this session in the server, so the folder choice screens can pick a folder by its id.
- **A folder's id is a short fingerprint of its location:** the same folder keeps its id from one search to the next (so a screen can keep its focus after "Look again"), and the id gives no one the location.
- **Each folder also comes with its trail,** the folder names from the place's top down to it, so the folder choice screens can show "SD card › Media › Films". It holds no part of the path above the place.
- **"in 4 folders" counts the folders that hold videos directly;** "62 videos" when there is only one.
- **A search stops after 10 seconds for all places together,** keeping what it read and marking the place "partial", so a slow or failing card can't hold onboarding up for long.

**Reason:** the issue asks for the report's rules and for full paths to stay in the backend; these are the smallest choices that let the folder choice screens build its screens on top without changing this part.

## 2026-10-30 — Onboarding: choosing the folders (the folder choice screens)

**Decision:**
- **The app never creates folders.** It offers only folders that already hold videos, and only reads them; the one file it writes is `settings.json`. The system's folder dialog behind "Browse somewhere else" (the Browse somewhere else work) offers "New folder", and a person could use it: that is the system's dialog, not Kettle.
- **There is no "choose a location" step.** Movies and TV shows can be in different places (films on the card, shows on internal storage), so each screen lists every place, grouped by place, instead of asking for one place first.
- **A folder that can't be used gets a message inside its row,** in Enamel's error style, never a separate screen: the person sees why right where they pressed, the focus stays there, and the message goes when the focus moves.
- **The same folder twice, or one folder inside the other, is refused.** The library would then list the same videos as both films and shows. Folders are compared by where they really are, links followed. Skipping both is refused too: the app would have nothing to show.
- **The backend checks the pair and writes the sentence,** so the rule is in one place and is tested without a browser; the page only shows what it is told. The page sends ids, never paths. Every folder found this session is kept by its id, so a choice made before Look again still counts.
- **An empty `movies_path` or `tv_path` now means "not set"** instead of stopping the app; both empty starts onboarding. A missing key or a value that isn't text still stops it with its sentence, as before. A folder left empty is never scanned, listed or played from (an empty path would otherwise mean the app's own folder).
- **No `settings.json` counts as neither folder set,** instead of stopping the app, and choosing folders creates the file; `settings.example.json`'s two paths are empty, so a copy of it starts onboarding too. The issue's goal is choosing folders without editing the file, and a new person otherwise never reached the flow. A file that still holds the old example's placeholder paths counts as set, as any path does.
- **A kind skipped in onboarding says "No folder chosen"** on its tab, and rescans don't report it as not available: it was a choice, not a fault. "Folder not available" stays for a folder that is set and isn't there.
- **Continue watching forgets an item only when the saved library for its folder no longer holds its file.** With nothing saved for that folder (none chosen yet, a kind skipped, a folder chosen and not scanned yet) the item and its picture stay, though no tile shows until the folder is back. Otherwise opening the app with no folders set would erase the whole row, which nothing can bring back.
- **A folder name that isn't valid text can't be saved,** and the row says the save failed: it can't go in a UTF-8 file, and the log gets one plain line without the name.
- **`settings.json` is written whole, in one go:** the new text goes into a temporary file next to it, which then replaces it, so a power cut never leaves it half written. Every other key keeps its value and its order; the file comes out as indented JSON, readable for hand editing (spacing written by hand isn't kept).
- **The new folders are used at once,** without restarting: Home then opens as at any launch.
- **B on screen 1 quits,** as on every screen without a menu (the hint says "B Quit"); "B Back" is on screen 2. When Settings opens the flow later, its B can go back there.
- **The flow's address is the page address ending in `#onboarding`;** it opens the flow even with folders set.
- **mpv is checked first.** Without mpv the "mpv not found" screen shows, as before, since nothing could be played after choosing folders anyway.
- **The issue's hint words are kept although Enamel's hint can't wrap:** in Enamel's smallest supported box the long A hint is cut at its start. It is recorded as an Enamel gap (`needs enamel`) instead of being styled in the app or shortened beyond the spec.
- **Under each folder, one meta line:** the count, then the examples, separated by a middle dot. A place with no folders gets no band.

**Reason:** the issue asks for the first three points to be recorded; the rest are the smallest choices that build it as specified with Enamel 0.9.0's parts and keep hand-edited settings working.

## 2026-11-04 — "No videos found yet" (the No videos found screen)

**Decision:**
- **The screen has no step label.** The issue's description of the screen doesn't list one, and nothing has been chosen yet, so "Step 1 of 3" would say nothing useful.
- **The backend writes the sentence** (`looked`), from the state of each place it really checked, so it is tested without a browser and can't say "no SD card" when a card was found. A card that can't be read yet is "not ready". A card with nothing to suggest is named as looked at, without calling it empty: it may hold short clips, which aren't suggested. A rarer mix of states (a USB drive not ready as well, a search that ran out of time) adds one short sentence for each rather than one long one, all starting with "Kettle", so the "It" that follows can only mean Kettle.
- **The hint bar says "A Look again" and "B Quit";** Y's hint goes, as A now says the same thing, and Y still works. B keeps its hint because it still quits, as on screen 1.
- **While the first search runs, no title shows.** Otherwise "Which folder has your movies?" could flash just before "No videos found yet".
- **Only screen 1 gives way to this screen.** A Look again on screen 2 that finds nothing stays on screen 2 with its one line, so the choice made on screen 1 can still be saved.
- **Up and Down scroll the page on this screen.** The button is the only thing to focus, and it is the last thing on the screen, so in a short window the words above it could not otherwise be read with the controller. The page goes to its end with `scrollTo`, not `scrollIntoView`: after `scrollIntoView`, Firefox kept pulling the page back to the focused button whenever Up tried to scroll away from it.

**Reason:** the smallest choices that build the issue with Enamel's numbered steps and button, keep the sentence true in every case, and keep every word reachable with the controller alone. Nothing on this screen writes anything.

## 2026-11-04 — "Browse somewhere else" (the Browse somewhere else work)

**Decision:**
- **The spike's recipe is followed as written:** kdialog, then zenity, then Tk, started as its own program on the request's own thread, with no time limit and the home folder as its start. The dialog is looked for when the page searches, so a launch that doesn't need onboarding pays nothing. Its error output goes nowhere, since it could name a folder and the launch log must not.
- **A picked folder doesn't save anything by itself.** It gets a row, focused, and the person chooses it with A, like any listed folder. A folder that can't be used shows its message in that row straight away, in the same words. A folder the search already found is the same row, not a second one.
- **A folder in none of the places shows under "Somewhere else",** with only its own name: the page never learns what is above it, and "Other drive" could be untrue. A folder with no videos can still be chosen and says "No videos found"; one too big to count in time says "At least N videos".
- **The log says which dialog and what happened** ("onboarding: folder dialog (kdialog): picked", or "cancelled"), and "failed", "not a folder" or "couldn't start" when that is what happened. Never a path. The name of the dialog is what the Nova test needs to report.
- **Only Kettle's own stop signal counts as a cancel, along with exit 1 and empty output.** A dialog that crashes counts as failed, so the row says so and the log doesn't say "cancelled", and the Tk helper exits with 2 when it can't open its window (Python's own exit for an error is 1, which would read as a cancel). A program that itself exits 1 because it can't open a window still reads as a cancel: that is the spike's rule, and the exit code alone can't tell them apart. This wasn't tried on a real kdialog or zenity.
- **Firefox didn't give up on a long request when tried, so nothing was added for that.** Its setting `network.http.response.timeout` (300 seconds) was expected to end it. Tried on Firefox 153.0.3, headless, on the Deck, with a POST left unanswered: still waiting after 330 seconds with the default, and after 40 seconds with the setting lowered to 5 (read back from Firefox as 5). The server saw one request each time, so no retry; a control request answered after 6 seconds was seen. Limits: this one version, a bare test page rather than the real app with a dialog held open, and the Nova wasn't tried. If the request did fail while the dialog stayed open, the page wouldn't break: the focus comes back and the row (on the no-videos screen, the line above the buttons) says "Couldn't open the folder window", though that dialog would still be open, B would no longer close it, a second try would say "The folder window is already open", and a folder picked in it would be lost.
- **While the dialog is open, B closes it** and the hint says "B Cancel". The issue doesn't ask for this, but a dialog that opens behind Kettle (the Nova risk) would otherwise leave the controller with no way out. The server closes any open dialog when it stops, so nothing is left running.
- **The A hint says "Browse" on this row,** since "This is my movies folder" would be untrue there. It is short so that it still fits in the smallest supported box. The hint bar can change height as the focus moves, so the focused row is brought back into view when it does.
- **On "No videos found yet" the two buttons sit one under the other.** Up and Down still scroll, and Down never scrolls past the focused button before moving to the next one, so every word can still be read in a short window.

**Reason:** the smallest choices that follow the spike and keep the words on screen true, the path private and the controller never stuck.

## 2026-11-04 — Onboarding part 1: fixes from the series review (the first onboarding review fixes)

**Decision:**
- **A folder that holds Kettle's own files can't be chosen.** Its row says "Kettle keeps its own files inside this folder, so it can't be used. Put your videos in a folder of their own, then press Y to look again.", and A stays there. "Its own files" means the app's folder (with `settings.json`), the logs folder and the data folder. Reason: CLAUDE.md says media folders are read-only to this app, and `settings.json`, the saved library and the logs would be written inside this one. **What it costs:** internal storage is the home folder and Kettle normally lives inside it, so someone whose only videos sit loose at the top of the home folder gets this row and nothing else to choose, and skipping both kinds is refused too. They can't get past onboarding until they move their videos into a folder of their own, themselves, in Desktop Mode. The storage report found no library at the top of the home folder on either device, so this should be rare. A refused folder from the dialog also names Browse, as Y can't find everything: the search leaves out short clips, hidden folders and skipped names. **A picked row isn't re-read by Look again,** so after videos are moved out of it, its count and example names stay as they were until it is picked again; it stays refused either way, so nothing wrong can be saved. A `settings.json` edited by hand isn't refused; there, Continue watching's pictures stay off, with a line in the log, as before.
- **A folder name ending in a space is saved as a `file://` address** in `settings.json`, and only such a name. `load_settings` trims a path, so that a pasted path with a stray space still works, and it reads a `file://` address back exactly. Trimming only when no such folder exists was the other way, but with a card out at launch it would look for the wrong folder. Every other folder stays a plain path, for hand editing.
- **Screens 1 and 2 say above their list what the search couldn't see:** a card that isn't ready, a search that ran out of time, storage that can't be read. The backend writes the line (`gaps`), so it is tested without a browser. It uses the "Looking for your videos" line's place, not its error style: nothing failed, and the folders found can still be chosen. Finding no card at all is not a gap, so nothing shows then. "No videos found yet" and an empty screen 2 already say this in their own sentences, so they don't get the line. Measured in Enamel's smallest supported box, the line was scrolled wholly off the top, and alone it is taller than the room above the hint bar. So when the line and the first row don't fit together, the screen still opens on the focused row, Up on that row scrolls up to the line and the title, and Down comes back. **The gap that leaves:** in that box the line isn't visible until Up, and nothing on screen says to press it. Opening at the line instead was tried and dropped: the focus was then out of sight, and A could save a folder never shown, which nothing in the app can change afterwards. For the same reason, A on a row scrolled out of view only brings it back. So that this never takes an extra press in normal use, a row that only just fits is placed exactly, and one taller than the room shows from its start and counts as in view from there. A row left with its top cut by its own message takes one extra A, which changes nothing. One press scrolls at most three quarters of the room above the hint bar, so lines stay whole from one view to the next.
- **A picked folder that can't be read says "Couldn't be read" and can't be chosen,** with a message in its row. One that can be read, with only unreadable parts and no videos, says "No videos found in the parts Kettle could read" and can still be chosen: the rest of it may fill up later. Picking a folder again replaces its row, so one that has become readable can be chosen.
- **Y from a screen with no folder list lands on the first folder,** as the spec says for a screen that opens; when it still finds nothing, the focus stays where it was.
- **The plain list says "No folder chosen"** for a skipped kind, in the normal style, as the normal view does: it was a choice, not a fault.

**Reason:** each fixes what the series review of "onboarding part 1" found, with the smallest change that keeps the words on screen true.

## 2026-11-05 — The keys just after saving the folders (the second onboarding review fixes)

**Decision:** from the save until Home is ready, A, B and every other key except d do nothing, so a second press never acts on the rows just removed. If Home still isn't ready after 10 seconds, the loading screen shows with its "Still working…" and B quits again, as at launch; A stays off until Home is ready. The 10 seconds are the loading screen's own, so no new words, looks or timings. **What it costs:** for those 10 seconds a press of B is ignored, and the empty page's hint bar still says "B Quit", which isn't true until they have passed; before this fix B did quit there. Home normally takes much less, so it only shows when something has stalled. A Home that answers just after the 10 seconds shows the loading screen only for a moment, as nothing holds it for its usual 2 seconds. This was tested by holding Home's answer back, not with a real stalled card.

**Reason:** the issue asks that B doesn't quit in that moment, and a stalled card must not be a dead end. Showing the loading screen at once would have added a flash, or a wait of 2 seconds, to every first launch.

## 2026-11-05 — The letter strip is drawn in front of the tabs, and scrolls rather than shrinking away (the letter strip fix)

**Cause:** the letters were always worked out correctly, but the solid band behind the tabs was stacked in front of them. With Continue watching showing, that band sits lower down the page until it docks, so it crossed the strip and hid the letters behind it.

**Decision:**
- **The strip is drawn in front of the tab strip.** Only the letters are drawn, with nothing behind them. Moving the strip's top down to follow the tabs was rejected: it would leave little room on first load and make the strip change as the page scrolls, which is what the issue rules out.
- **The tabs keep their place.** Giving the tab strip room for the letters made "TV Shows (beta)" break onto three lines in the smallest box, undoing the TV beta label. In a narrow window only the empty end of the TV Shows tab can reach the strip's column. That tab has no pill while the strip shows, as the strip is on Movies only, so nothing is covered; `tests/letter_strip_check.py` checks no letter sits on a tab's words or on a button.
- **Letters stop shrinking at seven tenths of Enamel's small text; below that the strip scrolls by touch**, and the app keeps the current letter in view. The fit-everything rule took them down to about 5 pixels in the smallest box, in view but unreadable. Enamel has no token for this floor, so it is worked out from `--en-text-small`.
- **TV Shows still has no strip.** Shows have no letter groups (the Movies list work, the title sorting work), so "the letter groups with titles in the current tab" is none. Adding them would change Left and Right there and is a new feature.

**What it costs:** in windows too short for every letter, not all letters show at once. With the scrollbar hidden, as on the Continue watching row, the only sign of more is a letter cut at the edge.

## 2026-11-05 — Fresh start opens onboarding; the folders chosen last one session (the fresh start onboarding work)

**Decision:** in fresh start both folders count as not set, whatever `settings.json` says, and the one file onboarding can save to is a `settings.json` in fresh start's temporary folder. The designer's choice on the folder choice screens ("let's go with 1"). All of it is one small step at launch (`launch_options.for_session`), so the onboarding code, the save and "Browse somewhere else" are exactly those a new user gets, and a normal launch takes the same path as before. That file is never read back: the app already has the choice in hand, and a next fresh start makes a new folder, so an old choice can't reappear, whether the last session quit or crashed. Every other setting still comes from the real file.

**A mistake in the real file still stops a fresh start** with its sentence, including a `movies_path` or `tv_path` that is missing or isn't text, although the folders' values aren't used. The settings are read before fresh start is looked at, and the same mistake would stop the normal shortcut too, so it is better seen than hidden.

**What it costs:** the check that refuses a folder holding Kettle's own files doesn't see the real data folder in fresh start, wherever `data_dir` puts it, as that folder isn't in use there and nothing is written to it. The app's folder and its logs are still refused. The log's `settings saved` line stays as it is, with one line at launch saying the folders last this session and `settings.json` isn't written.

**Reason:** onboarding couldn't be tested on the devices without changing the settings file by hand, and emptying it on the Nova would lose its auto-update switch (details on the folder choice screens).

## 2026-11-05 — Look again on the first launch's "mpv not found" (the mpv missing screen)

**Decision:** the button shows on a first launch only; later launches keep the message on its own. The issue asks for the smaller option unless the shared screen makes it harder, and it doesn't: the app has to ask whether this is a first launch anyway, and that one answer decides. So the mpv check is now followed by that question on the failing path too, with a 10-second limit on it, since a backend that has just failed the mpv check might not answer this either and the loading screen must still give way.

**Look again reads `mpv_command` from `settings.json` again.** The app reads settings once at launch, so without this, fixing the file as the screen asks would change nothing until a restart, and "Look again" would be untrue on that version of the message. It reads the real file in fresh start too (only reads it), and only this one setting, so nothing else changes while the app runs. If the file can't be read at that moment, half saved or broken, the screen says so in the file's own sentence, instead of carrying on with the old value.

**A press always shows something.** With the same answer, the screen adds "Tried again. Same answer.", in the same words on all three versions, and a check over a second says "Checking again…". It doesn't say nothing has changed: the page only compares the words on screen, and a viewer can change `mpv_command` from one program that can't be found to another and get the same sentence. The issue only says the screen stays; without these a press looks dead, and CLAUDE.md rules out failing silently. The app's existing status line, no new styling.

**During a check only A is off.** Not the app's "busy" state, which also stops the arrows: B and Up and Down keep working, so a stalled check, which the page gives up on after 30 seconds as at launch, never leaves a screen without keys. For half a second at least after mpv is found, screen 1's keys stay off, also when the search for folders fails, so a double press doesn't choose a folder or "I don't have movies".

**What it costs:** other settings changed by hand while the app is open still need a restart. If the question "is this a first launch?" fails or takes over 10 seconds, a first launch without mpv counts as a later one: the message shows with no button, and the viewer has to start the app again, as the app has no way to tell which screen comes next. A `flatpak info` that hangs forever isn't stopped by the backend, as at launch; the page stops waiting, and each later press can leave one more waiting behind it until the app quits.

## 2026-11-06 — The first scan and its result (the first scan screen)

**Decision:** After the folders are chosen, onboarding's screen 3 scans them and shows what it found, before the library opens. The temporary "Scan my folders" screen is gone. Details: `docs/spec.md`, "Onboarding: the first scan and its result".

- **A folder that looks mixed is noted on the result screen and never blocked.** Files in the Movies folder that look like episodes, and loose files in the TV Shows folder that look like films, get one line each. The app can't be sure, and a wrong guess shouldn't stop someone reaching their library.
- **No "Scan my folders" for anyone** (the designer's answer on the first scan screen): folders set with no saved library, or an empty library on Home, go straight to screen 3. It's the same flow, with no second screen to keep.
- **An empty library counts as no library** when deciding what to open. A scan that finds nothing still saves one, and Remove can empty one, and Home has no Change folders, so both go to screen 3. Missing items still count, because Home is where they can be removed.
- **"Nothing found" offers Change folders only** (the designer's answer on the first scan screen): Home would have nothing to show.
- **The panels and notes wait for Enamel** (the designer's answer on the first scan screen), which added them in 0.10.0 (the Enamel 0.10.0 upgrade), rather than being styled in the app.
- **The counts are worked out in onboarding's own code**, from the saved library the scan has just written, so neither the parser nor the library index changes. They count only what is in the folders now: a rescan keeps what has gone as missing, and those aren't counted.
- **"Could not be read" means** a video the scan had to skip (the file or its name can't be read), or a name that gave the name reader nothing: a film with no title, or an episode with neither a title nor a number. On the real library that is zero today, as expected.
- **"Looks like an episode" is a plain pattern in the file's name** (S01E02, 1x02), not the name reader asked a second time. The name reader finds numbers in titles such as "Quillmoor 13" when asked to read one as an episode, and a wrong note misleads, while a missed one costs nothing. It would also take time on a big library.
- **With folders already set and nothing chosen, B goes to screen 1, not screen 2** (decided, differs from the issue's "B goes back to screen 2"). Screen 2 there has no Movies choice behind it, so choosing a TV folder would clear the Movies folder already set, without anyone having said so.
- **A failed scan, or every folder out, says the existing message with Change folders** (decided). B does nothing during a scan, so the result needs a way out. One folder of two out is a note instead, and the other still opens: being kept from a library that's fine, because a second folder has a problem, would be worse.
- **A long scan says "Still working…" after 10 seconds with no change** (decided), the loading screen's words and time. The count moves in only two steps, as the grouping reports no progress of its own and this issue doesn't change the library index.

## 2026-11-10 — Bring in Enamel 0.11.0, Enamel's own look (the Enamel 0.11.0 upgrade)

**Decision:** The app takes Enamel 0.11.0 as it is. It marks a button or menu row as pressed while A is held (`data-pressed`), puts the page speckle on the loading screen only, gives its own boxes Enamel's new corners, and follows Enamel's units and grid rule in its own CSS (rem if a size should grow with the viewer's text, px if not, a multiple of 4 either way; exceptions listed in `docs/spec.md`, "Units and grid audit"). The lighter fallback is not switched on. The 200% text check runs at the window sizes that hold Enamel's smallest supported box at that text size.

**Reason:** the designer asked for Enamel's own look with this audit (2026-11-10). The speckle belongs on empty page ground and never behind list text, and the loading screen is the only such place. The 0.8.0 rule "never fixed pixels" is replaced by Enamel's own question, since 0.11.0's interface size now scales pixels too, through zoom. Enamel defines its smallest box in rem, so it grows with the viewer's text. Whether the Nova needs the lighter fallback is the designer's call after testing on the device: for everyone, or as a "lighter look" option, never by detecting the device. The Nova only gets code from `main`, so it is tested after the merge (decision of 2026-10-01).

## 2026-11-11 — Bring in Enamel 0.11.1, wording only (the Enamel 0.11.1 upgrade)

**Decision:** The app takes Enamel 0.11.1 as it is, through the update tool, and the pin moves to v0.11.1. Nothing else in the app changes. `THIRD_PARTY_LICENSES.md` now describes Enamel's reworded `NOTICE.md` (the neutral palette, spacing and motion designed to match Steam's Gaming Mode; no Valve code, class names, icons, logos or fonts; Enamel and Kettle not affiliated with Valve; no rights to the Enamel or Kettle names or the Kettle wordmark), and the README and licences list no longer call Enamel's repository private.

**Reason:** Enamel's changelog asks for it straight away: it rewrote its history when it went public, so the v0.11.0 tag the pin named is gone and the design system check could only skip. Every token and rule is the same once comments are left out (compared on the stylesheets), so nothing looks different. The new notice is not a licence question: Enamel's licence is still MIT, the copies are still unmodified, and the one limit it states (no rights to the names or the wordmark) was already in the 0.11.0 notice; only the wording of what Enamel matches changed.

## 2026-11-11 — The privacy guard (the privacy guard work)

**Decision:** One guard, `tools/privacy_guard.py`, checks every commit, commit message and push, and every tracked file in the quick and full checks, against a private word list kept outside both repos (`~/Development/.privacy-guard/words.txt`, shared with Enamel's guard), plus patterns that need no list. A missing or empty list makes it fail. The storage spike's checker now takes its words from it. Details: `docs/dev-environment.md`, "Privacy guard".

- **It never prints what it found**, only the file, the line and the kind of thing, so a failure can't leak the word it protects.
- **Placeholders pass:** `<user>`, `{user}`, `$USER` and `~/` in a path are fine; a real name after `/home/`, `/var/home/`, `/run/media/` or `/Users/` is not. A path that only contains `/home/` further along (`/somewhere/home/Videos`) is not a home folder.
- **Words match whole and ignore case**, so a private word inside a longer one doesn't stop a commit. Common folder words (Sample, Extras, Specials…) stay out of the list, as in the spike.
- **The commits' attribution address passes** (`noreply@anthropic.com`, in every commit's Co-Authored-By line): it is a public no-reply address, not a person's, and without it the commit-message check would stop every commit.
- **Only the known category names are headings in the list.** A file name in brackets ("[Group] Title [720p]") is an entry like any other; read as a heading, it would have been printed as the kind of a finding.
- **Third-party files** (`vendor/`, the bundled fonts) are checked against the list only: their authors' addresses and paths are copied unchanged.
- **Pictures and logs** are only reported when a file is added, so a picture already committed doesn't block every later change to it.
- **The hooks are written by a tracked setup script** (`tools/install_privacy_hooks.py`), since git never tracks hook files; it leaves any hook it didn't write alone and says so.
- **The repo's history is not rewritten** (that would mean a force-push). The one finding in the current files, the Nova's user name in a path in `docs/spikes/controls.md`, is fixed with a normal commit.

## 2026-11-13 — Settings for launch (the Settings screen work)

A minimal Settings screen, from Home's menu: change the Movies and TV Shows folders, and see the version and the licences. Rules in `docs/spec.md` ("Settings").

- **Settings writes `settings.json` too** (the issue asks for it). Until now onboarding was the only writer. Settings writes one kind's folder with the same code (the file read whole, the one key changed, every other setting kept in its order, written next to it and swapped in), so a hand-edited file keeps working; CLAUDE.md's design rule and the spec say so. In fresh start it writes only the session's temporary settings file, as onboarding does.
- **A version number** (settled by the designer): a `VERSION` file at the repo root, starting at `0.1.0-dev`. About reads it each time Settings opens.
- **mpv in `THIRD_PARTY_LICENSES.md`** (settled by the designer): a "Used but not bundled" section. About shows it with a short note and its link instead of a licence text, so About matches the file exactly. About reads its credits from that file each time, so the two can't drift; each bundled credit's licence text comes from the file next to it, through the backend, asked for by the credit's id, never by a path.
- **Old items show as Missing** (decided on the issue): when Settings changes a folder, the saved library's list for that kind moves to the new folder with every film, show, part and episode marked missing and no file known; the rescan that follows reads the new folder afresh and brings back whatever is at the same place inside it (an SD card copied to internal storage keeps its films and their Continue watching tiles), and the rest stays missing until Remove N missing items. This lives in the library store (`library_index.move_folder`); the scanner is unchanged. Marking them at once, rather than leaving it to the rescan, means they read Missing even if the rescan can't run (a film playing). A folder changed by hand in `settings.json` still starts as "Not scanned yet", and onboarding's Change folders is unchanged. The toast after such a change says what was added; the missing count shows in the menu's Remove row.
- **Movies' refusals name the TV shows folder.** Onboarding only ever checks the TV shows folder against the movies folder, so its sentences name the movies folder. From Settings, a TV shows choice gets those sentences word for word; a movies choice gets the same checks with the TV shows folder named ("Already your TV shows folder. …"), which is what the person is looking at.
- **One scan at a time:** a folder can't change while a scan runs ("Kettle is reading your folders. Choose again when it has finished."), as the running scan reads the folders as they were. The change starts its rescan itself, in the same request, and the page only follows it, so a scan that ends at once is never followed by a second one.
- **Stop using** saves an empty folder for that kind and starts no rescan; stopping the second kind is refused in its row, as onboarding refuses skipping both.
- **Badges on the folder screen:** each kind's folder now carries Enamel's badge ("Movies", "TV shows"), and the focus starts on this kind's folder, so the current choice is visible and choosing it again changes nothing.
- **A licence is plain page text** (`needs enamel`): Enamel has no view for reading a long text, so the licence is paragraphs of the page's body text under its name, scrolled with Up and Down like the "mpv not found" message. Nothing is styled in the app for it; the gap is on the issue for Enamel's "Gaps found by the apps" issue.

## 2026-11-13 — Bring in Enamel 0.12.0, the destructive row (the Enamel 0.12.0 upgrade)

**Decision:** The app takes Enamel 0.12.0 as it is, through the update tool, and the pin moves to v0.12.0. Nothing else in the app changes: the new red destructive row is not used anywhere yet.

**Reason:** Enamel's changelog asks Kettle Video to adopt 0.12.0 before its Home polish (the Home polish), which puts the destructive row on Quit in Home's menu; that stays the Home polish's job. The release only adds (the destructive row's rules for list and picker rows, and a `DESIGN.md` rule that red is a status colour, never a second accent); no token, class, state or script function is renamed or removed and no token is added, so nothing looks different.

## 2026-11-13 — Home polish: Quit in red now, the see-through bar waits for Enamel (the Home polish)

**Decision:** Quit in Home's menu is Enamel 0.12.0's destructive picker row (`.en-picker__row--destructive`), red whether it has the focus or not; no other row and not the B Quit hint changes. The see-through top bar with its fade is not built: the bar stays Enamel's opaque action bar, and the gap is a `needs enamel` question on the Home polish.

**Reason:** Enamel's `DESIGN.md` says the action bar "stays docked (sticky) and opaque while the content scrolls underneath" and it has no fade or "content underneath" style, so building the see-through bar would mean styling it in the app, which CLAUDE.md forbids. Quit in red can be built well with what Enamel has, so it ships on its own rather than waiting; the bar can follow once Enamel offers it.

## 2026-11-13 — Tidy-up after onboarding part 2 (the onboarding tidy-up)

**Decision:** The 10-second wait and "Still working…" are written once, in a small module of their own (`ui/js/still_working.js`), used by the loading screen, Home opening after onboarding and the result screen's scan; the loading screen keeps its words in `index.html`, held the same by a test. Onboarding's buttons and the "mpv not found" screen's Look again come from one shared maker in `ui/js/dom.js`. `openHomeAfterSave` is now `openHomeAfterOnboarding`; `showFirstScan` keeps its name. The spec's "Not built yet" also drops the Settings screen, built by the Settings screen work.

**Reason:** a refactor that changes nothing a viewer sees. The wait and words aren't Home's menu words, so they don't join `home_menu.js` beside the failed-scan message; a module of their own is the smallest clear home. `showFirstScan` still says what it does (the spec's own name for that screen is "the first scan and its result"), so renaming it would only churn. Leaving Settings in the "Not built yet" list would have left the spec as wrong as the issue set out to fix.

## 2026-11-13 — Home polish rework: Quit back to a plain row, the bar still waits for Enamel (the Home polish)

**Decision:** Quit in Home's menu goes back to Enamel's plain picker row, like the other rows, focused and not. It gets a red face only once Enamel has a destructive row that is plain until it has the focus. The top bar stays Enamel's opaque black action bar. Both gaps are `needs enamel` questions on the Home polish. This replaces the earlier "Quit in red now" entry for the Home polish.

**Reason:** The designer tested Quit red in every state and asked for it to look like the other rows, red only with the focus. Enamel 0.12.0's destructive row is red in every state by its own rule, and the app may not restyle it, so the plain row is the closest Enamel gets to that feedback: right while unfocused, missing only the red on focus. The bar looks black because Enamel draws it on `--en-surface-bar` (pure black), not on the page's `--en-surface-page` (dark blue-grey); the app sets neither and Enamel has no see-through or page-coloured bar, so nothing in the app can change it until Enamel adds one.

## 2026-11-14 — Keep-awake never blocks a sleep the viewer asks for (the power button fix)

**Cause:** the system lock that mpv runs inside (from the keep-awake work) asked for `idle:sleep` in block mode. The `sleep` part refuses *every* sleep while it is held, including one asked for with the power button or Steam's power menu. Steam turned the screen off and asked the system to sleep; the system refused; the film kept playing on a black screen and nothing turned the picture back on. Shutting down is a different request, so it still worked. Checked on the Steam Deck, read-only, with a stand-in command instead of a film: with the old lock held the system answers "inhibited" to "may this device sleep?"; with `idle` only it answers "yes". Not the same cause as the screen wake lock fix (the screen going off by itself, which the Firefox wake lock fixed and which can't block sleep); the two only share Steam not bringing the picture back once it is off.

**Decision:** the lock asks for `idle` only, never `sleep` (`backend/keep_awake.py`). Chosen by the designer on the power button fix (option 1) over removing the keep-awake work lock altogether (bigger, and loses a layer that still helps in Desktop Mode) or waiting for the Nova results. `launch.sh`, how mpv is started and mpv's own options don't change; mpv still runs inside the same lock tool, so the lock still ends however the film ends. The screen still stays on by itself during a film (the `idle` part, the screen wake lock fix's wake lock and mpv's `--stop-screensaver=yes`, all "don't go idle" requests). While asleep, mpv is frozen with everything else, so the film is at the same point on waking; Kettle adds no pause of its own (that needs the live mpv connection planned for later). Tests keep the lock to `idle` only, and on a device with the real tool check that the system still says "yes" to sleep while Kettle's lock is held.

**Nova risk:** the bug was seen on the Nova; if sleep also fails there without Kettle (mpv by hand, another app), that part is Armada's and gets a README note, not code. The Nova steps are on the power button fix.

## 2026-11-14 — Start-up problems shown on screen with what is already there (the start-up problem screen)

**Decision:** when Kettle can't start (Firefox missing, the server stopping while starting, most often a mistake in `settings.json`, or the server never answering), the launcher shows a short message saying what went wrong, what to do and the log's name, closed with A or B. With Firefox it is a small page in the same kiosk window, served by a separate message server (`backend/startup_error.py`, standard library only, using nothing from the app but the settings reader). With no Firefox it is the system's own dialog: zenity, which is part of SteamOS, else kdialog; with neither, only the log. The launcher now looks for Firefox before starting the server. Wording and look (the "mpv not found" screen's box, Enamel's primary button Close and the hint bar A Close, B Close) decided on the issue, as the issue asked for them to be agreed; reply there to change them.

**Reason:** "never fail silently" (audit finding H3): in Gaming Mode there is no terminal, so the app just opened and closed. The issue asked for no new tool or package: Firefox and Python are already needed, and zenity and kdialog are already on SteamOS, so nothing is added. A separate message server rather than the app's own: whatever stopped the app (a settings mistake, a broken install) must not stop the message too. Closing the page ends that server, so the launcher's usual "one of the two is gone, close the other" loop closes Firefox, with no Firefox setting changed.

**Nova risk:** Armada may have neither zenity nor kdialog, so with no Firefox there the message may only reach the log. With the Flatpak Firefox (as on the Nova) the page path is the same as on the Deck.

## 2026-11-17 — Bring in Enamel 0.13.1, the destructive row plain until focused (the Enamel 0.13.1 upgrade)

**Decision:** The app takes Enamel 0.13.1 (which includes 0.13.0) as it is, through the update tool, and the pin moves to v0.13.1. Nothing else in the app changes: no row uses the destructive look, and putting Quit in Home's menu back on it stays the Home polish's job.

**Reason:** 0.13.0 is the Enamel change the Home polish was waiting for: the destructive row now looks like a plain row of its kind until it has the focus, and is red with white text only while focused or pressed. 0.13.1 only rewords Enamel's documents and comments. Neither release renames, removes or adds a token, class, state or script function, and no screen uses the destructive row, so nothing looks different.


## 2026-11-17 — Home polish, third round: no bar at the top, Quit on Enamel's new destructive row (the Home polish)

**Decision:** Home has no bar at the top any more. Enamel's action bar (docked and black) is taken off; its Menu button stays at the top right of Home, on the page with no fill behind it, and scrolls away with the page. The tab strip stays pinned, now to the very top of the window. The hook keeps its name (`#action-bar.action-bar`, without `.en-actionbar`) and the app only lays it out (buttons on the right, wrapping, Enamel's tight space above and below); `--shell-bar-height` and its measuring go, and the short-window rule drops by the bar's height, from about 24.25rem to about 20rem. Up from the top row still reaches Menu, and the page goes to its top. Quit in Home's menu is Enamel 0.13.1's destructive picker row: like the other rows while unfocused, red with white text only while focused or pressed. This replaces both earlier Home polish entries; nothing in the Home polish waits for Enamel any more.

**Reason:** the designer's feedback on the Home polish (2026-11-14): "just remove the bar altogether and keep the button for the menu … let it just scroll so there's no need for an actual bar", and use Enamel's updated destructive row for Quit, which the Enamel 0.13.1 upgrade brought in. With no bar there is nothing to style, so the see-through bar Enamel lacked is no longer needed; the Menu button and the rows are Enamel's own, unchanged. Keeping the tabs pinned (rather than letting them scroll away too) is the smaller change: the feedback was about the bar, and the tabs are on the page's own colour, so nothing black remains at the top (decided on the Home polish; reply there to change it).

## 2026-11-17 — The release script: archive, checksum and notes from a tag (the release script work)

**Decision:** `tools/release.py` (developer only, standard library) builds a release from a tag: `<archive name>-<version>.tar.gz`, its `.sha256` checksum (the format `sha256sum -c` reads) and `<archive name>-<version>-notes.md`, by default in `dist/`, which git ignores. A release tag is `v` followed by the tag's own `VERSION` (`v0.1.0-dev` today); anything else, such as the old `v0.0.1-skeleton`, stops with a plain message saying which tag it should be. Everything is read from the tag with git, never from the working folder, and the archive takes only the app's own files: `backend/`, `ui/`, `vendor/`, `installer/`, `launch.sh`, `install-shortcut.sh`, `LICENSE`, `THIRD_PARTY_LICENSES.md`, `README.md`, `VERSION`, `CHANGELOG.md` and `settings.example.json` (a list of what goes in, not of what stays out). The privacy guard checks every file in the archive and the notes before anything is written. Every installer name (the name people read, the app id, the archive name, the install folder's name, the desktop entry) lives in `installer/names.env`, plain `KEY="value"` lines a shell can source and Python reads; it holds today's names, and the rename (the Kettle Video rename) changes them there once. `CHANGELOG.md` starts at 0.1.0-dev; older history stays here and in git.

**Reason:** the issue asks for the archive to hold nothing from the designer's devices: a list of what goes in can't let in a file nobody thought of, where a list of what stays out could. Reading the tag rather than the folder keeps untracked and uncommitted files out too. The archive is built the same way each time (fixed times from the tag, no build time inside), so the same tag gives the same checksum. Docs, tests, spikes, tools and scripts are for developing the app, not running it, so they stay in the repo (the README's links still reach the docs on GitHub).

## 2026-11-17 — Everything is called Kettle Video (the Kettle Video rename)

**Decision:** The app's old names go everywhere outside history: the desktop entry `install-shortcut.sh` writes is `kettle-video.desktop`, the lines the app writes to its mpv logs start `kettle-video:`, the launcher's environment settings are `KETTLE_VIDEO_PORT` and `KETTLE_VIDEO_LAUNCH_START`, and the guides name the `kettle-video` folder. The kiosk window gets a fresh Firefox profile, `kettle-video-profile`; the old `media-player-profile` is never moved, changed or deleted, and while it is there each launch log says once that it is no longer used and can be removed by hand. The private repo becomes `enamelware/kettle-video-private` (the designer's decision on the Kettle Video rename), keeping `kettle-video` free for the public repo (the clean copy work): it was renamed on GitHub once the designer said yes, and this clone and the board settings (`.claude/board.json`) point at the new address; GitHub forwards the old one. The installer's names in `installer/names.env` (the release script work) are `kettle-video` too. A check (`tests/test_kettle_video_name.py`) fails if "Media Player", `media-player`, `media_player`, "Kettle Watch" or "Kettle Player" come back anywhere outside `vendor/`, entries here or in a changelog dated up to the rename day, the October audit and the dated spike reports in `docs/spikes/`. The design system's old name has its own check (the Enamel rename). The app's data folder (`data/`) never carried an old name, so nothing in it moves.

**Reason:** a fresh profile loses nothing (the launcher writes its settings at every launch, the page stores nothing in the browser) and never touches files outside the repo, so it is safer than a move (the designer's decision on the Kettle Video rename). The spike reports are dated records of what was seen on the devices that day, like the audit, so they keep their words (decided on the Kettle Video rename). Logs from before the rename keep the old `media-player:` prefix; nothing reads it back.

## 2026-11-17 — The installer, and where an installed copy keeps its things (the installer work)

**Decision:** `installer/install.sh` installs Kettle Video into the home folder with one command (`bash install.sh`), never with `sudo`, a password, a system change or a write to Steam's files. It takes a release archive and its `.sha256` file (the newest `kettle-video-<version>.tar.gz` next to the script, or one named on the command line), checks the checksum and that every path stays inside the archive's one folder before anything is placed, unpacks beside the app folder and swaps it in, so a second install replaces only the app files. A folder at the app's place that the installer didn't make is left alone and the install stops. The places are the designer's (decided on the installer work): app files `~/.local/share/kettle-video/app`, data `~/.local/share/kettle-video/data`, settings `~/.config/kettle-video/settings.json`, logs `~/.local/state/kettle-video/logs`, each moved by its XDG variable when that is set to an absolute path. The installer leaves a mark file (`INSTALL_MARK` in `installer/names.env`) in the app folder; `backend/app_paths.py` sees it and points the settings reader, the server and the start-up message at those places. Without the mark (a development copy, this git folder on the Deck and the Nova) everything stays in the app folder exactly as before. The desktop entry (Multimedia in the app menu) uses the app's icon, `ui/kettle-video.png`. If mpv is missing the installer says why it's needed, shows `flatpak install flathub io.mpv.Mpv` and runs it only on a yes; on a no, no answer or a failure it finishes anyway and prints the per-user commands as a fallback. It ends with what it did, where everything lives and the Steam steps (right-click the menu entry, Add to Steam, then set the controller layout again). `launch.sh` asks the app where its logs go (`python3 -m backend.app_paths logs`) and writes its launch log, Firefox log, lock and Flatpak instance file there, falling back to `logs/` if the answer can't be worked out (the designer's yes on the installer work), so all of an installed copy's logs are in one place and none land in the app files an update replaces. The release script also writes `install.sh` next to the archive, with `names.env`'s lines written into its names block, so it works on its own. `install-shortcut.sh` stays, for development copies only.

**Reason:** a mark file is the smallest, clearest sign: a development copy can never get one by accident, and an unpacked archive without the installer behaves like a development copy. Deciding the places in one module (and keeping the installer's shell copy of the rule in step with a test) means the update (the installer's update step) can replace the app folder without touching settings, data or logs. The icon is a placeholder in Enamel's colours (raised grey, coral play mark; mustard stays on the wordmark only), drawn by `tools/make_icon.py`; it lives in `ui/` because the privacy guard approves the app's own pictures there (all decided on the installer work; reply there to change them).

**Nova risk:** Armada's documentation (armadaos.dev, checked 2026-11-17) says nothing about Flatpak remotes or password prompts; it is Fedora-based, where Flathub is normally a system remote. The Nova already runs the Flatpak mpv, so the system command is printed first, with `flatpak remote-add --user --if-not-exists flathub …` and `flatpak install --user flathub io.mpv.Mpv` for a device where it asks for a password or can't find flathub. The app finds a per-user Flatpak mpv the same way (`flatpak info io.mpv.Mpv`).

## 2026-11-17 — Updating by running the installer again, with rollback (the installer's update step)

**Decision:** One shared step, `installer/update.py` (standard library only, importing nothing from the app), places the app files for a first install and for an update; `install.sh` runs it, and the app's "Update and restart" (the Update and restart work) is to call the same step, so the checksum check and the rollback are written once. The release script writes it into the `install.sh` it puts next to the archive (between `# --- update logic ---` lines, read with a quoted heredoc), so the downloaded installer still needs no other file and never runs code from an archive it hasn't checked. Each version is unpacked into its own folder in `~/.local/share/kettle-video/versions/`, and `~/.local/share/kettle-video/app` becomes a shortcut (symlink) to the current one; switching versions replaces that shortcut with one rename, after everything has been flushed to disk. "Started cleanly" means, with no person needed: the new version's server starts from the app folder on a free port and reads the person's own settings file without a mistake, its page and every stylesheet and script the page links answer within 30 seconds, and `/api/onboarding` answers; then it is asked to close. It runs as a fresh start (the fresh start mode), with an empty temporary data folder of its own, so the person's data folder is never opened (reviewer round 1 on the installer's update step: a normal start tidies Continue watching's list and pictures, which a check must never do). Only after that is the previous version removed; if unpacking, the switch or the first start fails, the shortcut goes back to the previous version and the message says so. An older archive is installed only after a yes. An install made by the installer work's installer (a plain `app` folder) is moved into `versions/` by its first update.

**Reason:** a rename of a shortcut is a single step on Linux, so a power cut leaves the old version or the new one, complete, never a mix, using nothing but the standard library (an atomic swap of two real folders needs a system call Python doesn't offer). The menu entry, the Steam shortcut and the app's own paths all go through `app`, so none of them change. Checking the first start without a window keeps it quick and possible from a terminal or from the app itself, and asking for every file the page links catches a version whose server starts but whose page would be broken; reading the person's own settings catches a version that can't read them, while the app's own fresh start keeps the data folder out of reach. Writing the step into `install.sh` rather than shipping a fourth file keeps the download at three files. The first update of an install made by the installer work has one moment, between two renames, where a power cut would leave no `app` folder; the next run of the installer then installs as new and tidies up. That only affects installs made before this change, none of them released (all decided on the installer's update step; reply there to change them).

**Nova risk:** the shortcut and the version folders live in the home folder, which supports symlinks on the Nova's file systems too; the first start runs the same `python3` as the installer, so a Python too old for the new version is caught there and rolled back.

## 2026-11-18 — Uninstalling, keeping the data unless asked (the uninstaller work)

**Decision:** `installer/uninstall.sh` (bash, no `sudo`, nothing new) ships inside the app's `installer/` folder, so an installed copy is uninstalled with `bash ~/.local/share/kettle-video/app/installer/uninstall.sh`; the release script needs no change beyond requiring the new name. Every place it removes comes from `installer/names.env` and the same standard folders the installer uses. It always removes the app files (`app` and `versions/`), the menu entry and the kiosk window's Firefox profile (the designer's decision on the uninstaller work: app files; its name, `FIREFOX_PROFILE`, joins `names.env` and a test keeps `launch.sh`'s `PROFILE_NAME` in step, with `launch.sh` itself unchanged). The data it keeps unless asked is the library folder, the settings folder and the logs (decided on the uninstaller work): removed only after a yes and a second confirming yes. Everything is checked before anything goes; anything unexpected (not installed, a folder or menu entry the installer didn't make, a place outside the home folder, a media folder inside something to be removed, the app open, an update running, root) stops it with nothing removed. It ends with the reminder to remove the Steam shortcut by hand.

**Reason:** the uninstaller shipping in the app means it always matches the installed version and the download stays three files. Settings and logs count as data because the designer's decision lists settings with the data and a reinstall should find everything as it was; the logs are what a bug report needs, so they are never thrown away without asking. Checking everything first, and removing `versions/` before the `app` shortcut, means a stop never leaves a half-removed install, and a second run finishes one that was cut short. mpv's own resume positions belong to mpv, which the uninstall never touches.

## 2026-11-18 — A development copy gets its own app menu entry (the installer review fixes)

**Decision:** a development copy's `install-shortcut.sh` writes its own entry, `kettle-video-dev.desktop` (`DEV_DESKTOP_ENTRY` in `installer/names.env`), named "Kettle Video (dev)"; the installed copy keeps `kettle-video.desktop`, named "Kettle Video". Running `install-shortcut.sh` again moves the entry older versions of it wrote, but only when that file holds exactly this copy's `Exec=` line; it never touches any other, and refuses to run in an installed copy. The installer writes its entry only when it is missing or already starts the installed copy; otherwise it leaves it as it is, says how to move it and still finishes. The uninstaller removes the entry only when it starts the installed copy, and otherwise leaves it and carries on (before, it stopped). Also: `tools/release.py` reads `names.env` with `backend/app_paths.py`'s `read_names` (one copy) and refuses a `names.env` missing any required name.

**Reason:** the two copies shared one entry, so installing silently took over the development copy's and uninstalling then deleted it, or (the other way round) the uninstaller refused to run. Separate names are the only way both can be listed and each opens its own copy, as the issue asks; "(dev)" keeps the two apart in the menu and in Steam's Add a Game list while staying short. Steam shortcuts point at `launch.sh`, not at the entry, so existing ones keep working. Leaving a foreign entry alone, rather than stopping, follows the rule that the installer never changes what it didn't make, without blocking the install or uninstall themselves.

## 2026-11-18 — Never online by itself; Check for updates in Settings (the never-online work)

**Decision:** Kettle Video never goes online by itself (the designer's rule, now a hard rule in `CLAUDE.md`). The earlier developer auto-update is removed: `launch.sh`'s update step, `backend/dev_update.py`, the corner box and its checks (the designer's yes to the exact `launch.sh` change). The kiosk window's Firefox profile switches off Firefox's own traffic with the settings the designer approved, plus a "dead end": every request not for the app's own server goes to a proxy on the device at port 9, where nothing listens (the designer's option 1). Two more proxy settings, `network.proxy.failover_direct` and `network.proxy.allow_bypass`, are off (decided): measured on the Deck's Firefox 153, without them Remote Settings and Google's media plugin check still went direct once the closed door refused them. The same profile skips Firefox's Terms of Use notice (`termsofuse.bypassNotification`) and the "restore your previous session" suggestion (`browser.startup.couldRestoreSession.count` -1), the designer's later decision; both are the settings Mozilla's own test runs use, read from Firefox 153's own files. Check for updates is a row in Settings › About: one request to GitHub's latest release for a release install, `git ls-remote` of the remote's main for a git checkout without the installer's mark; plain words for every result and error; no Update and restart row until the Update and restart work (the designer's decision). "Last checked" is kept in the data folder and changes only after a check that got an answer (decided: a failed check didn't check anything). Results and What's new are lines and rows in Enamel's own row (decided), and the release notes use the licence's reading view.

**Reason:** the designer's rule, and the legal note on the issue: a check shows GitHub the device's IP address and the app's version, nothing else, so the privacy statement (the bug report form work) can say so plainly. A proxy dead end is the only way that keeps the rule true whatever a later Firefox adds, and the test (`tests/kiosk_profile_check.py`) reads the window's real connections, so it catches anything that goes round it. `git ls-remote` reads the remote's main without changing the copy, leaving the pull to the Update and restart work.

**Nova risk:** the Nova's Firefox may be another version, where a setting is named differently or missing: the dead end still holds for anything that respects the proxy, but a Firefox that adds a new way round it, or renames the Terms of Use or restore settings, could show a prompt again. The Nova loses its automatic update at launch: it now updates only when asked (the Update and restart work).

## 2026-11-18 — Update and restart in place, and Pull the latest version (the Update and restart work)

**Decision:** Update and restart (installed copies) and Pull the latest version (development copies) live in Settings › About, after Check for updates, each behind Enamel's picker confirm with Cancel first. `backend/app_update.py` downloads the release's archive and checksum from this app's GitHub release addresses only (taken from the check's own answer and kept by the server), into a `.download-…` folder beside the app folder, and hands them to the installer's shared step, `installer/update.py` (the installer's update step), loaded from the copy's own folder: one code path for the checksum, the start check and the rollback, none of it repeated in the app. **Restart in place** without changing `launch.sh` (decided): the server stops as for Quit, then the same process re-executes itself as the new version's server from the new folder (`os.execve`), so `launch.sh` and Steam keep seeing the same running process and the page reloads once a server with a new id answers; a message (`KETTLE_UPDATE_NOTE`) tells the new server what to say once ("Updated to 1.1.0", or after a rollback that the previous version was put back). It is offered only where it can work: an installed copy where the installer put it, and a release with both files (decided). While it runs only B works, as Cancel until installing starts, and no film can start; no update starts during a film (decided). The pull works only on `main`, with no changes to tracked files, as a fast-forward, and says why otherwise (decided).

**Reason:** the issue asks for one shared update path and a restart Steam doesn't notice; replacing the process in place keeps its id, which is all `launch.sh` watches, and the old server has already closed its port and files before the swap, so nothing it held is replaced under it. A test (`tests/test_restart_in_place.py`) runs the real `launch.sh` on an installed copy in a temporary home and checks the launcher and the server stay the same processes. A change a new version makes to `launch.sh` itself takes effect only at the next launch: bash keeps reading the file it opened.

**Nova risk:** the restart is the same process starting Python again, which should behave the same on ARM and Armada, but the Nova's Firefox (a different version or the Flatpak) reloading the page while its server is away for a second or two is untested there. If the window ever stays on the old page or closes, the log's `update:` and `restarting in place` lines show how far it got.

## 2026-11-18 — No telemetry; the network only when the user asks; a Privacy section and a bug report form (the bug report form work)

**Decision:** Kettle Video has no telemetry and uses the network only when the user triggers it. The README's Privacy section is the public promise, written from the audit posted on the bug report form work: the only connections are Check for updates and Update and restart in Settings › About (GitHub sees the device's IP address and the app's version), their development-copy forms (the copy's own git remote, reached with git's own settings, including any sign-in set up for it, so that remote can see which account is asking), and the installer's Flathub step for mpv, only after a yes. The kiosk window's Firefox profile keeps Firefox's own online features off (the never-online work). Any future feature that needs the network must be user-triggered and must change that statement first; this is the hard rule in `CLAUDE.md` (added by the never-online work with the designer's yes, not repeated). The Privacy section also names the development-copy actions and the installer's mpv step (decided): the code does both, and a promise that left them out would not be true of it. `tests/test_privacy_statement.py` fails if code that runs with the app gains a way online other than those actions, or if the statement loses one of its points. A GitHub bug report form (`.github/ISSUE_TEMPLATE/bug_report.yml`) asks for the device, the system and its version, Desktop or Gaming Mode, the app version, what happened, what was expected, the steps and whether it happens every time, and asks people to leave out personal file and folder names. Blank issues stay allowed (`config.yml`), so /draft, which makes issues with a title and body directly, is never sent through the form.

**Reason:** the statement is a promise to users, so it is audited against the code first and kept true by a test. The device list in the form names the test devices only as choices for reporting.


## 2026-11-18 — A release check for anything that mustn't go public (the release check work)

**Decision:** `tools/release_check.py` reads every tracked file and fails on anything that mustn't go public, naming each finding by file, line and kind, never by the text found, so its report can be posted anywhere. It builds on the privacy guard (the privacy guard work) and reuses its list and rules rather than copying them, and reuses the rename checks in `tests/` (the Kettle Video rename and the two before it) for old names. On top of those: the private words written in ROT13, backwards or encoded; film and show titles not on `tests/fixtures/invented_titles.txt`; what Enamel's own clean-up rules out from Steam's client (read from Enamel's `tools/release_check.py` with `scripts/peek.sh`; Kettle's patterns are its own, built from parts so the check passes on itself); secrets and files that hold them; tracked local Claude Code files; email addresses; links into this private repo's commits and issues; and commit addresses. The public-text check from the public-voice issue in this series joins it when built. `history` mode is the deep look at the whole history.

- **Titles by an invented list, never a real one** (from the issue). A title is allowed because it is known to be invented. Titles are read from video file names everywhere (not third-party files) and from `"title"` fields in tests, docs and spikes, also inside the scrambled and encoded forms. A plain `.ts` is not read as a video, since in code it is far more often something else. A title written only as plain words, not as a file name or a title field, can't be found without a list of real titles; the privacy guard's list still catches the designer's own films and shows in any form.
- **The sample library's Blender films are on the list** (decided): they are the one set of real films the repo may name (CLAUDE.md, "Sample library"), open-licensed and credited.
- **Emails** (decided): allowed are Enamelware's GitHub noreply address, the commits' attribution address (`noreply@anthropic.com`, not a person's), `git@github.com` (a server, not a mailbox) and the reserved example domains used by invented test data. Any other address fails, other GitHub noreply addresses included, since one names a personal account. Third-party files keep their authors' addresses, as in the privacy guard.
- **The release script checks what it publishes** (decided): `tools/release.py` runs the release check, in place of the privacy guard alone, on every file of the archive, the notes and `install.sh`; the repo as a whole gets the check as its own release step (`docs/dev-environment.md`, "Release check"). Checking the whole tag inside the script would refuse every release until the repo is clean, including the private test builds made today.

**Reason:** the series makes a public copy of this private repo, and everything that went wrong in Enamel's clean-up must be caught by a script, not by reading. Findings never repeat their text, so neither the check's output nor a report built from it can leak what it found.

## 2026-11-19 — Commits as Enamelware with the noreply address (the commit identity work)

**Decision:** every commit is authored and committed as **Enamelware** with `335260252+enamelware@users.noreply.github.com`, set in each clone's own git settings (`git config --local`), never the device-wide ones. The Steam Deck's clone is set; the commands for the Nova, or any new clone, are in `docs/dev-environment.md` ("Commit identity") and on the commit identity work. Claude Code's helper agents commit in the same clone and pick it up; a test commit made by one showed the new name and address. The release check (the release check work) allows this address and no other account's. Past commits keep their author: they stay in the private archive, and the public copy starts without history. `tests/test_commit_identity.py` checks the documented commands set exactly that name and address, for the repo only, and that commits made after them show it.

**Reason:** no personal name or email may reach a public commit. A clone's own settings are not part of the repo's tracked files, so a git revert doesn't undo them: setting the earlier values back with the same commands does (decided).

## 2026-11-19 — Public voice: no old issue numbers, a public-text check, and tools that say what they need (the public voice work)

**Decision:** every file now names earlier work in words ("the onboarding work", "the keep-awake work") instead of this private repo's issue numbers, since the public repo starts its numbering again; old dated entries here keep their date and meaning and lose only their numbers and links. Commit addresses and links into the private history are gone too. A public-text check (`tools/public_text.py`) joins the release check and fails on an old issue number, the person running the project named by role rather than as "the designer", a claude.ai link and a link to the private board; `tests/test_public_text.py` runs it on the whole repo, so none can come back. CLAUDE.md gains a "Public writing" section, the same rule as Enamel's adapted to Kettle Video, and `docs/how-this-repo-is-built.md` explains the workflow to visitors, linked from the README. Real film titles and near-copies of well-known ones in tests and docs are replaced with invented ones that keep each test's pattern (a number in a title, a year-like number, an article to drop), and the near-copies are off the invented list.

- **No issue numbers at all in files until the clean copy** (decided): the check can't tell an old number from a new one, so files name work in words; the workflow's placeholders (`#N`, `#M`) are letters, and commit messages still say `Refs #N`.
- **The instructions to Claude Code keep their wording** (decided): CLAUDE.md and `.claude/` lost only their issue numbers (CLAUDE.md's examples now say `Refs #N` and "#N #M failed"), so /next, /draft and /tidy work exactly as before; the role-word rule applies to every other file, where "the designer" replaces it. Rewording the workflow files in the project voice is left to an issue about the workflow.
- **"You" for the app's users** (decided): the rule's project voice has one exception besides the instructions to Claude Code: text addressed to the app's users (the README's install, update, privacy and usage steps, release notes in `CHANGELOG.md`, the app's own words on screen) may say "you", as it already does.
- **Issues stay with /draft's headings** (decided): the rule asks for public tickets in the project voice, without changing the headings /next reads.
- **Home folder paths written with a tilde are not a finding** (decided): Kettle Video's docs name the standard places every install uses (`~/.local/share/kettle-video`), which are not personal; full home paths with a name are already the privacy guard's.
- **Works on a stranger's machine:** the privacy guard says how to make a word list when there is none, `scripts/peek.sh` and `tools/update_enamel.py` print the command to clone Enamel when its folder is missing, and `scripts/test.sh` says before a browser check when it finds no Firefox. `docs/dev-environment.md` ("On another machine") lists what each tool needs.

**Reason:** the series makes a public copy of this repo; old numbers would point at the wrong public issues, and the rule has to be checked by a script, not by reading.

## 2026-11-24 — The clean public copy, and nothing public until a yes (the clean copy work)

**Decision:** `tools/public_copy.py` builds the public copy: the files git tracks at one commit, with no history, in a new folder outside this repo, as one commit by Enamelware with the noreply address and no remote; then it runs the release check on the copy, with commit addresses looked up in this repo, and stops. Making the public repo, pushing to it and copying issues there are separate steps, taken only after the designer's yes on the plan; this repo is never made public, not even for a moment, since its history holds everything this series removed.

- **A new folder only** (from the issue): the script refuses any folder that already exists, even an empty one, so it can never write over or into anything. It is the one place this series writes outside the repo; the real copy goes in a new folder next to the repo.
- **Enamel's public clean-up counts as brought in** (decided): Enamel 0.13.1, already pinned, is that clean-up's release; Enamel's one later change is wording-only, with no new version, and changes none of the files copied into `vendor/enamel/`.
- **The copy's first commit message names no issue** and carries no co-author line: it is the project's starting point, not a piece of work.

**Reason:** a repo made public can be cached or copied at once, so the copy is built and checked locally first, from tracked files only, and the step that can't be undone waits for an explicit yes.

## 2026-11-24 — The app points at the public repo; the licence headers keep their name (the public repo work)

**Decision:** the update check, and with it Update and restart's download address, use `enamelware/kettle-video`, and the setup steps clone it over HTTPS with no key. Every source file's licence header keeps its copyright line as it is (the designer's decision on the clean copy work). `tests/test_public_repo.py` fails if a file names the private archive outside the release check's rules, the rename checks' test data and decisions dated before this one.

- **The board settings and CLAUDE.md's repository line move last** (decided): they are what the board script and the workflow act on, and the go-public work is itself tracked in the archive, so they change as that work's last step, right before the final copy.

**Reason:** the public copy has to work from its first day, with updates coming from the public repo, and nothing in it should point at a repo visitors can't open.

## 2026-11-25 — Kettle Video goes public (the go-public work)

**Decision:** `enamelware/kettle-video` is the project's repo. It starts from one commit by Enamelware: a copy of the files at the end of the private development, with no history, checked clean by the release check (files and history) before it was pushed, and pushed from the copy's own folder only. The board settings and CLAUDE.md's repository line name it, so /next, /draft and /tidy act on its issues; the board itself stays private. The earlier development stays in a private, archived repo that is never made public, since its history holds everything the clean-up removed.

- **Issues start fresh** (the designer's yes on the plan): open proposals are written again as public tickets in the project voice, earlier work named in words. Closed work is described in CHANGELOG.md and this log, never copied.
- **Labels** are recreated with descriptions in the project voice ("the designer", Enamel's name).
- **Each device moves to a fresh clone** of the public repo; a clone of the archive is never pushed to the public repo.

**Reason:** a public repo can be cached or copied the moment it holds anything, so only a copy that has already passed every check goes up, and nothing of the private history can follow it.
