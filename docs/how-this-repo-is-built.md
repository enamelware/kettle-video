# How this repo is built

Kettle Video is built with [Claude Code](https://www.anthropic.com/claude-code), Anthropic's coding agent, working from a designer's specs and decisions. The designer decides what Kettle Video should be and how it should look and behave, writes that down as ideas and specs, and tries every finished change on the reference devices: a Steam Deck (SteamOS) and a Retroid Pocket Nova (Armada), in Gaming Mode, with a controller. Claude Code turns the specs into issues, builds them, tests them and records what it decided along the way. This page explains how that work moves, for a curious designer or developer reading the repo.

The instructions Claude Code follows are part of the repo: [`CLAUDE.md`](../CLAUDE.md) holds the rules specific to Kettle Video, the rules every Enamelware repo shares come from the Enamelware handbook (the public repository `enamelware/handbook` on GitHub), installed as a Claude Code plugin at project scope, and the [`.claude/`](../.claude) folder holds the commands and the helper agents described below.

## The planning board

Every piece of work is a GitHub issue and a card on a planning board. The board itself is private; the issues are public. A card moves through six columns:

- **Drafted**: an idea written up as an issue, waiting for the designer to read it and leave notes.
- **Ready for dev**: approved by the designer and waiting to be built, top of the column first.
- **Building**: being built on its own branch, with one progress comment on the issue that is kept up to date.
- **More to do**: tried by the designer and sent back with feedback; these are built again before anything new.
- **Ready for testing**: built, checked and merged; waiting for the designer to try it on a device.
- **Done**: tried and approved by the designer; the issue is closed on the next run.

Moving a card to Done is the approval. Nothing else closes an issue.

## The commands

Three commands drive the work. Each is a written set of steps in [`.claude/commands/`](../.claude/commands).

- **/draft** turns an idea or spec into one or more issues in Drafted. It splits an idea that holds several features into separate issues (a series), labels each with a size, and builds nothing.
- **/next** builds one issue: it resumes anything interrupted first, then takes the top card from More to do, or else from Ready for dev. It builds on a branch named after the issue, runs the checks the issue's size calls for, merges into `main` only when they pass, and moves the card to Ready for testing with a comment listing what was checked and what to try on a device. `/next all` works through every waiting issue in a row; `/next 3` stops after three.
- **/tidy** is idle work for when nothing is waiting: it adds missing tests or fixes docs that no longer match the code, and proposes refactors as new Drafted issues for the designer to approve.

While building, Claude Code never stops to ask. A choice that can be undone and has a clear best option is made and written on the issue as "Decided: …, Why: …", with the `decided` label, so the designer can review all of them together. Only a few things stop the work (a new dependency or licence question, anything that could touch someone's media or can't be undone, a product change nobody asked for, security or privacy): the issue then gets one plain question and the `blocked` label, and the run moves on.

## The helper agents

Each issue is built and checked by separate agents, so the one that wrote a change is never the only one that checked it. Their instructions are in [`.claude/agents/`](../.claude/agents).

- **The builder** (a general helper started by /next) builds the issue and writes the tests it needs.
- **reviewer** checks the change against the issue and the rules, fixes small tidy-ups itself, and says PASS or FAIL with a numbered list of real problems.
- **test-checker** checks, on larger issues, that every point of the issue is covered by a test that would fail if the feature broke, and adds any that are missing.
- **test-writer** adds missing tests and fixes out-of-date docs during idle work.
- **refactor-scout** reads the code during idle work and proposes the most worthwhile refactors as issues. It changes nothing itself.

A small guard (`.claude/hooks/agent_guard.py`) keeps each agent to the folders and commands its job needs.

## Sizes and checks

/draft labels every issue with a size, and the size decides how it is checked.

| Size | What it is | Checks before merging |
|---|---|---|
| S | One small change, about three files or fewer, no new screen or component, nothing about data, settings, design tokens, launching, the local server, privacy or licences | the reviewer, and the quick check |
| M | One feature, one screen or one component | the reviewer, and the quick check |
| L | Several screens, or a change across the app or the design system | test-checker, then the reviewer, the quick check, and the full check once, just before merging |

The quick check runs the privacy guard on every file, the unit tests, and the browser checks for the screens the change touches: the real app in a headless Firefox, driven with the keys a controller sends, at window widths from the smallest the design system supports to very wide. The full check runs every unit test, timings included, and every browser check. It also runs before any release.

A failed check sends the issue back to the builder; after two rounds of fixes that still fail, the issue is blocked with an explanation. An issue that turns out bigger than its label is moved up a size and takes the bigger path. Small neighbouring issues in the same area are built together on one branch, and the issues of a series get one more review of their combined change once the last one is merged.

## What a person still does

Everything that can be checked from a terminal is checked by Claude Code. The designer does the exploratory part: looking at each change on the reference devices, using it with a controller, playing films with mpv and trying it in Gaming Mode. Feedback goes on the issue, and the card goes back to More to do.

## The decision log

[`docs/decisions.md`](decisions.md) records why things are the way they are: each real decision, with its date and reason. The "Decided" comments on issues are the day-to-day record; the ones that shape the app are copied into the log. [`CHANGELOG.md`](../CHANGELOG.md) records what changed in each version, and [`docs/spec.md`](spec.md) describes how the app behaves today.

## Privacy and public writing

Nothing from the devices the app is developed on, their media or their accounts goes into the repo. The privacy guard (`tools/privacy_guard.py`) checks every commit and push against a private list of words kept outside the repo, and the release check (`tools/release_check.py`) looks for anything that mustn't go public before each release. Example content is always invented, and screenshots use only the Blender open movies described in [`docs/sample-library.md`](sample-library.md).

Everything in the repo is written for a stranger to read: in the project's voice, with nothing private in it. The rule is the "Public writing" section of [`CLAUDE.md`](../CLAUDE.md), and the public-text check (`tools/public_text.py`, part of the release check) catches the patterns it can.
