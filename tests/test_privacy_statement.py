# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The README's Privacy section stays true of the code (the bug report form work).

The Privacy section is a promise: Kettle Video never goes online by itself,
and the only connections are the actions the viewer chooses in Settings ›
About (Check for updates, then Update and restart; on a development copy,
the same check and Pull the latest version through git), the one-file
installer once the viewer opens it and says yes, and the installer's
Flathub step for mpv, after a yes.

These tests read the code itself, so they fail the moment that changes:

  - every way online in the code that runs with the app (the backend, the
    vendored Python libraries, the installer's shared update step, the
    one-file installer, launch.sh, the pages, mpv's scripts and options) is on one short list,
    each entry naming the Privacy section's words for it. A new way online
    anywhere else fails here, and so does one added to a listed file;
  - the server reaches those actions only from the viewer's own requests
    (POST /api/updates/check, /install, /pull), never at launch or from a GET;
  - the servers listen on this device only, and the installer's update step
    and launch.sh talk only to this device;
  - mpv only ever gets local files;
  - the Privacy section says each point of the promise.

tests/test_updates.py (the never-online work) checks the same actions with the network
replaced; this file is the static half. Nothing here goes online.

Run from the repo root:  python3 -m unittest tests.test_privacy_statement -v
"""

import ast
import re
import unittest
from pathlib import Path

from backend import mpv

REPO = Path(__file__).resolve().parent.parent

# Standard library modules that can open a connection to another machine.
NET_MODULES = {
    "urllib.request", "http.client", "socket", "ssl", "ftplib", "smtplib",
    "poplib", "imaplib", "telnetlib", "xmlrpc.client", "socketserver",
}
# Command words that go online when run (git's network commands, downloaders).
NET_WORDS = {"ls-remote", "fetch", "pull", "push", "clone", "curl", "wget"}
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
URL = re.compile(r"(?i)\b(?:https?|wss?|ftp)://([a-z0-9.-]+\.[a-z]{2,}|\d+\.\d+\.\d+\.\d+|localhost)")

# Every way online in the code that runs with the app, and the words the
# README's Privacy section uses for it. Adding one means saying it there.
ALLOWED = {
    # Check for updates: one request to GitHub's latest release, or git
    # ls-remote on a development copy. socket only for its error types.
    "backend/update_check.py": {
        "markers": {"import urllib.request", "import socket", "url api.github.com", "word ls-remote"},
        "promise": ["Check for updates", "asks GitHub for the latest version",
                    "ask that copy's own git remote",
                    "git connects with its own settings, including any sign-in you have set up for that remote"],
    },
    # Update and restart (download from this app's GitHub releases), and
    # Pull the latest version (git fetch) on a development copy.
    "backend/app_update.py": {
        "markers": {"import urllib.request", "url github.com", "word fetch"},
        "promise": ["Update and restart", "downloads the new version from GitHub",
                    "Pull the latest version"],
    },
    # The one-file installer (the one-file install work): after the viewer
    # opens it and says yes, GitHub's latest release and its two files from
    # this app's releases (tests/test_one_file_install.py checks the order).
    # socket only for its error types.
    "installer/one_file_install.py": {
        "markers": {"import urllib.request", "import socket", "url api.github.com",
                    "url github.com"},
        "promise": ["The one-file installer", "goes online only after you open it and say yes",
                    "asks GitHub for the latest release and downloads it from this "
                    "project's GitHub releases"],
    },
}
# Files with network modules that may talk to this device only: checked
# below that every address in them is this device's.
LOCAL_ONLY = {
    "backend/server.py": {"import http.server"},
    "backend/startup_error.py": {"import http.server"},
    "backend/mpv.py": {"import socket"},  # mpv's control socket, a file in /tmp
    "backend/sleep_pause.py": {"import socket"},  # the same control socket, to pause for sleep
    "installer/update.py": {"import urllib.request", "import socket"},
}


def _python_files():
    for folder in ("backend", "vendor"):
        for path in sorted((REPO / folder).rglob("*.py")):
            if "__pycache__" not in path.parts:
                yield path
    yield REPO / "installer" / "update.py"
    yield REPO / "installer" / "one_file_install.py"


def _docstrings(tree) -> set:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                found.add(id(first.value))
    return found


def markers(path: Path, strings: bool = True) -> set:
    """The ways online one Python file has: network modules it imports,
    and (with strings) other machines' addresses and network command words
    it holds outside its docstrings. The vendored libraries are read for
    imports only: their strings are their own documentation and examples."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    docs = _docstrings(tree)
    found = set()
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names = [node.module] + [f"{node.module}.{alias.name}" for alias in node.names]
        for name in names:
            if name in NET_MODULES or name == "http.server":
                found.add(f"import {name}")
        if not strings or id(node) in docs:
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in NET_WORDS:
                found.add(f"word {node.value}")
            for host in URL.findall(node.value):
                if host.lower() not in LOCAL_HOSTS:
                    found.add(f"url {host.lower()}")
        if isinstance(node, ast.JoinedStr):  # f"https://github.com/{REPO}/..."
            for part in node.values:
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    for host in URL.findall(part.value):
                        if host.lower() not in LOCAL_HOSTS:
                            found.add(f"url {host.lower()}")
    return found


def privacy_section() -> str:
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    found = re.search(r"^## Privacy\n(.*?)(?=^## )", readme, re.M | re.S)
    return found.group(1) if found else ""


class OnlyTheListedActionsGoOnline(unittest.TestCase):
    def test_every_way_online_is_on_the_list(self):
        seen = {}
        for path in _python_files():
            rel = path.relative_to(REPO).as_posix()
            found = markers(path, strings=path.parts[len(REPO.parts)] != "vendor")
            if found:
                seen[rel] = found
        for rel, found in seen.items():
            with self.subTest(file=rel):
                allowed = ALLOWED.get(rel, {}).get("markers", set()) | LOCAL_ONLY.get(rel, set())
                self.assertLessEqual(found, allowed,
                                     f"{rel} gained a way online: {sorted(found - allowed)}. "
                                     "If it is a new action the viewer chooses, list it here "
                                     "and say it in the README's Privacy section first.")

    def test_the_list_matches_the_code(self):
        # A listed way online that's gone means the list (and maybe the
        # Privacy section) is out of date.
        for rel, entry in ALLOWED.items():
            with self.subTest(file=rel):
                self.assertEqual(markers(REPO / rel), entry["markers"])

    def test_the_marker_finder_catches_a_new_way_online(self):
        # The test above is only as good as this: a stand-in file with each
        # kind of way online is caught.
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            stand_in = Path(tmp) / "invented_feature.py"
            stand_in.write_text(
                "import urllib.request\nfrom http.client import HTTPSConnection\n"
                "ADDRESS = f'https://example.org/{1}'\nCOMMAND = ['git', 'pull']\n",
                encoding="utf-8")
            self.assertEqual(markers(stand_in), {
                "import urllib.request", "import http.client",
                "url example.org", "word pull"})

    def test_local_only_files_talk_to_this_device_only(self):
        for rel in LOCAL_ONLY:
            text = (REPO / rel).read_text(encoding="utf-8")
            with self.subTest(file=rel):
                for host in URL.findall(text):
                    self.assertIn(host.lower(), LOCAL_HOSTS)
                # Servers listen on this device only.
                for address in re.findall(r"(?:HTTPServer|bind)\(\(\s*\"([^\"]*)\"", text):
                    self.assertEqual(address, "127.0.0.1")
        self.assertIn("socket.AF_UNIX", (REPO / "backend" / "mpv.py").read_text(encoding="utf-8"))

    def test_the_launcher_talks_to_this_device_only(self):
        launch = (REPO / "launch.sh").read_text(encoding="utf-8")
        for host in URL.findall(launch):
            self.assertIn(host.lower(), LOCAL_HOSTS)
        for word in ("curl", "wget", "git ", "ls-remote", "flatpak install"):
            self.assertNotIn(word, launch)

    def test_the_pages_load_nothing_from_elsewhere(self):
        ui = REPO / "ui"
        for path in [*ui.glob("*.html"), *(ui / "js").glob("*.js"), *(ui / "css").glob("*.css")]:
            text = path.read_text(encoding="utf-8")
            with self.subTest(file=path.name):
                self.assertEqual(URL.findall(text), [])
                self.assertNotRegex(text, r"\b(WebSocket|EventSource|XMLHttpRequest|sendBeacon|importScripts)\b")
                # fetch() only ever asks the app's own server.
                for target in re.findall(r"\bfetch\(\s*([^,)]+)", text):
                    self.assertRegex(target.strip(), r'^(["`]/|path$|fixture \?)')

    def test_mpv_scripts_never_go_online(self):
        for path in (REPO / "backend" / "mpv_scripts").glob("*.lua"):
            text = path.read_text(encoding="utf-8")
            with self.subTest(file=path.name):
                self.assertEqual(URL.findall(text), [])
                self.assertNotRegex(text, r"\bsubprocess\b|\bcurl\b|\bwget\b|\bytdl\b")

    def test_mpv_only_gets_local_files(self):
        args = mpv.build_command(["mpv"], Path("/invented/Movies/Invented Film (2020).mkv"),
                                 title="Invented Film", watch_later_dir=Path("/invented/state"))
        self.assertEqual(args[-1], "/invented/Movies/Invented Film (2020).mkv")
        self.assertFalse([arg for arg in args if "://" in arg], args)


class OnlyTheViewerStartsThem(unittest.TestCase):
    """The server reaches the actions only from the viewer's own requests."""

    def test_only_the_settings_actions_reach_them(self):
        tree = ast.parse((REPO / "backend" / "server.py").read_text(encoding="utf-8"))
        callers = {}
        for func in ast.walk(tree):
            if not isinstance(func, ast.FunctionDef):
                continue
            for node in ast.walk(func):
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                    name = f"{node.value.id}.{node.attr}"
                    if name in ("update_check.check", "updater.start_update", "updater.start_pull",
                                "app_update.download", "update_check.fetch_latest",
                                "update_check.remote_main"):
                        callers.setdefault(name, set()).add(func.name)
        # Innermost names: do_POST routes; the handlers are reached only from it.
        self.assertEqual(callers, {
            "update_check.check": {"make_handler", "_handle_update_check"},
            "updater.start_update": {"make_handler", "_handle_update_install"},
            "updater.start_pull": {"make_handler", "do_POST"},
        })
        server = (REPO / "backend" / "server.py").read_text(encoding="utf-8")
        post = server[server.index("def do_POST"):]
        post = post[:post.index("\n        def ", 1)]
        for route, handler in (('"/api/updates/check"', "self._handle_update_check()"),
                               ('"/api/updates/install"', "self._handle_update_install()"),
                               ('"/api/updates/pull"', "self._handle_update_start(updater.start_pull)")):
            with self.subTest(route=route):
                self.assertIn(f"if self.path == {route}:\n                return {handler}", post)
                # Called from that POST route and nowhere else.
                self.assertEqual(server.count(handler), 1)


class ThePrivacySection(unittest.TestCase):
    def test_it_says_each_point_of_the_promise(self):
        section = privacy_section()
        self.assertTrue(section, "the README has no Privacy section")
        flat = " ".join(section.replace("**", "").split())
        for point in ("Kettle Video collects nothing and never goes online by itself.",
                      "shows GitHub your IP address and the app's version",
                      "It sends nothing about you or your library.",
                      "Your library, settings and watch history stay on your device.",
                      "Firefox's own updates, telemetry and other online features switched off",
                      "The installer goes online only if mpv is missing and you say yes to installing it from Flathub.",
                      "this section will say so first"):
            with self.subTest(point=point):
                self.assertIn(point, flat)

    def test_it_names_every_way_online(self):
        flat = " ".join(privacy_section().replace("**", "").split())
        for rel, entry in ALLOWED.items():
            for words in entry["promise"]:
                with self.subTest(file=rel, words=words):
                    self.assertIn(words, flat)

    def test_the_installer_goes_online_only_after_a_yes(self):
        install = (REPO / "installer" / "install.sh").read_text(encoding="utf-8")
        runs = [line for line in install.splitlines()
                if re.search(r"\b(curl|wget|git)\b|flatpak (install|remote-add)", line)
                and not line.strip().startswith(("say", "#", "MPV_COMMAND="))]
        run = 'if flatpak install $FLATPAK_ASK flathub "$MPV_FLATPAK"; then'
        self.assertEqual([line.strip() for line in runs], [run])
        before = install[:install.index(run)]
        # Asked on the terminal, or in the one-file installer's window, which
        # shows the same command (KETTLE_VIDEO_MPV_ANSWER).
        self.assertIn("Install mpv now with that command? [y/N]", before[-900:])
        self.assertIn('answer="$KETTLE_VIDEO_MPV_ANSWER"', before[-900:])
        self.assertIn("y|Y|yes|Yes|YES)", before[-200:])
        self.assertNotRegex((REPO / "installer" / "uninstall.sh").read_text(encoding="utf-8"),
                            r"\b(curl|wget)\b|flatpak install|git (fetch|pull|clone)")

    def test_the_hard_rule_is_in_claude_md_once(self):
        claude = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertEqual(claude.count("Kettle Video never goes online by itself."), 1)
        self.assertIn("must update the README's privacy statement first", claude)


if __name__ == "__main__":
    unittest.main()
