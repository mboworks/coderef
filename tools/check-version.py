#!/usr/bin/env python3
"""Verify consistent versions and require an advance after a release commit."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")


def parse_version(value: str) -> tuple[int, int, int]:
    match = SEMVER.fullmatch(value)
    if not match:
        raise SystemExit(f"unsupported version: {value!r}")
    return tuple(map(int, match.groups()))


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


cargo_toml = (ROOT / "Cargo.toml").read_text()
cargo_match = re.search(
    r"^\[workspace\.package\].*?^version\s*=\s*\"([^\"]+)\"",
    cargo_toml,
    re.MULTILINE | re.DOTALL,
)
if not cargo_match:
    raise SystemExit("Cargo.toml has no workspace package version")
cargo_version = cargo_match.group(1)

versions = {
    "Cargo.toml": cargo_version,
    "npm/coderef/package.json": json.loads(
        (ROOT / "npm/coderef/package.json").read_text()
    )["version"],
    "extension/package.json": json.loads(
        (ROOT / "extension/package.json").read_text()
    )["version"],
}

lib_rs = (ROOT / "crates/coderef-core/src/lib.rs").read_text()
doc_match = re.search(r"docs\.rs/coderef-core/(\d+\.\d+\.\d+)", lib_rs)
if not doc_match:
    raise SystemExit("missing coderef-core html_root_url version")
versions["coderef-core html_root_url"] = doc_match.group(1)

changelog = (ROOT / "CHANGELOG.md").read_text()
changelog_match = re.search(r"^## v(\d+\.\d+\.\d+)\b", changelog, re.MULTILINE)
if not changelog_match:
    raise SystemExit("CHANGELOG.md has no version heading")
versions["CHANGELOG.md"] = changelog_match.group(1)

expected = set(versions.values())
if len(expected) != 1:
    details = "\n".join(f"  {path}: {version}" for path, version in versions.items())
    raise SystemExit(f"public versions disagree:\n{details}")

current = expected.pop()
try:
    tag = git("describe", "--tags", "--abbrev=0", "--match", "v[0-9]*")
except subprocess.CalledProcessError:
    raise SystemExit(0)

tag_version = tag.removeprefix("v")
tag_commit = git("rev-list", "-n", "1", tag)
head_commit = git("rev-parse", "HEAD")
worktree_clean = subprocess.run(
    ["git", "diff", "--quiet", "HEAD", "--"], cwd=ROOT, check=False
).returncode == 0
if head_commit == tag_commit and worktree_clean:
    if current != tag_version:
        raise SystemExit(f"release commit {tag} must contain version {tag_version}, got {current}")
elif parse_version(current) <= parse_version(tag_version):
    raise SystemExit(
        f"version {current} must be greater than latest release {tag_version}; "
        "equality is allowed only on the release commit"
    )

print(f"version invariant satisfied: {current} (latest release: {tag})")
