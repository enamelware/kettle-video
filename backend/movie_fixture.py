# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Invented films for measuring the Movies list (the Movies list work). Developer only.

The page asks for them with ?fixture=2000 in its address; nothing else ever
uses them. They go through the same order and letter groups as the real
library, and their IDs are not in the saved library, so they can't play.
See docs/spec.md ("Movies list").
"""

import random

from backend import library_index

MAX_COUNT = 5000

_WORDS = (
    "Example Night Return Silent River Glass House Last Summer Winter Garden "
    "Stranger Machine Long Road Distant Shore Paper Moon Iron Crown Hidden "
    "Valley Broken Signal Golden Hour Empty City Second Chance Midnight Train"
).split()
# Starts that exercise every kind of letter group.
_ARTICLES = ("The", "A", "An")
_STARTS = ["", "", "", "", "", "", "Émile", "Ørsted", "12", "1984", "#", "...", "Город", "東京", "Ángel", "Zoë"]


def invented_movies(count: int) -> list:
    """`count` saved-library films with invented names: always the same
    ones for the same count. Some titles are long, some films have parts,
    a few are missing, and a third start with The, A or An."""
    rng = random.Random(count)
    items = []
    for n in range(count):
        words = [rng.choice(_WORDS) for _ in range(rng.choice((1, 2, 2, 3, 3, 4, 12, 45)))]
        start = rng.choice(_STARTS)
        title = " ".join([start] + words if start else words)
        if n % 3 == 0:
            # A third start with The, A or An (the title sorting work).
            title = f"{_ARTICLES[n % 9 // 3]} {title}"
        year = rng.choice((None, *range(1950, 2026)))
        key = f"Invented {n:05d}"
        part_count = 2 if n % 17 == 0 else 1
        parts = [
            {"label": f"Part {p + 1}" if part_count > 1 else None, "path": f"{key}/part{p + 1}.mkv"}
            for p in range(part_count)
        ]
        item = {"id": library_index.item_id("fixture", key), "key": key, "title": title,
                "year": year, "parts": parts, "flags": []}
        if n % 41 == 0:
            item["status"] = "missing"
        items.append(item)
    return items


def with_invented_movies(answer: dict, count: int) -> dict:
    """The page's answer with its films replaced by `count` invented ones."""
    movies = {"status": "ok", "has_library": True, "available": True, "scanned_at": None,
              "items": library_index.render_movies(invented_movies(count))}
    return {**answer, "movies": movies}
