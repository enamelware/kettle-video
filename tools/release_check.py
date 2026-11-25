# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""The release check (the release check work): nothing that mustn't go public is in the
repo. Run before every release; tools/release.py runs it on the tag's files
and builds nothing if it finds anything.

    python3 tools/release_check.py [--repo FOLDER] [--list FILE] [--history REPO]
    python3 tools/release_check.py history [--repo FOLDER] [--list FILE]

The first form reads every file git tracks in FOLDER (default: this repo).
`history` is the deep look: every version of every file in every commit,
and every commit message, for secrets, private words, personal paths, Steam
IDs and email addresses.

A finding names the file, the line and the kind of thing found, never the
text itself, so the report can be pasted anywhere. Exit status: 0 clean, 1
findings, 2 the private word list is missing or empty.

It fails on:
- everything the privacy guard (tools/privacy_guard.py, the privacy guard work) fails
  on, with the same list and rules: the private words (card labels,
  the user name, film and show names from the cards, device, network and
  Bluetooth names, Steam accounts), home folders written out in full, Steam
  user folders and Steam IDs, and pictures or logs outside the approved
  folders;
- those private words also written scrambled: ROT13, reversed, or encoded
  as base64, hex, %-escapes, HTML entities or \\u escapes;
- film and show titles in test data, docs and code that are not on the list
  of invented titles (tests/fixtures/invented_titles.txt). The check never
  holds a list of real titles, which would itself be a leak: a title is
  allowed because it is known to be invented, never because it isn't known
  to be real. Titles are read from video file names (and, in tests/,
  docs/ and spikes/, from "title" fields), also inside the scrambled and
  encoded forms above;
- names, values or files from Steam's client, as Enamel's own clean-up
  rules them out (its tools/release_check.py, read with scripts/peek.sh):
  Steam's variable prefix and its system or colour names, the words for
  taking values out of Steam's files, a Steam client version, code that
  opens a debug connection to the Steam client, and a reference folder of
  captures;
- the app's old names, through the checks that already guard them
  (tests/test_kettle_video_name.py, the Kettle Video rename; tests/test_design_system_name.py
  and tests/test_account_name.py), never a second copy of their rules;
- anything that looks like a secret (tokens, keys, passwords), and files
  that usually hold one (.env, keys, .netrc);
- a tracked .claude/settings.local.json or CLAUDE.local.md;
- an email address other than Enamelware's GitHub noreply address, the
  commits' attribution address (noreply@anthropic.com), git@github.com and
  the reserved example domains used by invented test data;
- a link to this private repo's commits, issues or pull requests, and a
  commit address: a hex name of a commit in the repo's history (--history
  names another repo to look them up in, for a copy without history).

Third-party files (vendor/, ui/fonts/) are checked only against the private
word list and for secrets, as the privacy guard does: their authors' names,
addresses and examples stay as published.

It also runs the public-text check (tools/public_text.py, PUBLIC_TEXT_CHECKS
below): old issue numbers of the private repo, the person running the project
named by role outside the instructions to Claude Code, claude.ai links and links to
the private board, as CLAUDE.md's "Public writing" rules them out.

Some patterns would match their own text, so they are built from parts.
Standard library only.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import codecs
import html
import importlib
import re
import subprocess
import sys
import unicodedata
import urllib.parse
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT))
import privacy_guard  # noqa: E402

INVENTED_TITLES = "tests/fixtures/invented_titles.txt"
THIRD_PARTY = privacy_guard.THIRD_PARTY

# ---------------------------------------------------------------- titles

# The app's own list of video extensions (backend/scanner.py), written out
# here so the check works on a copy without importing the app. Plain ".ts"
# is left out: in code it is far more often something else.
VIDEO_EXTENSIONS = ("m2ts", "mpeg", "webm", "mkv", "mp4", "avi", "mov", "m4v", "wmv",
                    "flv", "mpg")
_VIDEO = re.compile(
    r"([^\"'`/\\<>|*?\n:=(){}\[\]─-╿]{1,160}?(?:\([^\"'`/\\\n()]*\)[^\"'`/\\\n()]*?)?"
    r"\.(?:" + "|".join(VIDEO_EXTENSIONS) + r"))(?![\w-])", re.I)
_TITLE_FIELD = re.compile(r"""(?:["']title["']\s*:\s*|\btitle\s*=\s*)(["'])([^"'\n]{2,120})\1""")
TITLE_FIELD_FOLDERS = ("tests/", "docs/", "spikes/")
_TAGS = re.compile(r"\[[^\]]*\]|\{[^}]*\}")
_YEAR = re.compile(r"[(\[]?\b(?:19|20)\d\d\b[)\]]?")
_EPISODE = re.compile(r"\b(?:s\d{1,3}(?:e\d{1,4})+|\d{1,2}x\d{1,4}|e\d{1,4}|ep\.?\s?\d+)\b.*", re.I)
_RELEASE = re.compile(
    r"\b(?:\d{3,4}p|4k|uhd|hdr|bluray|blu-ray|web-?dl|webrip|hdtv|dvdrip|x26[45]|h\.?26[45]|hevc|"
    r"10bit|aac|ac3|dts|ddp?5\.1|remux|proper|repack|sample|part\s?\d+|pt\s?\d+|cd\s?\d+|"
    r"directors?'?s? (?:cut|version))\b.*", re.I)
MAX_TITLE_WORDS = 10


def norm_title(text):
    """A title as the list compares it: case, accents' forms, dots, dashes,
    underscores and spacing don't matter."""
    text = unicodedata.normalize("NFKC", text).casefold()
    text = re.sub(r"[._\s]+", " ", text)
    return " ".join(text.strip(" -–—,;:!?'\"").split())


def title_of(name):
    """The title part of a video file name, or "" when nothing is left that
    reads like a title (only numbers, tags or episode markers)."""
    stem = name.rsplit(".", 1)[0]
    stem = _TAGS.sub(" ", stem)
    stem = re.sub(r"[._]+", " ", stem)
    stem = _EPISODE.sub("", stem)
    stem = _RELEASE.sub("", stem)
    stem = _YEAR.sub(" ", stem)
    stem = re.split(r"\s[-–—]\s|\s-$", stem + " ")[0]
    title = norm_title(stem)
    letters = sum(ch.isalpha() for ch in title)
    return title if letters >= 2 else ""


def titles_in(line, path=""):
    """Titles on one line: from video file names everywhere, and from
    "title" fields in tests, docs and spikes."""
    out = []
    for m in _VIDEO.finditer(line):
        name = m.group(1).strip()
        if len(name.split()) > MAX_TITLE_WORDS:
            continue
        title = title_of(name)
        if title:
            out.append(title)
    if path.startswith(TITLE_FIELD_FOLDERS) and not path.endswith((".html", ".htm")):
        for m in _TITLE_FIELD.finditer(line):
            title = norm_title(m.group(2))
            if sum(ch.isalpha() for ch in title) >= 2:
                out.append(title)
    return out


def read_titles(text):
    """The invented titles: one per line, # starts a note."""
    out = set()
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.add(norm_title(line))
    return out


# ---------------------------------------------------------------- scrambled

_B64 = re.compile(r"(?<![A-Za-z0-9+/_-])[A-Za-z0-9+/_-]{12,}={0,2}")
_HEX = re.compile(r"(?<![0-9A-Fa-f])(?:[0-9A-Fa-f]{2}){6,}(?![0-9A-Fa-f])")


def _readable(data):
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if not text or sum(ch.isprintable() or ch.isspace() for ch in text) < 0.9 * len(text):
        return None
    return text


def variants(line):
    """[(how, text)]: the line read as each scrambled or encoded form."""
    out = [("written in ROT13", codecs.encode(line, "rot13")), ("written backwards", line[::-1])]
    decoded = []
    for m in _B64.finditer(line):
        token = m.group(0)
        try:
            data = base64.b64decode(token + "=" * (-len(token) % 4),
                                    altchars=b"-_" if ("-" in token or "_" in token) else None)
        except (binascii.Error, ValueError):
            continue
        text = _readable(data)
        if text:
            decoded.append(text)
    if decoded:
        out.append(("encoded as base64", " ".join(decoded)))
    hexed = [t for t in (_readable(bytes.fromhex(m.group(0))) for m in _HEX.finditer(line)) if t]
    if hexed:
        out.append(("encoded as hex", " ".join(hexed)))
    if "%" in line:
        out.append(("encoded with % escapes", urllib.parse.unquote(line)))
    if "&" in line:
        out.append(("encoded as HTML entities", html.unescape(line)))
    if "\\u" in line or "\\x" in line:
        try:
            out.append(("encoded as \\u escapes",
                        line.encode("latin-1", "backslashreplace").decode("unicode_escape")))
        except (UnicodeDecodeError, UnicodeEncodeError):
            pass
    return [(how, text) for how, text in out if text != line]


# ---------------------------------------------------------------- Steam, secrets, links

GP = "g" + "p"
STEAM = [
    ("a name from Steam's client (its variable prefix, or its system or colour names)",
     re.compile(rf"(?<![\w-])--{GP}[A-Za-z0-9_-]|\b{GP}(?:System|Color)")),
    ("words for taking values out of Steam's files",
     re.compile(r"\b" + "extract" + r"ed\b|Valve" + r"['’]s variables", re.I)),
    ("a Steam client version",
     re.compile(r"\bsteam\s+client\s+(?:version\s+|build\s+)?\d{4,}|\bclient\s+version\s*[:=]?\s*\d"
                r"|\bbuild\s?id\s*[:=]\s*\d{6,}", re.I)),
    ("a debug connection to the Steam client",
     re.compile(r"(?:127\.0\.0\.1|localhost):80" + r"80\b|remote-debugging-" + "address"
                r"|cef-enable-" + "debugging|steam" + r"webhelper|/json/(?:list|version)\b")),
]
REFERENCE_FOLDERS = re.compile(r"(?:^|/)reference(?:s)?/", re.I)

SECRETS = re.compile(
    r"\bgh[pousr]_[A-Za-z0-9]{20,}|\bgithub_pat_\w{20,}|\bAKIA[0-9A-Z]{16}\b"
    r"|-----BEGIN [A-Z ]*PRIVATE " + "KEY" + r"|\bxox[abprs]-[\w-]{10,}|\bsk-(?:ant-)?[A-Za-z0-9_-]{20,}"
    r"|\bAIza[0-9A-Za-z_-]{35}\b"
    r"|\b(?:pass" + r"word|passwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token|token)"
    r"[\"']?\s*[:=]\s*[\"'](?!--|var\()[^\"'\s]{8,}[\"']", re.I)
SECRET_FILES = re.compile(r"(?:^|/)(?:\.env(?:\.[\w.-]+)?|\.netrc|\.git-credentials|id_(?:rsa|dsa|ecdsa|ed25519)"
                          r"|[^/]+\.(?:pem|key|p12|pfx|keystore))$", re.I)
LOCAL_FILES = (".claude/settings.local.json", "CLAUDE.local.md")

NOREPLY = "335260252+enamelware@users.noreply.github.com"
ALLOWED_EMAIL = re.compile(r"(?i)^(?:" + re.escape(NOREPLY) + r"|noreply@anthropic\.com|git@github\.com"
                           r"|[^@]+@example\.(?:invalid|com|org|net)|[^@]+@[^@]+\.test)$")

PRIVATE_REPO = "enamelware/kettle-video" + "-private"
REPO_LINK = re.compile(
    r"github\.com[/:]" + re.escape(PRIVATE_REPO) + r"(?:\.git)?/(?:commit|commits|issues|pull|pulls|compare)\b"
    r"|" + re.escape(PRIVATE_REPO) + r"#\d+"
    r"|github\.com/[\w-]+/[\w.-]+/commit/[0-9a-f]{7,40}", re.I)
_HASH = re.compile(r"(?<![\w-])(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)[0-9a-f]{7,40}(?![\w-])")

# The public-text check: module names in tools/ with a
# findings(path, text) -> [(line, kind)].
PUBLIC_TEXT_CHECKS = ("public_text",)

# ---------------------------------------------------------------- old names

OLD_NAME_CHECKS = ("tests.test_kettle_video_name", "tests.test_design_system_name",
                   "tests.test_account_name")
OLD_NAME_FILES = {"tests.test_kettle_video_name": "tests/test_kettle_video_name.py",
                  "tests.test_design_system_name": "tests/test_design_system_name.py",
                  "tests.test_account_name": "tests/test_account_name.py"}


def _old_name_checks():
    out = []
    for name in OLD_NAME_CHECKS:
        try:
            out.append((OLD_NAME_FILES[name], importlib.import_module(name).hits))
        except ImportError:
            continue
    return out


def old_name_lines(path, text, checks):
    """Line numbers where the rename checks find an old name."""
    numbers = set()
    lines = text.splitlines()
    for own_file, hits in checks:
        if path == own_file:
            continue
        found = set(hits([(path, text)]))
        if not found:
            continue
        for number, line in enumerate(lines, 1):
            if f"{path}: {line.strip()[:120]}" in found:
                numbers.add(number)
    return numbers


# ---------------------------------------------------------------- the check

class Check:
    """Everything one run needs: the private words, the invented titles, the
    rename checks and where commits are looked up."""

    def __init__(self, matcher, invented, history=None, old_names=True):
        self.matcher = matcher
        self.invented = invented
        self.history = history
        self.old_names = _old_name_checks() if old_names else []

    def line_kinds(self, path, line, titles=True):
        kinds = []
        third_party = path.startswith(THIRD_PARTY)
        for how, text in variants(line):
            kinds += [f"private word ({k}) {how}" for k in self.matcher.kinds(text)]
            if titles and not third_party:
                kinds += [f"a title not on the invented list, {how}"
                          for t in titles_in(text, path) if t not in self.invented]
        if titles and not third_party:
            kinds += ["a title not on the invented list"
                      for t in titles_in(line, path) if t not in self.invented]
        if SECRETS.search(line):
            kinds.append("something that looks like a secret")
        if third_party:
            return kinds
        for what, pattern in STEAM:
            if pattern.search(line):
                kinds.append(what)
        for m in privacy_guard.EMAIL.finditer(line):
            if not ALLOWED_EMAIL.match(m.group(0)):
                kinds.append("an email address other than the noreply address")
        if REPO_LINK.search(line):
            kinds.append("a link to this private repo's commits or issues")
        return kinds

    def file_findings(self, path, data):
        """[(line or None, kind)] for one file."""
        out = [(None, k) for k in privacy_guard.path_findings(path, self.matcher)]
        if REFERENCE_FOLDERS.search(path):
            out.append((None, "a reference folder of captures"))
        if SECRET_FILES.search(path):
            out.append((None, "a file that usually holds a secret"))
        if path in LOCAL_FILES:
            out.append((None, "a local Claude Code file tracked by git"))
        text = privacy_guard._text(data) if data is not None else None
        if text is None:
            return out
        for number, kind in privacy_guard.line_findings(text, self.matcher, path):
            if kind.startswith("email address"):
                continue  # this check's own, stricter email rule is below
            out.append((number, kind))
        for number, line in enumerate(text.splitlines(), 1):
            for kind in dict.fromkeys(self.line_kinds(path, line)):
                out.append((number, kind))
        if not path.startswith(THIRD_PARTY):
            for number in sorted(old_name_lines(path, text, self.old_names)):
                out.append((number, "an old name of the app, the design system or the account"))
            for number in self.commit_lines(text):
                out.append((number, "a commit address"))
            for module in PUBLIC_TEXT_CHECKS:
                for number, kind in importlib.import_module(module).findings(path, text):
                    out.append((number, kind))
        return out

    def commit_lines(self, text):
        """Line numbers holding a hex name that is a commit in the history."""
        if not self.history:
            return []
        where = {}
        for number, line in enumerate(text.splitlines(), 1):
            for m in _HASH.finditer(line):
                where.setdefault(m.group(0), []).append(number)
        if not where:
            return []
        commits = known_commits(self.history, list(where))
        return sorted({n for token in commits for n in where[token]})

    def run(self, items):
        """items: (path, bytes). Returns sorted 'path, line N: kind' lines."""
        found = []
        for path, data in items:
            for number, kind in self.file_findings(path, data):
                where = path if number is None else f"{path}, line {number}"
                found.append(f"{where}: {kind}")
        return list(dict.fromkeys(found))


class HistoryProblem(Exception):
    """The repo to look commits up in can't be read: the check stops rather
    than let commit addresses through unchecked."""


def history_ok(repo):
    """Raises HistoryProblem unless repo is a git repo with at least one
    commit, so commit addresses can really be looked up there."""
    try:
        result = subprocess.run(["git", "rev-parse", "--verify", "--quiet", "HEAD^{commit}"],
                                cwd=repo, capture_output=True, text=True)
    except OSError:
        result = None
    if result is None or result.returncode != 0:
        raise HistoryProblem(f"{privacy_guard._shown(repo)} is not a git repo with commits, so "
                             "commit addresses can't be looked up there. Give the repo "
                             "the copy was made from.")


def known_commits(repo, tokens):
    """The tokens that name a commit in repo's history (git cat-file)."""
    try:
        result = subprocess.run(["git", "cat-file", "--batch-check"], cwd=repo,
                                input="".join(f"{t}^{{commit}}\n" for t in tokens),
                                capture_output=True, text=True)
    except OSError:
        result = None
    if result is None or result.returncode != 0:
        raise HistoryProblem(f"git couldn't look commits up in {privacy_guard._shown(repo)}.")
    out = []
    for token, line in zip(tokens, result.stdout.splitlines()):
        if line.split()[1:2] == ["commit"]:
            out.append(token)
    return out


def repo_items(repo):
    """(path, bytes) for every file git tracks in repo."""
    return [(path, data) for _, path, data, _ in privacy_guard.tracked_items(cwd=str(repo))]


def invented_titles(repo):
    path = Path(repo) / INVENTED_TITLES
    try:
        return read_titles(path.read_text(encoding="utf-8"))
    except OSError:
        return set()


# ---------------------------------------------------------------- history

def history_items(repo):
    """(where, path, bytes) for every commit message and every version of
    every file in every commit. Read-only."""
    def git(*args, input=None):
        return subprocess.run(["git", *args], cwd=repo, input=input, capture_output=True,
                              check=True).stdout

    out = []
    log = git("log", "--all", "--format=%x00%h%x00%B")
    fields = log.split(b"\0")
    for i in range(1, len(fields) - 1, 2):
        out.append((f"commit {fields[i].decode()} message", "", fields[i + 1]))
    objects = git("rev-list", "--objects", "--all").decode("utf-8", "replace").splitlines()
    paths = {}
    for line in objects:
        sha, _, path = line.partition(" ")
        if path:
            paths.setdefault(sha, path)
    checked = git("cat-file", "--batch-check", input="".join(f"{s}\n" for s in paths).encode())
    blobs = [line.split()[0].decode() for line in checked.splitlines() if line.split()[1:2] == [b"blob"]]
    first = {}
    for line in git("log", "--all", "--reverse", "--format=%x00%h", "--raw", "--no-abbrev",
                    "--no-renames").decode("utf-8", "replace").splitlines():
        if line.startswith("\0"):
            commit = line[1:]
        elif line.startswith(":"):
            parts = line.split()
            if len(parts) >= 4:
                first.setdefault(parts[3], commit)
    for sha in blobs:
        data = git("cat-file", "blob", sha)
        out.append((f"{paths[sha]} (first in commit {first.get(sha, 'unknown')})", paths[sha], data))
    return out


def history_findings(repo, matcher):
    """Every finding in the whole history, by where it is."""
    check = Check(matcher, set(), history=None, old_names=False)
    found = []
    for where, path, data in history_items(repo):
        text = privacy_guard._text(data)
        if path and (SECRET_FILES.search(path) or path in LOCAL_FILES):
            found.append(f"{where}: a file that usually holds a secret or a local Claude Code file")
        for kind in privacy_guard.path_findings(path, matcher, added=False) if path else []:
            found.append(f"{where}: {kind}")
        if text is None:
            continue
        for number, kind in privacy_guard.line_findings(text, matcher, path):
            if not kind.startswith("email address"):
                found.append(f"{where}, line {number}: {kind}")
        for number, line in enumerate(text.splitlines(), 1):
            for kind in dict.fromkeys(check.line_kinds(path, line, titles=False)):
                found.append(f"{where}, line {number}: {kind}")
    return list(dict.fromkeys(found))


# ---------------------------------------------------------------- command line

def report(findings, what):
    for line in findings:
        print(f"RELEASE: {line}")
    if findings:
        kinds = Counter(line.rsplit(": ", 1)[1] for line in findings)
        print(f"Release check: {len(findings)} findings in {what}. Nothing may go public until "
              "they are gone. By kind: " + "; ".join(f"{k} {n}" for k, n in sorted(kinds.items())))
        return 1
    print(f"Release check: {what} clean.")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="tools/release_check.py",
                                     description="Fail on anything that mustn't go public.")
    parser.add_argument("mode", nargs="?", choices=("files", "history"), default="files")
    parser.add_argument("--repo", default=str(ROOT))
    parser.add_argument("--list", default=str(privacy_guard.DEFAULT_LIST))
    parser.add_argument("--history", help="the repo to look commit addresses up in "
                                          "(default: --repo)")
    args = parser.parse_args(argv)
    try:
        matcher = privacy_guard.Matcher(privacy_guard.read_list(args.list))
    except privacy_guard.ListProblem as problem:
        print(f"Release check FAILED: {problem}")
        return 2
    if args.mode == "history":
        return report(history_findings(args.repo, matcher), "the whole history")
    history = args.history or args.repo
    try:
        history_ok(history)
        check = Check(matcher, invented_titles(args.repo), history=history)
        return report(check.run(repo_items(args.repo)), "the tracked files")
    except HistoryProblem as problem:
        print(f"Release check FAILED: {problem}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
