# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The installer, installer/install.sh (the installer work).

Every test runs the real script in a temporary home folder, on a small
test archive with invented contents, with a PATH that holds only the
ordinary tools it needs plus stand-ins: `flatpak` and `mpv` (so mpv is
never really installed), `sudo` (which only records that it was called)
and, for one test, `id`. Checked: an install from a test archive places
the app, its folders, the desktop entry and the icon, with nothing
written outside the temporary home; sudo is never called; a checksum
mismatch or a bad archive stops with nothing changed; the mpv-missing path
asks and finishes on a no (and runs only the one Flathub command on a yes);
the summary and the Steam steps are printed; a second install replaces
only the app files; XDG overrides move the folders exactly as the app
(backend/app_paths.py) expects; the script the release puts next to the
archive works on its own.

Run: scripts/test.sh unit tests.test_installer
"""

import contextlib
import hashlib
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "installer" / "install.sh"
NAMES = ROOT / "installer" / "names.env"
UPDATER = ROOT / "installer" / "update.py"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from backend import app_paths  # noqa: E402
import release  # noqa: E402

NAME = app_paths.read_names(NAMES.read_text(encoding="utf-8"))
TOOLS = ("bash", "sh", "tar", "gzip", "sha256sum", "python3", "mktemp", "mkdir", "mv", "rm",
         "chmod", "cat", "cut", "head", "tail", "sort", "id", "dirname", "basename", "ls",
         "grep")
FLATPAK_STUB = """#!/bin/sh
echo "$*" >> "$STUB_LOG/flatpak"
case "$1" in
  info) [ -n "${FAKE_MPV_FLATPAK:-}" ] && exit 0; exit 1 ;;
  install) exit 0 ;;
esac
exit 0
"""
RECORD_STUB = """#!/bin/sh
echo "$*" >> "$STUB_LOG/{name}"
exit 1
"""
# A stand-in for the app's server (the installer's update step): enough for an update's first
# start to count as clean. It serves ui/, answers /api/onboarding and closes
# on /api/shutdown, like the real one.
STAND_IN_SERVER = b'''# invented stand-in for the app's server
import http.server, json, os, threading
from pathlib import Path

UI = Path(__file__).resolve().parent.parent / "ui"


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(UI), **kwargs)

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/api/onboarding":
            body = json.dumps({"needed": True}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def do_POST(self):
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()
        if self.path == "/api/shutdown":
            threading.Thread(target=server.shutdown, daemon=True).start()


server = http.server.ThreadingHTTPServer(
    ("127.0.0.1", int(os.environ["KETTLE_VIDEO_PORT"])), Handler)
print("invented server ready", flush=True)
server.serve_forever()
'''
# A version that can't start.
BROKEN_SERVER = b'import sys\nprint("invented failure: this version cannot start")\nsys.exit(1)\n'
PAGE = (b'<!doctype html>\n<html><head><link rel="stylesheet" href="css/look.css">\n'
        b'<script src="js/app.js"></script></head><body>invented</body></html>\n')


def make_archive(folder, version="0.2.0", extra=None, prefix=None, server=STAND_IN_SERVER):
    """A small invented release archive and its checksum file."""
    prefix = prefix or f"{NAME['ARCHIVE_NAME']}-{version}"
    files = {
        "launch.sh": (b"#!/bin/sh\necho launched\n", 0o755),
        "VERSION": (f"{version}\n".encode(), 0o644),
        "backend/__init__.py": (b"", 0o644),
        "backend/server.py": (server, 0o644),
        "ui/index.html": (PAGE, 0o644),
        "ui/css/look.css": (b"body { margin: 0; }\n", 0o644),
        "ui/js/app.js": (f"// invented app {version}\n".encode(), 0o644),
        "installer/update.py": (UPDATER.read_bytes(), 0o644),
        "installer/names.env": (NAMES.read_bytes(), 0o644),
        NAME["ICON_FILE"]: ((ROOT / NAME["ICON_FILE"]).read_bytes(), 0o644),
        "README.md": (b"invented readme\n", 0o644),
    }
    files.update(extra or {})
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for path, (data, mode) in files.items():
            name = path if path.startswith(("/", "..")) else f"{prefix}/{path}"
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), mode
            tar.addfile(info, io.BytesIO(data))
    archive = Path(folder, f"{NAME['ARCHIVE_NAME']}-{version}.tar.gz")
    archive.write_bytes(buffer.getvalue())
    Path(f"{archive}.sha256").write_text(
        release.sha256_line(archive.read_bytes(), archive.name), encoding="utf-8")
    return archive


def snapshot(folder):
    """{relative path: bytes or None} for everything under folder."""
    out = {}
    for path in sorted(Path(folder).rglob("*")):
        out[str(path.relative_to(folder))] = path.read_bytes() if path.is_file() else None
    return out


class InstallerTestCase(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.downloads = self.tmp / "downloads"
        self.downloads.mkdir()
        self.logs = self.tmp / "stub-log"
        self.logs.mkdir()
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        for tool in TOOLS:
            found = shutil.which(tool)
            if found:
                os.symlink(found, self.bin / tool)
        self.stub("flatpak", FLATPAK_STUB)
        self.stub("sudo", RECORD_STUB.format(name="sudo"))
        self.archive = make_archive(self.downloads)

    def stub(self, name, text):
        path = self.bin / name
        if path.exists() or path.is_symlink():
            path.unlink()
        path.write_text(text, encoding="utf-8")
        path.chmod(0o755)

    def env(self, **extra):
        env = {"HOME": str(self.home), "PATH": str(self.bin), "STUB_LOG": str(self.logs),
               "LANG": "C.UTF-8"}
        env.update(extra)
        return env

    def run_install(self, *args, answer="n\n", script=SCRIPT, **extra):
        return subprocess.run(["bash", str(script), *args], input=answer, env=self.env(**extra),
                              capture_output=True, text=True, timeout=60)

    def install(self, answer="n\n", **extra):
        result = self.run_install(str(self.archive), answer=answer, **extra)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def logged(self, name):
        path = self.logs / name
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    @property
    def places(self):
        return app_paths.install_places(NAME["APP_ID"], {"HOME": str(self.home)})


class Installs(InstallerTestCase):

    def setUp(self):
        super().setUp()
        self.downloads_before = snapshot(self.downloads)
        self.result = self.install()

    def test_places_the_app_files(self):
        app = self.places["APP_DIR"]
        self.assertEqual(app, self.home / ".local/share" / NAME["APP_ID"] / "app")
        self.assertTrue((app / "backend/server.py").is_file())
        self.assertTrue(os.access(app / "launch.sh", os.X_OK))
        self.assertEqual((app / "VERSION").read_text().strip(), "0.2.0")

    def test_leaves_the_mark_so_the_app_knows_it_is_installed(self):
        app = self.places["APP_DIR"]
        self.assertTrue((app / NAME["INSTALL_MARK"]).is_file())
        paths = app_paths.for_app(app, {"HOME": str(self.home)})
        self.assertTrue(paths.installed)
        self.assertEqual(paths.settings_file,
                         self.home / ".config" / NAME["APP_ID"] / "settings.json")
        self.assertEqual(paths.data_dir, self.home / ".local/share" / NAME["APP_ID"] / "data")
        self.assertEqual(paths.logs_dir, self.home / ".local/state" / NAME["APP_ID"] / "logs")

    def test_makes_the_settings_data_and_logs_folders_but_no_settings_file(self):
        for key in ("DATA_DIR", "CONFIG_DIR", "LOGS_DIR"):
            self.assertTrue(self.places[key].is_dir(), key)
        # The first launch's onboarding makes settings.json.
        self.assertFalse((self.places["CONFIG_DIR"] / "settings.json").exists())

    def test_adds_the_desktop_entry_with_the_icon(self):
        entry = self.home / ".local/share/applications" / NAME["DESKTOP_ENTRY"]
        text = entry.read_text(encoding="utf-8")
        app = self.places["APP_DIR"]
        self.assertIn(f"Name={NAME['APP_NAME']}\n", text)
        self.assertIn(f'Exec="{app}/launch.sh"\n', text)
        self.assertIn(f"Path={app}\n", text)
        icon = Path(text.split("Icon=", 1)[1].splitlines()[0])
        self.assertEqual(icon, app / NAME["ICON_FILE"])
        self.assertTrue(icon.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertTrue(text.startswith("[Desktop Entry]\n"))

    def test_nothing_is_written_outside_the_home_folder(self):
        self.assertEqual(snapshot(self.downloads), self.downloads_before)
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()),
                         ["bin", "downloads", "home", "stub-log"])
        # No unpacking folder is left behind: the app folder is a shortcut
        # to the one version folder (the installer's update step).
        share = self.home / ".local/share" / NAME["APP_ID"]
        self.assertEqual(sorted(p.name for p in share.iterdir()), ["app", "data", "versions"])
        self.assertTrue((share / "app").is_symlink())
        self.assertEqual([p.name for p in (share / "versions").iterdir()],
                         [Path(os.readlink(share / "app")).name])

    def test_never_calls_sudo(self):
        self.assertEqual(self.logged("sudo"), [])

    def test_prints_the_summary_and_the_steam_steps(self):
        out = self.result.stdout
        self.assertIn(f"Done. {NAME['APP_NAME']} 0.2.0 is installed.", out)
        self.assertIn("The checksum matches.", out)
        self.assertIn(str(self.places["LOGS_DIR"]), out)
        self.assertIn("Add to Steam", out)
        self.assertIn("controller layout again", out)
        self.assertIn("never changes Steam's files", out)


class Mpv(InstallerTestCase):

    def test_missing_asks_and_finishes_on_a_no(self):
        result = self.install(answer="n\n")
        out = result.stdout
        self.assertIn("mpv isn't installed", out)
        self.assertIn("flatpak install flathub io.mpv.Mpv", out)
        self.assertIn("Install mpv now with that command? [y/N]", out)
        self.assertIn('"mpv not found" screen', out)
        self.assertIn("flatpak install --user flathub io.mpv.Mpv", out)
        self.assertIn("Done.", out)
        self.assertEqual(self.logged("flatpak"), ["info io.mpv.Mpv"])

    def test_no_answer_at_all_counts_as_no(self):
        result = self.install(answer="")
        self.assertIn("Done.", result.stdout)
        self.assertNotIn("install flathub io.mpv.Mpv", self.logged("flatpak"))

    def test_a_yes_runs_only_the_one_flathub_command(self):
        result = self.install(answer="y\n")
        self.assertEqual(self.logged("flatpak"), ["info io.mpv.Mpv", "install flathub io.mpv.Mpv"])
        self.assertIn("mpv: installed from Flathub", result.stdout)
        self.assertEqual(self.logged("sudo"), [])

    def test_a_failed_flathub_install_still_finishes(self):
        self.stub("flatpak", FLATPAK_STUB.replace("install) exit 0", "install) exit 1"))
        result = self.install(answer="y\n")
        self.assertIn("mpv wasn't installed.", result.stdout)
        self.assertIn("flatpak install --user flathub io.mpv.Mpv", result.stdout)
        self.assertIn("Done.", result.stdout)

    def test_a_system_mpv_is_found_without_asking(self):
        self.stub("mpv", "#!/bin/sh\nexit 0\n")
        result = self.install()
        self.assertIn("mpv is installed.", result.stdout)
        self.assertNotIn("[y/N]", result.stdout)

    def test_the_flatpak_mpv_is_found_without_asking(self):
        result = self.install(FAKE_MPV_FLATPAK="1")
        self.assertIn("mpv is installed (the Flatpak).", result.stdout)
        self.assertNotIn("[y/N]", result.stdout)

    def test_without_flatpak_it_explains_and_finishes(self):
        (self.bin / "flatpak").unlink()
        result = self.install()
        self.assertIn("Flatpak isn't on this system", result.stdout)
        self.assertNotIn("[y/N]", result.stdout)
        self.assertIn("Done.", result.stdout)


class StopsWithNothingChanged(InstallerTestCase):

    def assert_stopped(self, result, *words):
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("Install stopped", result.stdout)
        self.assertIn("Nothing was installed or changed.", result.stdout)
        for word in words:
            self.assertIn(word, result.stdout)

    def test_a_checksum_mismatch(self):
        sum_file = Path(f"{self.archive}.sha256")
        sum_file.write_text("0" * 64 + f"  {self.archive.name}\n", encoding="utf-8")
        self.assert_stopped(self.run_install(str(self.archive)), "doesn't match its checksum")
        self.assertEqual(list(self.home.iterdir()), [])

    def test_a_changed_archive(self):
        data = bytearray(self.archive.read_bytes())
        data[-1] ^= 1
        self.archive.write_bytes(bytes(data))
        self.assert_stopped(self.run_install(str(self.archive)), "doesn't match its checksum")
        self.assertEqual(list(self.home.iterdir()), [])

    def test_a_missing_checksum_file(self):
        Path(f"{self.archive}.sha256").unlink()
        self.assert_stopped(self.run_install(str(self.archive)), "checksum file")
        self.assertEqual(list(self.home.iterdir()), [])

    def test_a_path_outside_the_archive_folder(self):
        archive = make_archive(self.downloads, "0.3.0", extra={"../escape.txt": (b"x", 0o644)})
        self.assert_stopped(self.run_install(str(archive)), "outside its own folder")
        self.assertEqual(list(self.home.iterdir()), [])
        self.assertFalse((self.downloads.parent / "escape.txt").exists())

    def test_an_archive_that_is_not_the_app(self):
        # An archive of something else: no launch.sh, no backend.
        archive = self.downloads / f"{NAME['ARCHIVE_NAME']}-0.3.0.tar.gz"
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
            info = tarfile.TarInfo("something-else/notes.txt")
            info.size = 2
            tar.addfile(info, io.BytesIO(b"hi"))
        archive.write_bytes(buffer.getvalue())
        Path(f"{archive}.sha256").write_text(
            f"{hashlib.sha256(buffer.getvalue()).hexdigest()}  {archive.name}\n")
        self.assert_stopped(self.run_install(str(archive)), "isn't a Kettle Video release")
        self.assertFalse(self.places["APP_DIR"].exists())

    def test_run_as_root(self):
        self.stub("id", "#!/bin/sh\necho 0\n")
        self.assert_stopped(self.run_install(str(self.archive)), "not as root or with sudo")
        self.assertEqual(list(self.home.iterdir()), [])
        self.assertEqual(self.logged("sudo"), [])

    def test_a_folder_the_installer_did_not_make(self):
        app = self.places["APP_DIR"]
        app.mkdir(parents=True)
        (app / "mine.txt").write_text("someone's own file\n")
        self.assert_stopped(self.run_install(str(self.archive)), "wasn't made by this installer")
        self.assertEqual(sorted(p.name for p in app.iterdir()), ["mine.txt"])


class InstallsAgain(InstallerTestCase):

    def test_replaces_only_the_app_files(self):
        self.install()
        settings = self.places["CONFIG_DIR"] / "settings.json"
        settings.write_text('{"movies_path": "/invented/Films", "tv_path": ""}\n')
        library = self.places["DATA_DIR"] / "library.json"
        library.write_text("{}\n")
        log = self.places["LOGS_DIR"] / "launch-1.log"
        log.write_text("an invented log\n")
        (self.places["APP_DIR"] / "old-only.txt").write_text("old\n")
        newer = make_archive(self.downloads, "0.3.0")
        result = self.run_install(str(newer), answer="n\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Replaced the app files", result.stdout)
        app = self.places["APP_DIR"]
        self.assertEqual((app / "VERSION").read_text().strip(), "0.3.0")
        self.assertFalse((app / "old-only.txt").exists())
        self.assertEqual(settings.read_text(), '{"movies_path": "/invented/Films", "tv_path": ""}\n')
        self.assertEqual(library.read_text(), "{}\n")
        self.assertEqual(log.read_text(), "an invented log\n")


class Places(InstallerTestCase):

    def test_xdg_overrides_move_the_folders_as_the_app_expects(self):
        env = {"XDG_DATA_HOME": str(self.home / "d"), "XDG_CONFIG_HOME": str(self.home / "c"),
               "XDG_STATE_HOME": str(self.home / "s")}
        self.install(**env)
        places = app_paths.install_places(NAME["APP_ID"], {"HOME": str(self.home), **env})
        self.assertEqual(places["APP_DIR"], self.home / "d" / NAME["APP_ID"] / "app")
        for key in ("APP_DIR", "DATA_DIR", "CONFIG_DIR", "LOGS_DIR"):
            self.assertTrue(places[key].is_dir(), key)
        self.assertTrue((self.home / "d/applications" / NAME["DESKTOP_ENTRY"]).is_file())
        paths = app_paths.for_app(places["APP_DIR"], {"HOME": str(self.home), **env})
        self.assertEqual(paths.settings_file.parent, places["CONFIG_DIR"])
        self.assertEqual(paths.logs_dir, places["LOGS_DIR"])
        self.assertFalse((self.home / ".local").exists())

    def test_relative_xdg_values_are_ignored(self):
        env = {"XDG_DATA_HOME": "d", "XDG_CONFIG_HOME": "c", "XDG_STATE_HOME": "s"}
        self.install(**env)
        self.assertEqual(self.places,
                         app_paths.install_places(NAME["APP_ID"], {"HOME": str(self.home), **env}))
        self.assertTrue(self.places["APP_DIR"].is_dir())
        self.assertTrue(self.places["LOGS_DIR"].is_dir())


class StandaloneScript(InstallerTestCase):
    """The release puts install.sh next to the archive (tools/release.py)."""

    def setUp(self):
        super().setUp()
        text = release.standalone_installer(SCRIPT.read_text(encoding="utf-8"),
                                            NAMES.read_text(encoding="utf-8"),
                                            UPDATER.read_text(encoding="utf-8"))
        self.script = self.downloads / "install.sh"
        self.script.write_text(text, encoding="utf-8")

    def test_finds_the_newest_archive_next_to_it(self):
        make_archive(self.downloads, "0.10.0")
        result = self.run_install(script=self.script)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.places["APP_DIR"] / "VERSION").read_text().strip(), "0.10.0")

    def test_without_an_archive_it_says_what_to_do(self):
        for path in self.downloads.glob("*.tar.gz*"):
            path.unlink()
        result = self.run_install(script=self.script)
        self.assertEqual(result.returncode, 1)
        self.assertIn("Put the release archive and its .sha256 file", result.stdout)
        self.assertEqual(list(self.home.iterdir()), [])


class TheScriptItself(unittest.TestCase):

    def test_never_runs_sudo(self):
        # sudo appears only in comments and in the messages that say it isn't needed.
        for number, line in enumerate(SCRIPT.read_text(encoding="utf-8").splitlines(), 1):
            code = line.strip()
            if "sudo" not in code or code.startswith("#"):
                continue
            self.assertTrue(code.startswith(("stop ", "say ")), f"line {number}: {line}")

    def test_never_writes_steam_files(self):
        text = SCRIPT.read_text(encoding="utf-8")
        for steam in (".steam", ".local/share/Steam", "shortcuts.vdf", "steam://"):
            self.assertNotIn(steam, text)

    def test_runnable(self):
        self.assertTrue(os.access(SCRIPT, os.X_OK))


class InstalledCopy(unittest.TestCase):
    """An installed copy keeps settings, data and logs in the home folder's
    standard places, never in its app folder (the designer's decision on the installer work)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.home = self.tmp / "home"
        self.env = {"HOME": str(self.home)}
        self.places = app_paths.install_places(NAME["APP_ID"], self.env)
        self.app = self.places["APP_DIR"]
        (self.app / "installer").mkdir(parents=True)
        shutil.copy(NAMES, self.app / "installer" / "names.env")
        (self.app / NAME["INSTALL_MARK"]).write_text("installed\n")
        self.paths = app_paths.for_app(self.app, self.env)

    def write_settings(self, data):
        self.places["CONFIG_DIR"].mkdir(parents=True, exist_ok=True)
        (self.places["CONFIG_DIR"] / "settings.json").write_text(json.dumps(data))

    def test_settings_come_from_the_config_folder(self):
        from backend.settings import load_settings
        self.write_settings({"movies_path": "/invented/Films", "tv_path": ""})
        (self.app / "settings.json").write_text('{"movies_path": "/wrong", "tv_path": ""}')
        settings = load_settings(self.app, self.paths)
        self.assertEqual(settings["movies_path"], "/invented/Films")
        self.assertEqual(settings["data_dir"], str(self.places["DATA_DIR"]))

    def test_a_relative_data_dir_stays_beside_the_data_folder(self):
        from backend.settings import load_settings
        self.write_settings({"movies_path": "", "tv_path": "", "data_dir": "other"})
        settings = load_settings(self.app, self.paths)
        self.assertEqual(settings["data_dir"], str(self.places["DATA_DIR"].parent / "other"))

    def test_the_start_up_message_names_the_places_from_home(self):
        from backend import startup_error
        self.write_settings({"movies_path": 3, "tv_path": ""})
        text = " ".join(startup_error.lines(startup_error.BACKEND_STOPPED,
                                            "logs/launch-1.log", self.app, self.env))
        self.assertIn(f"in ~/.config/{NAME['APP_ID']}, then start Kettle again.", text)
        self.assertIn(f"launch-1.log, in ~/.local/state/{NAME['APP_ID']}/logs.", text)
        self.assertNotIn(str(self.home), text)

    def test_the_server_uses_the_home_folder_places(self):
        from backend import server
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        ref = {}

        def run():
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                server.serve(self.app, self.env, port, ref, self.tmp)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()

        def ask(method, path):
            request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method,
                                             data=b"{}" if method == "POST" else None,
                                             headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=5) as answer:
                return json.loads(answer.read())

        for _ in range(100):
            try:
                needed = ask("GET", "/api/onboarding")["needed"]
                break
            except OSError:
                threading.Event().wait(0.05)
        ask("POST", "/api/shutdown")
        thread.join(10)
        self.assertTrue(needed)
        self.assertTrue(self.places["LOGS_DIR"].is_dir())
        self.assertTrue(self.places["CONFIG_DIR"].is_dir())
        self.assertFalse((self.app / "logs").exists())
        self.assertFalse((self.app / "data").exists())
        self.assertFalse((self.app / "settings.json").exists())


class DevelopmentCopy(unittest.TestCase):
    """A development copy (this git folder) keeps everything where it is."""

    def test_this_folder_is_not_an_installed_copy(self):
        self.assertFalse((ROOT / NAME["INSTALL_MARK"]).exists())
        paths = app_paths.for_app(ROOT, {"HOME": "/invented-home", "XDG_CONFIG_HOME": "/x"})
        self.assertFalse(paths.installed)
        self.assertEqual(paths.settings_file, ROOT / "settings.json")
        self.assertEqual(paths.data_dir, ROOT / "data")
        self.assertEqual(paths.logs_dir, ROOT / "logs")

    def test_the_logs_command_names_this_folders_logs(self):
        result = subprocess.run([sys.executable, "-m", "backend.app_paths", "logs"], cwd=ROOT,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.stdout.strip(), str(ROOT / "logs"))


if __name__ == "__main__":
    unittest.main()
