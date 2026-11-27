# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The release script (the release script work). Developer only: users never run it.

From a release tag it builds the archive the installer installs, the
archive's checksum and the release's notes:

    python3 tools/release.py TAG [--out FOLDER] [--repo FOLDER] [--list FILE]

    TAG       a release tag, v<VERSION>: the tag's own VERSION file must say
              the same version (v0.1.0-dev for VERSION 0.1.0-dev)
    --out     where the four files go (default: dist/ in the repo, which
              git ignores)
    --repo    the git repo to read the tag from (default: this one)
    --list    the privacy guard's word list (default: the guard's own)

It writes, named from installer/names.env (the one place for installer
names):

    <ARCHIVE_NAME>-<version>.tar.gz          the app and its licence files
    <ARCHIVE_NAME>-<version>.tar.gz.sha256   its SHA-256 checksum, in the
                                             format `sha256sum -c` reads
    <ARCHIVE_NAME>-<version>-notes.md        the CHANGELOG.md entry for the
                                             version
    install.sh                               the installer (the installer work), the
                                             tag's installer/install.sh with
                                             names.env's lines and
                                             installer/update.py (the installer's update step)
                                             written in, so it works on its
                                             own next to the archive

Privacy: everything is read from the tag's tracked files with git, never
from the working folder, so nothing that only exists on this device
(settings.json, data/, logs/, anything untracked) can get in. Only the
app's own folders and files are taken (INCLUDED below); tests, spikes,
tools, scripts, docs and Claude Code's files stay out. The release check
(tools/release_check.py, the release check work, which includes the privacy guard) then
checks every file in the archive, the notes and install.sh; if it finds
anything, or the privacy guard's list is missing, nothing is written. The
whole repo gets the same check as a release step of its own
(docs/dev-environment.md, "Release check").

Standard library only. Until the repo is public the installer takes its
archive from this script's output; after that, the same files go on the
GitHub release.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import re
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT))
import privacy_guard  # noqa: E402
import release_check  # noqa: E402
# names.env is read the one way the app reads it (the installer review fixes).
from backend.app_paths import read_names  # noqa: E402

NAMES_FILE = "installer/names.env"
# Every name names.env must give; a release without one of them is never
# built (the installer review fixes).
NAME_KEYS = ("APP_NAME", "APP_ID", "ARCHIVE_NAME", "INSTALL_FOLDER", "DESKTOP_ENTRY",
             "DEV_DESKTOP_ENTRY", "INSTALL_MARK", "ICON_FILE", "FIREFOX_PROFILE",
             "DEV_FIREFOX_PROFILE")
INSTALLER = "installer/install.sh"
# The shared update step install.sh runs (the installer's update step).
UPDATER = "installer/update.py"
# The block in install.sh that the release fills with names.env's lines.
NAMES_START = "# --- names ---"
NAMES_END = "# --- end names ---"
# The block the release fills with update.py's text, and the line that ends
# that text inside the script.
UPDATE_START = "# --- update logic ---"
UPDATE_END = "# --- end update logic ---"
UPDATE_DELIMITER = "KETTLE_VIDEO_UPDATE_PY"

# What the archive holds: the app, what it runs on, and its licences.
INCLUDED_FILES = {"LICENSE", "THIRD_PARTY_LICENSES.md", "README.md", "VERSION",
                  "CHANGELOG.md", "launch.sh", "install-shortcut.sh",
                  "settings.example.json"}
INCLUDED_FOLDERS = ("backend/", "ui/", "vendor/", "installer/")
# A release without these is never built.
REQUIRED_FILES = ("LICENSE", "THIRD_PARTY_LICENSES.md", "VERSION")


class ReleaseProblem(Exception):
    """Something that stops the release, said in plain words."""


# ---------------------------------------------------------------- pieces

def included(path):
    """True for a file that belongs in the archive."""
    return path in INCLUDED_FILES or path.startswith(INCLUDED_FOLDERS)


_HEADING = re.compile(r"^##\s+\[?([^\]\s]+)\]?")


def changelog_entry(text, version):
    """The notes under `## <version>` (up to the next `## `), or None."""
    lines, found = [], False
    for line in text.splitlines():
        heading = _HEADING.match(line) if line.startswith("## ") else None
        if heading:
            if found:
                break
            found = heading.group(1) == version
            continue
        if found:
            lines.append(line)
    if not found:
        return None
    return "\n".join(lines).strip() + "\n"


def _replace_block(script, start, end, body):
    """script with the lines between its start and end lines replaced by
    body (a list of lines). None if the pair isn't there exactly once."""
    lines = script.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if line.strip() == start]
    ends = [i for i, line in enumerate(lines) if line.strip() == end]
    if len(starts) != 1 or len(ends) != 1 or ends[0] < starts[0]:
        return None
    return "".join(lines[:starts[0] + 1] + body + lines[ends[0]:])


def standalone_installer(script, names_text, updater_text):
    """install.sh with its names block holding names.env's KEY="value"
    lines and its update block holding update.py's text (the installer's update step), so it
    needs no other file. None if a block isn't there or update.py's text
    can't be written in safely."""
    values = [line.strip() + "\n" for line in names_text.splitlines()
              if line.strip() and not line.strip().startswith("#") and "=" in line]
    script = _replace_block(script, NAMES_START, NAMES_END,
                            ["# Written in by tools/release.py from installer/names.env.\n",
                             *values])
    if script is None or "\0" in updater_text or any(
            line.strip() == UPDATE_DELIMITER for line in updater_text.splitlines()):
        return None
    code = updater_text if updater_text.endswith("\n") else updater_text + "\n"
    return _replace_block(script, UPDATE_START, UPDATE_END, [
        f"# Written in by tools/release.py from {UPDATER}.\n",
        'UPDATER=""\n',
        f"IFS= read -r -d '' UPDATER_CODE <<'{UPDATE_DELIMITER}'\n",
        code,
        f"{UPDATE_DELIMITER}\n",
    ])


def sha256_line(data, filename):
    """One line in the format `sha256sum -c` checks."""
    return f"{hashlib.sha256(data).hexdigest()}  {filename}\n"


# ---------------------------------------------------------------- git

def _git(repo, *args):
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True)
    if result.returncode != 0:
        raise ReleaseProblem("git couldn't read the repo: "
                             + result.stderr.decode("utf-8", "replace").strip())
    return result.stdout


def _tag_exists(repo, tag):
    result = subprocess.run(["git", "rev-parse", "--verify", "--quiet",
                             f"refs/tags/{tag}^{{commit}}"],
                            cwd=repo, capture_output=True)
    return result.returncode == 0


def _tag_file(repo, tag, path):
    """A file's text at the tag, or None if the tag doesn't hold it."""
    result = subprocess.run(["git", "show", f"refs/tags/{tag}:{path}"],
                            cwd=repo, capture_output=True)
    if result.returncode != 0:
        return None
    return result.stdout.decode("utf-8", "replace")


def tag_files(repo, tag):
    """[(path, tarinfo, bytes)] for every tracked file at the tag."""
    raw = _git(repo, "archive", "--format=tar", f"refs/tags/{tag}")
    out = []
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as tar:
        for member in tar.getmembers():
            if not (member.isfile() or member.issym()):
                continue
            data = tar.extractfile(member).read() if member.isfile() else b""
            out.append((member.name, member, data))
    return out


# ---------------------------------------------------------------- the release

def plan(repo, tag):
    """Check the tag and read what the release needs from it. Returns
    (version, names, notes, installer). Raises ReleaseProblem in plain words."""
    if not _tag_exists(repo, tag):
        raise ReleaseProblem(f"There is no tag called {tag}. Make the release tag "
                             "first (v followed by the version in VERSION).")
    version_text = _tag_file(repo, tag, "VERSION")
    if version_text is None or not version_text.strip():
        raise ReleaseProblem(f"The tag {tag} has no VERSION file, so it isn't a release tag.")
    version = version_text.strip()
    if tag != f"v{version}":
        raise ReleaseProblem(f"The tag {tag} doesn't match its version: VERSION says "
                             f"{version}, so the release tag should be v{version}.")
    names_text = _tag_file(repo, tag, NAMES_FILE)
    if names_text is None:
        raise ReleaseProblem(f"The tag {tag} has no {NAMES_FILE}, the file with the "
                             "installer's names.")
    names = read_names(names_text)
    missing_names = [key for key in NAME_KEYS if not names.get(key)]
    if missing_names:
        raise ReleaseProblem(f"{NAMES_FILE} at {tag} is missing {', '.join(missing_names)}: "
                             "the installer, updater and uninstaller need every name.")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", names.get("ARCHIVE_NAME", "")):
        raise ReleaseProblem(f"{NAMES_FILE} at {tag} has no usable ARCHIVE_NAME "
                             "(letters, digits, dots, dashes and underscores only).")
    changelog = _tag_file(repo, tag, "CHANGELOG.md")
    if changelog is None:
        raise ReleaseProblem(f"The tag {tag} has no CHANGELOG.md, so there are no "
                             "release notes to take.")
    notes = changelog_entry(changelog, version)
    if notes is None or not notes.strip():
        raise ReleaseProblem(f"CHANGELOG.md at {tag} has no entry for {version}. Add a "
                             f"line `## {version}` with the release notes under it.")
    script = _tag_file(repo, tag, INSTALLER)
    updater = _tag_file(repo, tag, UPDATER)
    if updater is None:
        raise ReleaseProblem(f"The tag {tag} has no {UPDATER}, the step the installer uses "
                             "to place and update the app files.")
    installer = (standalone_installer(script, names_text, updater)
                 if script is not None else None)
    if installer is None:
        raise ReleaseProblem(f"The tag {tag} has no usable {INSTALLER} (it needs its "
                             f"'{NAMES_START}' and '{UPDATE_START}' blocks), so there is "
                             "nothing to install with.")
    return version, names, notes, installer


def build_archive(files, prefix):
    """The .tar.gz bytes: the included files under prefix/, in the tag's own
    order, times and modes, so the same tag gives the same archive."""
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0) as zipped:
        with tarfile.open(fileobj=zipped, mode="w", format=tarfile.PAX_FORMAT) as tar:
            for path, member, data in files:
                info = tarfile.TarInfo(f"{prefix}/{path}")
                info.mode, info.mtime, info.type = member.mode, member.mtime, member.type
                info.linkname = member.linkname
                info.uname = info.gname = ""
                info.size = len(data) if member.isfile() else 0
                tar.addfile(info, io.BytesIO(data) if member.isfile() else None)
    return buffer.getvalue()


def release(tag, out=None, repo=ROOT, list_path=privacy_guard.DEFAULT_LIST):
    """Build the four files. Returns their paths. Raises ReleaseProblem."""
    version, names, notes, installer = plan(repo, tag)
    files = [f for f in tag_files(repo, tag) if included(f[0])]
    paths = {f[0] for f in files}
    missing = [p for p in REQUIRED_FILES if p not in paths]
    if missing:
        raise ReleaseProblem(f"The tag {tag} is missing {', '.join(missing)}: "
                             "the licence files always ship with the app.")

    try:
        matcher = privacy_guard.Matcher(privacy_guard.read_list(list_path))
    except privacy_guard.ListProblem as problem:
        raise ReleaseProblem(f"Privacy guard FAILED: {problem}")
    # The release check (the release check work), which includes the privacy guard, on
    # everything the release publishes. A shortcut (symlink) holds no text of
    # its own: the check reads where it points instead, since that path is
    # what ships.
    items = [(path, member.linkname.encode("utf-8") if member.issym() else data)
             for path, member, data in files]
    items.append(("release notes", notes.encode("utf-8")))
    items.append(("install.sh", installer.encode("utf-8")))
    titles = _tag_file(repo, tag, release_check.INVENTED_TITLES)
    invented = (release_check.read_titles(titles) if titles is not None
                else release_check.invented_titles(ROOT))
    try:
        findings = release_check.Check(matcher, invented, history=repo).run(items)
    except release_check.HistoryProblem as problem:
        raise ReleaseProblem(f"Release check FAILED: {problem}")
    if findings:
        lines = "\n".join(f"RELEASE: {line}" for line in findings)
        raise ReleaseProblem(f"{lines}\nRelease check: {len(findings)} findings in the "
                             "release. Remove them, or use invented names, then tag again.")

    stem = f"{names['ARCHIVE_NAME']}-{version}"
    archive = build_archive(files, stem)
    out = Path(out) if out else Path(repo) / "dist"
    out.mkdir(parents=True, exist_ok=True)
    archive_path = out / f"{stem}.tar.gz"
    sum_path = out / f"{stem}.tar.gz.sha256"
    notes_path = out / f"{stem}-notes.md"
    installer_path = out / "install.sh"
    archive_path.write_bytes(archive)
    sum_path.write_text(sha256_line(archive, archive_path.name), encoding="utf-8")
    notes_path.write_text(f"# {names.get('APP_NAME', stem)} {version}\n\n{notes}",
                          encoding="utf-8")
    installer_path.write_text(installer, encoding="utf-8")
    installer_path.chmod(0o755)
    return archive_path, sum_path, notes_path, installer_path


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="tools/release.py",
        description="Build the release archive, its checksum and release notes from a tag.")
    parser.add_argument("tag")
    parser.add_argument("--out")
    parser.add_argument("--repo", default=str(ROOT))
    parser.add_argument("--list", default=str(privacy_guard.DEFAULT_LIST))
    args = parser.parse_args(argv)
    try:
        written = release(args.tag, args.out, args.repo, args.list)
    except ReleaseProblem as problem:
        print("Release stopped, nothing written.")
        print(problem)
        return 1
    print("Release check: the release is clean.")
    for path in written:
        print(f"Wrote {privacy_guard._shown(path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
