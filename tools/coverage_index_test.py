import json
import tempfile
import unittest
from pathlib import Path

from coverage_index import archive, history, regenerate


class CoverageIndexTest(unittest.TestCase):
    def test_archive_keeps_late_attempts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "site"
            incoming = Path(directory) / "incoming"
            incoming.mkdir()
            (incoming / "metadata.json").write_text(json.dumps({"run_id": 7, "run_attempt": 2, "target": "main"}))
            (incoming / "html").mkdir()
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
                archive(root, incoming)
            pulls = Path(directory) / "pulls.json"
            pulls.write_text(json.dumps([[{"number": 12, "state": "closed", "merged_at": None}]]))
            reports = history(root, pulls)
            self.assertFalse(next(item for item in reports if item["target"] == "pr/12")["visible"])
            regenerate(root)
            self.assertNotIn("pr/12", (root / "index.html").read_text())


if __name__ == "__main__":
    unittest.main()
