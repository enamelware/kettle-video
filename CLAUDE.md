# Kettle Video

Kettle Video is a lightweight, controller-first browser for local movies and TV shows, built as a thin layer on top of mpv. It must feel native in SteamOS Gaming Mode. Kodi is too heavy for this; the goal is something small. (The name and brand are v0.1 and may change. The repository is `enamelware/kettle-video`; folders, file paths and ids say `kettle-video`.)

The owner is a senior product designer who knows HTML/CSS and is learning the AI-assisted workflow. Explain what you did and why in plain language, and keep changes small enough to review.

## Target devices

- Steam Deck: SteamOS, x86.
- Retroid Pocket Nova: Armada (SteamOS-like), ARM. Armada runs on many different handhelds.
- These are test devices, never layout targets (see "No layout is tied to a screen size" in Hard rules). Every UI change must adapt to any screen size and be usable with a controller only.
- Test in Gaming Mode, not just Desktop Mode.

**Device roles.** Development happens on the Steam Deck: it is the dev and first-test device. The Nova is tested less often, so ARM- or Armada-specific problems surface late. Flag those risks on the issue ("Nova risk") rather than leaving them for the owner to find. See `docs/decisions.md` ("Development moves to the Steam Deck").

## MVP

Testing happens with pre-set SD card folders on the Steam Deck and the Nova, so the first working version is deliberately minimal:

- Scan two configured folders (Movies, TV Shows) on launch.
- List video files as plain text, grouped by folder — no thumbnails, no parsed titles, no metadata.
- Selecting a file launches mpv; when mpv exits, return to the list.
- The folder paths come from the settings JSON file (set there directly, not through an onboarding flow).

**Onboarding is built (the onboarding work): with no folders set, a first launch checks for mpv, asks for the Movies and TV Shows folders, scans them and shows the result. Filename parsing and the TV show > season > episode hierarchy are built (the parsed library and saved library work): the app loads a saved library at launch and scans only when asked, or as part of onboarding. A first Continue watching row is built.** Everything else in this doc — Screens, the full Design rules, later Milestones — describes the intended full design and stays the target after the MVP ships; it just isn't built yet.

## Hard rules

- **Never commit anything from my devices, library or accounts.** The privacy guard (`tools/privacy_guard.py`) must pass before any commit or push; never bypass it (no --no-verify). Test data uses invented names only.
- **Sample library.** Automated test files keep invented names; running the app, examples and public screenshots use only the sample library of Blender open movies (`docs/sample-library.md`). Screenshots showing Blender content carry the credit line "(CC) Blender Foundation | studio.blender.org".
- **Never move, rename, or modify media files.** Media folders are read-only, to this app and to Claude Code (reading them to test is fine).
- **No scraping and no online metadata.** Titles come from filenames only.
- **Kettle Video never goes online by itself.** Any request to the internet happens only when the user chooses an action that clearly says it will go online. Any future feature that needs the network must be user-triggered and must update the README's privacy statement first. (The kiosk window's Firefox profile is part of this, see `docs/spec.md`, "Updates: never online by itself".)
- **No framework and no build step.** Plain HTML, CSS and JavaScript (ES modules). No React. No closed, proprietary or lock-in dependencies.
- **Backend is Python, standard library only**, except the unmodified third-party packages already in `vendor/` (see `THIRD_PARTY_LICENSES.md`). Never edit files in `vendor/`. Data lives in plain JSON files.
- **Ask before adding any dependency at all**, vendored or not.
- **Never edit anything inside `vendor/enamel/` by hand.** It is the vendored design system, Enamel; update it only with `tools/update_enamel.py` (see README, "Design system").
- **Read `vendor/enamel/DESIGN.md` before any interface work.**
- **All styling and components come from Enamel.** If something an issue needs is missing from Enamel or doesn't fit, don't style it inside this app: record the gap for Enamel's open "Gaps found by the apps" issue, as a question on this repo's issue with the label `needs enamel` (create the label if it's missing). If the issue can still be built well with what Enamel has, decide and carry on ("Decide, don't stall" below); if it can't, that issue and this rule contradict each other, which is a hard stop. /next never writes to Enamel's repo.
- **Do not reimplement playback.** Launch mpv as an external process and hand control back when it exits. Resume positions come from mpv's own saved state.
- **mpv may be missing** (e.g. on Armada). Detect it and guide the user; never fail silently.
- **No layout is tied to a screen size, a device or an aspect ratio.** Layouts adapt to the space they get. Breakpoints come from the content and are named by what they do, never by a device or a size. Nothing in the code, styles, tests or docs names a screen size, a device or an aspect ratio as a layout target. The Steam Deck and the Nova are test devices, never targets. Facts about a device that aren't about its screen stay (for example mpv being a Flatpak on the Nova, or Armada's settings).
- **Must run on both x86 and ARM.** Do not assume an architecture: plain Python and web files only, no compiled dependencies.

## Window

Firefox in kiosk mode for now (`launch.sh`). A Python webview window is possible later, but it would add a dependency and needs approval first. Keep the UI independent of the window layer.

## Design rules

- Input is keyboard keys, delivered by Steam Input, using the keys mpv already uses (arrows, Space/Enter, q/Esc). The controller drives mpv the same way. No Gamepad API. Always show a clear focus state. Nothing hover-only.
- Layouts are fluid and use tokens for spacing and type size. Check every UI change yourself across a range of window widths, from Enamel's smallest supported box to very wide (browser window sizes, screenshots): the owner works on the Deck and will rarely see other sizes.
- All styling goes through CSS custom properties (design tokens): colors, spacing, type, corner radius, density.
- Never hardcode a size the design system provides: read its token or measure the element (see "Design system changes are expected" below).
- Users can drop CSS snippets in a snippets folder. They load after the defaults and can be toggled in settings. Not built yet; the hooks they will use are listed in `docs/spec.md`, "Theming hooks".
- Class names and `data-` hooks are internal and may change; they are not a public API (see `docs/decisions.md`, "Snippet hooks are internal for now"). `docs/spec.md`, "Theming hooks", still lists every one of them: if one changes, update that list in the same commit.
- Settings live in one JSON file, read through the backend. The app writes it in two cases only: onboarding saves the two folders chosen on first launch, and the Settings screen saves one kind's folder when it is changed there.

## Brand (v0.1, may change)

Since the last design system step the app takes all its styling from Enamel (vendored at 0.13.1 since the Enamel 0.13.1 upgrade, motion included), with its single accent for focus rings and progress bars; the Mustard & Sage palette and the old colour variables are gone (rules and the replacement for each removed token in `docs/spec.md`, "Brand v0.1" and "Design system: the switch finished"). The loading screen shows the Kettle name in the bundled wordmark font; the window title, README and Steam shortcut say "Kettle Video". See `docs/decisions.md`.

- Name: Kettle Video. Kettle apps are named Kettle plus their medium, with no verbs (Kettle Audio is next). The wordmark on the loading screen stays "Kettle".
- Wordmark: Rubik Mono One, plain one-line text (no stacking, shadow or line). The font file is bundled with the app, never loaded online.
- Colours: Enamel's (one accent). Mustard stays only on the wordmark.

## Library

- Media folders are two paths (Movies, TV Shows) in the settings file.
- TV structure: show > season > episode.
- Cases the parser will need to handle (exact patterns are still an open question): one folder per movie (scene-style dotted names, or "Title (Year)"), multi-part movies (numbered files), cover images next to files, anime with absolute episode numbers and no season folders, unnumbered specials, "Sample" subfolders, and macOS `._` files (ignore these).

## Screens (from the design)

Today the app has a loading screen, first-launch onboarding (an mpv check when it's missing, choosing the Movies and TV Shows folders, then the first scan and its result screen), and one library screen with a Continue watching row above Movies and TV Shows tabs, where a show opens its episodes, and a Settings screen (Folders and About) opened from Home's menu. This is the target design once the detail screens are built:

- Home: list of sources plus a "Continue watching" shelf.
- Movies: detail screen per movie.
- TV: show > season > episode.
- Onboarding, 3 steps: choose a location, pick or create Movies and TV Shows folders, then a designed empty state.

## Architecture

Keep the core independent of the interface: folder scanner, library data, filename parsing and the mpv launcher form one backend with a clean interface. The standalone UI is the first client. A future Decky plugin, built later by a developer, should be able to reuse the same core, so keep it portable and documented.

Suggested layout (create as needed, not all at once):

```
backend/   scanner, parser, library store, mpv launcher, settings
ui/        html, css (tokens + defaults), js modules
themes/    example snippets
docs/      spec.md, decisions.md, dev-environment.md
tests/     parser fixtures
```

## Audience and distribution

- Audience: enthusiasts on Armada (SteamOS-like ARM handhelds) and SteamOS. Comfortable with Desktop Mode. There is no terminal in Gaming Mode, so everything must work without one.
- Installer: plan a one-click installer (a downloadable `.desktop` file plus a readable shell script) that checks for mpv and offers to install it, applies Flatpak folder permissions if needed, places the files, and prints the controller-layout steps. Installing, updating and uninstalling are built (`installer/install.sh`, `installer/update.py`, `installer/uninstall.sh`; no Flatpak folder permissions needed so far). `install-shortcut.sh` stays for development copies.
- mpv: a required dependency, not bundled for now. Detect a system mpv first, then the Flatpak (`flatpak info io.mpv.Mpv`). If missing, show an on-screen message with: `flatpak install flathub io.mpv.Mpv`
- Support: the launcher writes a log file. The README asks users to attach it to GitHub issues and lists the tested versions.
- Controllers: document the button-to-key mapping (D-pad = arrows, A = Space, B = q, X = Backspace, Y = a, L1 = j, R1 = l; full table in `docs/device-setup.md`) and test under different emulated controller types (Steam Deck, Xbox 360, DualSense).

## License

GPL-3.0-or-later (see `LICENSE`). Every new source file starts with this header, in the file's comment syntax:

```
SPDX-License-Identifier: GPL-3.0-or-later
Copyright (C) 2026 Mario Carabotta
```

## Ways of working

- One milestone or issue per session (except `/next all` and `/next N`, which build several in a row).
- Don't ask for plan approval when an item has a spec. Decide yourself, and stop only for a hard stop: see "Decide, don't stall" in "How we work". **/next (any mode) and /tidy never stop to ask me and never use the interactive question prompt:** a question goes into the issue's comments with the `blocked` label, the branch is kept, and the run carries on with the next issue. Only a normal session (not /next or /tidy) may ask me directly.
- Keep commits small, with clear messages, referencing the issue (`Refs #N`). **Do not push without asking.** `/next` and the "failed" phrase count as asking: /next pushes its `issue-N` branch at each checkpoint and merges into `main` only after the checks and tests pass. Never force-push.
- Record every real decision and its reason in `docs/decisions.md`. Link to it instead of repeating reasoning here.
- The filename parser is pure logic: build it with a set of sample filenames as automated tests.
- Stay inside this directory, except for reading the media folders named in `settings.json`. Never read or touch `~/.ssh`, credentials or anything else outside the project.
- Platform facts about SteamOS and Armada change quickly. Check current documentation rather than assuming.

## Testing

- **Claude Code owns all automated and command-line testing**: unit tests, running scripts and checking their output, running the parser or app against the real library on the SD card (read-only; the paths in this device's `settings.json`), timings, and anything else doable from a terminal on this device. Do it before a card reaches Ready for testing. Never merge or commit to `main` with failing tests (work-in-progress commits on an `issue-N` branch may be unfinished).
- **The owner only does exploratory testing on the devices**: looking at the UI, using the controller, playback, Gaming Mode. Never ask the owner to run commands or test cases. Ask for something else only if it genuinely can't be done from the terminal, and say why.

## How we work

Roadmap items are GitHub issues on the "Kettle" project board (IDs in `.claude/board.json`). The board also holds Enamel issues: /next, /tidy and /draft (and `scripts/board.sh`) read, build, move and create only this repository's issues and ignore the rest. Columns: Drafted, Ready for dev, Building, More to do (issues I tested and sent back with feedback in the comments), Ready for testing (I try it on whatever device I have to hand), Done (I move the card there myself when I'm happy; that is my approval).

- `/draft` writes issues into Drafted. The owner reviews them and moves the ones to build into Ready for dev. Several items can go in one paste, separated by a line with only `===`; each becomes its own issue(s), in order, and dependencies between items are linked both ways.
- Never start building an issue unless its board Status is Ready for dev or More to do. /next always clears More to do before taking anything from Ready for dev, and builds `refactor` issues in Ready for dev only after every other issue there.
- `/next` takes the top More to do issue first (addressing the owner's latest feedback), otherwise the top Ready for dev issue: Building, then tests, the checking agents its size calls for (below), merge into `main`, push, Ready for testing, with a comment on the issue listing what was verified automatically, the agents' verdicts (and, for More to do, what changed for each point of feedback), one short list of things to try (not grouped by device), and a "Nova risk" line only when the change might behave differently on ARM, Armada or a different screen shape.
- **Sizes.** /draft labels every issue with one of these (when unsure, the bigger one), and /next picks its path from it:
  - `size:S`: one small change, about 3 files or fewer, no new screen, no change to data, launch, privacy or licences.
  - `size:M`: one feature or one screen.
  - `size:L`: several screens, or a change across the app or the design system.
- **Checks by size** (`.claude/agents/`, details in `.claude/commands/next.md`, "Size and path"). The builder always writes the tests the change needs, as part of building it. S and M: the builder, then **reviewer**, which also checks the tests are adequate; quick checks; no separate test-checker. L: the builder, **test-checker** (finds what the builder's tests miss and adds tests, only in `tests/`) and reviewer, quick checks, plus the full check before merging. Every size keeps its own branch, merging only when checks pass, the progress comment, the testing comment and the board moves. Each agent answers PASS, or FAIL with a numbered list; on a FAIL the builder fixes and the path's agents run again, at most 2 fix rounds; still failing means `blocked` with a plain-language question. `.claude/hooks/agent_guard.py` enforces their limits (and those of test-writer and refactor-scout, below). See `docs/decisions.md`.
  - **The reviewer fixes tidy-ups itself** in one small extra commit and notes them (unused lines or imports, repeated set-up, a missing licence header, wording). It fails only for real problems: wrong behaviour, a broken layout, something the spec asks for that's missing (tests included), a gap not reported to me, a broken hard rule, security or privacy.
  - **Upgrades are automatic.** An S that turns out to touch more than about 3 files, or touches the data folder, `launch.sh`, privacy, licences, `settings.json`'s format or design system tokens, becomes M; an M that grows past one screen or feature becomes L. Change the size label and say why in one line on the issue; it then takes the new size's path.
  - **Small issues are bundled.** Two or more S issues next to each other in Ready for dev that touch the same area are built on one branch with one commit per issue and one review. Each card still moves and gets its own testing comment.
  - **Series are reviewed as a whole.** Issues /draft split from one feature share a `series: <name>` label and link to each other. Each is built on its own size's path; when the last one merges, one review covers the whole series' combined change (fit between the pieces, duplicated code, the feature as a whole against its spec). Fixes go in a small follow-up issue in the same series. The series' cards wait in Building, with a progress comment saying so, and move to Ready for testing only once that review passes.
  - **Board housekeeping:** every /next and /next all starts by closing any issue whose card is in Done but which is still open, with a one-line comment (`scripts/board.sh close-done`).
- **Branch per issue.** Every issue is built on its own branch `issue-N`, started from the latest `main`. Work in progress is committed and pushed there at checkpoints (plan, code, fixes after each check round). It is squashed into one `Refs #N` commit on `main` (one per issue for a bundle) only when its size's checking agents pass and the quick check passes on the final code; then the branch is deleted. `main` only ever holds finished, tested work, because the test devices are updated by hand from it. A blocked issue's branch stays parked until I unblock it.
- **Progress comment.** /next keeps one progress comment per issue, edited in place at each checkpoint (branch, done so far, what's next, the plan), so either of us can see where a run stopped.
- **Resume first.** Every /next and /next all first looks for unfinished work (cards in Building, unmerged `issue-N` branches, uncommitted changes, unpushed commits) and continues it from its progress comment before taking anything new. It always re-runs the quick check before merging, but re-runs the reviewer or test-checker only if the code changed since they last passed. Every step checks whether it already happened, so nothing is duplicated. Unclear state: leave the branch untouched, comment, add `blocked`, move on. Never start a new issue while another one has uncommitted changes. In /next all, each issue is built by its own fresh helper agent, so the main session stays small. Details in `.claude/commands/next.md`.
- **Decide, don't stall.** Make decisions fast; a question never stops a run.
  - **Decide yourself**, without asking or stopping, when all of these are true: the choice can be undone with a git revert; you would recommend one option; no hard stop applies. If two options seem equal, pick the smaller one that is easier to undo. Then comment on the issue: "Decided: <what>. Why: <one line>. To change it, reply on this issue." and add the `decided` label, so I can review all of these together on the board. Real decisions still go in `docs/decisions.md`. A theming hook change decided this way updates its docs in the same commit (Design rules).
  - **Hard stops** (the only reasons to stop): a new dependency or licence question; anything that could change, move or delete my media or other files outside the repo; anything a git revert can't undo; a product change nobody asked for that doesn't come from the issue or the design system (this includes visible changes beyond the spec that don't come from the issue or the design system); security or privacy; the issue and CLAUDE.md contradicting each other. For a hard stop: write one plain-language question in the issue, add `blocked` and move on to the next issue.
  - **Design system changes are expected.** When a new design system version (Enamel, vendored in `vendor/enamel/`) changes sizes, spacing, colours or components, the app follows it, and that is in scope. Never hardcode a size the design system provides: read its token or measure the element. Only treat it as a problem if something stops working (can't be reached, read or used), not because it looks different, and even then fix it in the app if you can.
  - **Never use the interactive question prompt** during /next, /next all or /tidy. Questions go in the issue. Either decide or block and move on.
  - **Time limit:** if one problem takes more than about 30 minutes without progress, write what you found in the issue, add `blocked` and move on.
- Board changes only through scripts/board.sh; tests only through scripts/test.sh.
- **Quick and full checks.** Every issue runs the quick check (`scripts/test.sh` naming the browser checks for the screens it touches; aim under 2 minutes, so if it grows past that, speed it up without checking less). The full check (`scripts/test.sh full`) runs before merging a `size:L` issue, before any `VERSION` bump or release, and once at the end of `/next all` if anything was merged; if it fails, find from the commits which issue caused it, move that issue to More to do with a plain-language comment, and release nothing. Never run the same check twice on the same code: `scripts/test.sh` remembers each pass against the exact code. See `docs/decisions.md`.
- **Enamel is pinned.** The adopted Enamel release is its tag in `ENAMEL_PIN`, the one place it is recorded; `vendor/enamel/` must match that tag exactly, and the design system check compares with that tag only, never with Enamel's main or its latest release, so a new Enamel release can't fail an unrelated issue. Upgrades are their own issue: at the start of `/next all`, if Enamel has a newer release tag than the pin (read with `scripts/peek.sh`), draft one "Bring in Enamel <version>" issue with its changelog summary unless one exists. Never upgrade inside another issue; an issue that needs a newer Enamel waits for that one.
- **One simple command at a time** during /next and /next all: never chain commands with `&&`, `;` or pipes (`|`), so each one can match the allow list. To filter output, do it in a separate step or with the built-in tools. Run git from this repo's folder without `-C`; read the other Kettle repo (Enamel) only with `scripts/peek.sh` (log, show, status, diff, tag, rev-parse, ls-files), while `git -C` keeps asking. Every helper agent (builder, reviewer, test-checker, test-writer, refactor-scout, any general-purpose helper) follows the same rules, which are written into each agent's own instructions and the builder's prompt.
- **A new ask or deny rule must never catch a read-only command.** Check it against git log, show, status and diff; gh issue view and list; ls, cat and grep; `scripts/board.sh list`; and `scripts/peek.sh`, and narrow any existing ask rule that catches one. `tests/test_agent_guard.py` checks this for the shared settings.
- **`git rm` is allowed without asking** for files git tracks inside this repo (a deletion is reversible, like any edit). Still ask for plain `rm`, `git rm` with a path outside the repo or with `-f`/`--force` (that throws away uncommitted changes), `git clean`, and anything that deletes untracked files. See `docs/decisions.md`.
- To delete one of your own memory notes, use scripts/forget-note.sh (allowed without asking; it accepts only a plain .md file name in this project's memory folder), never rm.
- `/next all` repeats /next through every More to do issue, then every Ready for dev issue, top to bottom; `/next N` stops after N issues. It ends with one summary: each issue with its size and the path it took (including upgrades, bundles and series reviews), what was resumed from an earlier interruption, what is Ready for testing, what is blocked and what each blocked issue needs from me, plus the idle work below.
- **Idle work** (`/tidy`, and at the end of `/next all` once More to do and Ready for dev have nothing left that isn't blocked; details in `.claude/commands/tidy.md`). First **test-writer** (Sonnet; may write only in `tests/`, `docs/` and `README.md`, never app code) makes up to 2 small improvements: missing tests for existing behaviour, or docs that no longer match the code. Each goes through its own branch, both checking agents, all tests and the merge, and the run reports them on one `tests` issue created in Ready for testing, with a short smoke check only. Then **refactor-scout** (Opus; read-only) proposes up to 3 refactors, which the run files in Drafted labelled `refactor` with a size label, skipping anything that overlaps an open or blocked issue or repeats an existing `refactor` issue. Neither changes what the app does.
- **Refactor issues** keep behaviour exactly the same: every automated test passes before and after, and no existing test is loosened or removed.
- **The `blocked` label.** In any mode, when an issue hits a hard stop, its tests still fail, one problem has taken about 30 minutes without progress, or the checking agents still say FAIL after 2 fix rounds, /next comments one plain-language question or explanation, adds `blocked`, leaves the issue in its column and moves on. /next skips blocked issues, and issues that need a blocked or unbuilt one first (it says which in a comment). I answer in the comments and remove the label; the next /next picks it up as normal.
- When asked to continue or change #N, read that issue and its comments with `gh` first.
- **Approval is the Done column.** I move a card from Ready for testing to Done myself when I'm happy; the board housekeeping at the start of the next /next closes the issue. Never move a card to Done or close an issue otherwise.
- Phrase (several issue numbers allowed, e.g. "#N #M failed: ..."): "#N failed: <what happened>": comment my feedback on the issue and move it to More to do. Do not start fixing it straight away; /next will pick it up.

## Public writing

Kettle Video's repo will be public, so everything a visitor can read makes sense to a stranger. That covers the README, `docs/`, `CHANGELOG.md`, code comments, tests, the workflow files in `.claude/`, issues, comments and commit messages. It follows the same rule as Enamel's.

- **Project voice.** "Kettle Video uses…", "Chosen because…". Never "I", "we" or "you" in public text, and "the designer" for the person who runs the project, never "owner". Instructions addressed to Claude Code, in this file and `.claude/`, may speak to it as "you", and keep their wording until an issue about the workflow changes it. Text addressed to the app's users (the README's install, update, privacy and usage steps, release notes in `CHANGELOG.md`, and the app's own on-screen words) may speak to them as "you".
- **Reference devices.** Devices are named only as reference hardware: Steam Deck (SteamOS) and Retroid Pocket Nova (Armada). They are for testing, never layout targets (see "Hard rules").
- **Nothing private.** No personal paths, machine or login names, personal media or real film and show titles, email addresses other than the commit address, and no references to private chats, documents, design canvases or the private board. Those are described in words; links only go to public places. Example content is always invented (see "Sample library" in "Hard rules").
- **No old issue numbers or commit addresses in files.** The public repo starts its numbering again, so a file names earlier work in words ("the onboarding work", "the keep-awake fix"), never by an issue number, a commit address or a link into the private history. A test's docstring names its issue the same way. Commit messages still say `Refs #N`.
- **Issues** are written as public tickets: in the project voice, for a stranger, with nothing private. They keep the headings /draft writes, which /next reads.
- **Testing comments and reports** follow the same voice.
- **Commit messages** follow it from now on. Past commits are never rewritten.
- **How the work is done** is explained for visitors in [docs/how-this-repo-is-built.md](docs/how-this-repo-is-built.md); public text points there instead of explaining workflow terms again.
- **Works on a stranger's machine.** A development tool either works without this device's set-up or says plainly what it needs (`docs/dev-environment.md`, "On another machine").
- **Checked automatically.** The public-text check (`tools/public_text.py`, part of the release check `tools/release_check.py`, and a unit test) fails on an old issue number, the project's owner named by role (outside this file and `.claude/`), a claude.ai link, and a link to the private board, in every published file. The release check also fails on commit addresses, links into the private history, real titles and everything the privacy guard finds.

## How to talk to me

- The owner is a product designer, not a developer. Write plans and summaries in plain language: short, with no jargon, or with any jargon explained in a few words. No code or library internals unless I ask.
- Every plan starts with: what I will do (5 bullets at most), what changes for the user, what could go wrong, and which files are touched (one line).
- Before showing a plan, check it against every rule in CLAUDE.md and in the prompt. End the plan with that checklist, each rule marked "respected" or "not respected". Do not ask the owner to verify rules that are already written down.
- Give file-by-file detail only when asked.
- When I need a decision, offer 3 options at most, say which one you recommend, and say why in one sentence.

## Milestones

1. Setup: repo scaffold, docs, this file.
2. Walking skeleton (**this is the MVP**, see above): scan two configured folders, list files as plain text grouped by folder, launch mpv on a file, return. Test on both devices.
3. Library: scan, filename parsing, JSON storage (built).
4. Controller UI: home, movie detail, TV hierarchy (a first version is built), focus navigation.
5. Resume and sources: Continue watching, SD card unavailable states.
6. Onboarding (post-MVP), settings, theming snippets.
7. v0.1 release on GitHub.

Later, not now: Flatpak packaging, then a Decky companion.

## Open questions (do not decide alone; raise them)

- Controller-friendly folder browser in Gaming Mode.
- SD card removal and re-insertion handling.
- Flatpak permissions (mpv's SD card access is answered: nothing needed, see `docs/decisions.md`; Firefox and the installer are still open).
- Exact filename patterns and loose files.
- Which window or wrapper shows the web UI (test on both devices).
