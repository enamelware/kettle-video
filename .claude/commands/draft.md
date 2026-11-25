---
description: Turn an idea or spec into one or more GitHub issues on the Kettle board as Drafted. Does not build anything.
argument-hint: <idea, sentence or spec; several items separated by a line with only ===>
---

Draft work items for the owner to review. The text is:

$ARGUMENTS

Follow CLAUDE.md, especially "How we work", "Public writing" and "How to talk to me", and the handbook's `enamelware:operations` skill ("Handing work to Claude Code", "Sizes"). **Do not build anything, create branches or edit project files.** This command only writes issues.

1. **Board.** Board changes only through `scripts/board.sh` (it reads the IDs in `.claude/board.json` itself). Run one simple command at a time: no `&&`, `;` or pipes.
   **This repo only.** The Kettle board also holds issues from other repositories (Enamel). Create, link and move only issues that belong to this repository. `scripts/board.sh list` already leaves the others out, and `gh issue` commands without `--repo` stay in this repository; never pass `--repo` or follow a link to act on another repository's issue.

2. **Items.** If the text contains a line with only `===` on it, it holds several items: split the text at those lines, ignore empty items, and handle each item through steps 3 to 5 in the order given. Otherwise the whole text is one item, exactly as before.

3. **Size and split.** Sizes are defined in the handbook's `enamelware:operations` skill ("Sizes"), with Kettle Video's files behind its limits listed in CLAUDE.md ("How we work"); use exactly those definitions, so labels are consistent and /next picks the right path. For each item, decide how many issues the text needs. An item that holds more than one feature or screen becomes several issues, each useful on its own and in a sensible build order; a change across the whole app or the design system that can't usefully be split stays one `size:L` issue. If a chunk depends on another, say so in its body ("Needs #N first").
   - **Series.** When one item is split into several issues, they form a series: create a label `series: <short name>` (a few plain words, for example `series: onboarding`) with `gh label create`, add it to every issue of the item, and link them to each other with one line at the top of each body: `Series: #A, #B, #C (this is 2 of 3).` Create the issues first, then add the lines with `gh issue edit --body-file`. When the last one merges, /next reviews the series' combined change once, and its cards wait in Building until that review passes. An item that stays one issue has no series label.
   - **Dependencies between items** in the same paste ("depends on the item above", "needs the colours item first"): link the issues by mentioning each in the other. The dependent issue says "Needs #N first" and the other says "Needed by #M". If an item depends on one that comes later in the paste, or the wording is unclear, create everything first, then add the lines with `gh issue edit --body-file`. If it is unclear which item is meant, say so in the reply instead of guessing.

4. **Write each issue** in plain language for a designer, no code or jargon, with three headings:
   - **What**: what changes for a viewer, and why.
   - **Watch for**: risks, edge cases, and anything that touches a hard stop (the handbook's `enamelware:decisions` skill, "Hard stops", and Kettle Video's own in `.claude/commands/next.md`, "Decide or block": new dependency or licence, files outside the repo, something a git revert can't undo, a product change that doesn't come from the issue or the design system, security or privacy).
   - **Done when**, in two parts:
     - **Checked automatically by Claude Code**: unit tests, scripts and their output, runs against the real library on the SD card (read-only), timings, anything doable from a terminal on this device.
     - **Checked by eye on the devices**: only what needs a person: how the UI looks, controller use, playback, Gaming Mode. Never commands. Write "nothing visible yet" when the change has no visible effect.
   Add exactly one size label (`size:S`, `size:M` or `size:L`, by the handbook's definitions; when unsure between two, take the bigger one) and a topic label if one fits (for example `parser`). Create a missing label with `gh label create`.

5. **Create and place** each issue:
   - `gh issue create --title ... --body ... --label ...` and note its URL and number.
   - Add it to the board: `scripts/board.sh add N`
   - Set Status to Drafted: `scripts/board.sh status N Drafted`

6. **Reply.**
   - One item: one line per issue: `#N (size) — what it does, in one plain sentence.`
   - Several items: one line per issue, in the order given: `#N — title (size)`, adding "needs #M" where a dependency was linked.
   - For each series, one more line: `Series "<name>": #A, #B, #C — reviewed together once the last one is built.`
   Then stop. The owner reviews on the board, leaves notes as issue comments, and moves the ones to build into Ready for dev.
