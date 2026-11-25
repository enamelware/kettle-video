# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The clean public copy (the clean copy work). Developer only.

Builds a copy of this repo's tracked files, with no history, in a new
folder, runs the release check on it, and stops:

    python3 tools/public_copy.py FOLDER [--ref REF] [--repo FOLDER] [--list FILE]

    FOLDER    where the copy goes: a folder that doesn't exist yet, in a
              folder that does. The script never writes into, over or
              next to anything that is already there.
    --ref     the commit to copy (default: HEAD)
    --repo    the git repo to copy from (default: this one)
    --list    the privacy guard's word list (default: the guard's own)

The copy is a new git repo with one commit holding every file git tracks at
REF, read with git, never from the working folder: nothing untracked or
uncommitted (settings.json, data/, logs/, .claude/settings.local.json) can
get in. That first commit, and any later one made in the copy, uses the
Enamelware identity with its GitHub noreply address, set in the copy's own
git settings only. The copy has no remote and nothing is pushed: making it
public is a separate step, taken by hand after the designer's yes.

Then the release check (tools/release_check.py) runs on the copy, with
commit addresses looked up in the repo it was copied from, and the copy's
one commit is checked for the identity. Exit status: 0 clean, 1 findings
(the copy stays for a look but must not go public), 2 nothing was built or
the check couldn't run (the folder already exists, the word list is
missing, git failed).

Standard library only.
"""

from __future__ import annotations

import argparse
import io
import subprocess
import sys
import tarfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT))
import privacy_guard  # noqa: E402
import release_check  # noqa: E402

NAME = "Enamelware"
EMAIL = release_check.NOREPLY
MESSAGE = "Kettle Video, first public version\n"


class CopyProblem(Exception):
    """Something that stops the copy, said in plain words."""


def _git(cwd, *args, data=None):
    result = subprocess.run(["git", *args], cwd=cwd, input=data, capture_output=True)
    if result.returncode != 0:
        raise CopyProblem(f"git {args[0]} failed: "
                          + result.stderr.decode("utf-8", "replace").strip())
    return result.stdout


def tracked_files(repo, ref):
    """[(path, tarinfo, bytes)] for every file git tracks at ref."""
    try:
        _git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    except CopyProblem:
        raise CopyProblem(f"{ref} is not a commit in {privacy_guard._shown(repo)}.")
    raw = _git(repo, "archive", "--format=tar", ref)
    out = []
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as tar:
        for member in tar.getmembers():
            if not (member.isfile() or member.issym()):
                continue
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts:
                raise CopyProblem(f"git gave an unsafe path: {member.name}")
            data = tar.extractfile(member).read() if member.isfile() else b""
            out.append((member.name, member, data))
    return out


def write_files(folder, files):
    """Write the files under folder, with their modes and shortcuts."""
    for name, member, data in files:
        target = folder / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if member.issym():
            target.symlink_to(member.linkname)
        else:
            target.write_bytes(data)
            target.chmod(0o755 if member.mode & 0o111 else 0o644)


def first_commit(folder):
    """A new repo in folder with one commit of everything, as Enamelware."""
    _git(folder, "init", "-q", "-b", "main")
    _git(folder, "config", "user.name", NAME)
    _git(folder, "config", "user.email", EMAIL)
    _git(folder, "config", "commit.gpgsign", "false")
    _git(folder, "add", "--all", "--force")
    _git(folder, "commit", "-q", "-F", "-", data=MESSAGE.encode("utf-8"))


def identity_findings(folder):
    """The copy has exactly one commit, written and committed as Enamelware
    with the noreply address."""
    log = _git(folder, "log", "--format=%an <%ae>%x00%cn <%ce>").decode("utf-8").splitlines()
    expected = f"{NAME} <{EMAIL}>"
    out = []
    if len(log) != 1:
        out.append(f"the copy has {len(log)} commits, not one")
    for line in log:
        if any(who != expected for who in line.split("\0")):
            out.append("a commit in the copy isn't by Enamelware with the noreply address")
    return out


def build(folder, ref="HEAD", repo=ROOT, list_path=privacy_guard.DEFAULT_LIST):
    """Build the copy in folder and check it. Returns the findings (an
    empty list when clean). Raises CopyProblem when nothing was built or the
    check couldn't run."""
    folder = Path(folder)
    if folder.exists() or folder.is_symlink():
        raise CopyProblem(f"{privacy_guard._shown(folder)} already exists. The copy only ever "
                          "goes into a new folder: name one that isn't there yet.")
    if not folder.parent.is_dir():
        raise CopyProblem(f"{privacy_guard._shown(folder.parent)} doesn't exist: the copy's "
                          "folder must go inside a folder that does.")
    try:
        matcher = privacy_guard.Matcher(privacy_guard.read_list(list_path))
    except privacy_guard.ListProblem as problem:
        raise CopyProblem(f"Privacy guard FAILED: {problem}")
    files = tracked_files(repo, ref)
    folder.mkdir()
    write_files(folder, files)
    first_commit(folder)
    try:
        check = release_check.Check(matcher, release_check.invented_titles(folder), history=repo)
        findings = check.run(release_check.repo_items(folder))
    except release_check.HistoryProblem as problem:
        raise CopyProblem(f"Release check FAILED: {problem}")
    return findings + identity_findings(folder)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="tools/public_copy.py",
        description="Build a copy of the tracked files with no history, then run the "
                    "release check on it.")
    parser.add_argument("folder")
    parser.add_argument("--ref", default="HEAD")
    parser.add_argument("--repo", default=str(ROOT))
    parser.add_argument("--list", default=str(privacy_guard.DEFAULT_LIST))
    args = parser.parse_args(argv)
    try:
        findings = build(args.folder, args.ref, args.repo, args.list)
    except CopyProblem as problem:
        print("Public copy stopped.")
        print(problem)
        return 2
    shown = privacy_guard._shown(args.folder)
    if findings:
        for line in findings:
            print(f"RELEASE: {line}")
        print(f"Public copy: built in {shown}, but the release check found {len(findings)} "
              "things. It must not go public until they are gone from the repo and the copy "
              "is built again.")
        return 1
    print(f"Public copy: built in {shown}, one commit as {NAME}, no history, no remote. "
          "Release check: the copy is clean. Nothing was published.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
