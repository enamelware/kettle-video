# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The Movies list's order and letter groups (the Movies list work). Pure logic.

Every film gets a letter group: "#" for a title that starts with a number
or a symbol, "A" to "Z" (an accented letter counts as its plain letter),
or "other" for a title in another alphabet. Latin letters that aren't
accented letters in Unicode's eyes (Ø, Ł, Æ, Đ, ß, Œ, Þ) count as their
nearest plain letter (O, L, A, D, S, O, T), for the group and the order.
The list runs #, A to Z, then other; inside a group, by title ignoring
capitals and accents, then year
(no year first), then ID, so the order never shuffles. A leading "The",
"A" or "An" is ignored for the order and the group (the title sorting work), so "The
Mossbrook" sits under M; equal titles then go by the full title. Rules and reasons:
docs/spec.md ("Movies list") and docs/decisions.md.
"""

import unicodedata
from typing import Optional

from backend.parser import title_sort_key, title_without_article

OTHER = "other"
# The order of the groups on screen.
GROUPS = ("#",) + tuple(chr(c) for c in range(ord("A"), ord("Z") + 1)) + (OTHER,)
_RANK = {group: n for n, group in enumerate(GROUPS)}


# Latin letters that Unicode doesn't split into a plain letter plus an
# accent, and their nearest plain letter (decided on the Movies list work). One letter
# each, so the group and the order agree. Ð (eth) looks like Đ, so it goes
# with it.
_NEAREST_PLAIN = str.maketrans({
    "Ø": "O", "ø": "o", "Ł": "L", "ł": "l", "Æ": "A", "æ": "a",
    "Đ": "D", "đ": "d", "Ð": "D", "ð": "d", "ß": "s", "ẞ": "S",
    "Œ": "O", "œ": "o", "Þ": "T", "þ": "t",
})


def plain_letters(text: str) -> str:
    """`text` with Ø, Ł, Æ, Đ, ß, Œ and Þ swapped for their nearest plain letter."""
    return text.translate(_NEAREST_PLAIN)


def sort_title(title: str) -> str:
    """The part of the title that sorting and grouping look at: without a
    leading The, A or An (the same rule as every other list)."""
    return title_without_article(title)


def letter_group(title: str) -> str:
    """ "#", "A" to "Z", or "other", from the title's first character."""
    text = sort_title(title)
    if not text:
        return "#"
    first = unicodedata.normalize("NFKD", plain_letters(text[0]))[0].upper()
    if "A" <= first <= "Z":
        return first
    if first.isalpha():
        return OTHER
    return "#"


def order_key(title: str, year: Optional[int], item_id: str) -> tuple:
    text = sort_title(title)
    # Ties: the accented spelling ("Orsted" before "Ørsted"), then the full
    # title with its article ("The Thistlecombe" and "Thistlecombe" always the same way round).
    return (_RANK[letter_group(title)], title_sort_key(plain_letters(text)), title_sort_key(text),
            title_sort_key(title), -1 if year is None else year, item_id)


def add_order(saved: list, shown: list) -> list:
    """`shown` (the page's films) in list order, each with "sort_index"
    (its place, from 0) and "letter" added. `saved` are the same films as
    saved, in the same order: their title and year are what is sorted."""
    pairs = sorted(
        zip(saved, shown),
        key=lambda pair: order_key(pair[0]["title"], pair[0]["year"], pair[0]["id"]),
    )
    result = []
    for n, (item, page_item) in enumerate(pairs):
        result.append({**page_item, "sort_index": n, "letter": letter_group(item["title"])})
    return result
