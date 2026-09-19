import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from coverage_index import archive, history, regenerate


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
            self.assertNotIn("pr/12", (root / "index.html").read_text())

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
                self.assertIn("pr/12", overview)
                links = re.findall(r'href="([^"]+)"', overview)
                self.assertEqual(links, ["runs/7/2/html/index.html"])
                report = root / links[0]
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


if __name__ == "__main__":
    unittest.main()
