#!/usr/bin/env python3
"""Retain and index immutable Rust coverage attempts."""

from __future__ import annotations

import argparse
import json
from html import escape
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

_METRICS = {"lines": ("LH", "LF"), "branches": ("BRH", "BRF"), "functions": ("FNH", "FNF")}
_REPOSITORY = "https://github.com/mboworks/coderef"


def _coverage(path: Path) -> dict:
    """Sum llvm-cov's per-file LCOV counters, without averaging percentages."""
    totals = {field: 0 for fields in _METRICS.values() for field in fields}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            field, _, value = line.partition(":")
            if field in totals:
                totals[field] += int(value)
    return {
        metric: {"covered": totals[hit], "total": totals[found],
                 "percent": 100 * totals[hit] / totals[found] if totals[found] else None}
        for metric, (hit, found) in _METRICS.items()
    }


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
    # Older artifacts used coverage/html as llvm-cov's output directory;
    # llvm-cov adds its own html/ directory below that.
    html_directory = source / "html"
    if not (html_directory / "index.html").is_file():
        html_directory = html_directory / "html"
    if not (html_directory / "index.html").is_file():
        raise ValueError("coverage report has no HTML index")
    if not (source / "lcov.info").is_file() or not (source / "lcov.info").stat().st_size:
        raise ValueError("coverage report has no LCOV data")
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
        if html_directory == source / "html/html":
            (staged / "html/html").rename(staged / "normalized-html")
            shutil.rmtree(staged / "html")
            (staged / "normalized-html").rename(staged / "html")
        staged.rename(destination)
    return 1


def _reports(root: Path) -> list[dict]:
    reports = []
    for metadata_path in sorted((root / "runs").glob("*/*/metadata.json")):
        metadata = _read(metadata_path)
        metadata["path"] = metadata_path.parent.relative_to(root).as_posix()
        metadata["coverage"] = _coverage(metadata_path.parent / "lcov.info")
        reports.append(metadata)
    return reports


def _pulls(path: Path) -> dict[int, dict]:
    if not path.exists():
        return {}
    value = _read(path)
    pulls = [item for page in value for item in page] if value and isinstance(value[0], list) else value
    return {int(item["number"]): item for item in pulls}


def history(root: Path, pulls_path: Path | None = None) -> list[dict]:
    root.mkdir(parents=True, exist_ok=True)
    pulls = _pulls(pulls_path) if pulls_path else {}
    registry = [{key: pull.get(key) for key in ("number", "state", "merged_at", "merge_commit_sha")}
                for pull in pulls.values()]
    (root / "pull-requests.json").write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
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
            report["reference_time"] = pull.get("merged_at")
        report["visible"] = visible
        reports.append(report)
    reports.sort(key=lambda value: (_time(value.get("reference_time") or value.get("completed_at")), value["path"]), reverse=True)
    (root / "history.json").write_text(json.dumps(reports, indent=2) + "\n", encoding="utf-8")
    return reports


def _run_order(report: dict) -> tuple:
    return (_time(report.get("created_at") or report.get("completed_at") or report.get("reference_time")),
            int(report.get("run_id", 0)), int(report.get("run_attempt", 1)))


def regenerate(root: Path) -> int:
    reports = _read(root / "history.json") if (root / "history.json").exists() else _reports(root)
    pulls = _pulls(root / "pull-requests.json")
    merges = {pull["merge_commit_sha"]: number for number, pull in pulls.items()
              if pull.get("merged_at") and pull.get("merge_commit_sha")}
    latest = {}
    for original in sorted(reports, key=_run_order, reverse=True):
        report = dict(original)
        target = report.get("target", "main")
        phase = ""
        if target == "main":
            number = merges.get(report.get("head_sha") or report.get("sha"))
            if number is None:
                continue
            target = f"pr/{number}"
            phase = "post-merge"
        elif target.startswith("pr/"):
            phase = "pre-merge"
        if target.startswith("pr/"):
            pull = pulls.get(int(target[3:]))
            if pull is not None:
                report["visible"] = pull.get("state") != "closed" or bool(pull.get("merged_at"))
                report["reference_time"] = pull.get("merged_at")
        if not report.get("visible", True):
            continue
        report.update(target=target, phase=phase)
        latest.setdefault((target, phase), report)
    phases = sorted(latest.values(), key=lambda report: (
        bool(report.get("reference_time")),
        _time(report.get("reference_time") or report.get("created_at") or report.get("completed_at")),
        report["phase"], _run_order(report)), reverse=True)
    visible = [report for report in phases
               if report["phase"] != "pre-merge" or (report["target"], "post-merge") not in latest]
    (root / "index.html").write_text(_render(
        root, visible, "coderef coverage reports",
        "One result per PR, ordered by merge time, then open PRs. Pre-merge coverage is replaced "
        "only by coverage of the exact merge commit. Closed unmerged PRs are omitted; "
        "their direct report URLs remain available.",
        _link("history.html", "Pre-merge and post-merge results")), encoding="utf-8")
    (root / "history.html").write_text(_render(
        root, phases, "coderef pre-merge and post-merge coverage",
        "One result per PR phase. Post-merge results test the exact merge commit; "
        "retries and unrelated main runs are omitted.",
        _link("index.html", "Current coverage overview")), encoding="utf-8")
    return len(visible)


def _render(root: Path, reports: list[dict], title: str, description: str, navigation: str) -> str:
    rows = []
    for report in reports:
        target = report.get("target", "main")
        path = report["path"]
        label = f"PR {target[3:]}" if target.startswith("pr/") else target
        if report.get("phase"):
            label += f" ({report['phase']})"
        if target == "main":
            source = _link(f"{_REPOSITORY}/tree/main", "main branch")
        elif target.startswith("pr/"):
            source = _link(f"{_REPOSITORY}/pull/{quote(target[3:], safe='')}", f"PR #{target[3:]}")
        else:
            source = escape(target)
        completed = report.get("completed_at") or report.get("reference_time")
        timestamp = (_time(completed).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
                     if completed else "n/a")
        sha = report.get("head_sha") or report.get("sha")
        commit = _link(f"{_REPOSITORY}/commit/{quote(sha, safe='')}", sha[:7]) if sha else "n/a"
        run_id = report.get("run_id")
        workflow = "n/a"
        if run_id:
            workflow = _link(f"{_REPOSITORY}/actions/runs/{quote(str(run_id), safe='')}", f"run {run_id}")
            attempt = report.get("run_attempt", 1)
            if int(attempt) > 1:
                workflow += f" (attempt {escape(str(attempt))})"
        details = (
            _link(f"{path}/html/index.html", label),
            _link(f"{path}/lcov.info", "LCOV") + " · " + _link(f"{path}/metadata.json", "Metadata"),
            source, timestamp, commit, workflow,
        )
        cells = [f"<td>{value}</td>" for value in details]
        # Read LCOV for old histories too, without modifying archived snapshots.
        metrics = report.get("coverage") or _coverage(root / path / "lcov.info")
        for metric in _METRICS:
            value = metrics[metric]
            rate = "n/a" if value["percent"] is None else f'{value["percent"]:.2f}%'
            cells.append(f'<td title="{value["covered"]}/{value["total"]}">{rate}</td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")
    headings = ("Report", "Data", "Source", "Completed", "Commit", "Workflow", "Lines", "Branches", "Functions")
    table = ('<div class="tableScroll"><table class="reportsTable"><thead><tr>'
             + "".join(f'<th scope="col">{heading}</th>' for heading in headings)
             + "</tr></thead><tbody>\n" + "\n".join(rows) + "\n</tbody></table></div>"
             if rows else "<p>No coverage reports are available.</p>")
    return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    body {{ font: 16px/1.5 system-ui, sans-serif; margin: 2rem auto; max-width: 96rem; padding: 0 1rem; }}
    a {{ color: #0969da; }}
    .tableScroll {{ overflow-x: auto; }}
    table {{ border-collapse: collapse; margin: 1rem 0 2rem; }}
    th, td {{ border: 1px solid #d0d7de; padding: .35rem .65rem; text-align: right; }}
    .reportsTable th:nth-child(-n+6), .reportsTable td:nth-child(-n+6) {{ text-align: left; }}
    .reportsTable td:nth-child(n+7) {{ font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-variant-numeric: tabular-nums; }}
  </style>
</head>
<body>
  <h1>{escape(title)}</h1>
  <p>{navigation}</p>
  <p>{escape(description)}</p>
  <p>Coverage is measured for Rust. n/a means no measurements are available for that metric.</p>
  {table}
</body>
</html>
'''


def _link(url: str, label: str) -> str:
    return f'<a href="{escape(url, quote=True)}">{escape(label)}</a>'


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
