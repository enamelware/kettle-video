# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Turn ONE file or folder name into a small, predictable ParsedName.

Pure logic on top of the bundled guessit. It does not walk folders and does
not decide show or movie; the caller says which with `kind`. guessit is
imported lazily on the first call, so importing this module stays fast.
Rules and reasons: docs/decisions.md ("Single-name normaliser").
"""

import functools
import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from backend.scanner import VIDEO_EXTENSIONS
from backend.vendor_path import VENDOR_DIR, use_vendor

KINDS = ("movie", "episode")

# "Season 2", "season.02", "S02", "S 2" and nothing else.
_SEASON_ONLY = re.compile(r"^\s*(?:season|s)[\s._-]*(\d{1,3})\s*$", re.IGNORECASE)

# Explicit multi-episode markers: S01E01E02, S01E01-E02, 1x01-02, 1x01-1x02.
_MULTI_EPISODE = re.compile(
    r"S\d{1,3}E\d{1,4}(?:[-_. ]?E\d{1,4})+"
    r"|\b\d{1,2}x\d{1,4}(?:-(?:\d{1,2}x)?\d{1,4})+\b",
    re.IGNORECASE,
)

# A bare three-digit number after a dash: anime's absolute numbering,
# "Show - 112" (the three-digit episode fix). The number must stand alone (no digit after).
_DASH_NUMBER = re.compile(r"(?:^|[\s_])-[\s_]+(\d{3})(?!\d)")

_BRACKET_TAGS = re.compile(r"\[[^\]]*\]|\{[^}]*\}")

# Words a number cut off from an episode title: no brackets, no tags.
_PLAIN_REST = re.compile(r"[\w\s.,'!?&-]*")

_guessit = None


@dataclass(frozen=True)
class ParsedName:
    title: str
    year: Optional[int] = None
    season: Optional[int] = None
    episode: Optional[int] = None
    episodes: list = field(default_factory=list)
    episode_title: Optional[str] = None
    raw: str = ""
    flags: list = field(default_factory=list)


def _load_guessit():
    global _guessit
    if _guessit is None:
        use_vendor()
        from guessit import guessit

        _guessit = guessit
    return _guessit


# What this name reader's answers depend on: this file and the bundled
# guessit and rebulk versions. The saved library keeps reader_version() with
# its saved names, and reads every name again once when it changes, so a
# name reader update shows up on the next Rescan (the quick rescan and Remove work).
_READER_FILES = (
    Path(__file__),
    VENDOR_DIR / "guessit" / "__version__.py",
    VENDOR_DIR / "rebulk" / "__version__.py",
)


def fingerprint(paths) -> str:
    """A short code that changes whenever any of these files changes."""
    digest = hashlib.sha1()
    for path in paths:
        try:
            digest.update(Path(path).read_bytes())
        except OSError:
            digest.update(b"(unreadable)")
        digest.update(b"\0")
    return digest.hexdigest()[:16]


@functools.lru_cache(maxsize=None)
def reader_version() -> str:
    return fingerprint(_READER_FILES)


def _strip_extension(name: str) -> str:
    # Only known video extensions, so folder names like
    # "Example.Movie.1995.1080p" keep their last dotted part.
    lower = name.lower()
    for ext in VIDEO_EXTENSIONS:
        if lower.endswith(ext):
            return name[: -len(ext)]
    return name


def _fallback_title(stem: str) -> str:
    text = _BRACKET_TAGS.sub(" ", stem)
    text = text.replace(".", " ").replace("_", " ")
    return " ".join(text.split())


def _unique(values) -> list:
    # Advanced mode can report the same value twice ("01" and "1").
    unique = []
    for value in values:
        if value not in unique:
            unique.append(value)
    return unique


def _values(matches: dict, key: str) -> list:
    return _unique(m.value for m in matches.get(key, []))


def _ints(values: list) -> list:
    return [v for v in values if isinstance(v, int)]


def _text(values: list) -> Optional[str]:
    value = " ".join(str(v) for v in values)
    return value or None


def _words(text: str, dots: str) -> list:
    return text.replace(".", dots).split()


def _digit_run(stem: str, start: int, end: int) -> tuple:
    # guessit can split "100" into a season "1" and a lost "00"; take it whole.
    while start > 0 and stem[start - 1].isdigit():
        start -= 1
    while end < len(stem) and stem[end].isdigit():
        end += 1
    return start, end


def _plain_rest(stem: str, end: int, spans: list) -> Optional[str]:
    """The unclaimed text from `end` up to the next match, or None if it
    holds anything but plain words (a bracket, a tag...)."""
    stop = min([a for a, _ in spans if a >= end] + [len(stem)])
    rest = stem[end:stop]
    if not _PLAIN_REST.fullmatch(rest):
        return None
    # A dot glued to the next match ("Doors.720p") is a separator.
    return rest.rstrip(".") if stop < len(stem) else rest


@dataclass(frozen=True)
class _Number:
    """A number put together from guessit's pieces: same `value` and `span`."""

    value: int
    span: tuple


def _absolute_numbers(stem: str, matches: dict) -> dict:
    """Read "Show - 112" as episode 112, not season 1, episode 12.

    guessit splits a bare three-digit number after a dash into a season and
    an episode when no tag follows it. When both pieces sit inside such a
    number, they become one episode with the whole number. Scene-style names
    without a dash ("Show.Name.112.HDTV") keep guessit's reading. Rule and
    reason: docs/decisions.md ("Three-digit anime numbers").
    """
    for found in _DASH_NUMBER.finditer(stem):
        a, b = found.span(1)

        def inside(m):
            return a <= m.span[0] and m.span[1] <= b

        seasons = [m for m in matches.get("season", []) if inside(m)]
        episodes = [m for m in matches.get("episode", []) if inside(m)]
        if not (seasons and episodes):
            continue
        matches = dict(matches)
        matches["season"] = [m for m in matches["season"] if not inside(m)]
        if not matches["season"]:
            del matches["season"]
        rest = [m for m in matches["episode"] if not inside(m)]
        matches["episode"] = sorted(
            rest + [_Number(int(found.group(1)), (a, b))], key=lambda m: m.span[0]
        )
    return matches


def _from_original(stem: str, match, guessed: str, extras: list, spans: list = ()):
    """Rebuild a title from the original text at guessit's position.

    `extras` are numbers guessit read as an episode or season but that are
    not the episode kept; one inside the title or touching it (at most one
    separator between, before or after) becomes part of the title, and when
    such a number cut the title short, the plain words after it come back
    too. `spans` are the positions of every match, to know where those words
    end. The rebuilt text is used only if, without its full stops and those
    numbers, it has the same words as guessit's value. Otherwise guessit's
    value is kept, so this can only put back full stops, numbers and the
    words a number cut off.

    Returns (title, the extras that became part of it).
    """
    start, end = match.span
    absorbed = []
    for extra in sorted(extras, key=lambda m: m.span[0]):
        a, b = _digit_run(stem, *extra.span)
        if a <= end + 1 and b >= start - 1:
            start, end = min(start, a), max(end, b)
            absorbed.append((extra, a, b))

    rest = ""
    if absorbed and end == max(b for _, _, b in absorbed):
        rest = _plain_rest(stem, end, spans)
        if rest is None:
            return guessed, []

    # In a spaced name, a dot glued to what follows ("Example.S01E02") is a
    # separator, not a full stop.
    while (
        " " in stem and end > start and stem[end - 1] == "." and end < len(stem)
        and not stem[end].isspace()
    ):
        end -= 1

    text = stem[start:end]
    check = list(text)
    for _, a, b in absorbed:
        check[a - start : b - start] = " " * (b - a)
    check = "".join(check)
    text += rest

    if " " not in stem:
        # Dotted or underscored name: dots are separators, not full stops.
        text = text.replace(".", " ").replace("_", " ")
        check = check.replace(".", " ").replace("_", " ")

    text = " ".join(text.lstrip(" -_").rstrip(" -_[(").split())
    check = check.lstrip(" -_").rstrip(" -_[(")
    if guessed.split() in (_words(check, ""), _words(check, " ")) and text:
        return text, [extra for extra, _, _ in absorbed]
    return guessed, []


def _fold(text: str) -> str:
    """Lower case, accents removed: what sorting and the article check compare."""
    plain = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in plain if not unicodedata.combining(ch)).casefold()


def title_sort_key(title: str) -> tuple:
    """Sort titles ignoring case and accents, so "É" sorts with "E".

    Uses only Python's own Unicode data, never the device's language
    settings, so the order is the same on every device. Close enough rather
    than right for every language ("ß", Scandinavian letters). Titles keep
    their accents for display.
    """
    return (_fold(title or ""), unicodedata.normalize("NFC", title or "").casefold())


_ARTICLES = ("the", "an", "a")


def title_without_article(title: str) -> str:
    """The part of a title that sorting looks at (the title sorting work): leading spaces
    trimmed and a leading English "The ", "A " or "An " dropped, once, when
    a letter or digit follows. "The Mossbrook" -> "Mossbrook"; "The", "A.B." and
    "Thelwick" stay as they are. English only: Le, La, Die and so on clash
    with other languages. See docs/decisions.md.
    """
    text = unicodedata.normalize("NFC", title or "").strip()
    for article in _ARTICLES:
        size = len(article) + 1
        rest = text[size:]
        if _fold(text[:size]) == article + " " and any(ch.isalnum() for ch in rest):
            return rest.lstrip()
    return text


def library_order(title: str, year: Optional[int]) -> tuple:
    """The order of films and shows in a list: by title ignoring a leading
    The, A or An, then the full title, then year (no year first)."""
    return (title_sort_key(title_without_article(title)), title_sort_key(title), -1 if year is None else year)


def parse_name(name: str, kind: str) -> ParsedName:
    """Parse one file or folder name. Never raises for a bad name."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, got {kind!r}")

    stem = _strip_extension(name)

    season_only = _SEASON_ONLY.match(stem)
    if season_only:
        return ParsedName(
            title="", season=int(season_only.group(1)), raw=name, flags=["season-only"]
        )

    # Advanced mode: every value comes with its position in `stem`.
    matches = {}
    if stem.strip():
        try:
            result = _load_guessit()(stem, {"type": kind, "advanced": True})
            matches = {k: v if isinstance(v, list) else [v] for k, v in result.items()}
        except Exception:
            matches = {}
        matches = _absolute_numbers(stem, matches)

    flags = []

    titles = _values(matches, "title")
    title = _text(titles[:1])
    if title and " " in stem:
        # Only full stops can come back here ("Dr."); case is never changed.
        title, _ = _from_original(stem, matches["title"][0], title, [])
    if title and not any(ch.isalnum() for ch in title):
        # A name made only of symbols: guessit drops some; keep them all.
        title = " ".join(stem.split())
    if not title:
        title = _fallback_title(stem)
        flags.append("fallback")

    episodes = _ints(_values(matches, "episode"))
    multi = _MULTI_EPISODE.search(stem)
    kept = episodes if multi else episodes[:1]

    # A number inside or at the start of an episode title ("The 100 Doors",
    # "511 Example Place") can be read as an extra episode or an invented
    # season. Numbers after the kept episode may join the title instead.
    in_title = []
    episode_title = _text(_values(matches, "episode_title"))
    if episode_title and len(matches["episode_title"]) == 1:
        dropped = [m for m in matches.get("episode", []) if m.value not in kept]
        after = [m for m in matches.get("episode", []) if m.value in kept[:1]]
        first_end = min((m.span[1] for m in after), default=None)
        late_seasons = [
            m for m in matches.get("season", [])
            if first_end is not None and m.span[0] >= first_end
        ]
        spans = [m.span for ms in matches.values() for m in ms]
        episode_title, in_title = _from_original(
            stem, matches["episode_title"][0], episode_title, dropped + late_seasons, spans
        )

    seasons = _ints(
        _unique(m.value for m in matches.get("season", []) if not any(m is x for x in in_title))
    )
    if len(seasons) > 1:
        flags.append("extra-numbers-ignored")

    if len(episodes) > 1 and not multi:
        episodes = episodes[:1]
        if "extra-numbers-ignored" not in flags:
            flags.append("extra-numbers-ignored")

    years = _ints(_values(matches, "year"))

    return ParsedName(
        title=title,
        year=years[0] if years else None,
        season=seasons[0] if seasons else None,
        episode=episodes[0] if episodes else None,
        episodes=episodes,
        episode_title=episode_title,
        raw=name,
        flags=flags,
    )
