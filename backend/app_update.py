# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Update and restart, and Pull the latest version (the Update and restart work).

Both start only from Settings › About, after Check for updates (the never-online work) found
something newer, and only after the viewer says yes in Enamel's confirm.
Kettle Video never goes online by itself: these are the only requests here,
and each one follows that clear choice.

An installed copy (made by installer/install.sh, with its mark):
  1. the release's archive and its checksum file are downloaded from this
     app's GitHub releases into a temporary folder beside the app folder.
     The request carries nothing about the viewer, the device or the
     library: the same plain user agent as the check, no cookies. Cancel
     works until the download ends;
  2. both are handed to the installer's shared update step (installer/
     update.py, the installer's update step), which checks the checksum, places the new version,
     checks it starts cleanly and rolls back on failure. There is no second
     checksum check or rollback here: one code path;
  3. the app restarts in place (see restart_in_place): the same process,
     so launch.sh and Steam still see the app running, and the window
     reloads by itself.

A development copy (a git checkout without the installer's mark): the
copy's own main is fetched and fast-forwarded, only with no local changes,
only on main; then the same restart.

Try a branch, Back to main and Restore data (the "Try a branch" work),
development copies only, take the same one slot and the same restart; the
git, the backups and the restore are backend/try_branch.py, the only code
here that opens the data folder or the settings file, and only for those
three. Update and restart and Pull never open either.
"""

import importlib.util
import os
import shutil
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from datetime import datetime

from backend import app_paths, try_branch, update_check

# The restart's message for the page, handed to the new server (one read).
NOTE_ENV = "KETTLE_UPDATE_NOTE"
# The only place a release is downloaded from.
DOWNLOAD_BASE = f"https://github.com/{update_check.REPO}/releases/download/"
# Downloads go in a folder of this name beside the app folder, removed after.
DOWNLOAD_PREFIX = ".download-"
CHUNK = 64 * 1024
READ_TIMEOUT_S = 30
# Nothing the app would ever release is this big.
MAX_DOWNLOAD = 500 * 1024 * 1024
# How long fetching main may take on a development copy.
PULL_TIMEOUT_S = 120

IDLE, DOWNLOADING, INSTALLING, PULLING, RESTARTING, FAILED, CANCELLED = (
    "idle", "downloading", "installing", "pulling", "restarting", "failed", "cancelled")
# Try a branch, Back to main and Restore data (the "Try a branch" work).
SWITCHING, BACKING_UP, CHECKING_START, RESTORING = ("switching", "backing up", "checking", "restoring")
RUNNING = (DOWNLOADING, INSTALLING, PULLING, RESTARTING, SWITCHING, BACKING_UP, CHECKING_START, RESTORING)

# The words the page shows, in Enamel's toast.
INSTALLING_TEXT = "Installing…"
PULLING_TEXT = "Pulling the latest version…"
RESTARTING_TEXT = "Restarting…"
CANCELLED_TEXT = "Update cancelled. Nothing was changed."
NOT_WHILE_PLAYING = "Not while a film is playing."
ALREADY_UPDATING = "An update is already running."
NOT_OFFERED = "Check for updates first."
CANT_UPDATE_HERE = ("This copy can't update itself. Run the installer again to update it.")
LOCAL_CHANGES = "Not pulled: this copy has changes of its own. Nothing was changed."
NOT_ON_MAIN = "Not pulled: this copy isn't on main. Nothing was changed."
MOVED_AWAY = "Not pulled: this copy has moved away from main. Nothing was changed."
PULL_OFFLINE = "Couldn't pull: no connection. Nothing was changed."
PULL_LATER = "Couldn't pull right now. Nothing was changed. Try again later."


def downloading_text(version: str, percent: Optional[int]) -> str:
    return f"Downloading {version}… {percent}%" if percent is not None else f"Downloading {version}…"


def updated_text(version: str) -> str:
    return f"Updated to {version}"


def pulled_text(commit: str) -> str:
    return f"Updated to the latest version ({commit[:7]})"


def up_to_date_text(commit: str) -> str:
    return f"Already up to date ({commit[:7]})"


def size_text(size: Optional[int]) -> Optional[str]:
    """The download size for the Update and restart row, or None."""
    if not isinstance(size, int) or size <= 0:
        return None
    megabytes = round(size / (1024 * 1024))
    return "Less than 1 MB" if megabytes < 1 else f"About {megabytes} MB"


# --- Which copy, and where the installer put it ---

def installed_app_dir(root: Path, environ=None) -> Optional[Path]:
    """The installer's app folder when this copy is the installed one
    there (it has the mark, and the app folder leads to it); else None: a
    copy anywhere else is never updated from inside the app."""
    root = Path(root)
    if not app_paths.is_installed(root):
        return None
    app_id = app_paths.names(root)["APP_ID"]
    app_dir = app_paths.install_places(app_id, os.environ if environ is None else environ)["APP_DIR"]
    if os.path.realpath(app_dir) != os.path.realpath(root):
        return None
    return app_dir


def load_installer(root: Path):
    """This copy's own installer/update.py, the shared update step."""
    path = Path(root) / "installer" / "update.py"
    spec = importlib.util.spec_from_file_location("kettle_video_installer_update", path)
    module = importlib.util.module_from_spec(spec)
    # Registered first: its dataclasses look themselves up there.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# --- The release to download ---

def release_download(release: dict, archive_name: str, version: str) -> Optional[dict]:
    """The archive and checksum of this version, from the check's answer:
    {"archive": url, "checksum": url, "file": name, "size": bytes | None},
    or None unless both are there, at this app's GitHub release addresses."""
    wanted = f"{archive_name}-{version}.tar.gz"
    found = {}
    for asset in release.get("assets") or []:
        if not isinstance(asset, dict):
            continue
        url = asset.get("browser_download_url")
        if not isinstance(url, str) or not url.startswith(DOWNLOAD_BASE) or not url.endswith("/" + str(asset.get("name"))):
            continue
        if asset.get("name") == wanted:
            found["archive"] = url
            found["size"] = asset.get("size") if isinstance(asset.get("size"), int) else None
        elif asset.get("name") == wanted + ".sha256":
            found["checksum"] = url
    if "archive" not in found or "checksum" not in found:
        return None
    return {**found, "file": wanted, "version": version}


class Cancelled(Exception):
    pass


class DownloadFailed(Exception):
    def __init__(self, why: str, offline: bool = False):
        super().__init__(why)
        self.offline = offline


def download(url: str, dest: Path, user_agent: str, cancel: threading.Event,
             progress: Callable[[int, Optional[int]], None], limit: int = MAX_DOWNLOAD) -> None:
    """One file from this app's GitHub releases into dest, read a piece at
    a time so Cancel is heard between pieces. The standard library's own web
    client, no cookie store; nothing sent but the request and a plain user
    agent. Raises Cancelled or DownloadFailed; dest may be left half-written
    (its folder is removed by the caller)."""
    if not url.startswith(DOWNLOAD_BASE):
        raise DownloadFailed("not a release address")
    request = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "application/octet-stream"})
    opener = urllib.request.build_opener()
    try:
        with opener.open(request, timeout=READ_TIMEOUT_S) as answer, open(dest, "wb") as out:
            total = answer.headers.get("Content-Length")
            total = int(total) if total and total.isdigit() else None
            done = 0
            progress(done, total)
            while True:
                if cancel.is_set():
                    raise Cancelled()
                piece = answer.read(CHUNK)
                if not piece:
                    break
                done += len(piece)
                if done > limit:
                    raise DownloadFailed("bigger than any release")
                out.write(piece)
                progress(done, total)
            if total is not None and done != total:
                raise DownloadFailed("the download stopped part way")
    except urllib.error.HTTPError as exc:
        exc.close()
        raise DownloadFailed(f"GitHub answered {exc.code}")
    except urllib.error.URLError as exc:
        raise DownloadFailed(f"no answer ({type(exc.reason).__name__})", update_check._offline(exc.reason))
    except (TimeoutError, ConnectionError) as exc:
        raise DownloadFailed(f"no answer ({type(exc).__name__})")
    except OSError as exc:
        raise DownloadFailed(f"couldn't save it ({type(exc).__name__})", update_check._offline(exc))


# --- The restart in place ---

def restart_in_place(root: Path, note: str, environ=None) -> None:
    """Become the app's server again, from root, in this same process. The
    process launch.sh started (and Steam watches) stays the same one, so the
    app never looks closed; the new server opens the same port, and the
    page, waiting for it, reloads. Called once the old server has stopped.
    note reaches the new server through NOTE_ENV, for the page's toast."""
    env = dict(os.environ if environ is None else environ)
    env[NOTE_ENV] = note
    sys.stdout.flush()
    sys.stderr.flush()
    os.chdir(root)
    os.execve(sys.executable, [sys.executable, "-u", "-m", "backend.server"], env)


# --- The update ---

class Updater:
    """One update at a time, in the background, its state read by the page.

    root: this copy's folder. log: one line for the launch log. restart(root,
    note): stop the server and restart in place (backend/server.py).
    is_playing(): a film is playing. Tests replace download, installer and
    git with stand-ins."""

    def __init__(self, root: Path, log: Callable[[str], None], restart: Callable[[Path, str], None],
                 is_playing: Callable[[], bool], environ=None,
                 download: Optional[Callable] = None, installer: Optional[Callable] = None,
                 git: Optional[Callable] = None, data_dir: Optional[Path] = None,
                 settings_file: Optional[Path] = None, media_roots: Optional[Callable] = None,
                 pulls: Optional[Callable] = None, start_check: Optional[Callable] = None,
                 now: Optional[Callable] = None):
        """data_dir, settings_file: this copy's own (never a fresh start's),
        for the backups; without them (most tests) no branch is switched.
        media_roots(): the media folders now, never backed up. pulls,
        start_check, now: stand-ins for GitHub's pull request list, the
        installer's start check and the clock."""
        self.root = Path(root)
        self.log = log
        self.restart = restart
        self.is_playing = is_playing
        self.environ = os.environ if environ is None else environ
        self._download = download or globals()["download"]
        self._installer = installer
        self._git = git or update_check._git
        self.lock = threading.Lock()
        self.cancel_asked = threading.Event()
        self.state = {"state": IDLE, "text": ""}
        self.offer = None  # the newer release found by the last check
        self.data_dir = Path(data_dir) if data_dir else None
        self.settings_file = Path(settings_file) if settings_file else None
        self.media_roots = media_roots or (lambda: [])
        self._pulls = pulls or try_branch.fetch_pulls
        self._start_check = start_check
        self._now = now or datetime.now
        self.list_lock = threading.Lock()
        self.listed = {}  # branch: label, from the last Try a branch list

    # What the page sees.
    def status(self) -> dict:
        with self.lock:
            return dict(self.state)

    def busy(self) -> bool:
        with self.lock:
            return self.state["state"] in RUNNING

    def _set(self, state: str, text: str = "", **more) -> None:
        with self.lock:
            self.state = {"state": state, "text": text, **more}

    # After a check: keep what an update needs; tell the page what it may offer.
    def offered(self, result: dict, release: Optional[dict]) -> dict:
        result = dict(result)
        with self.lock:
            self.offer = None
            if result.get("state") == "newer" and result.get("development"):
                result["can_pull"] = True
            elif result.get("state") == "newer" and release is not None:
                archive_name = app_paths.names(self.root).get("ARCHIVE_NAME") or app_paths.DEFAULT_APP_ID
                found = release_download(release, archive_name, result["version"])
                if found is not None and installed_app_dir(self.root, self.environ) is not None:
                    self.offer = found
                    result["can_update"] = True
                    size = size_text(found["size"] if found["size"] is not None else result.get("download_size"))
                    if size:
                        result["download_text"] = size
        return result

    def _begin(self, state: str, text: str, **more) -> Optional[str]:
        """Take the one update slot, or the reason it can't start now."""
        if self.is_playing():
            return NOT_WHILE_PLAYING
        with self.lock:
            if self.state["state"] in RUNNING:
                return ALREADY_UPDATING
            self.state = {"state": state, "text": text, **more}
            self.cancel_asked.clear()
        return None

    def start_update(self, version: str) -> Optional[str]:
        """Start Update and restart for version. None once started, else the
        reason in plain words (nothing started)."""
        with self.lock:
            offer = self.offer
        if offer is None or offer["version"] != version:
            return NOT_OFFERED
        app_dir = installed_app_dir(self.root, self.environ)
        if app_dir is None:
            return CANT_UPDATE_HERE
        refused = self._begin(DOWNLOADING, downloading_text(version, 0), version=version)
        if refused:
            return refused
        self.log(f"update: downloading {version}")
        threading.Thread(target=self._update, args=(offer, app_dir), daemon=True).start()
        return None

    def cancel(self) -> bool:
        """Cancel works only while downloading."""
        with self.lock:
            if self.state["state"] != DOWNLOADING:
                return False
            self.cancel_asked.set()
        return True

    def _update(self, offer: dict, app_dir: Path) -> None:
        version = offer["version"]
        current = _version(self.root)
        folder = None
        try:
            _clear_downloads(app_dir.parent)
            folder = Path(tempfile.mkdtemp(prefix=DOWNLOAD_PREFIX, dir=app_dir.parent))
            archive = folder / offer["file"]
            agent = update_check.user_agent(current)

            def progress(done, total):
                total = total or offer["size"]
                percent = min(100, done * 100 // total) if total else None
                self._set(DOWNLOADING, downloading_text(version, percent), version=version)

            self._download(offer["archive"], archive, agent, self.cancel_asked, progress)
            self._download(offer["checksum"], Path(f"{archive}.sha256"), agent, self.cancel_asked,
                           lambda done, total: None, 64 * 1024)
            with self.lock:
                if self.cancel_asked.is_set():
                    raise Cancelled()
                # From here on, Cancel no longer works.
                self.state = {"state": INSTALLING, "text": INSTALLING_TEXT, "version": version}
            self.log(f"update: downloaded {version}, installing")
            names = app_paths.names(self.root)
            install = self._installer or load_installer(self.root).install
            said = []
            result = install(archive, app_dir, names["INSTALL_MARK"], names.get("APP_NAME") or "Kettle Video",
                             confirm_older=lambda old, new: False, say=said.append,
                             environ={k: v for k, v in self.environ.items() if k != NOTE_ENV})
            for line in said:
                for part in str(line).splitlines():
                    if part.strip():
                        self.log(f"update: {part.strip()}")
        except Cancelled:
            self.log("update: cancelled during the download; nothing was changed")
            self._set(CANCELLED, CANCELLED_TEXT)
            return
        except DownloadFailed as exc:
            self.log(f"update: couldn't download ({exc}); nothing was changed")
            self._set(FAILED, f"Couldn't download {version}: no connection. Nothing was changed."
                      if exc.offline else f"Couldn't download {version} right now. Nothing was changed. "
                      "Try again later.")
            return
        except OSError as exc:
            self.log(f"update: couldn't make the download folder ({type(exc).__name__}); nothing was changed")
            self._set(FAILED, f"Couldn't download {version}: there's no room for it. Nothing was changed.")
            return
        except Exception as exc:  # the installer itself failed to load or run
            self.log(f"update: the update step failed ({type(exc).__name__}); see above")
            self._set(FAILED, f"Couldn't update to {version}. Try again later, or run the installer again.")
            return
        finally:
            if folder is not None:
                shutil.rmtree(folder, ignore_errors=True)
        self._after_install(result, version, current, app_dir)

    def _after_install(self, result, version: str, current: str, app_dir: Path) -> None:
        outcome = result.outcome
        now = Path(os.path.realpath(app_dir))
        if outcome == "updated":
            self._restart(now, updated_text(version))
        elif outcome == "rolled back" and now == Path(os.path.realpath(self.root)):
            # Put back: this version, restarted as it was.
            self._restart(now, f"The update to {version} didn't work, so {current} was put back as it was.")
        elif outcome == "rolled back":
            self._set(FAILED, f"The update to {version} didn't work and {current} couldn't be put back. "
                      "Run the installer again.")
        elif "checksum" in (result.message or ""):
            self._set(FAILED, f"The download of {version} was damaged, so nothing was changed. Try again later.")
        else:
            self._set(FAILED, f"Couldn't update to {version}, so nothing was changed. Try again later.")

    def _restart(self, root: Path, note: str) -> None:
        self._set(RESTARTING, RESTARTING_TEXT)
        self.log(f"update: restarting in place ({note})")
        self.restart(root, note)

    # --- Pull the latest version (development copies) ---

    def start_pull(self) -> Optional[str]:
        if not update_check.is_development(self.root):
            return CANT_UPDATE_HERE
        refused = self._begin(PULLING, PULLING_TEXT)
        if refused:
            return refused
        self.log("update: pulling main")
        threading.Thread(target=self._pull, daemon=True).start()
        return None

    def _pull(self) -> None:
        # Every way out ends with plain words: the page never waits for ever.
        try:
            text, commit = self._pull_main()
            if commit is None and text == "current":
                self.log("update: not pulled (already up to date)")
                self._set(IDLE, up_to_date_text(self._head()))
                return
        except update_check.CheckFailed as exc:
            self.log(f"update: couldn't pull ({exc}); nothing was changed")
            self._set(FAILED, PULL_OFFLINE if exc.offline else PULL_LATER)
            return
        except Exception as exc:  # git missing, or anything else unexpected
            self.log(f"update: couldn't pull ({type(exc).__name__}); nothing was changed")
            self._set(FAILED, PULL_LATER)
            return
        if commit is None:
            self.log(f"update: not pulled ({text})")
            self._set(FAILED, text)
            return
        self._restart(self.root, pulled_text(commit))

    def _head(self) -> str:
        return self._git(self.root, ["rev-parse", "HEAD"], update_check.TIMEOUT_S).stdout.strip()

    def _clean(self) -> bool:
        done = self._git(self.root, ["status", "--porcelain", "--untracked-files=no"], update_check.TIMEOUT_S)
        return done.returncode == 0 and not done.stdout.strip()

    def _pull_main(self):
        """(words, new commit) after a fast-forward to the remote's main, or
        (the reason, None) with nothing changed. Raises CheckFailed."""
        branch = update_check.BRANCH
        if not self._clean():
            return LOCAL_CHANGES, None
        on = self._git(self.root, ["symbolic-ref", "--quiet", "--short", "HEAD"], update_check.TIMEOUT_S)
        if on.stdout.strip() != branch:
            return NOT_ON_MAIN, None
        remotes = self._git(self.root, ["remote"], update_check.TIMEOUT_S).stdout.split()
        if not remotes:
            raise update_check.CheckFailed("no remote")
        remote = "origin" if "origin" in remotes else remotes[0]
        fetched = self._git(self.root, ["fetch", "--quiet", "--no-tags", remote, branch], PULL_TIMEOUT_S)
        if fetched.returncode != 0:
            said = fetched.stderr.lower()
            raise update_check.CheckFailed("the remote didn't answer",
                                           any(w in said for w in update_check.OFFLINE_WORDS))
        before = self._head()
        # Checked again just before: the pull never goes over changes.
        if not self._clean():
            return LOCAL_CHANGES, None
        merged = self._git(self.root, ["merge", "--ff-only", "--quiet", "FETCH_HEAD"], update_check.TIMEOUT_S)
        if merged.returncode != 0:
            return MOVED_AWAY, None
        after = self._head()
        if after == before:
            return "current", None
        self.log(f"update: main pulled, {before[:7]} to {after[:7]}")
        return "pulled", after

    # --- Try a branch, Back to main, Restore data (development copies) ---

    def can_switch(self) -> bool:
        """A development copy with its own data folder: the branch rows show."""
        return self.data_dir is not None and self.settings_file is not None \
            and update_check.is_development(self.root)

    def branch_state(self) -> Optional[dict]:
        """For Settings › About, read from the device only (never online):
        the branch the copy is on (None on main), its label, and the newest
        backup. None when this copy can't switch."""
        if not self.can_switch():
            return None
        try:
            branch = try_branch.current_branch(self.root, self._git)
            commit = None if branch else try_branch.head(self.root, self._git)
        except Exception as exc:  # git missing: no branch rows to offer
            self.log(f"try a branch: couldn't read the branch ({type(exc).__name__})")
            return None
        backups = try_branch.list_backups(self.data_dir)
        on = None
        if branch != try_branch.MAIN:
            name = branch or (commit or "")[:7]
            label = next((b.get("to_label") for b in backups if b.get("to") == branch and branch), None)
            on = {"branch": name, "label": label or name}
        return {"on": on, "restore": try_branch.backup_summary(backups[0]) if backups else None}

    def list_branches(self) -> dict:
        """Try a branch's list: the one time it goes online, only when the
        designer chooses it. {"ok": True, "branches": [...], "titles": bool}
        or {"ok": False, "text": why}."""
        if not self.can_switch():
            return {"ok": False, "text": CANT_UPDATE_HERE}
        if not self.list_lock.acquire(blocking=False):
            return {"ok": False, "text": try_branch.LISTING_TEXT}
        try:
            current = try_branch.current_branch(self.root, self._git)
            names = try_branch.remote_branches(self.root, self._git)
            try:
                pulls, titles = self._pulls(_version(self.root)), True
            except update_check.CheckFailed as exc:
                self.log(f"try a branch: no pull request list ({exc}); branches only")
                pulls, titles = [], False
        except update_check.CheckFailed as exc:
            self.log(f"try a branch: couldn't list the branches ({exc})")
            return {"ok": False, "text": try_branch.LIST_OFFLINE if exc.offline else try_branch.LIST_LATER}
        except Exception as exc:  # git missing, or anything else unexpected
            self.log(f"try a branch: couldn't list the branches ({type(exc).__name__})")
            return {"ok": False, "text": try_branch.LIST_LATER}
        finally:
            self.list_lock.release()
        rows = try_branch.picker_list(names, pulls, current)
        with self.lock:
            self.listed = {row["branch"]: row["label"] for row in rows}
        self.log(f"try a branch: {len(rows)} branches listed, "
                 f"{sum(1 for row in rows if row['pull'])} with an open pull request")
        if not rows:
            return {"ok": False, "text": try_branch.NO_BRANCHES}
        return {"ok": True, "branches": rows, "titles": titles}

    def start_switch(self, branch: str) -> Optional[str]:
        """Switch to a branch from the last list. None once started."""
        if not self.can_switch():
            return CANT_UPDATE_HERE
        with self.lock:
            label = self.listed.get(branch) if isinstance(branch, str) else None
        if label is None:
            return try_branch.NOT_LISTED
        return self._start_branch(branch, label, fetch=True)

    def start_back_to_main(self) -> Optional[str]:
        """Back to the copy's own main, never online. None once started."""
        if not self.can_switch():
            return CANT_UPDATE_HERE
        try:
            if try_branch.current_branch(self.root, self._git) == try_branch.MAIN:
                return try_branch.ALREADY_ON_MAIN
        except Exception:
            return try_branch.SWITCH_LATER
        return self._start_branch(try_branch.MAIN, try_branch.MAIN, fetch=False)

    def _start_branch(self, branch: str, label: str, fetch: bool) -> Optional[str]:
        refused = self._begin(SWITCHING, try_branch.switching_text(label))
        if refused:
            return refused
        self.log(f"try a branch: switching to {branch}")
        threading.Thread(target=self._switch, args=(branch, label, fetch), daemon=True).start()
        return None

    def _switch(self, branch: str, label: str, fetch: bool) -> None:
        # Every way out ends with plain words: the page never waits for ever.
        git, root = self._git, self.root
        backup = None
        try:
            # This copy's own start check, read before anything changes.
            start_check = self._start_check or load_installer(root).started_cleanly
            before_branch = try_branch.current_branch(root, git)
            before = try_branch.head(root, git)
            start = try_branch.fetch_branch(root, git, branch) if fetch else None
            try_branch.ready(root, git, branch, start)
            if try_branch.unsafe_data_dir(self.data_dir, root, self.media_roots(), self.environ):
                raise try_branch.Refused(try_branch.UNSAFE_DATA)
            self._set(BACKING_UP, try_branch.BACKING_UP_TEXT)
            try:
                backup = try_branch.make_backup(self.data_dir, self.settings_file, {
                    "from": before_branch, "from_label": self._label_of(before_branch),
                    "commit": before, "to": branch, "to_label": label}, self._now())
            except OSError as exc:
                self.log(f"try a branch: couldn't back up the data ({type(exc).__name__}); nothing was changed")
                raise try_branch.Refused(try_branch.BACKUP_FAILED)
            self.log(f"try a branch: data backed up ({backup['id']})")
            self._set(SWITCHING, try_branch.switching_text(label))
            try_branch.switch_to(root, git, branch, start)
        except try_branch.Refused as exc:
            if backup is not None:
                try_branch.remove_backup(self.data_dir, backup["id"])
            self.log(f"try a branch: not switched ({exc})")
            self._set(FAILED, str(exc))
            return
        except update_check.CheckFailed as exc:
            self.log(f"try a branch: couldn't switch ({exc}); nothing was changed")
            self._set(FAILED, try_branch.SWITCH_OFFLINE if exc.offline else try_branch.SWITCH_LATER)
            return
        except Exception as exc:  # git missing, or anything else unexpected
            if backup is not None:
                try_branch.remove_backup(self.data_dir, backup["id"])
            self.log(f"try a branch: couldn't switch ({type(exc).__name__}); nothing was changed")
            self._set(FAILED, try_branch.SWITCH_LATER)
            return
        self._set(CHECKING_START, try_branch.CHECKING_TEXT)
        try:
            ok, why = start_check(root, {k: v for k, v in self.environ.items() if k != NOTE_ENV})
        except Exception as exc:
            ok, why = False, f"the check itself failed ({type(exc).__name__})"
        if not ok:
            back = try_branch.go_back(root, git, before_branch, before)
            try_branch.remove_backup(self.data_dir, backup["id"])
            back_on = self._label_of(before_branch) or before[:7]
            self.log(f"try a branch: {branch} didn't start cleanly: {why} "
                     f"({'back on' if back else 'could not go back to'} {back_on})")
            self._set(FAILED, try_branch.didnt_start_text(label, back_on, why) if back
                      else f"{label} didn't start, and Kettle Video couldn't go back to {back_on}. "
                           "Choose Back to main.")
            return
        self.log(f"try a branch: now on {branch} ({try_branch.head(root, git)[:7]})")
        self._restart(root, "Back on main" if branch == try_branch.MAIN else try_branch.now_on_text(label))

    def _label_of(self, branch: Optional[str]) -> Optional[str]:
        if branch is None:
            return None
        with self.lock:
            listed = self.listed.get(branch)
        if listed:
            return listed
        for backup in try_branch.list_backups(self.data_dir):
            if backup.get("to") == branch and backup.get("to_label"):
                return backup["to_label"]
        return branch

    def start_restore(self, backup_id: str) -> Optional[str]:
        """Restore data from before the last switch: only the newest backup,
        the one the confirm named. None once started."""
        if not self.can_switch():
            return CANT_UPDATE_HERE
        backups = try_branch.list_backups(self.data_dir)
        if not backups or backups[0]["id"] != backup_id:
            return try_branch.NO_BACKUP
        if try_branch.unsafe_data_dir(self.data_dir, self.root, self.media_roots(), self.environ):
            return try_branch.UNSAFE_RESTORE
        refused = self._begin(RESTORING, try_branch.RESTORING_TEXT)
        if refused:
            return refused
        self.log(f"try a branch: restoring the data from {backup_id}")
        threading.Thread(target=self._restore, args=(backups[0],), daemon=True).start()
        return None

    def _restore(self, backup: dict) -> None:
        try:
            try_branch.restore(self.data_dir, self.settings_file, backup)
        except Exception as exc:
            self.log(f"try a branch: couldn't restore ({type(exc).__name__}); the data is as it was")
            self._set(FAILED, try_branch.RESTORE_FAILED)
            return
        self.log(f"try a branch: data restored from {backup['id']}")
        self._restart(self.root, try_branch.restored_text(backup))


def _version(root: Path) -> str:
    try:
        return (Path(root) / "VERSION").read_text(encoding="utf-8").strip() or "unknown"
    except (OSError, UnicodeDecodeError):
        return "unknown"


def _clear_downloads(parent: Path) -> None:
    """Download folders left by an update cut short (power off). Only this
    app's own: real folders named DOWNLOAD_PREFIX… beside the app folder."""
    try:
        entries = list(Path(parent).iterdir())
    except OSError:
        return
    for entry in entries:
        if entry.name.startswith(DOWNLOAD_PREFIX) and entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry, ignore_errors=True)
