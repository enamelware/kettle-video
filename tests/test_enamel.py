# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The vendored design system, Enamel (the first design system step and the Enamel rename).

Checks: the copies in vendor/enamel/ are byte-for-byte the same as
Enamel's release of the version pinned in ENAMEL_PIN, read from its tag in
Enamel's folder (v0.7.0 for 0.7.0), never from its main branch or
the folder as it is, so newer versions and work in progress never fail
these tests (the finished-version check, the Enamel 0.6.0 upgrade; skipped with a plain reason where that folder
or the tag isn't, e.g. the Nova); the copy's VERSION agrees with the pin,
which holds exactly one tag, and an update moves the pin with the copies; the update script copies a named
version from its tag, never the folder as it is, prints the old and new
version (run on temporary folders, so the tests never change vendor/ or
Enamel), copies what changed and rewrites nothing when nothing
changed; the folder is ~/Development/enamel, or the folder under the
design system's old name when that is the only one (the Enamel rename);
vendor/ holds Enamel only, under its new name; the page links both stylesheets
before its own, then loads the behaviour script (the picker confirm work) before the
app; the server sends those three files, and nothing else under vendor/;
nothing in them or the page's links points online.

Run from the repo root:  python3 -m unittest tests.test_enamel -v
"""

import contextlib
import http.client
import io
import os
import re
import subprocess
import tempfile
import threading
import unittest
from unittest import mock
from html.parser import HTMLParser
from http.server import ThreadingHTTPServer
from pathlib import Path

from backend.server import make_handler
from tools import update_enamel as tool

ROOT = Path(__file__).resolve().parent.parent
UI_DIR = ROOT / "ui"
VENDOR = ROOT / "vendor" / "enamel"
SOURCE = tool.DEFAULT_SOURCE
STYLESHEETS = ["vendor/enamel/tokens/enamel.css", "vendor/enamel/components/enamel-components.css"]
SCRIPT = "vendor/enamel/components/enamel-components.js"  # the picker's behaviour (the picker confirm work)


def git(folder, *args):
    return subprocess.run(["git", "-C", str(folder), *args], capture_output=True, timeout=30)


def recorded_version():
    """The Enamel version the app has adopted: the tag pinned in ENAMEL_PIN."""
    return tool.pinned_version()


def mismatched_files(source):
    """The vendored files that differ from Enamel's release of the recorded version."""
    version = recorded_version()
    return [name for name in tool.FILES
            if (VENDOR / name).read_bytes() != tool.released_file(source, version, name)]


class VendoredFilesTest(unittest.TestCase):
    def test_every_file_is_vendored(self):
        for name in tool.FILES:
            with self.subTest(name=name):
                self.assertTrue((VENDOR / name).is_file(), f"vendor/enamel/{name} is missing")

    def test_copies_match_the_source(self):
        # The Enamel 0.6.0 upgrade: compared with the release tag for the version the app
        # records (v0.7.0), never with Enamel's main or its folder as it is.
        version = recorded_version()
        reason = tool.why_not_released(SOURCE, version)
        if reason:
            self.skipTest(reason)
        for name in tool.FILES:
            with self.subTest(name=name):
                self.assertEqual((VENDOR / name).read_bytes(), tool.released_file(SOURCE, version, name))


    def test_stylesheets_carry_the_vendored_version_and_licence(self):
        version = (VENDOR / "VERSION").read_text().strip()
        self.assertRegex(version, r"^\d+\.\d+\.\d+$")
        for name in ("tokens/enamel.css", "components/enamel-components.css"):
            with self.subTest(name=name):
                head = (VENDOR / name).read_text()[:400]
                self.assertIn(f"version {version}.", head)
                self.assertIn("SPDX-License-Identifier: MIT", head)
        self.assertIn("MIT License", (VENDOR / "LICENSE").read_text())

    def test_listed_in_third_party_licenses(self):
        text = (ROOT / "THIRD_PARTY_LICENSES.md").read_text()
        version = (VENDOR / "VERSION").read_text().strip()
        row = next((line for line in text.splitlines() if line.startswith("| Enamel")), "")
        self.assertIn(version, row)
        self.assertIn("MIT", row)

    def test_licences_list_describes_the_notice(self):
        # The Enamel 0.11.1 upgrade: the licences list follows Enamel's own NOTICE.md, which
        # 0.11.1 reworded; the limit on the names and wordmark must be in both.
        notice = re.sub(r"\s+", " ", (VENDOR / "NOTICE.md").read_text())
        text = re.sub(r"\s+", " ", (ROOT / "THIRD_PARTY_LICENSES.md").read_text())
        for claim in ("grants no rights to the Enamel or Kettle names or the Kettle wordmark",
                      "Steam's Gaming Mode", "no Valve code, class names, icons, logos or fonts"):
            with self.subTest(claim=claim):
                self.assertIn(claim, notice)
                self.assertIn(claim, text)

    def test_the_copy_is_the_pinned_version(self):
        # The pin (ENAMEL_PIN) is the one place the adopted release is
        # recorded; the copy's own VERSION and CLAUDE.md must agree with it.
        self.assertEqual(tool.pinned_tag(), tool.tag_for(recorded_version()))
        self.assertRegex(recorded_version(), r"^\d+\.\d+\.\d+$")
        self.assertEqual((VENDOR / "VERSION").read_text().strip(), recorded_version())
        self.assertIn(f"vendored at {recorded_version()}", (ROOT / "CLAUDE.md").read_text())

    def test_the_spec_names_the_pinned_version(self):
        # The Enamel 0.12.0 upgrade: the spec's brand section and its own section for the
        # bring-in name the adopted release, as CLAUDE.md does.
        spec = (ROOT / "docs" / "spec.md").read_text()
        self.assertIn(f"(vendored at {recorded_version()} since the Enamel {recorded_version()} upgrade", spec)
        self.assertRegex(spec, rf"(?m)^## Design system: Enamel {re.escape(recorded_version())}\b")
        self.assertIn(f"tools/update_enamel.py {recorded_version()}`", spec)

    def test_the_decisions_record_the_pinned_version(self):
        # The Enamel 0.13.1 upgrade: every bring-in is a real decision, so docs/decisions.md
        # has an entry for the adopted release, as the spec has a section.
        decisions = (ROOT / "docs" / "decisions.md").read_text()
        self.assertRegex(
            decisions,
            rf"(?m)^## \d{{4}}-\d{{2}}-\d{{2}} — Bring in Enamel {re.escape(recorded_version())}\b",
        )

    def test_upgrades_are_their_own_issue(self):
        # /next all drafts "Bring in Enamel <version>" for a newer release and
        # never upgrades inside another issue; the reviewer holds the line.
        nxt = (ROOT / ".claude" / "commands" / "next.md").read_text()
        self.assertIn("scripts/peek.sh tag --sort=-version:refname", nxt)
        self.assertIn("Bring in Enamel <version>", nxt)
        self.assertIn("Never upgrade Enamel, or change `ENAMEL_PIN` or `vendor/enamel/`, inside another issue", nxt)
        reviewer = (ROOT / ".claude" / "agents" / "reviewer.md").read_text()
        self.assertIn("`ENAMEL_PIN` and `vendor/enamel/` change only in an issue titled", reviewer)

    def test_only_enamel_is_vendored_under_its_new_name(self):
        # The Enamel rename: vendor/enamel/ replaces the folder under the old name.
        self.assertTrue(VENDOR.is_dir())
        self.assertEqual([p.name for p in (ROOT / "vendor").iterdir() if p.name.startswith("kettle")], [])
        self.assertIn("MIGRATION.md", tool.FILES)

    def test_nothing_points_online(self):
        for name in ("tokens/enamel.css", "components/enamel-components.css"):
            with self.subTest(name=name):
                css = re.sub(r"/\*.*?\*/", "", (VENDOR / name).read_text(), flags=re.S)
                # Since 0.11.0 (the Enamel 0.11.0 upgrade) the speckle is drawn by images written
                # into the file itself (data: URLs), which load nothing. Their
                # SVG names its namespace with an address that is never fetched.
                inline = re.findall(r'url\("data:[^"]*"\)', css)
                for image in inline:
                    self.assertNotRegex(image.replace("http://www.w3.org/2000/svg", ""), r"https?:|//[a-z]")
                css = re.sub(r'url\("data:[^"]*"\)', "", css)
                self.assertNotIn("@import", css)
                self.assertNotIn("url(", css)
                self.assertNotRegex(css, r"https?:|//[a-z]")


class StandIn:
    """A temporary git folder standing in for Enamel."""

    def make_stand_in(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.source = Path(tmp.name) / "enamel"
        self.source.mkdir()
        self.assertEqual(git(self.source, "init", "--quiet", "-b", "main").returncode, 0)

    def write_files(self, files):
        for name, data in files.items():
            (self.source / name).parent.mkdir(parents=True, exist_ok=True)
            (self.source / name).write_bytes(data)

    def commit(self, message, tag=None):
        git(self.source, "add", "-A")
        result = git(self.source, "-c", "user.name=test", "-c", "user.email=test@example.invalid",
                     "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", message)
        self.assertEqual(result.returncode, 0, result.stderr)
        if tag:
            self.assertEqual(git(self.source, "tag", "-f", tag).returncode, 0)

    def state(self):
        """Enamel's branch, status, tags and working files, to prove nothing changed."""
        files = {p.relative_to(self.source): p.read_bytes()
                 for p in self.source.rglob("*") if p.is_file() and ".git" not in p.parts}
        return (git(self.source, "status", "--porcelain", "--branch").stdout,
                git(self.source, "rev-parse", "HEAD").stdout,
                git(self.source, "show-ref").stdout, files)


class RecordedVersionTest(StandIn, unittest.TestCase):
    """The comparison above, on a stand-in where the recorded version is tagged."""

    def setUp(self):
        self.make_stand_in()
        self.tag = tool.tag_for(recorded_version())
        self.write_vendored_copies()
        self.commit("the recorded version", tag=self.tag)

    def write_vendored_copies(self):
        self.write_files({name: (VENDOR / name).read_bytes() for name in tool.FILES})

    def write_newer_version(self):
        self.write_files({"VERSION": b"9.9.9\n", tool.FILES[0]: b"a newer version\n",
                          SCRIPT.removeprefix("vendor/enamel/"): b"a newer script\n"})

    def test_a_newer_version_on_main_is_ignored(self):
        self.write_newer_version()
        self.commit("9.9.9 on main", tag="v9.9.9")
        self.assertEqual(mismatched_files(self.source), [])

    def test_work_in_progress_is_ignored(self):
        git(self.source, "switch", "--quiet", "-c", "issue-1")
        self.write_newer_version()  # unfinished, not committed
        self.assertEqual(mismatched_files(self.source), [])
        self.commit("work in progress on issue-1")
        self.assertEqual(mismatched_files(self.source), [])

    def test_a_difference_from_the_recorded_version_is_caught(self):
        for name in tool.FILES:
            with self.subTest(name=name):
                self.write_vendored_copies()
                (self.source / name).write_bytes(b"not what the app has\n")
                self.commit(f"change {name}", tag=self.tag)  # the tag moves to it
                self.assertEqual(mismatched_files(self.source), [name])

    def test_enamel_is_left_as_it_was(self):
        git(self.source, "switch", "--quiet", "-c", "issue-1")
        (self.source / "VERSION").write_text("9.9.9\n")
        before = self.state()
        mismatched_files(self.source)
        self.run_real_check(self.source)
        self.assertEqual(self.state(), before)

    def test_skipped_with_a_plain_reason(self):
        version = recorded_version()
        self.assertIsNone(tool.why_not_released(self.source, version))
        self.assertIn("isn't on this device", tool.why_not_released(self.source / "nowhere", version))
        plain = self.source.parent / "plain"
        plain.mkdir()
        self.assertIn("isn't a git folder", tool.why_not_released(plain, version))
        git(self.source, "tag", "-d", self.tag)
        self.assertIn(f"has no tag {self.tag}", tool.why_not_released(self.source, version))

    def test_a_branch_named_like_the_tag_doesnt_count(self):
        git(self.source, "tag", "-d", self.tag)
        git(self.source, "branch", self.tag)
        self.assertIn(f"has no tag {self.tag}", tool.why_not_released(self.source, recorded_version()))

    # The real check itself (test_copies_match_the_source), pointed at the
    # stand-in, so the tests above can't pass while the real check still reads
    # Enamel's main or its folder as it is.
    def run_real_check(self, source):
        result = unittest.TestResult()
        with mock.patch.dict(globals(), {"SOURCE": source}):
            VendoredFilesTest("test_copies_match_the_source").run(result)
        return result

    def assert_passes(self, result):
        self.assertEqual((result.failures, result.errors, result.skipped), ([], [], []))

    def test_the_real_check_ignores_a_newer_version_and_work_in_progress(self):
        self.write_newer_version()
        self.commit("9.9.9 on main", tag="v9.9.9")
        self.assert_passes(self.run_real_check(self.source))
        git(self.source, "switch", "--quiet", "-c", "issue-1")
        (self.source / "DESIGN.md").write_text("half done\n")
        self.assert_passes(self.run_real_check(self.source))

    def test_the_real_check_catches_a_difference_in_the_tag(self):
        (self.source / SCRIPT.removeprefix("vendor/enamel/")).write_text("not what the app has\n")
        self.commit("change the behaviour script", tag=self.tag)
        self.write_vendored_copies()  # the folder itself matches; only the tag differs
        self.commit("main matches the app again")
        result = self.run_real_check(self.source)
        self.assertEqual(len(result.failures), 1)
        self.assertEqual(result.skipped, [])

    def test_the_real_check_is_skipped_with_a_plain_reason(self):
        plain = self.source.parent / "plain"
        plain.mkdir()
        for source, reason in ((self.source / "nowhere", "isn't on this device"),
                               (plain, "isn't a git folder")):
            with self.subTest(reason=reason):
                result = self.run_real_check(source)
                self.assertEqual(len(result.skipped), 1)
                self.assertIn(reason, result.skipped[0][1])
        git(self.source, "tag", "-d", self.tag)
        result = self.run_real_check(self.source)
        self.assertEqual(len(result.skipped), 1)
        self.assertIn(f"has no tag {self.tag}", result.skipped[0][1])


class SourceFolderTest(unittest.TestCase):
    """The Enamel rename: the folder is Enamel's own name first, then the old one."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.new, self.old = Path(tmp.name) / "enamel", Path(tmp.name) / "old-name"

    def test_the_candidates_are_enamel_then_the_old_name(self):
        self.assertEqual([p.name for p in tool.SOURCE_CANDIDATES][0], "enamel")
        self.assertEqual(len(tool.SOURCE_CANDIDATES), 2)
        self.assertEqual({p.parent for p in tool.SOURCE_CANDIDATES}, {Path.home() / "Development"})

    def test_enamel_comes_first_when_both_exist(self):
        self.new.mkdir()
        self.old.mkdir()
        self.assertEqual(tool.default_source((self.new, self.old)), self.new)

    def test_the_old_name_when_enamel_is_missing(self):
        self.old.mkdir()
        self.assertEqual(tool.default_source((self.new, self.old)), self.old)

    def test_enamel_when_neither_exists(self):
        self.assertEqual(tool.default_source((self.new, self.old)), self.new)


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stylesheets = []
        self.order = []  # every stylesheet and script, in page order

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "link" and attrs.get("rel") == "stylesheet":
            self.stylesheets.append(attrs["href"])
            self.order.append(attrs["href"])
        if tag == "script":
            self.order.append((attrs.get("src"), attrs.get("type")))


class PageLinksTest(unittest.TestCase):
    def test_both_stylesheets_load_first(self):
        parser = _Links()
        parser.feed((UI_DIR / "index.html").read_text())
        self.assertEqual(parser.stylesheets[:2], STYLESHEETS)
        self.assertEqual(parser.stylesheets[2:], ["css/tokens.css", "css/defaults.css"])
        for href in parser.stylesheets:
            self.assertNotRegex(href, r"^(https?:)?//")

    def test_script_loads_after_the_stylesheets_and_before_the_app(self):
        # The picker confirm work: a plain (not module) script, so it has run before the
        # app's module starts, and the page asks for it locally.
        parser = _Links()
        parser.feed((UI_DIR / "index.html").read_text())
        self.assertEqual(parser.order, [*STYLESHEETS, "css/tokens.css", "css/defaults.css",
                                        (SCRIPT, None), ("js/app.js", "module")])


class UpdateScriptTest(StandIn, unittest.TestCase):
    """The tool on a stand-in Enamel and a temporary vendor folder (the vendor copy test fix)."""

    def setUp(self):
        self.make_stand_in()
        self.vendor = self.source.parent / "vendor"
        self.pin = self.source.parent / "ENAMEL_PIN"
        self.write_version("1.0.0")
        self.commit("1.0.0", tag="v1.0.0")

    def write_version(self, version, only=None):
        self.write_files({name: (f"{version}\n" if name == "VERSION" else f"{name} {version}\n").encode()
                          for name in tool.FILES if only is None or name in (only, "VERSION")})

    def released(self, version):
        return {name: tool.released_file(self.source, version, name) for name in tool.FILES}

    def vendored(self):
        return {name: (self.vendor / name).read_bytes() for name in tool.FILES}

    def test_copies_everything_the_first_time(self):
        self.assertEqual(tool.update(self.source, "1.0.0", self.vendor), list(tool.FILES))
        self.assertEqual(self.vendored(), self.released("1.0.0"))

    def test_copies_the_named_version_not_the_folder_as_it_is(self):
        self.write_version("1.1.0")
        self.commit("1.1.0", tag="v1.1.0")
        self.write_version("2.0.0")  # work in progress, not committed
        tool.update(self.source, "1.0.0", self.vendor)
        self.assertEqual(self.vendored(), self.released("1.0.0"))
        self.assertEqual(tool.read_version(self.vendor), "1.0.0")
        tool.update(self.source, "1.1.0", self.vendor)
        self.assertEqual(self.vendored(), self.released("1.1.0"))

    def test_never_copies_main(self):
        self.write_version("1.1.0")
        self.commit("1.1.0 on main, not tagged")
        with self.assertRaises(FileNotFoundError) as caught:
            tool.update(self.source, "1.1.0", self.vendor)
        self.assertIn("has no tag v1.1.0", str(caught.exception))
        self.assertFalse(self.vendor.exists())

    def test_enamel_is_left_as_it_was(self):
        self.write_version("1.1.0")
        self.commit("1.1.0", tag="v1.1.0")
        git(self.source, "switch", "--quiet", "-c", "issue-1")
        self.write_version("2.0.0")
        before = self.state()
        tool.update(self.source, "1.0.0", self.vendor)
        self.assertEqual(self.state(), before)

    def test_leaves_the_copies_untouched_when_nothing_changed(self):
        tool.update(self.source, "1.0.0", self.vendor)
        for name in tool.FILES:
            os.utime(self.vendor / name, ns=(1, 1))
        self.assertEqual(tool.update(self.source, "1.0.0", self.vendor), [])
        for name in tool.FILES:
            self.assertEqual((self.vendor / name).stat().st_mtime_ns, 1, name)

    def test_copies_only_what_changed(self):
        tool.update(self.source, "1.0.0", self.vendor)
        self.write_files({"VERSION": b"1.1.0\n"})
        self.commit("1.1.0", tag="v1.1.0")
        self.assertEqual(tool.update(self.source, "1.1.0", self.vendor), ["VERSION"])
        self.assertEqual(tool.read_version(self.vendor), "1.1.0")

    def test_a_missing_file_in_the_release_copies_nothing(self):
        git(self.source, "rm", "--quiet", "DESIGN.md")
        self.write_files({"VERSION": b"1.1.0\n"})
        self.commit("1.1.0 without DESIGN.md", tag="v1.1.0")
        with self.assertRaises(FileNotFoundError):
            tool.update(self.source, "1.1.0", self.vendor)
        self.assertFalse(self.vendor.exists())

    def test_a_tag_whose_version_file_disagrees_copies_nothing(self):
        git(self.source, "tag", "v1.2.0")  # points at 1.0.0's files
        with self.assertRaises(FileNotFoundError) as caught:
            tool.update(self.source, "1.2.0", self.vendor)
        self.assertIn("doesn't say version 1.2.0", str(caught.exception))
        self.assertFalse(self.vendor.exists())

    def run_main(self, *args, code=0):
        """Run the script on the temporary folders only (the vendor copy test fix)."""
        # update()'s default target is fixed when the tool loads, so both it
        # and VENDOR_DIR are pointed at the temporary vendor folder.
        update = tool.update
        out, err = io.StringIO(), io.StringIO()
        with (
            mock.patch.object(tool, "VENDOR_DIR", self.vendor),
            mock.patch.object(tool, "PIN_FILE", self.pin),
            mock.patch.object(tool, "update", lambda source, version: update(source, version, self.vendor)),
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
        ):
            self.assertEqual(tool.main(["update_enamel.py", *args]), code)
        return out.getvalue() + err.getvalue()

    def test_prints_old_and_new_version(self):
        before = {name: (VENDOR / name).read_bytes() for name in tool.FILES}
        real_pin = tool.PIN_FILE.read_bytes()
        first = self.run_main("1.0.0", str(self.source))
        self.assertIn("Old version: none", first)
        self.assertIn("New version: 1.0.0", first)
        self.write_files({"VERSION": b"1.1.0\n"})
        self.commit("1.1.0", tag="v1.1.0")
        out = self.run_main("1.1.0", str(self.source))
        self.assertIn("Old version: 1.0.0", out)
        self.assertIn("New version: 1.1.0", out)
        self.assertIn("Copied: VERSION", out)
        same = self.run_main("1.1.0", str(self.source))
        self.assertIn("Old version: 1.1.0", same)
        self.assertIn("New version: 1.1.0", same)
        self.assertIn("Nothing changed", same)
        # The real vendor/enamel/ and the real pin are never touched by the tests.
        self.assertEqual({name: (VENDOR / name).read_bytes() for name in tool.FILES}, before)
        self.assertEqual(tool.PIN_FILE.read_bytes(), real_pin)

    def test_an_update_moves_the_pin_with_the_copies(self):
        self.pin.write_text("# a comment that stays\nv0.9.0\n")
        out = self.run_main("1.0.0", str(self.source))
        self.assertIn("Pinned in ENAMEL_PIN: v1.0.0", out)
        self.assertEqual(self.pin.read_text(), "# a comment that stays\nv1.0.0\n")
        self.assertEqual(tool.pinned_version(self.pin), "1.0.0")

    def test_a_failed_update_leaves_the_pin_alone(self):
        self.pin.write_text("v0.9.0\n")
        self.run_main("3.0.0", str(self.source), code=1)
        self.assertEqual(self.pin.read_text(), "v0.9.0\n")

    def test_the_pin_holds_exactly_one_tag(self):
        for text in ("# only a comment\n", "v1.0.0\nv1.1.0\n", "1.0.0\n"):
            with self.subTest(text=text):
                self.pin.write_text(text)
                with self.assertRaises(ValueError):
                    tool.pinned_tag(self.pin)

    def test_the_version_must_be_named(self):
        self.assertIn("Usage:", self.run_main(code=2))
        self.assertFalse(self.vendor.exists())

    def test_problems_are_reported_plainly(self):
        plain = self.source.parent / "plain"
        plain.mkdir()
        for args, reason in (((("1.0.0", str(self.source.parent / "nowhere"))), "isn't on this device"),
                             (("1.0.0", str(plain)), "isn't a git folder"),
                             (("3.0.0", str(self.source)), "has no tag v3.0.0")):
            with self.subTest(reason=reason):
                out = self.run_main(*args, code=1)
                self.assertIn("Couldn't update Enamel", out)
                self.assertIn(reason, out)
        self.assertFalse(self.vendor.exists())


class ServerTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        logs = Path(tmp.name)
        settings = {"movies_path": tmp.name, "tv_path": tmp.name, "mpv_command": "mpv", "mpv_args": []}
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        self.port = self.httpd.server_address[1]
        with contextlib.redirect_stdout(io.StringIO()):
            base = make_handler(UI_DIR, logs, settings, {}, self.port)

        class Quiet(base):
            def log_message(self, format, *args):
                pass

        self.httpd.RequestHandlerClass = Quiet
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("GET", path)
        response = conn.getresponse()
        body = response.read()
        conn.close()
        return response, body

    def test_serves_both_stylesheets(self):
        for href in STYLESHEETS:
            with self.subTest(href=href):
                response, body = self.get("/" + href)
                self.assertEqual(response.status, 200)
                self.assertTrue(response.getheader("Content-Type").startswith("text/css"))
                self.assertEqual(body, (ROOT / href).read_bytes())

    def test_serves_the_behaviour_script(self):
        response, body = self.get("/" + SCRIPT)
        self.assertEqual(response.status, 200)
        self.assertTrue(response.getheader("Content-Type").startswith("text/javascript"))
        self.assertEqual(body, (ROOT / SCRIPT).read_bytes())

    def test_nothing_else_under_vendor(self):
        for path in (
            "/vendor/enamel/DESIGN.md",
            "/vendor/enamel/VERSION",
            "/vendor/enamel/components/enamel-components.min.js",
            "/vendor/enamel/components/",
            "/vendor/enamel/../../settings.json",
            "/vendor/enamel/%2e%2e/%2e%2e/settings.json",
            "/vendor/six.py",
        ):
            with self.subTest(path=path):
                response, _ = self.get(path)
                self.assertEqual(response.status, 404)


if __name__ == "__main__":
    unittest.main()
