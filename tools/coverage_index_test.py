import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from coverage_index import _coverage, archive, history, regenerate


class CoverageIndexTest(unittest.TestCase):
    def report(self, incoming, nested=False):
        html = incoming / ("html/html" if nested else "html")
        html.mkdir(parents=True)
        (html / "index.html").write_text('<a href="source.html">source</a>')
        (html / "source.html").write_text("covered source")
        (incoming / "lcov.info").write_text("SF:src/lib.rs\nDA:1,1\nend_of_record\n")

    def test_archive_keeps_late_attempts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "site"
            incoming = Path(directory) / "incoming"
            incoming.mkdir()
            (incoming / "metadata.json").write_text(json.dumps({"run_id": 7, "run_attempt": 2, "target": "main"}))
            self.report(incoming)
            self.assertEqual(archive(root, incoming), 1)
            self.assertEqual(archive(root, incoming), 0)
            self.assertTrue((root / "runs/7/2/html").exists())

    def test_closed_unmerged_report_hidden(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "site"
            for run, target in (("1", "pr/12"), ("2", "main")):
                incoming = Path(directory) / run
                incoming.mkdir()
                (incoming / "metadata.json").write_text(json.dumps({"run_id": run, "target": target, "completed_at": "2026-01-01T00:00:00Z"}))
                self.report(incoming)
                archive(root, incoming)
            pulls = Path(directory) / "pulls.json"
            pulls.write_text(json.dumps([[{"number": 12, "state": "closed", "merged_at": None}]]))
            reports = history(root, pulls)
            self.assertFalse(next(item for item in reports if item["target"] == "pr/12")["visible"])
            regenerate(root)
            self.assertNotIn("PR 12", (root / "index.html").read_text())
            self.assertIn("PR 12", (root / "history.html").read_text())

    def test_coverage_cli_archive_history_regenerate_links_resolve(self):
        script = Path(__file__).with_name("coverage_index.py")
        for nested in (False, True):
            with self.subTest(legacy_layout=nested), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / "site/coverage"
                incoming = Path(directory) / "incoming"
                self.report(incoming, nested=nested)
                metadata = {"run_id": "7", "run_attempt": "2", "target": "pr/12",
                            "reference_time": "2026-01-01T00:00:00Z"}
                (incoming / "metadata.json").write_text(json.dumps(metadata))
                pulls = Path(directory) / "pulls.json"
                pulls.write_text(json.dumps([[{"number": 12, "state": "closed",
                                              "merged_at": "2026-01-02T00:00:00Z"}]]))
                for args in (("archive", root, "--incoming", incoming),
                             ("history", root, pulls), ("regenerate", root)):
                    subprocess.run([sys.executable, str(script), *map(str, args)], check=True)
                overview = (root / "index.html").read_text()
                self.assertIn("PR 12", overview)
                links = re.findall(r'href="([^"]+)"', overview)
                self.assertEqual([link for link in links if link.endswith("html/index.html")],
                                 ["runs/7/2/html/index.html"])
                for link in links:
                    if not link.startswith("https://"):
                        self.assertTrue((root / link).is_file(), link)
                report = root / "runs/7/2/html/index.html"
                self.assertTrue(report.is_file())
                self.assertTrue((report.parent / "source.html").is_file())
                original = report.read_text()
                (incoming / ("html/html" if nested else "html") / "index.html").write_text("changed")
                self.assertEqual(archive(root, incoming), 0)
                self.assertEqual(report.read_text(), original)

    def test_coverage_archive_incomplete_report_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            incoming = Path(directory) / "incoming"
            incoming.mkdir()
            (incoming / "metadata.json").write_text('{"run_id": "7"}')
            with self.assertRaisesRegex(ValueError, "HTML index"):
                archive(Path(directory) / "site", incoming)
            (incoming / "html").mkdir()
            (incoming / "html/index.html").write_text("report")
            with self.assertRaisesRegex(ValueError, "LCOV"):
                archive(Path(directory) / "site", incoming)

    def test_coverage_lcov_multiple_files_uses_weighted_totals(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lcov.info"
            path.write_text("SF:a.rs\nLF:10\nLH:10\nFNF:2\nFNH:1\nBRF:0\nBRH:0\nend_of_record\n"
                            "SF:b.rs\nLF:90\nLH:0\nFNF:8\nFNH:1\nBRF:0\nBRH:0\nend_of_record\n")
            metrics = _coverage(path)
            self.assertEqual(metrics["lines"], {"covered": 10, "total": 100, "percent": 10.0})
            self.assertEqual(metrics["functions"], {"covered": 2, "total": 10, "percent": 20.0})
            self.assertEqual(metrics["branches"], {"covered": 0, "total": 0, "percent": None})
            path.write_text("SF:a.rs\nBRF:4\nBRH:3\nend_of_record\n")
            self.assertEqual(_coverage(path)["branches"]["percent"], 75.0)
            self.assertIsNone(_coverage(path)["lines"]["percent"])

    def test_coverage_overview_table_links_metrics_and_retry_visible(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "site"
            incoming = Path(directory) / "incoming"
            self.report(incoming)
            (incoming / "lcov.info").write_text("LF:4\nLH:3\nFNF:2\nFNH:1\nBRF:0\nBRH:0\n")
            metadata = {"run_id": "7", "run_attempt": "2", "target": "pr/12",
                        "head_sha": "abcdef0123456789", "completed_at": "2026-01-01T03:00:00+02:00"}
            (incoming / "metadata.json").write_text(json.dumps(metadata))
            archive(root, incoming)
            reports = history(root)
            self.assertEqual(reports[0]["coverage"]["lines"]["percent"], 75.0)
            self.assertEqual(regenerate(root), 1)
            html = (root / "index.html").read_text()
            self.assertEqual(re.findall(r'<th scope="col">([^<]+)</th>', html),
                             ["Report", "Data", "Source", "Completed", "Commit", "Workflow",
                              "Lines", "Branches", "Functions"])
            for value in ('class="reportsTable"', '2026-01-01 01:00:00 UTC', 'attempt 2',
                          'href="runs/7/2/lcov.info"', 'href="runs/7/2/metadata.json"',
                          'href="https://github.com/mboworks/coderef/pull/12"',
                          'href="https://github.com/mboworks/coderef/commit/abcdef0123456789"',
                          'href="https://github.com/mboworks/coderef/actions/runs/7"',
                          '<td title="3/4">75.00%</td>', '<td title="0/0">n/a</td>',
                          '<td title="1/2">50.00%</td>'):
                self.assertIn(value, html)
            self.assertEqual(json.loads((root / "runs/7/2/metadata.json").read_text()), metadata)
            # Histories generated before metrics were added still get populated table cells.
            del reports[0]["coverage"]
            (root / "history.json").write_text(json.dumps(reports))
            regenerate(root)
            self.assertIn('75.00%', (root / "index.html").read_text())

    def test_coverage_overview_empty_and_legacy_metadata_render_safely(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(regenerate(root), 0)
            self.assertIn("No coverage reports", (root / "index.html").read_text())
            records = [{"path": "runs/7/1", "target": '<script>alert("x")</script>'},
                       {"path": "runs/8/1", "target": "main", "sha": "123456789"}]
            (root / "history.json").write_text(json.dumps(records))
            self.assertEqual(regenerate(root), 2)
            html = (root / "index.html").read_text()
            self.assertNotIn('<script>', html)
            self.assertIn('&lt;script&gt;', html)
            self.assertIn('href="https://github.com/mboworks/coderef/tree/main"', html)
            self.assertIn('href="https://github.com/mboworks/coderef/commit/123456789"', html)
            self.assertIn('n/a', html)

    def test_coverage_overview_history_preserves_order_and_attempts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "site"
            incoming = Path(directory) / "incoming"
            self.report(incoming)
            for run, attempt, completed in (("7", "1", "2026-01-01T00:00:00Z"),
                                            ("7", "2", "2026-01-03T00:00:00Z"),
                                            ("8", "1", "2026-01-02T00:00:00Z")):
                (incoming / "metadata.json").write_text(json.dumps({
                    "run_id": run, "run_attempt": attempt, "target": "main", "completed_at": completed}))
                archive(root, incoming)
            history(root)
            self.assertEqual(regenerate(root), 1)
            html = (root / "index.html").read_text()
            links = re.findall(r'href="(runs/[^"]+/html/index.html)"', html)
            self.assertEqual(links, ["runs/7/2/html/index.html"])
            self.assertIn('href="history.html"', html)
            archived = (root / "history.html").read_text()
            links = re.findall(r'href="(runs/[^"]+/html/index.html)"', archived)
            self.assertEqual(links, ["runs/7/2/html/index.html", "runs/8/1/html/index.html",
                                     "runs/7/1/html/index.html"])
            self.assertIn('href="index.html"', archived)

    def test_overview_late_retry_keeps_latest_run_and_main_first(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reports = [
                {"target": "main", "run_id": "7", "run_attempt": "10", "path": "runs/7/10",
                 "created_at": "2026-01-01T00:00:00Z", "completed_at": "2026-01-04T00:00:00Z"},
                {"target": "main", "run_id": "8", "run_attempt": "2", "path": "runs/8/2",
                 "created_at": "2026-01-02T00:00:00Z"},
                {"target": "main", "run_id": "8", "run_attempt": "10", "path": "runs/8/10",
                 "created_at": "2026-01-02T00:00:00Z"},
                {"target": "pr/12", "run_id": "9", "path": "runs/9/1",
                 "completed_at": "2026-01-05T00:00:00Z"},
                {"target": "pr/12", "run_id": "6", "path": "runs/6/1",
                 "completed_at": "2026-01-01T00:00:00Z"},
            ]
            original = json.dumps(reports)
            (root / "history.json").write_text(original)
            self.assertEqual(regenerate(root), 2)
            html = (root / "index.html").read_text()
            links = re.findall(r'href="(runs/[^"]+/html/index.html)"', html)
            self.assertEqual(links, ["runs/8/10/html/index.html", "runs/9/1/html/index.html"])
            archived = (root / "history.html").read_text()
            self.assertEqual(len(re.findall(r'href="runs/[^"]+/html/index.html"', archived)), 5)
            self.assertEqual((root / "history.json").read_text(), original)

    def test_overview_merged_pr_keeps_pr_run_and_uses_merge_time(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "site"
            incoming = Path(directory) / "incoming"
            self.report(incoming)
            targets = [("1", "main"), ("2", "pr/12"), ("3", "pr/13"), ("4", "pr/14")]
            for run, target in targets:
                (incoming / "metadata.json").write_text(json.dumps({
                    "run_id": run, "target": target, "head_sha": f"sha{run}",
                    "completed_at": f"2026-01-0{run}T00:00:00Z"}))
                archive(root, incoming)
            pulls = Path(directory) / "pulls.json"
            pulls.write_text(json.dumps([
                {"number": 12, "state": "closed", "merged_at": "2026-01-06T00:00:00Z"},
                {"number": 13, "state": "closed", "merged_at": "2026-01-05T00:00:00Z"},
                {"number": 14, "state": "open", "merged_at": None}]))
            records = history(root, pulls)
            merged = next(row for row in records if row["target"] == "pr/12")
            self.assertEqual(merged["run_id"], "2")
            self.assertEqual(merged["head_sha"], "sha2")
            self.assertEqual(merged["reference_time"], "2026-01-06T00:00:00Z")
            regenerate(root)
            html = (root / "index.html").read_text()
            links = re.findall(r'href="(runs/[^"]+/html/index.html)"', html)
            self.assertEqual(links, [f"runs/{run}/1/html/index.html" for run in (1, 2, 3, 4)])

    def test_history_refresh_merge_reorders_without_replacing_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "site"
            incoming = Path(directory) / "incoming"
            self.report(incoming)
            (incoming / "lcov.info").write_text("LF:10\nLH:9\nFNF:2\nFNH:1\n")
            for number in (12, 13):
                (incoming / "metadata.json").write_text(json.dumps({
                    "run_id": str(number), "target": f"pr/{number}", "head_sha": f"tested-{number}",
                    "created_at": "2026-01-01T00:00:00Z", "completed_at": "2026-01-01T00:01:00Z"}))
                archive(root, incoming)
            snapshots = {path.relative_to(root): path.read_bytes()
                         for path in (root / "runs").rglob("*") if path.is_file()}
            pulls = Path(directory) / "pulls.json"
            values = [{"number": 12, "state": "closed", "merged_at": "2026-01-02T00:00:00Z"},
                      {"number": 13, "state": "open", "merged_at": None}]
            pulls.write_text(json.dumps(values))
            history(root, pulls)
            regenerate(root)
            before = (root / "index.html").read_text()
            self.assertLess(before.index("PR #12"), before.index("PR #13"))
            values[1].update(state="closed", merged_at="2026-01-03T00:00:00Z")
            pulls.write_text(json.dumps(values))
            reports = history(root, pulls)
            regenerate(root)
            after = (root / "index.html").read_text()
            self.assertLess(after.index("PR #13"), after.index("PR #12"))
            row = next(item for item in reports if item["target"] == "pr/13")
            self.assertEqual(row["head_sha"], "tested-13")
            self.assertEqual(row["run_id"], "13")
            self.assertEqual(row["coverage"]["lines"]["percent"], 90.0)
            self.assertEqual({path.relative_to(root): path.read_bytes()
                              for path in (root / "runs").rglob("*") if path.is_file()}, snapshots)

    def test_history_refresh_before_first_report_renders_empty_overview(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "coverage"
            self.assertEqual(history(root), [])
            self.assertEqual(regenerate(root), 0)
            self.assertIn("No coverage reports", (root / "index.html").read_text())
            self.assertTrue((root / "history.html").is_file())


if __name__ == "__main__":
    unittest.main()
