#!/usr/bin/env python3
"""Retain and index immutable Rust coverage attempts."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _time(value: str | None) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def archive(root: Path, incoming: Path | None = None) -> int:
    """Copy an incoming report into its immutable run/attempt location."""
    source = incoming or root
    metadata = _read(source / "metadata.json")
    run_id = str(metadata["run_id"])
    attempt = str(metadata.get("run_attempt", 1))
    destination = root / "runs" / run_id / attempt
    if destination.exists():
        return 0
    root.mkdir(parents=True, exist_ok=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root) as temporary:
        staged = Path(temporary) / "report"
        shutil.copytree(source, staged)
        staged.rename(destination)
    return 1


def _reports(root: Path) -> list[dict]:
    reports = []
    for metadata_path in sorted((root / "runs").glob("*/*/metadata.json")):
        metadata = _read(metadata_path)
        metadata["path"] = metadata_path.parent.relative_to(root).as_posix()
        reports.append(metadata)
    return reports


def _pulls(path: Path) -> dict[int, dict]:
    if not path.exists():
        return {}
    value = _read(path)
    pulls = [item for page in value for item in page] if value and isinstance(value[0], list) else value
    return {int(item["number"]): item for item in pulls}


def history(root: Path, pulls_path: Path | None = None) -> list[dict]:
    pulls = _pulls(pulls_path) if pulls_path else {}
    reports = []
    for report in _reports(root):
        target = report.get("target", "main")
        visible = True
        if target.startswith("pr/"):
            number = int(target.split("/", 1)[1])
            pull = pulls.get(number, {})
            visible = pull.get("state") != "closed" or bool(pull.get("merged_at"))
            report["pull_request"] = number
            report["pull_state"] = pull.get("state", "unknown")
        report["visible"] = visible
        reports.append(report)
    reports.sort(key=lambda value: (_time(value.get("reference_time") or value.get("completed_at")), value["path"]), reverse=True)
    (root / "history.json").write_text(json.dumps(reports, indent=2) + "\n", encoding="utf-8")
    return reports


def regenerate(root: Path) -> int:
    reports = _read(root / "history.json") if (root / "history.json").exists() else _reports(root)
    visible = [item for item in reports if item.get("visible", True)]
    rows = ["<!doctype html><meta charset=\"utf-8\"><title>coderef coverage</title>", "<h1>coderef coverage</h1>", "<ul>"]
    for report in visible:
        target = report.get("target", "main")
        link = f"runs/{report['path']}/html/index.html"
        rows.append(f"<li><a href=\"{link}\">{target}</a> ({report.get('reference_time') or report.get('completed_at', 'unknown')})</li>")
    rows.append("</ul>")
    (root / "index.html").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return len(visible)


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("archive", "history", "regenerate"):
        command = commands.add_parser(name)
        command.add_argument("root", type=Path)
        if name == "archive":
            command.add_argument("--incoming", type=Path)
        if name == "history":
            command.add_argument("pulls", type=Path)
    args = parser.parse_args()
    if args.command == "archive":
        return 0 if not archive(args.root, args.incoming) else 0
    if args.command == "history":
        history(args.root, args.pulls)
    else:
        regenerate(args.root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
