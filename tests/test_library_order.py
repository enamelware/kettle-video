# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The Movies list's order and letter groups (the Movies list work), with invented
titles: capitals and accents ignored, letter groups (#, A to Z, other),
equal titles by year then ID, the page's answer keeping every field and
adding two, films played by ID, and the developer-only invented films.
The title sorting work: a leading The, A or An ignored for the order and the groups,
on the Movies and TV Shows tabs.

Run from the repo root:  python3 -m unittest discover -s tests -t . -v
"""

import contextlib
import http.client
import io
import json
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from backend import library_index, library_order, movie_fixture, mpv
from backend.parser import library_order as library_order_key
from backend.parser import title_without_article
from backend.server import make_handler
from tests.test_library_index import make_folders
from tests.test_parsed_library import _strings

UI_DIR = Path(__file__).resolve().parent.parent / "ui"


def film(title, year=None, item_id=None, parts=1):
    key = item_id or f"{title} {year}"
    return {"id": item_id or library_index.item_id("movies", key), "key": key, "title": title, "year": year,
            "parts": [{"label": f"Part {n + 1}" if parts > 1 else None, "path": f"{key}/{n}.mkv"}
                      for n in range(parts)],
            "flags": []}


def ordered_titles(items):
    return [i["display_title"] for i in library_index.render_movies(items)]


class LetterGroupTest(unittest.TestCase):
    def test_latin_title(self):
        self.assertEqual(library_order.letter_group("Example Night"), "E")
        self.assertEqual(library_order.letter_group("example night"), "E")

    def test_number(self):
        self.assertEqual(library_order.letter_group("1984 Example"), "#")

    def test_symbol(self):
        for title in ("#Example", "...Example", "[Example]", "~Example", "¡Example!"):
            with self.subTest(title=title):
                self.assertEqual(library_order.letter_group(title), "#")

    def test_accented_letter_counts_as_its_plain_letter(self):
        self.assertEqual(library_order.letter_group("Émile Example"), "E")
        self.assertEqual(library_order.letter_group("ángel example"), "A")
        self.assertEqual(library_order.letter_group("Zoë"), "Z")

    def test_latin_letters_count_as_their_nearest_plain_letter(self):
        cases = {"Ørsted": "O", "øresund": "O", "Łódź": "L", "łąka": "L", "Æble": "A", "æon": "A",
                 "Đakovo": "D", "đak": "D", "Ðoor": "D", "ßeta": "S", "Œuvre": "O", "œil": "O",
                 "Þór": "T", "þing": "T"}
        for title, group in cases.items():
            with self.subTest(title=title):
                self.assertEqual(library_order.letter_group(title), group)

    def test_another_alphabet_is_other(self):
        for title in ("Город Example", "東京 Example", "Ελλάδα"):
            with self.subTest(title=title):
                self.assertEqual(library_order.letter_group(title), "other")

    def test_empty_title_is_hash(self):
        self.assertEqual(library_order.letter_group(""), "#")

    def test_group_order_is_hash_a_to_z_then_other(self):
        self.assertEqual(library_order.GROUPS, ("#", *"ABCDEFGHIJKLMNOPQRSTUVWXYZ", "other"))


class OrderTest(unittest.TestCase):
    def test_capitals_and_accents_are_ignored(self):
        titles = ordered_titles([film("Fjord"), film("emile"), film("Émile Two"), film("Ember"), film("EMILE ONE")])
        self.assertEqual(titles, ["Ember", "emile", "EMILE ONE", "Émile Two", "Fjord"])

    def test_emile_sits_with_emile(self):
        titles = ordered_titles([film("Émile", 2001), film("Example"), film("emile", 1999), film("Eagle")])
        self.assertEqual(titles, ["Eagle", "emile (1999)", "Émile (2001)", "Example"])

    def test_groups_run_hash_a_to_z_then_other(self):
        titles = ordered_titles([film("Город"), film("Zephyrine"), film("~Tilde"), film("Alpha"), film("12 Example"),
                                 film("Émile"), film("東京")])
        self.assertEqual(titles, ["12 Example", "~Tilde", "Alpha", "Émile", "Zephyrine", "Город", "東京"])

    def test_latin_letters_sort_as_their_nearest_plain_letter(self):
        titles = ordered_titles([film("Oslo"), film("Ørsted"), film("Ozone"), film("Lyon"), film("Łódź"),
                                 film("Lutz"), film("Afar"), film("Adam"), film("Æble"), film("Bjørn"),
                                 film("Bjorg"), film("Bjorz"), film("Straße"), film("Strasx"), film("Strase")])
        self.assertEqual(titles, ["Æble", "Adam", "Afar", "Bjorg", "Bjørn", "Bjorz", "Łódź", "Lutz", "Lyon",
                                  "Ørsted", "Oslo", "Ozone", "Strase", "Straße", "Strasx"])

    def test_plain_title_before_its_lookalike(self):
        shown = library_index.render_movies([film("Ørsted", None, "a"), film("Orsted", None, "b")])
        self.assertEqual([i["display_title"] for i in shown], ["Orsted", "Ørsted"])
        self.assertEqual([i["letter"] for i in shown], ["O", "O"])

    def test_equal_titles_by_year_then_id(self):
        items = [film("Same", 2010, "c"), film("Same", 2001, "b"), film("Same", None, "z"), film("Same", 2001, "a")]
        shown = library_index.render_movies(items)
        self.assertEqual([i["id"] for i in shown], ["z", "a", "b", "c"])
        # The same whatever order they come in.
        self.assertEqual([i["id"] for i in library_index.render_movies(items[::-1])], ["z", "a", "b", "c"])

    def test_sort_index_counts_from_zero_in_list_order(self):
        shown = library_index.render_movies([film("Bravo"), film("Alpha"), film("Charlie")])
        self.assertEqual([(i["sort_index"], i["letter"]) for i in shown], [(0, "A"), (1, "B"), (2, "C")])


class ArticleTest(unittest.TestCase):
    """The title sorting work: a leading English The, A or An is ignored, once."""

    def test_examples_from_the_issue(self):
        cases = {"The Mossbrook": "M", "A Burrow's Tale": "B", "An Emberfall": "E", "The": "T", "A": "A",
                 "A.B. Example Machine": "A", "Theatre of Example": "T", "Thelwick": "T",
                 "The 37 Lanterns": "#", "The The": "T", "Anna": "A", "Another Example": "A",
                 "THE MOSSBROOK": "M", "the mossbrook": "M", "  The Mossbrook": "M", "The  Mossbrook": "M"}
        for title, group in cases.items():
            with self.subTest(title=title):
                self.assertEqual(library_order.letter_group(title), group)

    def test_title_without_article(self):
        cases = {"The Mossbrook": "Mossbrook", "A Burrow's Tale": "Burrow's Tale", "An Emberfall": "Emberfall",
                 "The": "The", "A": "A", "The The": "The", "A.B. Example Machine": "A.B. Example Machine",
                 "Thelwick": "Thelwick", "The 37 Lanterns": "37 Lanterns", "The ...": "The ...", "An ": "An",
                 "The Émile": "Émile"}
        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assertEqual(title_without_article(title), expected)

    def test_english_only(self):
        for title in ("Le Example", "La Example", "El Example", "Der Example", "Die Example", "Il Example", "Les Example"):
            with self.subTest(title=title):
                self.assertEqual(library_order.letter_group(title), title[0])
                self.assertEqual(title_without_article(title), title)

    def test_order_follows_the_word_after_the_article(self):
        titles = ordered_titles([film("The Mossbrook"), film("Thelwick"), film("Mango"), film("A Burrow's Tale"),
                                 film("Theatre of Example"), film("An Emberfall"), film("Bravo"), film("Echo"),
                                 film("The 37 Lanterns"), film("The"), film("A"), film("The The"), film("Zephyrine")])
        self.assertEqual(titles, ["The 37 Lanterns", "A", "Bravo", "A Burrow's Tale", "Echo", "An Emberfall",
                                  "Mango", "The Mossbrook", "The", "The The", "Theatre of Example", "Thelwick", "Zephyrine"])

    def test_capitals_and_accents_still_fold(self):
        titles = ordered_titles([film("Emma"), film("The Émile"), film("Emilf"), film("emild")])
        self.assertEqual(titles, ["emild", "The Émile", "Emilf", "Emma"])
        self.assertEqual(library_order.letter_group("The Émile"), "E")
        self.assertEqual(library_order.letter_group("The Ørsted"), "O")

    def test_letter_and_index_follow_the_new_order(self):
        shown = library_index.render_movies([film("The Mossbrook"), film("Mango"), film("Tango")])
        self.assertEqual([(i["display_title"], i["sort_index"], i["letter"]) for i in shown],
                         [("Mango", 0, "M"), ("The Mossbrook", 1, "M"), ("Tango", 2, "T")])

    def test_ties_by_full_title_then_year_then_id(self):
        items = [film("Thistlecombe", None, "a"), film("The Thistlecombe", None, "b"), film("The Thistlecombe", 1982, "d"),
                 film("The Thistlecombe", 1982, "c")]
        expected = ["b", "c", "d", "a"]
        self.assertEqual([i["id"] for i in library_index.render_movies(items)], expected)
        self.assertEqual([i["id"] for i in library_index.render_movies(items[::-1])], expected)

    def test_display_title_and_fields_unchanged(self):
        item = film("The Mossbrook", 1999)
        before = library_index._render_movie(item)
        after = library_index.render_movies([item])[0]
        self.assertEqual(before["display_title"], "The Mossbrook (1999)")
        self.assertEqual(set(after) - set(before), {"sort_index", "letter"})
        self.assertEqual({k: after[k] for k in before}, before)

    def test_shows_use_the_same_rule_even_from_an_older_saved_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            roots = {"movies": str(Path(tmp, "Movies")), "tv": str(Path(tmp, "TV Shows"))}
            Path(roots["movies"]).mkdir()
            for show in ("The Oakhollow", "Nature Example", "Parks Example", "Thelwick Show"):
                path = Path(roots["tv"], show, "Season 1", f"{show} S01E01.mkv")
                path.parent.mkdir(parents=True)
                path.write_bytes(b"x")
            with contextlib.redirect_stdout(io.StringIO()):
                index = library_index.full_scan(roots, None, lambda done, total: None)
            expected = ["Nature Example", "The Oakhollow", "Parks Example", "Thelwick Show"]
            self.assertEqual([i["title"] for i in index["sources"]["tv"]["items"]], expected)
            # A library saved before the title sorting work had another order; the page still gets the new one.
            index["sources"]["tv"]["items"].reverse()
            answer = library_index.render(index, roots)
        self.assertEqual([s["display_title"] for s in answer["tv"]["items"]], expected)
        for show in answer["tv"]["items"]:
            self.assertNotIn("sort_index", show)
            self.assertNotIn("letter", show)

    def test_identical_shows_by_id_whatever_order_they_arrive_in(self):
        def show(item_id, title="The Oakhollow", year=2005):
            return {"id": item_id, "title": title, "year": year, "path": f"{item_id}", "seasons": []}

        items = [show("c"), show("a"), show("b", "Oakhollow", 2005), show("d", "The Oakhollow", None), show("e")]
        expected = ["b", "d", "a", "c", "e"]  # "oakhollow" before "the oakhollow", then no year first
        for arrived in (items, items[::-1], items[2:] + items[:2]):
            index = {"sources": {"tv": {"root": "/tv", "items": list(arrived)}}}
            answer = library_index.render(index, {"movies": "/movies", "tv": "/tv"})
            self.assertEqual([i["id"] for i in answer["tv"]["items"]], expected)

    def test_shows_and_films_share_the_rule(self):
        self.assertEqual(sorted(["The Oakhollow", "Parks", "Nature"], key=lambda t: library_order_key(t, None)),
                         ["Nature", "The Oakhollow", "Parks"])
        self.assertLess(library_order_key("The Thistlecombe", None), library_order_key("Thistlecombe", None))
        self.assertLess(library_order_key("The Thistlecombe", None), library_order_key("The Thistlecombe", 1982))


class AnswerTest(unittest.TestCase):
    def test_every_existing_field_kept_and_two_added(self):
        item = film("Example", 2001, parts=2)
        before = library_index._render_movie(item)
        after = library_index.render_movies([item])[0]
        self.assertEqual(set(after) - set(before), {"sort_index", "letter"})
        self.assertEqual({k: after[k] for k in before}, before)

    def test_shows_are_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            roots = make_folders(Path(tmp))
            with contextlib.redirect_stdout(io.StringIO()):
                index = library_index.full_scan(roots, None, lambda done, total: None)
            answer = library_index.render(index, roots)
        for show in answer["tv"]["items"]:
            self.assertNotIn("sort_index", show)
            self.assertNotIn("letter", show)
        self.assertTrue(all("letter" in m for m in answer["movies"]["items"]))

    def test_play_path_for_an_id(self):
        item = film("Example", 2001, parts=2)
        item["parts"][0]["status"] = "missing"
        index = {"sources": {"movies": {"root": "/r", "items": [item]}}}
        self.assertEqual(library_index.movie_play_path(index, "/r", item["id"]), item["parts"][1]["path"])
        self.assertIsNone(library_index.movie_play_path(index, "/r", "nope"))
        self.assertIsNone(library_index.movie_play_path(index, "/other", item["id"]))
        self.assertIsNone(library_index.movie_play_path(None, "/r", item["id"]))


class FixtureTest(unittest.TestCase):
    def test_invented_films_are_the_same_each_time_and_cover_every_kind(self):
        first = movie_fixture.invented_movies(2000)
        self.assertEqual(first, movie_fixture.invented_movies(2000))
        self.assertEqual(len(first), 2000)
        shown = library_index.render_movies(first)
        letters = {i["letter"] for i in shown}
        self.assertTrue({"#", "other", "E", "Z"} <= letters)
        # "Ørsted" titles are under O, never "other" (decided on the Movies list work).
        orsted = [i for i in shown if i["display_title"].startswith("Ørsted")]
        self.assertTrue(orsted)
        self.assertTrue(all(i["letter"] == "O" for i in orsted))
        self.assertTrue(any(i["subtitle"] == "2 parts" for i in shown))
        self.assertTrue(any(i["missing"] for i in shown))
        self.assertTrue(any(len(i["display_title"]) > 60 for i in shown))
        # About a third start with The, A or An (the title sorting work), grouped by the next word.
        articled = [i for i in shown if i["display_title"].split(" ", 1)[0] in ("The", "A", "An")]
        self.assertTrue(600 <= len(articled) <= 734, len(articled))
        self.assertTrue(all(i["letter"] == library_order.letter_group(title_without_article(i["display_title"]))
                            for i in articled))

    def test_ordering_2000_films_is_quick(self):
        items = movie_fixture.invented_movies(2000)
        began = time.perf_counter()
        library_index.render_movies(items)
        self.assertLess(time.perf_counter() - began, 1.0)


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.roots = make_folders(self.root)
        settings = {"movies_path": self.roots["movies"], "tv_path": self.roots["tv"], "mpv_command": "mpv",
                    "mpv_args": [], "resume": True, "keep_awake": False, "data_dir": str(self.root / "data")}
        self.settings = settings
        logs = self.root / "logs"
        logs.mkdir()
        httpd_ref = {}
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        self.port = self.httpd.server_address[1]
        self.out = io.StringIO()
        with contextlib.redirect_stdout(self.out):
            self.httpd.RequestHandlerClass = make_handler(UI_DIR, logs, settings, httpd_ref, self.port)
        self.httpd.RequestHandlerClass.log_message = lambda *args: None
        httpd_ref["server"] = self.httpd
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def request(self, method, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        conn.request(method, path, body=json.dumps(body if body is not None else {}) if method == "POST" else None,
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        data = json.loads(resp.read().decode("utf-8"))
        conn.close()
        return resp.status, data

    def scan(self):
        with contextlib.redirect_stdout(self.out):
            self.request("POST", "/api/library/scan")
            end = time.time() + 30
            while self.request("GET", "/api/library/scan/status")[1]["state"] != "idle":
                if time.time() > end:
                    self.fail("scan did not finish")
                time.sleep(0.05)

    def test_films_come_in_order_with_their_groups_and_no_full_path(self):
        self.scan()
        answer = self.request("GET", "/api/library/parsed")[1]
        films = answer["movies"]["items"]
        self.assertEqual([f["sort_index"] for f in films], list(range(len(films))))
        ranks = [library_order.GROUPS.index(f["letter"]) for f in films]
        self.assertEqual(ranks, sorted(ranks))
        self.assertNotIn(self.tmp.name, json.dumps(answer))
        for value in _strings(answer):
            self.assertFalse(value.startswith("/"), value)

    def test_a_film_plays_by_its_id(self):
        self.scan()
        films = self.request("GET", "/api/library/parsed")[1]["movies"]["items"]
        target = films[0]
        played = []
        found = {"available": True, "command": ["mpv"], "via": "configured"}
        with mock.patch.object(mpv, "detect", return_value=found), \
                mock.patch.object(mpv, "play", side_effect=lambda cmd, path, *a: played.append(path) or {"ok": True}):
            code, answer = self.request("POST", "/api/play", {"source": "movies", "id": target["id"]})
            self.assertEqual((code, answer), (200, {"started": True, "keep_awake": False}))
            end = time.time() + 5
            while not played and time.time() < end:
                time.sleep(0.02)
            code, answer = self.request("POST", "/api/play", {"source": "movies", "id": "not-an-id"})
        self.assertEqual(played, [Path(self.roots["movies"], target["parts"][0]["path"]).resolve()])
        self.assertEqual((code, answer), (400, {"error": "file not found"}))

    def test_kettles_title_reaches_the_player(self):
        # The playback controls work (the designer's choice A): D-pad Up in mpv shows Kettle's title.
        self._check_title_reaches_the_player()

    def test_kettles_title_reaches_the_player_with_resume_off(self):
        # The title doesn't depend on Resume / Continue watching being on.
        self.settings["resume"] = False
        self._check_title_reaches_the_player()

    def _check_title_reaches_the_player(self):
        self.scan()
        target = self.request("GET", "/api/library/parsed")[1]["movies"]["items"][0]
        titles = []
        found = {"available": True, "command": ["mpv"], "via": "configured"}

        def fake_play(*args, **kwargs):
            titles.append(kwargs.get("title", args[8] if len(args) > 8 else None))
            return {"ok": True}

        with mock.patch.object(mpv, "detect", return_value=found), \
                mock.patch.object(mpv, "play", side_effect=fake_play):
            self.request("POST", "/api/play", {"source": "movies", "id": target["id"]})
            end = time.time() + 5
            while not titles and time.time() < end:
                time.sleep(0.02)
        self.assertEqual(len(titles), 1)
        self.assertIsNotNone(titles[0], "no title was handed to mpv")
        # The list's own wording ("Title (Year)"), then " · Part 1" for a split film.
        self.assertTrue(titles[0].startswith(target["display_title"]), (titles, target["display_title"]))
        self.assertNotIn("/", titles[0])

    def test_fixture_switch_is_off_unless_asked(self):
        self.scan()
        real = self.request("GET", "/api/library/parsed")[1]
        invented = self.request("GET", "/api/library/parsed?fixture=2000")[1]
        self.assertEqual(len(invented["movies"]["items"]), 2000)
        self.assertEqual(invented["tv"], real["tv"])
        self.assertLess(len(real["movies"]["items"]), 2000)
        for bad in ("abc", "0", "999999", ""):
            with self.subTest(fixture=bad):
                answer = self.request("GET", f"/api/library/parsed?fixture={bad}")[1]
                self.assertEqual(answer["movies"], real["movies"])
        # The real answer afterwards is still the real one.
        self.assertEqual(self.request("GET", "/api/library/parsed")[1]["movies"], real["movies"])


if __name__ == "__main__":
    unittest.main()
