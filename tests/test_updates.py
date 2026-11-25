# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Check for updates, and never going online by itself (the never-online work).

The network is replaced throughout: GitHub by a stand-in server on this
device, the copy's remote by a local git folder, and every other way out
(sockets to anything but this device, name lookups, the real check
functions) by fakes that fail the test if they are touched. Nothing here
goes online.

  - no request at launch, while the app is used, after a while or on its
    own: only the Settings action (POST /api/updates/check) checks;
  - the request asks for the latest release and carries nothing else: no
    cookies, no identifiers, the plain user agent with the app's version;
    one request, given up after the time limit, never retried;
  - each result and error in its words; the download size comes from the
    release answer;
  - the development check (a git checkout without the installer's mark)
    compares with the remote's main; a release install never does;
  - "Last checked" changes only after a check that got an answer, and
    survives a restart.

Run from the repo root:  python3 -m unittest tests.test_updates -v
"""

import contextlib
import errno
import http.client
import io
import json
import re
import socket
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.error
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from backend import update_check
from backend.server import make_handler

REPO = Path(__file__).resolve().parent.parent
UI_DIR = REPO / "ui"
TODAY = date(2026, 11, 18)

RELEASE = {
    "tag_name": "v1.1.0",
    "name": "Kettle Video 1.1.0",
    "body": "## Changes\n- Invented change one\n- Invented change two\n\nThanks to everyone.",
    "assets": [
        {"name": "kettle-video-1.1.0.tar.gz.sha256", "size": 90},
        {"name": "kettle-video-1.1.0.tar.gz", "size": 41_943_040},
        {"name": "install.sh", "size": 12_000},
    ],
}


class Untouchable(AssertionError):
    pass


@contextlib.contextmanager
def no_way_out(test):
    """Every way online fails the test: a socket to anything but this
    device, a name lookup for anything but this device, and the real check
    functions. Yields the list of what was tried."""
    tried = []
    real_connect = socket.socket.connect
    real_getaddrinfo = socket.getaddrinfo

    def local(host):
        return host in ("127.0.0.1", "localhost", "::1")

    def connect(sock, address):
        if isinstance(address, tuple) and not local(address[0]):
            tried.append(f"connect {address[0]}")
            raise Untouchable(f"tried to connect to {address[0]}")
        return real_connect(sock, address)

    def getaddrinfo(host, *args, **kwargs):
        if not local(host):
            tried.append(f"lookup {host}")
            raise Untouchable(f"tried to look up {host}")
        return real_getaddrinfo(host, *args, **kwargs)

    def fetch(*args, **kwargs):
        tried.append("fetch_latest")
        raise Untouchable("checked for a release")

    def remote(*args, **kwargs):
        tried.append("remote_main")
        raise Untouchable("asked the remote")

    with mock.patch.object(socket.socket, "connect", connect), \
            mock.patch.object(socket, "getaddrinfo", getaddrinfo), \
            mock.patch.object(update_check, "fetch_latest", fetch), \
            mock.patch.object(update_check, "remote_main", remote):
        yield tried


class StandInGitHub:
    """GitHub's release information, on this device. Writes down every
    request it gets, with its headers and body."""

    def __init__(self, status=200, answer=RELEASE, delay=0):
        self.requests = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def do_GET(self):
                length = int(self.headers.get("Content-Length") or 0)
                outer.requests.append({"method": "GET", "path": self.path,
                                       "headers": dict(self.headers.items()),
                                       "body": self.rfile.read(length) if length else b""})
                if delay:
                    time.sleep(delay)
                data = json.dumps(answer).encode() if not isinstance(answer, bytes) else answer
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except OSError:
                    pass

            do_POST = do_GET

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/repos/{update_check.REPO}/releases/latest"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class Versions(unittest.TestCase):
    def test_newer(self):
        self.assertTrue(update_check.is_newer("1.1.0", "1.0.0"))
        self.assertTrue(update_check.is_newer("v0.1.0", "0.1.0-dev"))  # the release after its dev builds
        self.assertTrue(update_check.is_newer("1.10.0", "1.9.3"))
        self.assertFalse(update_check.is_newer("1.0.0", "1.0.0"))
        self.assertFalse(update_check.is_newer("0.9.0", "1.0.0"))
        self.assertFalse(update_check.is_newer("0.1.0-dev", "0.1.0"))
        self.assertFalse(update_check.is_newer("not a version", "1.0.0"))


class Results(unittest.TestCase):
    def test_up_to_date(self):
        result = update_check.release_result({**RELEASE, "tag_name": "v1.0.0"}, "1.0.0", "kettle-video")
        self.assertEqual(result, {"state": "current", "text": "Up to date (v1.0.0)"})

    def test_running_something_newer_is_up_to_date(self):
        result = update_check.release_result({**RELEASE, "tag_name": "v1.0.0"}, "1.2.0", "kettle-video")
        self.assertEqual(result["text"], "Up to date (v1.2.0)")

    def test_newer_with_notes_and_download_size_from_the_answer(self):
        result = update_check.release_result(RELEASE, "1.0.0", "kettle-video")
        self.assertEqual(result["state"], "newer")
        self.assertEqual(result["text"], "Version 1.1.0 is available")
        self.assertEqual(result["version"], "1.1.0")
        self.assertEqual(result["notes"], RELEASE["body"])
        # The archive's own size, not the checksum's or the installer's.
        self.assertEqual(result["download_size"], 41_943_040)

    def test_no_archive_in_the_answer_means_no_size(self):
        result = update_check.release_result({**RELEASE, "assets": []}, "1.0.0", "kettle-video")
        self.assertIsNone(result["download_size"])

    def test_an_answer_without_a_version_is_an_error(self):
        for answer in ({}, {"tag_name": None}, {"tag_name": "latest"}):
            with self.subTest(answer=answer), self.assertRaises(update_check.CheckFailed):
                update_check.release_result(answer, "1.0.0", "kettle-video")


class LastChecked(unittest.TestCase):
    def test_words(self):
        words = update_check.last_checked_text
        self.assertEqual(words(None, TODAY), "Last checked: never")
        self.assertEqual(words(TODAY, TODAY), "Last checked: today")
        self.assertEqual(words(date(2026, 11, 17), TODAY), "Last checked: yesterday")
        self.assertEqual(words(date(2026, 3, 2), TODAY), "Last checked: 2 March 2026")

    def test_kept_on_the_device(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(update_check.load_last_checked(Path(tmp)))
            update_check.save_last_checked(Path(tmp) / "data", TODAY)
            self.assertEqual(update_check.load_last_checked(Path(tmp) / "data"), TODAY)
            (Path(tmp) / "data" / update_check.STATE_FILE).write_text("not json")
            self.assertIsNone(update_check.load_last_checked(Path(tmp) / "data"))


class TheRequest(unittest.TestCase):
    """The real web client, against the stand-in GitHub on this device."""

    def fetch(self, github, version="1.0.0", timeout=update_check.TIMEOUT_S):
        with mock.patch.object(update_check, "LATEST_URL", github.url):
            return update_check.fetch_latest(version, timeout=timeout)

    def test_asks_for_the_latest_release_and_nothing_else(self):
        github = StandInGitHub()
        self.addCleanup(github.close)
        self.assertEqual(self.fetch(github, "1.0.0"), RELEASE)
        [request] = github.requests
        self.assertEqual(request["method"], "GET")
        self.assertEqual(request["path"], f"/repos/{update_check.REPO}/releases/latest")
        self.assertEqual(request["body"], b"")
        headers = {k.lower(): v for k, v in request["headers"].items()}
        # The plain user agent with the app's name and version, and what any
        # request needs; no cookies, no identifiers, nothing about the device.
        self.assertEqual(headers.pop("user-agent"), "Kettle-Video/1.0.0")
        self.assertEqual(headers.pop("accept"), "application/vnd.github+json")
        self.assertEqual(set(headers), {"host", "accept-encoding", "connection"})
        self.assertEqual(headers["accept-encoding"], "identity")

    def test_the_real_address_is_githubs_release_information(self):
        self.assertEqual(update_check.LATEST_URL,
                         "https://api.github.com/repos/enamelware/kettle-video/releases/latest")
        request = update_check.latest_request("2.0.0")
        self.assertEqual(request.get_method(), "GET")
        self.assertIsNone(request.data)
        self.assertEqual(dict(request.header_items()),
                         {"User-agent": "Kettle-Video/2.0.0", "Accept": "application/vnd.github+json"})

    def test_gives_up_after_the_time_limit_and_never_retries(self):
        github = StandInGitHub(delay=3)
        self.addCleanup(github.close)
        start = time.monotonic()
        with self.assertRaises(update_check.CheckFailed) as caught:
            self.fetch(github, timeout=0.5)
        self.assertLess(time.monotonic() - start, 2.5)
        self.assertFalse(caught.exception.offline)
        time.sleep(0.5)
        self.assertEqual(len(github.requests), 1)
        self.assertEqual(update_check.TIMEOUT_S, 10)

    def test_github_refusing_or_broken_answers_are_try_later(self):
        for status, answer in ((403, {"message": "rate limited"}), (404, {"message": "Not Found"}),
                               (500, {}), (200, b"<html>not json</html>"), (200, ["a list"])):
            github = StandInGitHub(status=status, answer=answer)
            self.addCleanup(github.close)
            with self.subTest(status=status), self.assertRaises(update_check.CheckFailed) as caught:
                self.fetch(github)
            self.assertFalse(caught.exception.offline)

    def test_no_connection(self):
        lookups = socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        with mock.patch.object(socket, "getaddrinfo", side_effect=lookups), \
                self.assertRaises(update_check.CheckFailed) as caught:
            update_check.fetch_latest("1.0.0")
        self.assertTrue(caught.exception.offline)
        unreachable = OSError(errno.ENETUNREACH, "Network is unreachable")
        with mock.patch.object(socket, "create_connection", side_effect=unreachable), \
                self.assertRaises(update_check.CheckFailed) as caught:
            update_check.fetch_latest("1.0.0")
        self.assertTrue(caught.exception.offline)


class CheckWords(unittest.TestCase):
    """check() as the server calls it, for a release install."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "app"
        self.root.mkdir()
        self.data = Path(self.tmp.name) / "data"

    def run_check(self, fetch):
        return update_check.check(self.root, self.data, "1.0.0", TODAY, fetch=fetch,
                                  remote=lambda root: self.fail("a release install asked a remote"))

    def failing(self, offline):
        def fetch(version):
            raise update_check.CheckFailed("stand-in", offline)
        return fetch

    def test_each_result_and_error(self):
        cases = [
            (lambda v: {**RELEASE, "tag_name": "v1.0.0"}, "current", "Up to date (v1.0.0)"),
            (lambda v: RELEASE, "newer", "Version 1.1.0 is available"),
            (self.failing(True), "error", "Couldn't check: no connection"),
            (self.failing(False), "error", "Couldn't check right now. Try again later."),
        ]
        for fetch, state, text in cases:
            with self.subTest(text=text):
                result = self.run_check(fetch)
                self.assertEqual((result["state"], result["text"]), (state, text))
                self.assertFalse(result["development"])
                self.assertNotIn("Traceback", json.dumps(result))

    def test_the_version_sent_is_the_apps(self):
        asked = []
        self.run_check(lambda version: asked.append(version) or RELEASE)
        self.assertEqual(asked, ["1.0.0"])

    def test_last_checked_changes_only_after_an_answer(self):
        result = self.run_check(self.failing(False))
        self.assertEqual(result["last_checked"], "Last checked: never")
        self.assertFalse((self.data / update_check.STATE_FILE).exists())
        result = self.run_check(lambda v: RELEASE)
        self.assertEqual(result["last_checked"], "Last checked: today")
        self.assertEqual(update_check.load_last_checked(self.data), TODAY)
        later = update_check.check(self.root, self.data, "1.0.0", date(2026, 11, 19),
                                   fetch=self.failing(True))
        self.assertEqual(later["last_checked"], "Last checked: yesterday")

    def test_the_log_line_says_nothing_private(self):
        result = self.run_check(lambda v: RELEASE)
        self.assertEqual(result["log"], "update check: latest release: newer")


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          env={"GIT_AUTHOR_NAME": "Invented", "GIT_AUTHOR_EMAIL": "invented@example.invalid",
                               "GIT_COMMITTER_NAME": "Invented", "GIT_COMMITTER_EMAIL": "invented@example.invalid",
                               "HOME": str(cwd), "PATH": "/usr/bin:/bin", "GIT_CONFIG_NOSYSTEM": "1"}).stdout.strip()


class Development(unittest.TestCase):
    """A git checkout compares with its remote's main: here the remote is a
    folder on this device."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.remote = base / "remote.git"
        self.copy = base / "copy"
        self.data = base / "data"
        git(base, "init", "--quiet", "--bare", "-b", "main", str(self.remote))
        git(base, "init", "--quiet", "-b", "main", str(self.copy))
        (self.copy / "VERSION").write_text("0.1.0-dev\n")
        git(self.copy, "add", "VERSION")
        git(self.copy, "commit", "--quiet", "-m", "first")
        git(self.copy, "remote", "add", "origin", str(self.remote))
        git(self.copy, "push", "--quiet", "origin", "main")

    def check(self):
        return update_check.check(self.copy, self.data, "0.1.0-dev", TODAY,
                                  fetch=lambda v: self.fail("a development copy asked GitHub"))

    def test_only_a_git_checkout_without_the_mark(self):
        self.assertTrue(update_check.is_development(self.copy))
        (self.copy / "kettle-video-installed").write_text("")
        self.assertFalse(update_check.is_development(self.copy))
        self.assertFalse(update_check.is_development(Path(self.tmp.name) / "data"))

    def test_up_to_date_with_main(self):
        head = git(self.copy, "rev-parse", "HEAD")
        result = self.check()
        self.assertEqual(result["state"], "current")
        self.assertEqual(result["text"], f"Up to date (v0.1.0-dev, {head[:7]})")
        self.assertTrue(result["development"])
        self.assertEqual(result["last_checked"], "Last checked: today")

    def test_a_newer_main(self):
        other = Path(self.tmp.name) / "other"
        git(Path(self.tmp.name), "clone", "--quiet", str(self.remote), str(other))
        (other / "NEW").write_text("invented\n")
        git(other, "add", "NEW")
        git(other, "commit", "--quiet", "-m", "second")
        git(other, "push", "--quiet", "origin", "main")
        newer = git(other, "rev-parse", "HEAD")
        before = git(self.copy, "rev-parse", "HEAD")
        result = self.check()
        self.assertEqual(result["state"], "newer")
        self.assertEqual(result["text"], f"A newer version is on main ({newer[:7]})")
        # Nothing pulled, nothing fetched into the copy: that is the Update and restart work.
        self.assertEqual(git(self.copy, "rev-parse", "HEAD"), before)
        self.assertNotIn(newer, git(self.copy, "rev-list", "--all"))

    def test_ahead_of_main_is_up_to_date(self):
        (self.copy / "LOCAL").write_text("invented\n")
        git(self.copy, "add", "LOCAL")
        git(self.copy, "commit", "--quiet", "-m", "local")
        self.assertEqual(self.check()["state"], "current")

    def test_no_remote_is_try_later(self):
        git(self.copy, "remote", "remove", "origin")
        result = self.check()
        self.assertEqual((result["state"], result["text"]),
                         ("error", "Couldn't check right now. Try again later."))
        self.assertEqual(result["last_checked"], "Last checked: never")


class Server(unittest.TestCase):
    """The app's own server, with every way online replaced."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.servers = []

    def tearDown(self):
        for httpd in self.servers:
            httpd.shutdown()
            httpd.server_close()

    def start(self):
        settings = {"movies_path": str(self.root), "tv_path": str(self.root), "mpv_command": "mpv",
                    "mpv_args": [], "data_dir": str(self.root / "data")}
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        self.port = httpd.server_address[1]
        with contextlib.redirect_stdout(io.StringIO()):
            base = make_handler(UI_DIR, self.root, settings, {"server": httpd}, self.port)

        class Quiet(base):
            def log_message(self, format, *args):
                pass

        httpd.RequestHandlerClass = Quiet
        self.servers.append(httpd)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()

    def request(self, method, path, body=None):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
            headers = {"Content-Type": "application/json"} if body is not None else {}
            conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
            resp = conn.getresponse()
            raw = resp.read()
            conn.close()
        try:
            data = json.loads(raw)
        except ValueError:
            data = None
        return resp.status, data, out.getvalue()

    def test_nothing_goes_online_at_launch_or_while_the_app_is_used(self):
        with no_way_out(self) as tried:
            self.start()
            for path in ("/", "/index.html", "/js/app.js", "/api/onboarding", "/api/mpv-status",
                         "/api/library/parsed", "/api/status", "/api/continue", "/api/dev",
                         "/api/settings", "/api/library/scan/status"):
                with self.subTest(path=path):
                    status, _, _ = self.request("GET", path)
                    self.assertLess(status, 500)
            time.sleep(1.5)  # nothing on a timer either
            self.request("GET", "/api/settings")
        self.assertEqual(tried, [])

    def test_settings_says_last_checked_without_going_online(self):
        with no_way_out(self) as tried, mock.patch.object(update_check, "is_development", return_value=False):
            self.start()
            _, answer, _ = self.request("GET", "/api/settings")
        self.assertEqual(answer["updates"], {"last_checked": "Last checked: never", "development": False})
        self.assertEqual(tried, [])

    def test_only_the_settings_action_checks(self):
        asked = []
        with mock.patch.object(update_check, "is_development", return_value=False), \
                mock.patch.object(update_check, "fetch_latest", lambda v: asked.append(v) or RELEASE):
            self.start()
            self.request("GET", "/api/settings")
            self.assertEqual(asked, [])
            status, answer, log = self.request("POST", "/api/updates/check", {})
        self.assertEqual(status, 200)
        self.assertEqual(len(asked), 1)
        self.assertEqual(answer["state"], "newer")
        self.assertEqual(answer["text"], "Version 1.1.0 is available")
        self.assertEqual(answer["notes"], RELEASE["body"])
        self.assertEqual(answer["last_checked"], "Last checked: today")
        self.assertNotIn("log", answer)
        self.assertIn("update check: latest release: newer", log)

    def test_a_get_never_checks(self):
        with no_way_out(self) as tried:
            self.start()
            status, _, _ = self.request("GET", "/api/updates/check")
        self.assertNotEqual(status, 200)
        self.assertEqual(tried, [])

    def test_last_checked_survives_a_restart(self):
        with mock.patch.object(update_check, "is_development", return_value=False), \
                mock.patch.object(update_check, "fetch_latest", lambda v: RELEASE):
            self.start()
            self.request("POST", "/api/updates/check", {})
        with no_way_out(self) as tried, mock.patch.object(update_check, "is_development", return_value=False):
            self.start()  # a new server on the same data folder: the app started again
            _, answer, _ = self.request("GET", "/api/settings")
        self.assertRegex(answer["updates"]["last_checked"], r"^Last checked: (today|yesterday)$")
        self.assertEqual(tried, [])

    def test_one_check_at_a_time(self):
        release = threading.Event()

        def slow(version):
            release.wait(5)
            return RELEASE

        with mock.patch.object(update_check, "is_development", return_value=False), \
                mock.patch.object(update_check, "fetch_latest", slow):
            self.start()
            first = []
            thread = threading.Thread(target=lambda: first.append(self.request("POST", "/api/updates/check", {})))
            thread.start()
            time.sleep(0.3)
            # The rest of the app keeps answering, and a second check waits its turn.
            self.assertEqual(self.request("GET", "/api/status")[0], 200)
            self.assertEqual(self.request("POST", "/api/updates/check", {})[0], 409)
            release.set()
            thread.join(5)
        self.assertEqual(first[0][1]["state"], "newer")


class ThePage(unittest.TestCase):
    """The page asks for a check from one place: A on the Settings row."""

    def test_only_settings_select_asks(self):
        js = {path.name: path.read_text(encoding="utf-8") for path in (UI_DIR / "js").glob("*.js")}
        self.assertEqual([name for name, text in js.items() if "/api/updates/check" in text], ["api.js"])
        callers = {name: re.findall(r"\bcheckForUpdates\(", text) for name, text in js.items()}
        self.assertEqual({name: len(found) for name, found in callers.items() if found},
                         {"api.js": 1, "settings.js": 3})
        settings = js["settings.js"]
        # Its own definition, the call to the server, and the Settings action.
        self.assertIn("result = await api.checkForUpdates();", settings)
        self.assertIn('else if (item.dataset.kind === "update-check") checkForUpdates();', settings)

    def test_the_page_never_loads_anything_from_elsewhere(self):
        for path in [*UI_DIR.glob("*.html"), *(UI_DIR / "js").glob("*.js"), *(UI_DIR / "css").glob("*.css")]:
            with self.subTest(file=path.name):
                self.assertNotRegex(path.read_text(encoding="utf-8"), r"(?i)\b(https?:)?//[a-z0-9.-]+\.[a-z]{2,}/")


class TheLauncher(unittest.TestCase):
    def test_the_automatic_updater_is_gone(self):
        launch = (REPO / "launch.sh").read_text()
        self.assertNotIn("dev_update", launch)
        self.assertNotIn("dev_auto_update", launch)
        self.assertFalse((REPO / "backend" / "dev_update.py").exists())

    def test_the_kiosk_profile_has_its_dead_end(self):
        launch = (REPO / "launch.sh").read_text()
        for line in ('user_pref("network.proxy.type", 1);',
                     'user_pref("network.proxy.http", "127.0.0.1");',
                     'user_pref("network.proxy.http_port", 9);',
                     'user_pref("network.proxy.ssl", "127.0.0.1");',
                     'user_pref("network.proxy.ssl_port", 9);',
                     'user_pref("network.proxy.share_proxy_settings", true);',
                     'user_pref("network.proxy.allow_hijacking_localhost", false);',
                     'user_pref("network.proxy.failover_direct", false);',
                     'user_pref("network.proxy.allow_bypass", false);',
                     'user_pref("termsofuse.bypassNotification", true);',
                     'user_pref("browser.startup.couldRestoreSession.count", -1);'):
            with self.subTest(line=line):
                self.assertIn(line, launch)


if __name__ == "__main__":
    unittest.main()
