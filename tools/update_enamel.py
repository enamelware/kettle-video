# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Copy one released version of the Enamel design system into vendor/enamel/.

Run from anywhere:  python3 tools/update_enamel.py VERSION [ENAMEL_FOLDER]

VERSION is an Enamel release such as 0.7.0. Its files are read from the
release's git tag (v0.7.0), never from the folder as it happens to be, so
work in progress in Enamel can't come in by mistake (the Enamel 0.6.0 upgrade). The
folder defaults to ~/Development/enamel, or to the design system's folder
under its old name if that one doesn't exist (the Enamel rename). It is only read,
never changed: no branch is switched and no file touched. Each file is
copied unchanged, and only when it differs from the vendored copy, so
nothing is rewritten when nothing has changed. The copies in vendor/enamel/
are never edited by hand or by this script (the first design system step).

The adopted release is pinned in ENAMEL_PIN at the repo's root: its tag,
such as v0.7.0, in one place. A successful update writes the new tag there,
so the pin and the copies always move together, and only in an upgrade's
own "Bring in Enamel <version>" issue.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Enamel's folder, then the same folder under the design system's name
# before 0.7.0 (the Enamel rename), for a device where it hasn't been renamed yet.
SOURCE_CANDIDATES = (
    Path.home() / "Development" / "enamel",
    Path.home() / "Development" / "kettle-ui",
)
# Enamel's public repository, for a device that has no copy yet.
PUBLIC_REPO = "https://github.com/enamelware/enamel.git"
VENDOR_DIR = Path(__file__).resolve().parent.parent / "vendor" / "enamel"
PIN_FILE = Path(__file__).resolve().parent.parent / "ENAMEL_PIN"
# The files Kettle Video takes from Enamel, at the same paths in both folders.
FILES = (
    "tokens/enamel.css",
    "components/enamel-components.css",
    "components/enamel-components.js",
    "DESIGN.md",
    "VERSION",
    "LICENSE",
    "NOTICE.md",
    "MIGRATION.md",
)


def default_source(candidates=SOURCE_CANDIDATES) -> Path:
    """The first candidate folder that exists, or the first one if none does."""
    return next((folder for folder in candidates if folder.is_dir()), candidates[0])


DEFAULT_SOURCE = default_source()


def read_version(folder: Path) -> str:
    try:
        return (folder / "VERSION").read_text(encoding="utf-8").strip() or "unknown"
    except OSError:
        return "none"


def tag_for(version: str) -> str:
    """Enamel's release tag for a version: 0.7.0 is v0.7.0."""
    return f"v{version}"


def pinned_tag(pin: Path | None = None) -> str:
    """The adopted release's tag: the one line in ENAMEL_PIN that isn't a comment."""
    pin = pin or PIN_FILE
    lines = [line.strip() for line in pin.read_text(encoding="utf-8").splitlines()]
    tags = [line for line in lines if line and not line.startswith("#")]
    if len(tags) != 1 or not tags[0].startswith("v"):
        raise ValueError(f"{pin.name} must hold exactly one release tag, such as v0.7.0")
    return tags[0]


def pinned_version(pin: Path | None = None) -> str:
    """The adopted release's version: v0.7.0 is 0.7.0."""
    return pinned_tag(pin).removeprefix("v")


def write_pin(version: str, pin: Path | None = None) -> None:
    """Point the pin at a new release, keeping its comment lines."""
    pin = pin or PIN_FILE
    lines = pin.read_text(encoding="utf-8").splitlines() if pin.is_file() else []
    comments = [line for line in lines if line.startswith("#")]
    pin.write_text("\n".join([*comments, tag_for(version)]) + "\n", encoding="utf-8")


def _git(source: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(source), *args], capture_output=True, timeout=30)


def why_not_released(source: Path, version: str) -> str | None:
    """Why this version's files can't be read from Enamel here, or None if they can."""
    if not source.is_dir():
        return (f"{source} isn't on this device. Clone Enamel there "
                f"(git clone {PUBLIC_REPO} \"{source}\"), or give its folder as the second argument")
    if not (source / ".git").exists():
        return f"{source} isn't a git folder"
    tag = tag_for(version)
    if _git(source, "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}^{{commit}}").returncode != 0:
        return f"{source} has no tag {tag} for version {version}"
    return None


def released_file(source: Path, version: str, name: str) -> bytes:
    """A file as it is in the release's tag. Only reads; never switches branch."""
    result = _git(source, "show", f"refs/tags/{tag_for(version)}:{name}")
    if result.returncode != 0:
        raise FileNotFoundError(f"{name} isn't in Enamel's {tag_for(version)}")
    return result.stdout


def update(source: Path, version: str, vendor: Path = VENDOR_DIR) -> list[str]:
    """Copy every file of the release that differs; return the ones copied."""
    reason = why_not_released(source, version)
    if reason:
        raise FileNotFoundError(reason)
    files = {name: released_file(source, version, name) for name in FILES}
    if files["VERSION"].decode("utf-8", "replace").strip() != version:
        raise FileNotFoundError(f"Enamel's {tag_for(version)} doesn't say version {version} in VERSION")
    copied = []
    for name, new in files.items():
        target = vendor / name
        if target.is_file() and target.read_bytes() == new:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(new)
        copied.append(name)
    return copied


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("Usage: python3 tools/update_enamel.py VERSION [ENAMEL_FOLDER]  (for example 0.7.0)",
              file=sys.stderr)
        return 2
    version = argv[1]
    source = Path(argv[2]).expanduser() if len(argv) > 2 else DEFAULT_SOURCE
    old = read_version(VENDOR_DIR)
    try:
        copied = update(source, version)
        write_pin(version)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"Couldn't update Enamel: {exc}", file=sys.stderr)
        return 1
    print(f"Old version: {old}")
    print(f"New version: {read_version(VENDOR_DIR)}")
    if copied:
        print("Copied: " + ", ".join(copied))
    else:
        print("Nothing changed: the copies already match.")
    print(f"Pinned in ENAMEL_PIN: {tag_for(version)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
