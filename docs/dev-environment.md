# Dev environment

## Iterating on the UI/backend without the kiosk wrapper

```
cp settings.example.json settings.json   # fill in real (or test) folder paths; left empty, the app asks at launch
python3 -m backend.server
```

Then open `http://127.0.0.1:8756/` in any regular browser tab — no need to run the kiosk flow while developing.

## Running the real kiosk flow

```
./launch.sh
```

Starts the backend, opens Firefox in kiosk mode with a dedicated profile, and shuts everything down when you choose **Quit** in the menu (`q` or B opens it with Quit chosen; press Enter or A).

Only one copy runs at a time: a second launch while the app is open or starting logs a line and stops (the lock is `launch.lock` in the logs folder). On quit, Firefox gets up to 15 s to close on its own before it is forced (the start-up fix).

## Logs

Each run writes, under `logs/` (in an installed copy, `~/.local/state/kettle-video/logs`: `launch.sh` asks `python3 -m backend.app_paths logs`, and falls back to `logs/` if that fails, the installer work), `launch-<timestamp>.log` (the launcher), `firefox-<timestamp>.log` (Firefox's own output) and one `mpv-<timestamp>.log` per file played.

Useful lines: `page loaded N s after launch` (start-up time), `firefox closed cleanly in about N s` or `forcing it shut`, and `firefox closed without ever opening the app` (a Firefox that dies at start, often a damaged profile).

## Things to confirm on real devices

- Python version: 3.10+ is needed, because the bundled guessit (in `vendor/`) requires it. Confirmed: Steam Deck 3.13, Nova 3.14.
- Whether Firefox is a system install or the Flatpak on each device (`launch.sh` detects this automatically and logs which it found).
- Whether mpv is a system install or the Flatpak on each device (also auto-detected and logged).

## A development copy

What a development copy (this git folder) needs beyond the [README](../README.md), which describes an installed copy.

### Setting it up

Setting up a new device, step by step (tools, getting the code, adding to Steam, controller layout, troubleshooting): see [`device-setup.md`](device-setup.md). The short version:

Run the app: on first launch it asks for your Movies and TV Shows folders and saves them in `settings.json`, creating the file if there is none. To change them later, open the menu (the **Menu** button at the top, or Start) and choose **Settings** (see [Settings](user-guide.md#settings)). To set things by hand instead:

```
cp settings.example.json settings.json
```

Edit `settings.json` and fill in your real `movies_path` and `tv_path` (with both left empty, the app asks at launch). Leave `mpv_command` as `"auto"` unless you need to point at a specific mpv binary. `mpv_args` is an optional list of extra flags passed straight to mpv, e.g. `["--hwdec=auto"]`, for testing decode settings without editing code — leave it as `[]` normally. `resume` (`true` by default) controls whether films continue where you stopped them; see [Resume](user-guide.md#resume). `keep_awake` (`true` by default) keeps the device awake while a film is open; see [Watching movies](user-guide.md#watching-movies).

### Running it

```
./launch.sh
```

This starts the backend, opens Firefox in kiosk mode pointed at it, and closes everything down again when you choose **Quit** in the menu (`q` or B opens it with Quit chosen; press Enter or A) (or when either the backend or Firefox is closed by any other means — whichever goes first takes the other down with it).

For day-to-day development without the kiosk wrapper, see [Iterating on the UI/backend without the kiosk wrapper](#iterating-on-the-uibackend-without-the-kiosk-wrapper) above.

### Adding a development copy to Steam

On the Steam Deck, Steam's own "Browse" button (**My Library → Add a Non-Steam Game → Browse**) works fine — just point it at `launch.sh`.

On the Nova, that same "Browse" button doesn't work, so instead:

```
./install-shortcut.sh
```

This writes a `kettle-video-dev.desktop` entry to `~/.local/share/applications/`, named **Kettle Video (dev)**. Restart Steam (or just reopen the dialog), go to **My Library → Add a Non-Steam Game**, and "Kettle Video (dev)" will already be listed — no Browse needed.

**A development copy and an installed copy on one device** each have their own app menu entry: **Kettle Video (dev)** (`kettle-video-dev.desktop`) opens the development copy and **Kettle Video** (`kettle-video.desktop`) the installed one. Neither script changes or removes the other's entry, and Steam shortcuts you already made keep working. Earlier versions of `install-shortcut.sh` wrote `kettle-video.desktop` themselves; running it again moves that entry to its own name (only if it opens this copy). Until then, the installer leaves that entry as it is, says so and doesn't add its own (run `install-shortcut.sh` again, then the installer); the uninstaller leaves it as it is too. `install-shortcut.sh` refuses to run in an installed copy, which already has its entry. The two copies never share data either: a development copy's kiosk window has its own Firefox profile, `kettle-video-dev-profile`, and keeps its resume positions in mpv's own folder, while the installed copy has `kettle-video-profile` and a resume folder of its own (`docs/spec.md`, "Each copy keeps its own data").

### Updating by running the installer again

Running the installer again always works, also when Update and restart isn't offered: double-click the release's `install-kettle-video.desktop`, or put the newer release's `install.sh`, archive and `.sha256` file in one folder and run `bash install.sh` there. All the ways use the same steps:

- It finds the installed copy, prints the version you have and the one in the archive, and replaces only the app files. Your library, settings, resume positions, Continue watching and logs are never touched.
- The archive is checked against its checksum before anything changes.
- An older archive than the version you have gets a warning and a question first; anything but yes changes nothing.
- The version you have is kept until the new one has **started cleanly**: its server starts, its page and every file the page needs load, and it answers. If that or any install step fails, the previous version is put back and the installer says so. Nothing to do on your side: Kettle Video opens as before.
- If the device loses power during an update, Kettle Video is either the old version or the new one, never a mix; the next run of the installer tidies up what was left.

### Third-party code

The filename parser uses [guessit](https://github.com/guessit-io/guessit) and its dependencies. They are bundled, unmodified, in `vendor/`, so nothing needs to be installed with pip. `THIRD_PARTY_LICENSES.md` lists each one with its version, license and source, and mpv, which is used but not bundled. The Settings screen's About section shows the same list.

The Kettle wordmark on the loading screen uses the Rubik Mono One font (SIL Open Font License 1.1). It is bundled, unmodified, in `ui/fonts/` with its license file and is never loaded online; it's listed in `THIRD_PARTY_LICENSES.md` too.

The design system (Enamel, MIT) is vendored in `vendor/enamel/`; see [Design system](#design-system).

### Design system

The app's styling comes from the design system for the Kettle apps, **Enamel** (MIT licence, the designer's own project, [github.com/enamelware/enamel](https://github.com/enamelware/enamel)). Its two stylesheets, its behaviour script, its `DESIGN.md`, `VERSION`, `LICENSE`, `NOTICE.md` and `MIGRATION.md` are copied, unchanged, into `vendor/enamel/`, and the page loads both stylesheets before the app's own. Nothing is loaded online.

The Enamel release the app has adopted is pinned in one place, `ENAMEL_PIN` at the repo's root (its release tag, such as `v0.7.0`). The copy in `vendor/enamel/` must match that tag exactly, and the design system check compares with that tag only, never with Enamel's main branch or its latest release, so a new Enamel release can't fail an unrelated issue. Upgrades are their own issue: when Enamel publishes a newer release, `/next all` drafts one "Bring in Enamel <version>" issue.

To take a newer Enamel (in that issue only), check its `CHANGELOG.md` for the version Kettle Video should adopt, then run `python3 tools/update_enamel.py 0.7.0` (with that version) on a device that has Enamel at `~/Development/enamel` (or still under its old folder name; or give another folder as a second argument). It reads the files from that version's release tag (`v0.7.0`), never from Enamel's folder as it happens to be, so work in progress there can't come in by mistake. It copies only the files that changed, prints the old and new version, moves the pin in `ENAMEL_PIN` to the new tag, and never changes Enamel itself. The tests compare the app's copy with the pinned tag, and are skipped with a plain reason where Enamel or that tag isn't on the device. Never edit the copies in `vendor/enamel/` by hand; then update the version in `THIRD_PARTY_LICENSES.md` and run the tests.

## Tests

From the repo root:

```
scripts/test.sh [NAME...]       # quick: unit suite without timings, plus the named checks
scripts/test.sh full            # everything: the whole unit suite, then every check
scripts/test.sh unit MODULE...  # only these unit test modules
scripts/test.sh check NAME      # one slower check, tests/NAME.py
scripts/test.sh checks          # every tests/*_check.py
```

**Quick** is what every issue runs (aim: under 2 minutes). It runs the unit suite without the four timing tests (marked `@full_only`, from `tests/full_only.py`), and alongside it the browser checks for the screens the change touches: the ones named, such as `scripts/test.sh home_shell_check`, plus any `tests/*_check.py` the change itself adds or edits compared with `main`. **Full** (`scripts/test.sh full`, or `all`) runs everything, timings included, before any version bump or release and once at the end of `/next all` if anything was merged.

A pass is remembered against the exact code (every file git would commit, uncommitted ones included), in git's own folder (`.git/kettle-test-results/`), so running the same thing again on the same code says it already passed instead of running it twice. A full pass counts for everything; `--again` runs it anyway.

### On another machine

The repo works on any Linux machine with Python 3.10 or later; the Steam Deck and the Nova are only the reference devices. A few development tools need something from the machine they run on, and each says so when it is missing:

- **The privacy guard** (`tools/privacy_guard.py`), and so `scripts/test.sh` (quick and full start with it), the commit hooks and the release check, need a private word list at `~/Development/.privacy-guard/words.txt`. Without one they stop and say so; `python3 tools/privacy_guard.py build` makes one from that machine (its user name, card labels and the titles on its cards), and words can be added by hand in its last section.
- **Reading Enamel** with `scripts/peek.sh`, `tools/update_enamel.py` and the tests that compare `vendor/enamel/` with the pinned tag needs a clone of Enamel (`https://github.com/enamelware/enamel.git`) in a folder called `enamel` next to this repo (for `update_enamel.py`, `~/Development/enamel` unless another folder is given). Without it, `peek.sh` and `update_enamel.py` print the clone command, and those tests are skipped with a plain reason. The app itself never needs it: `vendor/enamel/` holds everything it uses.
- **The browser checks** (`tests/*_check.py`) need Firefox, either a system one on `PATH` or the Flatpak `org.mozilla.firefox`; `scripts/test.sh` says so before a check when it finds neither. Checks that play films need mpv (and `ffmpeg` for the frame pictures), and say "skipped" when it is missing.
- **Checks on the real library** (`absolute_numbers_check`, `storage_privacy_check`, and the "real" cases of the Home, Movies list, loading screen and parsed view checks) read the Movies and TV Shows folders named in that machine's `settings.json`, read-only. Where a folder isn't there, the check fails or is skipped, so set two real folders there first (invented files will do).
- **The board script** (`scripts/board.sh`) and the workflow's commands need the GitHub command line (`gh`), signed in with access to the planning board in `.claude/board.json`. On SteamOS a system update removes anything installed outside the home folder, so install `gh` inside it; if `gh` goes missing, suspect an update. Board access needs the `project` scope (`gh auth refresh -h github.com -s project`): it prints a one-time code for the designer to enter in a browser, so run it in the background and pass the code on from its output.

### Privacy guard

`tools/privacy_guard.py` (the privacy guard work) keeps anything from the designer's devices, library or accounts out of the repo. It checks text against a private word list kept outside both Kettle repos, `~/Development/.privacy-guard/words.txt` (card labels, the user name, film and show names, device, network and Bluetooth names, Steam IDs; never committed, printed or pasted), and also catches, with no list: home folders written out in full (write `~/` or `<user>`), Steam user folders and IDs, email addresses other than GitHub's noreply ones and the commits' attribution address (`noreply@anthropic.com`), and new pictures or logs outside the approved folders (pictures: `docs/screenshots/`, `ui/` and `vendor/`; no check looks inside a picture, so each screenshot is looked at before it is committed, see `docs/screenshots/README.md`). A finding names the file, the line and the kind of thing, never the word. If the list is missing or empty, the guard fails.

- The quick and full checks start with it on every tracked file (`scripts/test.sh privacy` runs it alone).
- `python3 tools/install_privacy_hooks.py` puts it in front of every commit (the files and the message) and every push, in this clone. Run it once per clone; never bypass the hooks with `--no-verify`.
- `python3 tools/privacy_guard.py build` (re)writes the list on this device, by reading only; `count` says how many entries each category holds. Film and show names come from the cards only, never from the home folder, so the sample library (`~/Videos/kettle-sample-library`, see `docs/sample-library.md`) stays out of the list (the sample library guard fix).
- Tests use a temporary list of invented words only (`tests/test_privacy_guard.py`).

### Release archive

`python3 tools/release.py v<VERSION>` (the release script work) builds a release from its tag into `dist/` (git ignores it), five files: the archive the installer installs, its `.sha256` checksum, release notes taken from the version's entry in `CHANGELOG.md`, `install.sh`, the tag's `installer/install.sh` with `installer/names.env`'s lines and `installer/update.py` written in, so it works on its own next to the archive (the installer work, the installer's update step), and `install-kettle-video.desktop`, the one-file installer: the tag's `installer/one_file_install.py` with the names written in, as a desktop launcher (the one-file install work, `docs/spec.md`, "Installing with one file"). Then it shows a summary and asks; only `yes` uploads the four files other than the notes as a GitHub pre-release (never the latest), with the notes as its text, through a GitHub CLI that is installed and already signed in, or else it prints the website steps (the release flow work; the whole checklist is `docs/RELEASING.md`). It reads only the tag's tracked files, takes only the app and its licence files, and runs the release check (below, which includes the privacy guard) over everything it writes; a tag that doesn't match its `VERSION`, or a missing CHANGELOG entry, stops it with a plain message. Every installer name lives in `installer/names.env`, and a release whose `names.env` is missing one stops (the installer review fixes). Reasons: `docs/decisions.md`.

### Commit identity

Every commit is authored as Enamelware with GitHub's noreply address for the account (the commit identity work), so no personal name or email reaches a public commit. It is set in this repo's own git settings, never the device-wide ones, once per clone (the Steam Deck's is set; on the Nova, or any new clone, run these from the repo's folder):

```
git config --local user.name "Enamelware"
git config --local user.email "335260252+enamelware@users.noreply.github.com"
```

`git config --local --get user.email` shows the result. Claude Code's helper agents commit in the same clone, so they pick it up too. The release check (below) allows no other address. Commits made before the commit identity work keep their old author; they stay in the private archive (the public copy starts without history).

### Release check

`python3 tools/release_check.py` (the release check work) fails if the repo holds anything that mustn't go public, and lists each finding with its file, line and kind, never the text it found. It covers everything the privacy guard covers (same list, same rules), those private words also written in ROT13, backwards or encoded (base64, hex, % escapes, HTML entities, `\u` escapes), film and show titles not on the list of invented ones (`tests/fixtures/invented_titles.txt`), anything from Steam's client that Enamel's own clean-up rules out, the old names (through the rename checks in `tests/`), secrets and files that hold them, a tracked `.claude/settings.local.json` or `CLAUDE.local.md`, email addresses other than Enamelware's GitHub noreply address, and links to this private repo's commits or issues or a commit's address. Titles are read from video file names, and from `"title"` fields in tests, docs and spikes; a new invented title goes on the list. `--repo FOLDER` checks another folder (such as a clean copy), `--history REPO` looks commit addresses up in another repo's history, and `history` is the deep look at every version of every file and every commit message (a few minutes). Tests: `tests/test_release_rules.py`.

**Release steps:** (in full, with the device tests and marking the latest: `docs/RELEASING.md`)

1. `scripts/test.sh full` passes.
2. `python3 tools/release_check.py` finds nothing in the repo.
3. Bump `VERSION`, add its `CHANGELOG.md` entry, tag `v<VERSION>` and push the tag.
4. `python3 tools/release.py v<VERSION>`, which runs the release check again on everything it writes, then asks before uploading it as a pre-release.

### Clean public copy

`python3 tools/public_copy.py FOLDER` (the clean copy work) builds a copy of the files git tracks at one commit (`--ref`, default `HEAD`), with no history, in a new folder, then runs the release check on it and stops. It reads the files with git, never from the working folder, so nothing untracked or uncommitted gets in. It refuses a folder that already exists, even an empty one, and leaves it untouched. The copy is a new git repo with one commit by Enamelware with the noreply address (also set in the copy's own git settings), and no remote: nothing is pushed or published. Commit addresses are looked up in the repo it was copied from. Exit status: 0 clean, 1 findings (the copy must not go public), 2 nothing built or the check couldn't run. It needs the private word list, like the release check. Tests: `tests/test_public_copy.py`.

Board and progress-comment changes go through `scripts/board.sh` (run it without arguments for its usage), and finished `issue-N` branches are deleted with `scripts/branch-done.sh N`. These wrappers exist so each repeated operation is covered by one narrow permission rule; see `docs/decisions.md`, "Fewer approval prompts".

**Permission rules** (`.claude/settings.json`). A new ask or deny rule must never catch a read-only command: check it against git log, show, status and diff; gh issue view and list; ls, cat and grep; `scripts/board.sh list`; and `scripts/peek.sh`, and narrow any existing ask rule that catches one (`tests/test_agent_guard.py` checks this). `git rm` runs without asking for files git tracks inside this repo, since a deletion is reversible like any edit; plain `rm`, `git rm` with a path outside the repo or with `-f`/`--force`, `git clean`, and anything that deletes untracked files still ask (see `docs/decisions.md`). The handbook plugin (`enamelware@enamelware`, from `enamelware/handbook`) is enabled in the same file, at project scope; it adds no permission rule. No rule may contain a colon followed by a star (`:*`): Claude Code warns about any such rule at every start, so a push that names its target with a colon (such as `issue-5:main` or `:issue-5`) is asked about by the session check in `.claude/hooks/agent_guard.py` (`session` mode, wired in the same file to every Bash command) instead of by a rule. Only plugins that are installed are switched on there.

`tests/test_vendor.py` checks that guessit is loaded from `vendor/` (not a system install) and can parse a TV and a movie filename. The filename parser has its own tests in the unit suite.

`tests/launch_cycles.py [cycles]` opens and quits the whole app several times in a row (default 10) on a temporary copy, with a headless Firefox and a throwaway profile and home folder, and checks that the page loads every time, Firefox closes cleanly and a second launch is blocked. It needs Firefox and is not part of the unit tests.

`tests/loading_screen_check.py [screenshot-dir]` checks the loading screen (the loading screen work) in a headless Firefox driven through Marionette, Firefox's built-in remote control, with a throwaway profile and home folder. It covers a slow library (the bundled font, "Still working…" after 10 s), q quitting during the screen, a failing library (the error banner) and the real folders from `settings.json` (read-only). It saves screenshots across the range of window widths in `tests/window_sizes.py`. It needs Firefox, takes about half a minute and is not part of the unit tests.

`tests/play_failure_check.py` checks that the page never stays stuck on "Playing…" (the stuck Playing fix), in the same headless Firefox set-up. A fake backend fails in several ways while a film starts or plays (a broken answer, a dropped connection, a frozen backend, no answer to the play request, mpv refused or failing to start); each time "Playing…" must go away, a plain error must show and the arrows must work again. It also checks that one missed answer during a film doesn't end the wait. It needs Firefox, takes about a minute and is not part of the unit tests.

`tests/held_key_check.py` checks that holding A or B counts as one press (the held button fix), in the same headless Firefox set-up. It holds a key by sending it several times before letting go, checks the page sees those as repeats, then checks that a held A on a show opens it without playing an episode, a held B in the episode list goes back without quitting, and a held Down still moves several rows. It needs Firefox, takes about half a minute and is not part of the unit tests.

### Other slower checks

Each is run with `scripts/test.sh check NAME` (the file name without `.py`), needs Firefox unless it says otherwise, and is not part of the unit tests. Most take half a minute to a minute. The opening comment at the top of each file (after the licence header) says exactly what it covers. Extra options, such as a screenshot folder (the browser checks save screenshots there, one per window width in `tests/window_sizes.py`: from Enamel's smallest supported box, 320 by 240, to 2560 wide, labelled by width only, the responsive layout work) or `--mpv`, only work when the file is run directly, for example `python3 tests/NAME.py [screenshot-dir]`; `scripts/test.sh check NAME` takes the name alone.

- `saved_library_check` (the saved library work): first launch, its scan and result (since the first scan screen), the Rescan row, relaunch with the saved library, a folder taken away, a failed scan.
- `parsed_view_check` (the parsed library view): the parsed library view with invented titles, the plain-list fallback, and the real folders (read-only).
- `click_focus_check` (the click-then-Enter fix): clicking or tapping a row, then Enter, plays or opens the right row.
- `missing_items_check` (the quick rescan and Remove work): missing films, parts and episodes, the Remove question, and no rescans while a film plays.
- `movies_list_check` (the Movies list work): the Movies list with 2,000 invented films, jump by letter, long titles, draw times.
- `letter_strip_check` (the letter strip fix): every letter on the strip drawn and uncovered at first load, after a tab switch, a rescan and a film, with Continue watching shown or hidden; every letter readable and reachable across window sizes.
- `continue_watching_check` (the Continue watching work): the Continue watching row, from a stopped film to resuming and removing tiles. Also needs ffmpeg.
- `continue_row_layout_check` (the tile alignment work): the Continue watching tiles share one bottom edge, with one tile and with six. Also needs ffmpeg.
- `home_shell_check` (the Home shell work): the Menu button at the top (Enamel's action bar from the Home actions work; since the Home polish no bar, it scrolls with the page), tabs with counts, pinned tab strip and hint bar.
- `tv_beta_check` (the TV beta label): the TV Shows tab reads "TV SHOWS (BETA)", "(BETA)" stays on the line of "SHOWS", the tab keeps its size whether selected, focused, both or neither, and both tabs fit, at every window width.
- `fresh_start_check` (the fresh start mode): in fresh start, the FRESH START marker on every screen (loading, first launch, Home, the menu, a show's episodes, Playing…, mpv not found) at every window width, on top and covering nothing; no marker without fresh start. Since the fresh start onboarding work also fresh start's way in, started as the launcher starts it: "No videos found yet" and both onboarding screens with the marker, choosing folders reaching the result screen, the pretend app folder's settings and data unchanged, and the next fresh start asking again.
- `home_actions_check` (the Home actions work): the Menu button with no bar behind it, scrolling away while the tabs stay pinned (the Home polish), Quit red only while focused (the Home polish), Up to it and Down back, the menu by Menu, Start and B, Rescan's progress and result in the toast, Remove and Quit from the menu.
- `settings_check` (the Settings screen work): Settings from the menu at every width, both sections readable and clear of the hint bar, a folder change with its rescan, refused choices and Stop using, a licence scrolled to its end, B back to Home.
- `updates_check` (the never-online work): Settings › About's Check for updates at every window width with a stand-in GitHub: Last checked, Checking… while the controller still moves, the results and errors in the row, What's new with its notes scrolled to the end and B back. Firefox uses the kiosk profile's settings, so nothing goes online.
- `app_update_check` (the Update and restart work): Update and restart in Settings › About at every window width with stand-ins for GitHub, the download, the install and the restart: the row with its size, Enamel's confirm with Cancel first, the download toast with B Cancel, Installing…, the page reloading by itself with "Updated to 1.1.0", and a development copy's Pull the latest version and its refusal. Nothing goes online and nothing is installed.
- `size_readout_check` (the sizing spike): with the size readout on, one launch log line at start with the window's size, the device pixel ratio, the screen's size and the zoom note, matching what the page measures (also with Firefox scaled); off, no line; the library opens as normal either way.
- `enamel_sizes_check` (the Enamel 0.8.0 upgrade): Home at every window width draws Enamel's sizes (rows at least 64px with 24px text, the Menu button and its row, tabs, the hint bar, the shelf gap), the app leaves Enamel's root size at 100%, and turning it up grows the app's own sizes with Enamel's. Since Enamel 0.11.0 (the Enamel 0.11.0 upgrade) the root size works through zoom, so the root font size stays the viewer's own and the text is checked as drawn.
- `onboarding_check` (the folder choice screens): onboarding's two screens at every window width, with invented folders and temporary settings files: the step label, group bands and Movies badge, the focus on the first folder, Down scrolling the list, A, B and Y, the message inside a focused row, a tap choosing a row, a good choice saved and the result screen following, skipping both refused, and "Looking for your videos" for a slow search. Since the No videos found screen and the Browse somewhere else work also "No videos found yet" and "Browse somewhere else", with a stand-in dialog program and never a real dialog. Since the first onboarding review fixes also Y from a screen with no list, the line above the list, refused rows (a folder that can't be read, or that holds Kettle's own files) and the plain list's words. Since the second onboarding review fixes also a second press just after Open my library, with Home held back (past 10 seconds too), and the keys after a failed save.
- `first_scan_check` (the first scan screen): onboarding's screen 3 at every window width, with invented folders: the scan with A, B and Y doing nothing, the result, the panels side by side only when both fit, the notes, B, Change folders and Open my library. Once each: a skipped kind, nothing found, folders already set, a failed scan, a card out, taps, a second press, a long scan, and Home finding an empty library.
- `mpv_look_again_check` (the mpv missing screen): the first launch's "mpv not found" screen with Look again, for all three of its messages at every window width, with stand-ins for mpv and flatpak appearing on a temporary PATH: the focus, every word reachable, staying on the same answer, the message following a new answer, and screen 1 once mpv is found. Once: a stalled check, second presses, a later launch with no button, this device's real mpv when it has one (only looked for, never started), and fresh start with pretend mpv is missing, started as the launcher starts it. Takes about two minutes.
- `enamel_check` (the first design system step): both Enamel stylesheets load before the app's own and every file comes from the app's own server.
- `design_system_check` (the second design system step): each screen in Enamel (Home and its menu, onboarding's folder screens, a folder row with a message), with one focus at a time, nothing cut off and no row, button or menu row cutting its text at the bottom. To refresh the committed screenshots, run it directly with `docs/screenshots/design-system/` as the screenshot folder.
- `text_size_check` (the Enamel 0.11.0 upgrade): the same screens and checks as `design_system_check`, with Firefox's default text size at 200%, at every window size that holds Enamel's smallest supported box at that size.
- `design_system_lists_check` (the third design system step, the last design system step, the picker confirm work): the lists, tiles and the Remove question as an Enamel picker. Also needs ffmpeg.
- `playback_controls_mpv_check` (the playback controls work): the playback keys with the real mpv and two short clips made with ffmpeg. Needs mpv and ffmpeg, not Firefox; no window opens.
- `sleep_pause_mpv_check` (the sleep pause fix): a film paused for sleep and kept at its spot on waking, with the real mpv, a short clip made with ffmpeg and a stand-in for gdbus sending the sleep messages: paused, put back after a jump, "Paused" shown, nothing moved without a jump, and A playing on. Needs mpv and ffmpeg, not Firefox; no window opens.
- `continue_watching_mpv_check` (the Continue watching work, the server shutdown check): the quit script with the real mpv: saved position and frame, and closing mpv mid-film. Needs mpv and ffmpeg, not Firefox.
- `try_branch_check` (the "Try a branch" work): Try a branch, Back to main and Restore data in Settings › About on a development copy, at every window width, with git, GitHub's pull request list, the start check and the restart as stand-ins (the backups and the restore are real, in a temporary data folder): the rows, the picker with open pull requests first, each confirm with Cancel first, the restart with its note, a refusal with a local change, and the data put back exactly.
- `startup_error_check` (the start-up problem screen): the launcher's start-up problem page, served by the real message server with a broken settings file in a temporary folder, at every window width: every line, Close focused and in view above the hint bar (A Close, B Close), nothing cut off, Up and Down reaching the first and last lines; then, on a development copy on a branch that couldn't start (git a stand-in), Back to main beside Close: Right focuses it (A Back to main), A goes back once and says so, B closes; then A, B, Enter, Escape and a tap each closing it.
- `mpv_check_failure_check` (the settings mistakes work): when the mpv check at launch fails or mpv_command is broken, the loading screen gives way to a plain message that fits (or, in a very short window, that Down scrolls to its end). Settings are temporary copies.
- `mpv_quit_check` (the mpv quit spike): the quit-capture spike in `spikes/mpv-quit/` with the real mpv saves the right record and picture when B is pressed, and leaves resume alone. Needs mpv and ffmpeg, not Firefox. Run directly, it takes `--mpv flatpak` or `--mpv system` to choose which mpv.
- `absolute_numbers_check` (the three-digit episode fix): three-digit anime episode numbers on the real TV folder from `settings.json` (names only, read-only), with the parser timing. Needs no Firefox, ffmpeg or mpv, and takes a minute or two.
- `kiosk_profile_check` (the never-online work): the kiosk window never goes online by itself. Starts the Firefox `launch.sh` uses, with a new profile holding exactly `launch.sh`'s settings, on the app's page, twice, closing it the way the launcher does: for 30 seconds no connection from the window reaches anything but this device (its sockets are read every quarter second), nothing a setting switches off is even tried (its dead end points at a stand-in on the device that writes down where each request wanted to go and hangs up), and no Terms of Use notice, bar or dialog shows on either launch. Takes about a minute and a half.
- `storage_privacy_check` (the storage spike): the storage spike report and scripts hold no real names from the SD card (read-only). Skipped when the spike folder is gone or no card is mounted. Needs no Firefox, ffmpeg or mpv.
- `screen_awake_check` (the screen wake lock fix): the page keeps the screen on while a film plays, with a stand-in for Firefox's Screen Wake Lock: held during the film and released after it, asked again if Firefox lets go, released when the backend is lost or mpv stops with an error, never asked with keep_awake off, and a refused or missing wake lock changes nothing else. Playing is faked; takes about half a minute.
- `reflow_check` (the responsive layout work): in a narrow, tall window the tabs wrap onto two lines and nothing slips under them; in a short window an error or "Playing…" never pushes the selected row under the hint bar.
