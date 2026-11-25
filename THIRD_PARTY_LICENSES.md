# Third-party licenses

The backend is Python standard library only, except for the packages below. They are bundled in `vendor/` so nothing has to be installed with pip. All of them are pure Python, so they run the same on x86 and ARM.

The copies in `vendor/` are **unmodified**. They were copied as released, leaving out only their `__pycache__` and `test` folders and their packaging metadata (`.dist-info`). Each package's license file sits next to it in `vendor/` as `<name>.LICENSE`.

| Package | Version | License (from package metadata) | In `vendor/` | Source |
|---|---|---|---|---|
| guessit | 4.4.0 | LGPL-3.0-or-later | `guessit/`, `guessit.LICENSE` | [PyPI](https://pypi.org/project/guessit/4.4.0/) · [project](https://github.com/guessit-io/guessit) |
| rebulk | 6.0.1 | MIT | `rebulk/`, `rebulk.LICENSE` | [PyPI](https://pypi.org/project/rebulk/6.0.1/) · [project](https://github.com/Toilal/rebulk) |
| babelfish | 0.6.1 | BSD-3-Clause | `babelfish/`, `babelfish.LICENSE` | [PyPI](https://pypi.org/project/babelfish/0.6.1/) · [project](https://github.com/Diaoul/babelfish) |
| python-dateutil | 2.9.0.post0 | Dual License: Apache-2.0 and BSD-3-Clause (see its license file) | `dateutil/`, `python-dateutil.LICENSE` | [PyPI](https://pypi.org/project/python-dateutil/2.9.0.post0/) · [project](https://github.com/dateutil/dateutil) |
| six | 1.17.0 | MIT | `six.py`, `six.LICENSE` | [PyPI](https://pypi.org/project/six/1.17.0/) · [project](https://github.com/benjaminp/six) |

guessit uses the other four. guessit 4.4.0 and rebulk 6.0.1 need **Python 3.10 or newer**.

## Replacing a vendored package

You can swap any of these for a newer unmodified release. Replace its folder (or `six.py`) in `vendor/` with the one from the new release, using the same layout, and update its `.LICENSE` file and this table. Then run `python3 -m unittest discover -s tests -t .` from the repo root to check it still loads from `vendor/` and still parses.

## Design system

The UI's styling comes from Enamel, the design system for the Kettle apps (the designer's own project). Its files are copied **unmodified** into `vendor/enamel/` by `tools/update_enamel.py`, with its licence and notice next to them. MIT fits with this GPL app; Enamel keeps its own licence. Its `NOTICE.md` says its neutral palette, spacing and motion are designed to match Steam's Gaming Mode, that it includes no Valve code, class names, icons, logos or fonts, that Enamel and Kettle are not affiliated with Valve, and that the MIT licence grants no rights to the Enamel or Kettle names or the Kettle wordmark.

| Package | Version | License | In `vendor/` | Source |
|---|---|---|---|---|
| Enamel | 0.13.1 | MIT, Copyright (c) 2026 Mario Carabotta | `enamel/` (`tokens/enamel.css`, `components/enamel-components.css`, `components/enamel-components.js`, `DESIGN.md`, `VERSION`, `LICENSE`, `NOTICE.md`, `MIGRATION.md`) | github.com/enamelware/enamel; `~/Development/enamel` on the Steam Deck |

## Fonts

The UI bundles one font, used only for the Kettle wordmark on the loading screen. It is **unmodified**: the file from the official Google Fonts repository, not trimmed or converted. Its license file sits next to it.

| Font | Version | License | In the app | Source |
|---|---|---|---|---|
| Rubik Mono One (Regular) | 2.000 | SIL Open Font License 1.1 (OFL-1.1), Copyright 2015 The Rubik Project Authors | `ui/fonts/RubikMonoOne-Regular.ttf`, `ui/fonts/RubikMonoOne-OFL.txt` | [google/fonts `ofl/rubikmonoone`](https://github.com/google/fonts/tree/0fc79a83d486f399f0fe3c07f4d0a5ab6a39ad1f/ofl/rubikmonoone) · [project](https://github.com/alexeiva/rubikmonoone) |

The OFL lets the font ship with this GPL app; the font keeps its own license.

## Used but not bundled

Kettle Video plays every video with mpv, but mpv is **not bundled**: the app only launches the copy already installed on the device (the system's mpv, or the Flatpak `io.mpv.Mpv`), as a separate program, and hands control back when it closes. No mpv code or file ships with this app.

| Program | License | In the app | Source |
|---|---|---|---|
| mpv | GPL-2.0-or-later (LGPL-2.1-or-later for builds made that way) | not bundled: launched as a separate program | [mpv.io](https://mpv.io/) · [project](https://github.com/mpv-player/mpv) |

The Settings screen's About section lists every entry on this page, in this order, and shows each bundled one's license text from the file named above (the Settings screen work).
