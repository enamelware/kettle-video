# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Try a branch, Back to main, and the data backups that go with them (the
"Try a branch" work). Development copies only: a git checkout without the
installer's mark (update_check.is_development). A release install never
shows, runs or reads any of this.

Going online. Only "Try a branch" does, and only when the designer chooses
it: one git ls-remote for the remote's branches, one request to GitHub's
public pull request list for this app's repo (no token, no login, no
cookies, a plain user agent), and, once a branch is chosen, one git fetch of
that branch. If the pull request list can't be fetched, the branches are
still listed, without issue titles. "Back to main" and "Restore data" never
go online: Back to main switches to the copy's own main, which "Pull the
latest version" brings up to date.

Switching. Only with no local changes (nothing is ever discarded or
stashed), and a local branch is only ever moved forward. Before every
switch, everything the app saves is backed up (see below); a failed backup
stops the switch. After the switch, the branch must start cleanly (the
installer's own start check, as a fresh start, so it never opens the data
folder); if it doesn't, the copy goes back to where it was, its backup is
removed again, and nothing is changed.

Backups. In a "backups" folder inside this copy's own data folder: a copy
of the data folder (library, Continue watching and its pictures, the
update check's date) and of settings.json (the folders and settings).
Nothing outside them: mpv's resume positions stay in mpv's own folder,
shared with any other mpv use, and the kiosk Firefox profile holds nothing
of the app's (both decided on the issue). Media files are never copied: a
data folder that is a media folder, is inside one or holds one is refused,
and so is one inside an installed copy's own places. Shortcuts are copied
as shortcuts, never followed. The last KEEP backups are kept; making a new
one deletes the oldest. Restore puts the newest one back exactly, after a
confirm naming its branch and date.

Pure logic apart from git (passed in as `git`, update_check._git's shape)
and fetch_pulls(), which the tests replace with stand-ins.
"""

import json
import os
import re
import shutil
import tempfile
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping, Optional

from backend import app_paths, update_check

PULLS_URL = f"https://api.github.com/repos/{update_check.REPO}/pulls?state=open&per_page=100"
MAIN = update_check.BRANCH
BACKUPS = "backups"
KEEP = 3
INFO = "backup.json"
DATA = "data"
SETTINGS = "settings.json"
# A finished backup's folder name: when it was made, to the second, then a
# number if two were made in the same second.
NAME = re.compile(r"^\d{8}-\d{6}(-\d+)?$")
MAKING = ".making-"
RESTORING = ".restoring-"
REPLACED = ".replaced-"
ISSUE_BRANCH = re.compile(r"^issue-(\d+)(?:\b|$)")
SWITCH_TIMEOUT_S = 120

# The words the page shows.
LISTING_TEXT = "Listing branches…"
LIST_OFFLINE = "Couldn't list the branches: no connection."
LIST_LATER = "Couldn't list the branches right now. Try again later."
NO_BRANCHES = "There are no other branches to try."
BACKING_UP_TEXT = "Backing up your data…"
CHECKING_TEXT = "Checking that it starts…"
RESTORING_TEXT = "Putting your data back…"
LOCAL_CHANGES = "Not switched: this copy has changes of its own. Nothing was changed."
OWN_COMMITS = "Not switched: this copy's {branch} has changes of its own. Nothing was changed."
NOT_LISTED = "List the branches first."
NO_SUCH_BRANCH = "That branch is no longer on GitHub. Nothing was changed."
SWITCH_OFFLINE = "Couldn't switch: no connection. Nothing was changed."
SWITCH_LATER = "Couldn't switch right now. Nothing was changed. Try again later."
BACKUP_FAILED = "Not switched: your data couldn't be backed up. Nothing was changed."
UNSAFE_DATA = ("Not switched: the data folder in settings.json isn't this copy's own, "
               "so it isn't backed up. Nothing was changed.")
UNSAFE_RESTORE = ("Not restored: the data folder in settings.json isn't this copy's own. "
                  "Nothing was changed.")
ALREADY_ON_MAIN = "Already on main."
NO_MAIN = "This copy has no main to go back to. Nothing was changed."
NO_BACKUP = "There is no backup to restore."
RESTORE_FAILED = "Couldn't put your data back. It is as it was before you chose Restore."
BACK_ON_MAIN_AT_START = "Back on main, with your data backed up. Close this, then start Kettle Video again."
BACK_AT_START_FAILED = "Couldn't go back to main. Nothing was changed."
MONTHS = update_check.MONTHS


def didnt_start_text(label: str, back_on: str, why: str) -> str:
    return f"{label} didn't start, so Kettle Video stayed on {back_on}. Nothing was changed. ({why})"


def switching_text(label: str) -> str:
    return f"Switching to {label}…"


def now_on_text(label: str) -> str:
    return f"Now on {label}"


def restored_text(info: dict) -> str:
    return f"Your data is back as it was on {when_text(info)}"


# --- Which branch ---

def current_branch(root: Path, git: Callable) -> Optional[str]:
    """The branch this copy is on, or None (no branch: a detached commit)."""
    done = git(root, ["symbolic-ref", "--quiet", "--short", "HEAD"], update_check.TIMEOUT_S)
    name = done.stdout.strip() if done.returncode == 0 else ""
    return name or None


def issue_number(branch: str) -> Optional[int]:
    found = ISSUE_BRANCH.match(branch or "")
    return int(found.group(1)) if found else None


def clean(root: Path, git: Callable) -> bool:
    """No changes of its own to files git follows (settings.json, data/ and
    logs/ are ignored by git, so they never count)."""
    done = git(root, ["status", "--porcelain", "--untracked-files=no"], update_check.TIMEOUT_S)
    return done.returncode == 0 and not done.stdout.strip()


def _remote(root: Path, git: Callable) -> str:
    remotes = git(root, ["remote"], update_check.TIMEOUT_S).stdout.split()
    if not remotes:
        raise update_check.CheckFailed("no remote")
    return "origin" if "origin" in remotes else remotes[0]


def _failed(done, why: str) -> update_check.CheckFailed:
    said = (done.stderr or "").lower()
    return update_check.CheckFailed(why, any(w in said for w in update_check.OFFLINE_WORDS))


# --- Listing (online, only when the designer chooses Try a branch) ---

def remote_branches(root: Path, git: Callable) -> list:
    """The branch names on the copy's remote. Changes nothing here."""
    remote = _remote(root, git)
    done = git(root, ["ls-remote", "--quiet", "--heads", remote], update_check.TIMEOUT_S)
    if done.returncode != 0:
        raise _failed(done, "the remote didn't answer")
    names = []
    for line in done.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].startswith("refs/heads/"):
            names.append(parts[1][len("refs/heads/"):])
    return names


def pulls_request(version: str) -> urllib.request.Request:
    """The one request for the open pull requests: nothing but the question
    and a plain user agent, no token, no cookies."""
    return urllib.request.Request(PULLS_URL, method="GET", headers={
        "User-Agent": update_check.user_agent(version),
        "Accept": "application/vnd.github+json",
    })


def fetch_pulls(version: str, timeout: float = update_check.TIMEOUT_S) -> list:
    """GitHub's open pull requests for this app's repo, as
    [{"branch", "number", "title"}]. Raises CheckFailed."""
    opener = urllib.request.build_opener()
    try:
        with opener.open(pulls_request(version), timeout=timeout) as answer:
            data = json.loads(answer.read(5_000_000).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        exc.close()
        raise update_check.CheckFailed(f"GitHub answered {exc.code}")
    except urllib.error.URLError as exc:
        raise update_check.CheckFailed(f"no answer ({type(exc.reason).__name__})",
                                       update_check._offline(exc.reason))
    except OSError as exc:
        raise update_check.CheckFailed(f"no answer ({type(exc).__name__})", update_check._offline(exc))
    except (ValueError, UnicodeDecodeError):
        raise update_check.CheckFailed("an answer that isn't a pull request list")
    return pulls_from(data)


def pulls_from(data) -> list:
    """The parts of GitHub's answer the picker needs; anything else is left out."""
    pulls = []
    for pull in data if isinstance(data, list) else []:
        if not isinstance(pull, dict) or not isinstance(pull.get("head"), dict):
            continue
        branch, number, title = pull["head"].get("ref"), pull.get("number"), pull.get("title")
        if isinstance(branch, str) and isinstance(number, int) and isinstance(title, str):
            pulls.append({"branch": branch, "number": number, "title": title.strip()})
    return pulls


def _plain_title(title: str, number: int) -> str:
    """A pull request title without a leading "Refs #N:" or "#N", which the
    label already says."""
    return re.sub(rf"^(?:refs\s+)?#{number}\s*[:·\-–—]?\s*", "", title, flags=re.I).strip() or title


def picker_list(branches: list, pulls: Optional[list], current: Optional[str]) -> list:
    """The picker's rows: branches with an open pull request first (newest
    first), as "#N · title" with the branch under it (unless it is just
    issue-N), then the others by
    name. main is left out ("Back to main" is its own row). The branch the
    copy is on is marked current."""
    on_remote = set(branches)
    by_branch = {}
    for pull in pulls or []:
        if pull["branch"] in on_remote and pull["branch"] != MAIN:
            by_branch.setdefault(pull["branch"], pull)
    rows = []
    for branch, pull in sorted(by_branch.items(), key=lambda item: -item[1]["number"]):
        number = issue_number(branch) or pull["number"]
        # The branch under the title, unless it only repeats the number
        # (issue-40 under "#N · …"): a shorter row fits the smallest window.
        desc = None if branch == f"issue-{number}" else branch
        rows.append({"branch": branch, "label": f"#{number} · {_plain_title(pull['title'], pull['number'])}",
                     "desc": desc, "open_pull": True})
    for branch in sorted(b for b in on_remote if b not in by_branch and b != MAIN):
        rows.append({"branch": branch, "label": branch, "desc": None, "open_pull": False})
    for row in rows:
        row["current"] = row["branch"] == current
    return rows


# --- Switching ---

class Refused(Exception):
    """A switch that didn't start, with nothing changed: the plain words."""


def fetch_branch(root: Path, git: Callable, branch: str) -> str:
    """Bring the remote's branch into the copy's remote-tracking branch
    (changes no working file). The name to switch to. Raises CheckFailed,
    or Refused when the branch is gone."""
    remote = _remote(root, git)
    done = git(root, ["fetch", "--quiet", "--no-tags", remote,
                      f"+refs/heads/{branch}:refs/remotes/{remote}/{branch}"], SWITCH_TIMEOUT_S)
    if done.returncode != 0:
        if "couldn't find remote ref" in (done.stderr or "").lower():
            raise Refused(NO_SUCH_BRANCH)
        raise _failed(done, "the remote didn't answer")
    return f"{remote}/{branch}"


def _has(root: Path, git: Callable, ref: str) -> bool:
    return git(root, ["rev-parse", "--verify", "--quiet", ref], update_check.TIMEOUT_S).returncode == 0


def ready(root: Path, git: Callable, branch: str, start: Optional[str]) -> None:
    """Raises Refused unless the copy can switch to branch with nothing
    lost: no changes of its own, and a local branch of that name only ever
    moved forward (to start, the remote-tracking branch). With start None,
    the local branch must be there."""
    if not clean(root, git):
        raise Refused(LOCAL_CHANGES)
    local = f"refs/heads/{branch}"
    if start is None:
        if not _has(root, git, local):
            raise Refused(NO_MAIN)
    elif _has(root, git, local):
        ahead = git(root, ["merge-base", "--is-ancestor", local, start], update_check.TIMEOUT_S)
        if ahead.returncode != 0:
            raise Refused(OWN_COMMITS.format(branch=branch))


def switch_to(root: Path, git: Callable, branch: str, start: Optional[str]) -> None:
    """Switch the copy to branch, made from (or moved forward to) start, the
    remote-tracking branch; with start None, the local branch as it is.
    Never over changes of its own, never moving a local branch anywhere but
    forward. Raises Refused with nothing changed."""
    ready(root, git, branch, start)
    if start is None:
        args = ["switch", "--quiet", branch]
    else:
        args = ["switch", "--quiet", "--track", "-C", branch, start]
    done = git(root, args, update_check.TIMEOUT_S)
    if done.returncode != 0:
        raise Refused(SWITCH_LATER)


def back_to_main_at_start(root: Path, git: Callable, data_dir: Path, settings_file: Path, media_roots,
                          environ: Mapping[str, str], now: datetime) -> str:
    """Back to main from the start-up problem screen, when a branch couldn't
    start: the same rules as Back to main in Settings (no changes of its
    own, the data backed up first, never online), done at once. No start
    check: Kettle Video is started again by hand. The plain words to show;
    raises Refused with nothing changed."""
    before_branch = current_branch(root, git)
    if before_branch == MAIN:
        raise Refused(ALREADY_ON_MAIN)
    before = head(root, git)
    ready(root, git, MAIN, None)
    if unsafe_data_dir(data_dir, root, media_roots, environ):
        raise Refused(UNSAFE_DATA)
    label = next((b["to_label"] for b in list_backups(data_dir)
                  if before_branch and b.get("to") == before_branch and b.get("to_label")), before_branch)
    try:
        backup = make_backup(data_dir, settings_file, {
            "from": before_branch, "from_label": label, "commit": before, "to": MAIN, "to_label": MAIN}, now)
    except OSError:
        raise Refused(BACKUP_FAILED)
    try:
        switch_to(root, git, MAIN, None)
    except Refused:
        remove_backup(data_dir, backup["id"])
        raise
    return BACK_ON_MAIN_AT_START


def head(root: Path, git: Callable) -> str:
    return git(root, ["rev-parse", "HEAD"], update_check.TIMEOUT_S).stdout.strip()


def go_back(root: Path, git: Callable, branch: Optional[str], commit: str) -> bool:
    """Put the copy back where it was before a switch (its branch, or the
    commit it was on). True when it is."""
    args = ["switch", "--quiet", branch] if branch else ["switch", "--quiet", "--detach", commit]
    git(root, args, update_check.TIMEOUT_S)
    return head(root, git) == commit and current_branch(root, git) == branch


# --- Backups ---

def _inside(path: Path, folder: Path) -> bool:
    try:
        path.relative_to(folder)
        return True
    except ValueError:
        return False


def unsafe_data_dir(data_dir: Path, root: Path, media_roots, environ: Mapping[str, str] = os.environ) -> bool:
    """True when the data folder can't be backed up or restored safely: it
    is missing as a path, a media folder, inside one or holding one, or
    inside an installed copy's own places (a release install's data is never
    touched)."""
    if not data_dir:
        return True
    data = Path(os.path.realpath(data_dir))
    for media in media_roots or ():
        if not media:
            continue
        media = Path(os.path.realpath(media))
        if _inside(data, media) or _inside(media, data):
            return True
    app_id = app_paths.names(Path(root))["APP_ID"]
    places = app_paths.install_places(app_id, environ)
    for place in (places["DATA_DIR"].parent, places["CONFIG_DIR"], places["LOGS_DIR"].parent):
        place = Path(os.path.realpath(place))
        if _inside(data, place) or _inside(place, data):
            return True
    return False


def backups_dir(data_dir: Path) -> Path:
    return Path(data_dir) / BACKUPS


def _read_info(folder: Path) -> Optional[dict]:
    try:
        info = json.loads((folder / INFO).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(info, dict) or not isinstance(info.get("made"), str):
        return None
    try:
        datetime.fromisoformat(info["made"])
    except ValueError:
        return None
    return info


def list_backups(data_dir: Path) -> list:
    """The finished backups, newest first, as {"id", "path", **info}."""
    folder = backups_dir(data_dir)
    try:
        entries = list(folder.iterdir())
    except OSError:
        return []
    found = []
    for entry in entries:
        if not NAME.match(entry.name) or entry.is_symlink() or not entry.is_dir():
            continue
        info = _read_info(entry)
        if info is not None:
            found.append({**info, "id": entry.name, "path": entry})
    found.sort(key=lambda b: (b["made"], b["id"]), reverse=True)
    return found


def _remove(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        path.unlink(missing_ok=True)
    else:
        shutil.rmtree(path)


def _copy_entry(source: Path, target: Path) -> None:
    """One file or folder, shortcuts copied as shortcuts (never followed)."""
    if source.is_symlink():
        os.symlink(os.readlink(source), target)
    elif source.is_dir():
        shutil.copytree(source, target, symlinks=True)
    else:
        shutil.copy2(source, target)


def prune(data_dir: Path, keep: int = KEEP) -> list:
    """Delete the oldest finished backups past keep, and anything a backup
    or restore cut short left behind. Only this app's own folders in
    backups/. The ids deleted."""
    folder = backups_dir(data_dir)
    deleted = []
    for old in list_backups(data_dir)[keep:]:
        shutil.rmtree(old["path"], ignore_errors=True)
        deleted.append(old["id"])
    try:
        entries = list(folder.iterdir())
    except OSError:
        return deleted
    for entry in entries:
        if entry.name.startswith((MAKING, RESTORING, REPLACED)) and entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry, ignore_errors=True)
    return deleted


def make_backup(data_dir: Path, settings_file: Path, info: dict, now: datetime, keep: int = KEEP) -> dict:
    """Copy the data folder (all but backups/) and settings.json into a new
    backup, then keep only the newest `keep`. Made beside its final place and
    renamed into it, so a backup cut short is never taken for a finished one.
    Raises OSError with nothing left behind."""
    data_dir = Path(data_dir)
    folder = backups_dir(data_dir)
    folder.mkdir(parents=True, exist_ok=True)
    making = Path(tempfile.mkdtemp(prefix=MAKING, dir=folder))
    try:
        (making / DATA).mkdir()
        for entry in sorted(data_dir.iterdir()):
            if entry.name == BACKUPS:
                continue
            _copy_entry(entry, making / DATA / entry.name)
        if Path(settings_file).is_file():
            shutil.copy2(settings_file, making / SETTINGS)
        made = {**info, "made": now.isoformat(timespec="seconds"),
                "settings": Path(settings_file).is_file()}
        (making / INFO).write_text(json.dumps(made, indent=2) + "\n", encoding="utf-8")
        stamp = now.strftime("%Y%m%d-%H%M%S")
        name, number = stamp, 1
        while (folder / name).exists():
            number += 1
            name = f"{stamp}-{number}"
        os.rename(making, folder / name)
    except BaseException:
        shutil.rmtree(making, ignore_errors=True)
        raise
    prune(data_dir, keep)
    return {**made, "id": name, "path": folder / name}


def remove_backup(data_dir: Path, backup_id: str) -> None:
    if NAME.match(backup_id or ""):
        shutil.rmtree(backups_dir(data_dir) / backup_id, ignore_errors=True)


def restore(data_dir: Path, settings_file: Path, backup: dict) -> None:
    """Put the data folder (all but backups/) and settings.json back exactly
    as the backup has them. Staged first; if anything fails part way, what
    was there is put back. Raises OSError."""
    data_dir = Path(data_dir)
    folder = backups_dir(data_dir)
    source = Path(backup["path"])
    staged = Path(tempfile.mkdtemp(prefix=RESTORING, dir=folder))
    replaced = Path(tempfile.mkdtemp(prefix=REPLACED, dir=folder))
    try:
        for entry in sorted((source / DATA).iterdir()):
            _copy_entry(entry, staged / entry.name)
        settings_copy = source / SETTINGS
        if backup.get("settings") and settings_copy.is_file():
            shutil.copy2(settings_copy, staged / f".{SETTINGS}")
        moved, placed = [], []
        try:
            for entry in sorted(data_dir.iterdir()):
                if entry.name == BACKUPS:
                    continue
                os.rename(entry, replaced / entry.name)
                moved.append(entry.name)
            for entry in sorted(staged.iterdir()):
                if entry.name == f".{SETTINGS}":
                    continue
                os.rename(entry, data_dir / entry.name)
                placed.append(entry.name)
            if (staged / f".{SETTINGS}").exists():
                os.replace(staged / f".{SETTINGS}", settings_file)
        except OSError:
            for name in placed:
                _remove(data_dir / name)
            for name in moved:
                os.rename(replaced / name, data_dir / name)
            raise
    finally:
        shutil.rmtree(staged, ignore_errors=True)
        shutil.rmtree(replaced, ignore_errors=True)


def when_text(info: dict) -> str:
    made = datetime.fromisoformat(info["made"])
    return f"{made.day} {MONTHS[made.month - 1]} at {made:%H:%M}"


def backup_summary(info: dict) -> dict:
    """What the page shows of the newest backup: its id, the row's meta and
    the confirm's question, naming the branch and the date."""
    on = info.get("from_label") or info.get("from") or "a commit with no branch"
    return {"id": info["id"],
            "text": f"Saved {when_text(info)}, on {on}",
            "question": f"Put back your data as it was on {when_text(info)}, on {on}? "
                        "Kettle Video will restart."}
