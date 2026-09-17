#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) M. Boerger, the MBO Works authors
# SPDX-License-Identifier: Apache-2.0
"""Verify the four platform bundles before publishing a complete GitHub release."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

PLATFORMS = {"linux-x64": "tar.gz", "linux-arm64": "tar.gz",
             "macos-arm64": "tar.gz", "windows-x64": "zip"}


def gh(*args):
    return subprocess.check_output(["gh", *args], text=True)


def verify_local(tag, directory):
    if not re.fullmatch(r"v\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", tag):
        raise ValueError("Expected a v-prefixed semantic-version tag")
    expected = {f"coderef-{tag}-{platform}.{extension}"
                for platform, extension in PLATFORMS.items()}
    expected |= {name + ".sha256" for name in list(expected)}
    actual = {path.name for path in directory.iterdir()}
    if actual != expected:
        raise ValueError(f"Release must contain exactly the eight platform assets: {sorted(expected)}")
    digests = {}
    for name in sorted(expected):
        path = directory / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"Invalid release asset: {name}")
        digests[name] = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    for name in expected:
        if not name.endswith(".sha256"):
            checksum = (directory / (name + ".sha256")).read_text().strip()
            if checksum != digests[name].removeprefix("sha256:"):
                raise ValueError(f"Checksum mismatch: {name}")
    return digests


def verify_remote(release, digests):
    assets = release["assets"]
    if len(assets) != len(digests) or {asset["name"] for asset in assets} != set(digests):
        raise ValueError("Remote release does not contain exactly the expected assets")
    for asset in assets:
        if asset["state"] != "uploaded" or asset.get("digest") != digests[asset["name"]]:
            raise ValueError(f"Remote asset is incomplete or has the wrong digest: {asset['name']}")


def publish(repository, tag, directory, notes):
    digests = verify_local(tag, directory)
    # A failed API request must fail, never be mistaken for a missing release.
    pages = json.loads(gh("api", "--paginate", "--slurp", f"repos/{repository}/releases"))
    matches = [release for page in pages for release in page if release["tag_name"] == tag]
    if len(matches) > 1:
        raise ValueError("Multiple releases have the requested tag")
    if matches and not matches[0]["draft"]:
        verify_remote(matches[0], digests)
        return  # An identical published release needs no mutation; downstream retries may proceed.
    if not matches:
        gh("release", "create", tag, "--repo", repository, "--verify-tag", "--draft",
           "--title", f"coderef {tag}", "--notes-file", str(notes))
    gh("release", "upload", tag, "--repo", repository,
       *(str(directory / name) for name in sorted(digests)), "--clobber")
    release = json.loads(gh("api", f"repos/{repository}/releases/tags/{tag}"))
    if not release["draft"]:
        raise ValueError("Release was published before upload verification completed")
    verify_remote(release, digests)
    prerelease = "-" in tag
    gh("release", "edit", tag, "--repo", repository, "--draft=false",
       f"--prerelease={str(prerelease).lower()}", f"--latest={str(not prerelease).lower()}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag")
    parser.add_argument("directory", type=Path)
    parser.add_argument("notes", type=Path)
    args = parser.parse_args()
    publish(os.environ["GITHUB_REPOSITORY"], args.tag, args.directory, args.notes)


if __name__ == "__main__":
    main()
