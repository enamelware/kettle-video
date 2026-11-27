# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Each copy keeps its own data, and "delete your data" removes all of the
installed copy's (the each-copy-its-own-data work, found by the launch
rehearsal).

Checked, in made-up home folders with invented names only:
- every place the installed copy writes to, found the way the app finds it
  (backend/app_paths.py, backend/resume_positions.py, launch.sh), is listed
  here, and the uninstaller's "delete your data" removes each one, leaving
  nothing of the app behind;
- the installed copy and a development copy use different kiosk Firefox
  profiles (launch.sh itself, run on both kinds of copy) and different
  resume-position folders (the server's play request, end to end with a
  stand-in mpv);
- the uninstaller never removes anything of a development copy (its
  folder, its profile, mpv's own resume positions it uses) or anything in
  the media folders settings.json names, even inside the home folder;
- an update from the shared layout keeps the installed copy's data, and its
  resume positions are carried over once, from mpv's own folder (only
  read); a brand-new install, including one after "delete your data",
  starts with none.

Run: scripts/test.sh unit tests.test_each_copy_own_data
"""

import contextlib
import http.client
import io
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from backend import app_paths, launch_options, resume_positions, update_check
from backend import continue_watching, library_index, onboarding
from backend.settings import load_settings
from backend.server import make_handler
from tests.test_installer import NAME, ROOT, snapshot
from tests.test_kettle_video_name import FAKE_FIREFOX
from tests.test_reinstall_keeps_data import VERSION, tracked_app_files
from tests.test_uninstaller import UninstallTestCase

import release  # noqa: E402  (tools/, put on the path by tests.test_installer)

UI_DIR = ROOT / "ui"
FLATPAK_MPV = ["flatpak", "run", resume_positions.FLATPAK_ID]

# Everything the installed copy writes to, and who writes it. Temporary
# folders under /tmp are not listed: the app makes and deletes each one
# itself (mpv's control socket kettle-mpv-…, the stop frame kettle-quit-…,
# a fresh start's kettle-fresh-…), and /tmp is emptied at every restart.
# mpv's own folder isn't either: since this work the installed copy never
# writes there (a development copy does), so it is never the uninstaller's.
WRITERS = {
    "settings.json": "backend/onboarding.py, Settings (backend/settings_screen.py)",
    "data: library": "backend/library_index.py",
    "data: Continue watching and its pictures": "backend/continue_watching.py",
    "data: last update check": "backend/update_check.py",
    "data: resume carry-over note": "backend/resume_positions.py",
    "data: resume positions (normal mpv)": "mpv, told by backend/resume_positions.py",
    "resume positions (Flatpak mpv)": "mpv, told by backend/resume_positions.py",
    "logs": "launch.sh, backend/server.py, backend/mpv.py",
    "Firefox profile (system Firefox)": "launch.sh and Firefox",
    "Firefox profile (Flatpak Firefox)": "launch.sh and Firefox",
    "app files": "installer/update.py",
    "an update's download, cut short": "backend/app_update.py",
    "an update's switch-over, cut short": "installer/update.py",
    "menu entry": "installer/install.sh",
}


def every_place(home, app_dir):
    """{what: path} for everything the installed copy in app_dir writes,
    each found the way the app finds it."""
    environ = {"HOME": str(home)}
    paths = app_paths.for_app(app_dir, environ)
    assert paths.installed
    data = paths.data_dir
    app_id = app_paths.names(app_dir)["APP_ID"]
    profile = app_paths.firefox_profile(app_dir)
    share = paths.data_dir.parent
    return {
        "settings.json": paths.settings_file,
        "data: library": data / library_index.FILE_NAME,
        "data: Continue watching and its pictures": data / continue_watching.FILE_NAME,
        "data: last update check": data / update_check.STATE_FILE,
        "data: resume carry-over note": data / resume_positions.CARRY_FILE,
        "data: resume positions (normal mpv)":
            resume_positions.own_folder(data, app_id, ["mpv"], environ),
        "resume positions (Flatpak mpv)":
            resume_positions.own_folder(data, app_id, FLATPAK_MPV, environ),
        "logs": paths.logs_dir,
        # launch.sh: PROFILE_HOME/PROFILE_NAME, for each kind of Firefox.
        "Firefox profile (system Firefox)": home / ".mozilla" / profile,
        "Firefox profile (Flatpak Firefox)": home / ".var/app/org.mozilla.firefox/data" / profile,
        "app files": share / "app",
        "an update's download, cut short": share / ".download-invented",
        "an update's switch-over, cut short": share / ".app-invented",
        "menu entry": home / ".local/share/applications" / NAME["DESKTOP_ENTRY"],
    }


def write_invented(place, what):
    """Something invented in place, as using the app would leave it."""
    if what == "an update's switch-over, cut short":
        place.symlink_to("versions/invented")
    elif what in ("settings.json",) or place.suffix == ".json":
        place.parent.mkdir(parents=True, exist_ok=True)
        if not place.exists():
            place.write_text('{"invented": true}\n', encoding="utf-8")
    else:
        place.mkdir(parents=True, exist_ok=True)
        (place / "invented-file").write_bytes(b"invented")


class DeleteYourDataRemovesEverything(UninstallTestCase):

    def setUp(self):
        super().setUp()
        self.install_with_data()
        self.app = Path(os.path.realpath(self.places["APP_DIR"]))
        self.every = every_place(self.home, self.app)
        for what, place in self.every.items():
            if what not in ("app files", "menu entry"):
                write_invented(place, what)

    def test_every_place_is_listed_with_its_writer(self):
        self.assertEqual(sorted(self.every), sorted(WRITERS))

    def test_the_places_are_the_ones_the_installer_and_uninstaller_name(self):
        flatpak = self.every["resume positions (Flatpak mpv)"]
        self.assertEqual(flatpak, self.home / ".var/app/io.mpv.Mpv/data" / NAME["APP_ID"] / "watch_later")
        uninstaller = (ROOT / "installer" / "uninstall.sh").read_text(encoding="utf-8")
        self.assertIn('mpv_resume_dir="$HOME/.var/app/io.mpv.Mpv/data/$APP_ID"', uninstaller)
        self.assertEqual(self.every["data: resume positions (normal mpv)"].parent,
                         self.places["DATA_DIR"])
        self.assertEqual(self.every["Firefox profile (system Firefox)"].name, NAME["FIREFOX_PROFILE"])
        self.assertEqual(self.places["APP_DIR"].name, "app")
        self.assertIn('app_dir.with_name(f".{app_dir.name}-', (ROOT / "installer/update.py").read_text())
        from backend import app_update
        self.assertEqual(app_update.DOWNLOAD_PREFIX, ".download-")

    def test_yes_yes_yes_removes_each_one(self):
        result = self.uninstall("y\ny\ny\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for what, place in self.every.items():
            with self.subTest(what=what):
                self.assertFalse(place.exists() or place.is_symlink(), place)
        self.assertIn("starts from scratch", result.stdout)

    def test_nothing_of_the_app_is_left_in_the_home_folder(self):
        result = self.uninstall("y\ny\ny\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        left = [str(p.relative_to(self.home)) for p in self.home.rglob("*")]
        files = [name for name in left if not (self.home / name).is_dir()]
        self.assertEqual(files, [])
        for name in left:
            self.assertNotIn("kettle", name.lower())

    def test_the_flatpak_resume_folder_is_named_before_asking(self):
        out = self.uninstall("n\n").stdout
        self.assertIn(str(self.every["resume positions (Flatpak mpv)"].parent), out)
        self.assertIn("resume positions", out)

    def test_saying_no_to_the_data_keeps_the_resume_positions(self):
        flatpak = self.every["resume positions (Flatpak mpv)"]
        before = snapshot(flatpak.parent)
        result = self.uninstall("y\nn\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(snapshot(flatpak.parent), before)
        self.assertTrue((self.every["data: resume positions (normal mpv)"] / "invented-file").is_file())

    def test_a_resume_folder_that_is_a_shortcut_stops_it(self):
        folder = self.every["resume positions (Flatpak mpv)"].parent
        shutil.rmtree(folder)
        elsewhere = self.home / "invented-elsewhere"
        elsewhere.mkdir()
        folder.symlink_to(elsewhere)
        before = snapshot(self.home)
        result = self.uninstall("y\ny\ny\n")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("isn't the folder the installer made", result.stdout)
        self.assertEqual(snapshot(self.home), before)


class NeverTheDevelopmentCopyOrTheMedia(UninstallTestCase):
    """A development copy, its profile, mpv's own resume positions and media
    folders inside the home folder, all invented, stay byte for byte."""

    def setUp(self):
        super().setUp()
        self.install_with_data()
        self.dev = self.home / "Invented Projects" / "kettle-video"
        (self.dev / "installer").mkdir(parents=True)
        shutil.copy(ROOT / "installer" / "names.env", self.dev / "installer" / "names.env")
        (self.dev / "launch.sh").write_text("#!/bin/sh\n")
        (self.dev / "settings.json").write_text('{"movies_path": "", "tv_path": ""}\n')
        for name in ("data/library.json", "data/continue.json", "logs/launch-1.log"):
            (self.dev / name).parent.mkdir(exist_ok=True)
            (self.dev / name).write_text("invented development data\n")
        dev_profile = app_paths.firefox_profile(self.dev)
        self.kept = [self.dev,
                     self.home / ".mozilla" / dev_profile,
                     self.home / ".var/app/org.mozilla.firefox/data" / dev_profile]
        environ = {"HOME": str(self.home)}
        self.kept += resume_positions.mpv_folders(["mpv"], environ)
        self.kept += resume_positions.mpv_folders(FLATPAK_MPV, environ)
        for folder in self.kept[1:]:
            folder.mkdir(parents=True)
            (folder / "0123456789ABCDEF").write_text("start=42.0\n")
        # Media folders inside the home folder this time.
        self.films = self.home / "Videos" / "Invented Films"
        self.shows = self.home / "Videos" / "Invented Shows"
        for folder in (self.films, self.shows):
            folder.mkdir(parents=True)
            (folder / "Invented Film (2031).mkv").write_bytes(b"not a real film")
        (self.places["CONFIG_DIR"] / "settings.json").write_text(json.dumps(
            {"movies_path": str(self.films), "tv_path": str(self.shows)}) + "\n")
        self.kept += [self.films, self.shows]
        self.before = {str(p): snapshot(p) for p in self.kept}

    def test_development_copy_and_media_are_untouched(self):
        self.assertNotEqual(app_paths.firefox_profile(self.dev), NAME["FIREFOX_PROFILE"])
        result = self.uninstall("y\ny\ny\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("were deleted", result.stdout)
        self.assertEqual({str(p): snapshot(p) for p in self.kept}, self.before)

    def test_a_moved_data_folder_is_named_and_left_alone(self):
        moved = self.home / "Invented Elsewhere" / "data"
        moved.mkdir(parents=True)
        (moved / "library.json").write_text("{}\n")
        settings = json.loads((self.places["CONFIG_DIR"] / "settings.json").read_text())
        settings["data_dir"] = str(moved)
        (self.places["CONFIG_DIR"] / "settings.json").write_text(json.dumps(settings))
        result = self.uninstall("y\ny\ny\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"Your settings keep the library in {moved}", result.stdout)
        self.assertEqual((moved / "library.json").read_text(), "{}\n")


class OnlyTheExactPlacesBesideTheApp(UninstallTestCase):
    """Beside the app folder, only an update's own leftovers go: a download
    folder (.download-…) and a switch-over shortcut (.app-…). Anything else
    there, or one of those names on the wrong kind of thing, is a guess and
    stays, and a shortcut is never followed into what it points at."""

    def test_anything_else_beside_the_app_stays(self):
        self.install_with_data()
        share = self.places["APP_DIR"].parent
        dev = self.home / "Invented Projects" / "kettle-video"
        (dev / "data").mkdir(parents=True)
        (dev / "data" / "library.json").write_text("invented development data\n")
        (share / ".download-shortcut").symlink_to(dev)
        (share / ".app-folder").mkdir()
        (share / ".app-folder" / "mine.txt").write_text("someone's own file\n")
        (share / ".invented-other").mkdir()
        (share / ".invented-other" / "mine.txt").write_text("someone's own file\n")
        (share / "invented-notes.txt").write_text("someone's own notes\n")
        kept = [dev, share / ".app-folder", share / ".invented-other"]
        before = {str(p): snapshot(p) for p in kept}
        result = self.uninstall("y\ny\ny\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual({str(p): snapshot(p) for p in kept}, before)
        self.assertTrue((share / ".download-shortcut").is_symlink())
        self.assertEqual((share / "invented-notes.txt").read_text(), "someone's own notes\n")
        self.assertFalse(self.places["APP_DIR"].exists() or self.places["APP_DIR"].is_symlink())


class NeverAMediaFolderInsideTheFlatpakResumeFolder(UninstallTestCase):
    """A media folder settings.json names inside the Flatpak mpv's folder for
    the installed copy stops "delete your data" with nothing removed."""

    def test_it_stops_with_nothing_removed(self):
        self.install_with_data()
        folder = resume_positions.flatpak_folder(NAME["APP_ID"], {"HOME": str(self.home)})
        films = folder / "Invented Films"
        films.mkdir(parents=True)
        (films / "Invented Film (2031).mkv").write_bytes(b"not a real film")
        (self.places["CONFIG_DIR"] / "settings.json").write_text(json.dumps(
            {"movies_path": str(films), "tv_path": ""}) + "\n")
        before = snapshot(self.home)
        result = self.uninstall("y\ny\ny\n")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("your media folder", result.stdout)
        self.assertIn(str(films), result.stdout)
        self.assertEqual(snapshot(self.home), before)


class CarryOverFromAnOlderMpv(unittest.TestCase):
    """mpv before 0.36 kept its positions in its settings folder: an update
    carries those over too, once, and only reads them."""

    def test_positions_in_the_older_folder_are_carried_over(self):
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        environ = {"HOME": str(tmp / "home")}
        data = tmp / "home/.local/share" / NAME["APP_ID"] / "data"
        data.mkdir(parents=True)
        for command in (["mpv"], FLATPAK_MPV):
            with self.subTest(command=command[0]):
                older = resume_positions.mpv_folders(command, environ)[1]
                self.assertIn("config", str(older))
                older.mkdir(parents=True)
                (older / "0123456789ABCDEF").write_text("start=7.5\n")
                before = snapshot(older)
                (data / resume_positions.CARRY_FILE).unlink(missing_ok=True)
                resume_positions.note_first_launch(data, had_library=True)
                own = resume_positions.folder_for_play(True, None, data, NAME["APP_ID"], command,
                                                       [], True, lambda line: None, environ)
                self.assertEqual(snapshot(own), before)
                self.assertEqual(snapshot(older), before, "mpv's own folder is only read")
                shutil.rmtree(own)


class EachCopyHasItsOwnProfile(unittest.TestCase):
    """launch.sh, run on an installed copy and on a development copy, with
    a stand-in Firefox that notes the profile it was given."""

    def launch(self, installed):
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        app, bin_dir, home = tmp / "app", tmp / "bin", tmp / "home"
        for d in (app, bin_dir, home):
            d.mkdir()
        for name in ("launch.sh", "backend", "ui", "vendor", "installer"):
            src = ROOT / name
            if src.is_dir():
                shutil.copytree(src, app / name, ignore=shutil.ignore_patterns("__pycache__"))
            else:
                shutil.copy2(src, app / name)
        if installed:
            (app / NAME["INSTALL_MARK"]).write_text("installed\n")
        else:
            (app / "settings.json").write_text('{"movies_path": "", "tv_path": ""}\n')
        for name, text in (("firefox", FAKE_FIREFOX), ("flatpak", "#!/bin/sh\nexit 1\n")):
            (bin_dir / name).write_text(text)
            (bin_dir / name).chmod(0o755)
        out = tmp / "firefox-out.json"
        env = dict(os.environ, HOME=str(home), PATH=f"{bin_dir}:{os.environ['PATH']}",
                   FAKE_OUT=str(out))
        for name in ("KETTLE_VIDEO_PORT", "KETTLE_VIDEO_LAUNCH_START", "KETTLE_DEV_UPDATE",
                     "KETTLE_LAUNCH_LOG", "MOZ_HEADLESS", "XDG_DATA_HOME", "XDG_CONFIG_HOME",
                     "XDG_STATE_HOME", "KETTLE_FRESH_START"):
            env.pop(name, None)
        proc = subprocess.run(["bash", "launch.sh"], cwd=app, env=env, capture_output=True,
                              text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        args = json.loads(out.read_text())["args"]
        return Path(args[args.index("-profile") + 1]), home

    def test_installed_and_development_copies_use_different_profiles(self):
        installed, home = self.launch(installed=True)
        self.assertEqual(installed, home / ".mozilla" / NAME["FIREFOX_PROFILE"])
        dev, home = self.launch(installed=False)
        self.assertEqual(dev, home / ".mozilla" / NAME["DEV_FIREFOX_PROFILE"])
        self.assertNotEqual(NAME["FIREFOX_PROFILE"], NAME["DEV_FIREFOX_PROFILE"])

    def test_app_paths_names_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp)
            (app / "installer").mkdir()
            shutil.copy(ROOT / "installer" / "names.env", app / "installer" / "names.env")
            self.assertEqual(app_paths.firefox_profile(app), NAME["DEV_FIREFOX_PROFILE"])
            (app / NAME["INSTALL_MARK"]).write_text("")
            self.assertEqual(app_paths.firefox_profile(app), NAME["FIREFOX_PROFILE"])


class EachCopyHasItsOwnResumePositions(unittest.TestCase):
    """The play request, end to end with a stand-in mpv that notes its
    options, for an installed copy and a development copy."""

    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.movies = self.tmp / "Movies"
        self.movies.mkdir()
        (self.movies / "Invented Film (2031).mkv").write_bytes(b"")
        self.out = self.tmp / "mpv-args.txt"
        self.mpv = self.tmp / "invented-mpv"
        self.mpv.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{self.out}"\n')
        self.mpv.chmod(0o755)
        env = {k: v for k, v in os.environ.items() if not k.startswith("XDG_")}
        env["HOME"] = str(self.home)
        self.enterContext(mock.patch.dict(os.environ, env, clear=True))
        self.httpd = None

    def tearDown(self):
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()

    def start(self, installed, data_dir, mpv_args=()):
        settings = {"movies_path": str(self.movies), "tv_path": "", "mpv_command": str(self.mpv),
                    "mpv_args": list(mpv_args), "resume": True, "keep_awake": False,
                    "data_dir": str(data_dir)}
        logs = self.tmp / "logs"
        logs.mkdir(exist_ok=True)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        port = self.httpd.server_address[1]
        httpd_ref = {"server": self.httpd}
        with contextlib.redirect_stdout(io.StringIO()):
            base = make_handler(UI_DIR, logs, settings, httpd_ref, port,
                                installed=installed, app_id=NAME["APP_ID"])

        class Quiet(base):
            def log_message(self, format, *args):
                pass

        self.httpd.RequestHandlerClass = Quiet
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return port

    def play(self, port):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("POST", "/api/play", json.dumps(
            {"source": "movies", "path": "Invented Film (2031).mkv"}),
            {"Content-Type": "application/json"})
        self.assertEqual(conn.getresponse().status, 200)
        conn.close()
        end = time.time() + 10
        while time.time() < end:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", "/api/status")
            state = json.loads(conn.getresponse().read())["state"]
            conn.close()
            if state == "idle":
                break
            time.sleep(0.05)
        args = self.out.read_text().splitlines()
        self.httpd.shutdown()
        self.httpd.server_close()
        self.httpd = None
        return [a.split("=", 1)[1] for a in args if a.startswith("--watch-later-dir=")]

    def test_installed_and_development_copies_use_different_folders(self):
        installed_data = self.tmp / "installed-data"
        with contextlib.redirect_stderr(io.StringIO()):
            installed = self.play(self.start(True, installed_data))
            dev = self.play(self.start(False, self.tmp / "dev-data"))
        self.assertEqual(installed, [str(installed_data / "watch_later")])
        self.assertTrue((installed_data / "watch_later").is_dir())
        self.assertEqual(dev, [], "a development copy keeps mpv's own folder")

    def test_their_own_watch_later_dir_in_mpv_args_wins(self):
        mine = str(self.tmp / "my-own")
        with contextlib.redirect_stderr(io.StringIO()):
            args = self.play(self.start(True, self.tmp / "data", [f"--watch-later-dir={mine}"]))
        self.assertEqual(args, [mine])

    def test_flatpak_mpv_gets_a_folder_it_can_write(self):
        folder = resume_positions.own_folder(self.tmp / "data", NAME["APP_ID"], FLATPAK_MPV)
        self.assertEqual(folder, self.home / ".var/app/io.mpv.Mpv/data" / NAME["APP_ID"] / "watch_later")
        self.assertNotIn(folder, resume_positions.mpv_folders(FLATPAK_MPV))
        self.assertTrue(resume_positions.is_flatpak(["/usr/bin/flatpak", "run", "io.mpv.Mpv"]))
        self.assertFalse(resume_positions.is_flatpak(["mpv"]))

    def test_fresh_start_still_wins(self):
        fresh = self.tmp / "fresh" / "watch_later"
        got = resume_positions.folder_for_play(True, fresh, self.tmp / "data", NAME["APP_ID"],
                                               ["mpv"], [], True, lambda line: None)
        self.assertEqual(got, fresh)
        self.assertFalse((self.tmp / "data").exists())


class CarryOverOnUpdate(unittest.TestCase):
    """The installed copy's first plays after updating from the shared layout."""

    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.environ = {"HOME": str(self.tmp / "home")}
        self.data = self.tmp / "home/.local/share" / NAME["APP_ID"] / "data"
        self.data.mkdir(parents=True)
        self.lines = []

    def shared(self, command):
        folder = resume_positions.mpv_folders(command, self.environ)[0]
        folder.mkdir(parents=True)
        for name in ("0123456789ABCDEF", "FEDCBA9876543210"):
            (folder / name).write_text(f"# invented\nstart=12.5\n")
        return folder

    def play(self, command):
        return resume_positions.folder_for_play(True, None, self.data, NAME["APP_ID"], command,
                                                [], True, self.lines.append, self.environ)

    def test_an_update_carries_the_positions_over_once(self):
        for command in (["mpv"], FLATPAK_MPV):
            with self.subTest(command=command[0]):
                shared = self.shared(command)
                before = snapshot(shared)
                (self.data / resume_positions.CARRY_FILE).unlink(missing_ok=True)
                resume_positions.note_first_launch(self.data, had_library=True)
                own = self.play(command)
                self.assertEqual(snapshot(own), before)
                self.assertEqual(snapshot(shared), before, "mpv's own folder is only read")
                # Later positions in mpv's own folder (a development copy's) stay there.
                (shared / "00000000000000AA").write_text("start=1.0\n")
                resume_positions.note_first_launch(self.data, had_library=True)
                self.assertEqual(snapshot(self.play(command)), before)
                self.assertTrue(any("carried over 2" in line for line in self.lines))
                shutil.rmtree(own)
                self.assertEqual(sorted(self.play(command).iterdir()), [], "once only")
                shutil.rmtree(self.tmp / "home/.var", ignore_errors=True)
                shutil.rmtree(self.tmp / "home/.local/state", ignore_errors=True)

    def test_a_brand_new_install_starts_with_none(self):
        self.shared(["mpv"])
        resume_positions.note_first_launch(self.data, had_library=False)
        self.assertEqual(list(self.play(["mpv"]).iterdir()), [])

    def test_the_server_notes_an_update_at_its_first_start(self):
        for had_library, expected in ((True, True), (False, False)):
            with self.subTest(had_library=had_library):
                data = self.tmp / f"data-{had_library}"
                data.mkdir()
                if had_library:
                    (data / library_index.FILE_NAME).write_text("{}\n")
                settings = {"movies_path": "", "tv_path": "", "mpv_command": "auto",
                            "mpv_args": [], "resume": True, "keep_awake": False,
                            "data_dir": str(data)}
                with contextlib.redirect_stdout(io.StringIO()), \
                        contextlib.redirect_stderr(io.StringIO()):
                    make_handler(UI_DIR, self.tmp, settings, {}, 0, installed=True,
                                 app_id=NAME["APP_ID"])
                stored = json.loads((data / resume_positions.CARRY_FILE).read_text())
                self.assertEqual(stored, {"carry_over": expected})

    def test_fresh_start_and_development_copies_note_nothing(self):
        settings = {"movies_path": "", "tv_path": "", "mpv_command": "auto", "mpv_args": [],
                    "resume": True, "keep_awake": False, "data_dir": str(self.data)}
        options = launch_options.LaunchOptions(data_dir=self.data, fresh_root=self.tmp,
                                               watch_later_dir=self.tmp / "wl")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            make_handler(UI_DIR, self.tmp, dict(settings), {}, 0, options, installed=True,
                         app_id=NAME["APP_ID"])
            make_handler(UI_DIR, self.tmp, dict(settings), {}, 0)
        self.assertFalse((self.data / resume_positions.CARRY_FILE).exists())


class UpdateKeepsTheInstalledCopysData(UninstallTestCase):
    """The real installer, twice, on an archive of this repo's own files:
    the update's first start is the real server's, from the shared layout."""

    def setUp(self):
        super().setUp()
        self.archive = self.downloads / f"{NAME['ARCHIVE_NAME']}-{VERSION}.tar.gz"
        self.archive.write_bytes(release.build_archive(
            tracked_app_files(), f"{NAME['ARCHIVE_NAME']}-{VERSION}"))
        Path(f"{self.archive}.sha256").write_text(
            release.sha256_line(self.archive.read_bytes(), self.archive.name), encoding="utf-8")

    def test_the_update_keeps_everything_and_carries_the_positions_over(self):
        self.install()
        places = self.places
        (places["CONFIG_DIR"] / "settings.json").write_text(json.dumps(
            {"movies_path": str(self.media / "Films"), "tv_path": str(self.media / "Shows")}))
        (places["DATA_DIR"] / library_index.FILE_NAME).write_text('{"invented": "library"}\n')
        (places["DATA_DIR"] / continue_watching.FILE_NAME).write_text('{"invented": "row"}\n')
        # The shared layout: one profile, and mpv's own resume positions.
        shared_profile = self.home / ".mozilla" / NAME["FIREFOX_PROFILE"]
        shared_profile.mkdir(parents=True)
        (shared_profile / "user.js").write_text("// invented\n")
        shared = resume_positions.mpv_folders(["mpv"], {"HOME": str(self.home)})[0]
        shared.mkdir(parents=True)
        (shared / "0123456789ABCDEF").write_text("start=99.0\n")
        before = {key: snapshot(places[key]) for key in ("CONFIG_DIR", "DATA_DIR")}
        before_shared = snapshot(shared)

        result = self.install()
        self.assertIn("It started cleanly.", result.stdout)
        # The update's own first start is a fresh start: it changes nothing.
        after = {key: snapshot(places[key]) for key in ("CONFIG_DIR", "DATA_DIR")}
        self.assertEqual(after, before)
        self.assertEqual(snapshot(shared), before_shared)
        self.assertTrue((shared_profile / "user.js").is_file(), "the installed copy keeps it")

        # The first real launch, as backend/server.py's serve() starts it.
        app = Path(os.path.realpath(places["APP_DIR"]))
        environ = {"HOME": str(self.home)}
        paths = app_paths.for_app(app, environ)
        self.assertEqual(app_paths.firefox_profile(app), NAME["FIREFOX_PROFILE"])
        settings = load_settings(app, paths)
        self.assertFalse(onboarding.needed(settings))
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            make_handler(app / "ui", paths.logs_dir, settings, {}, 0, None, paths.settings_file,
                         paths.settings_file, paths.installed, app_paths.names(app)["APP_ID"])
        carry = json.loads((places["DATA_DIR"] / resume_positions.CARRY_FILE).read_text())
        self.assertEqual(carry, {"carry_over": True})
        own = resume_positions.folder_for_play(True, None, places["DATA_DIR"], NAME["APP_ID"],
                                               ["mpv"], [], True, lambda line: None, environ)
        self.assertEqual(snapshot(own), before_shared)
        self.assertEqual(snapshot(shared), before_shared)
        after = {key: snapshot(places[key]) for key in ("CONFIG_DIR",)}
        self.assertEqual(after, {"CONFIG_DIR": before["CONFIG_DIR"]})
        for name in (library_index.FILE_NAME, continue_watching.FILE_NAME):
            self.assertEqual((places["DATA_DIR"] / name).read_bytes(),
                             before["DATA_DIR"][name], name)

    def test_after_delete_your_data_a_new_install_starts_from_scratch(self):
        self.install_with_data()
        shared = resume_positions.mpv_folders(["mpv"], {"HOME": str(self.home)})[0]
        shared.mkdir(parents=True)
        (shared / "0123456789ABCDEF").write_text("start=99.0\n")
        result = self.uninstall("y\ny\ny\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.install()
        places = self.places
        resume_positions.note_first_launch(places["DATA_DIR"],
                                           (places["DATA_DIR"] / library_index.FILE_NAME).exists())
        own = resume_positions.folder_for_play(True, None, places["DATA_DIR"], NAME["APP_ID"],
                                               ["mpv"], [], True, lambda line: None,
                                               {"HOME": str(self.home)})
        self.assertEqual(list(own.iterdir()), [])
        self.assertFalse((places["CONFIG_DIR"] / "settings.json").exists())


if __name__ == "__main__":
    unittest.main()
