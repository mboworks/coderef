# SPDX-FileCopyrightText: Copyright (c) M. Boerger, the MBO Works authors
# SPDX-License-Identifier: Apache-2.0
"""Rust aggregate history survives source expiry and original LCOV compaction."""

import contextlib
import datetime
import gzip
import io
import json
from pathlib import Path
import tempfile
import unittest

import compact_site
import coverage_index
import site_artwork


class SiteStorageTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.coverage = self.root / 'coverage'
        self.now = datetime.datetime(2026, 10, 4, tzinfo=datetime.timezone.utc)

    def report(self, run, days):
        report = self.coverage / f'runs/{run}/1'
        (report / 'html').mkdir(parents=True)
        (report / 'html/index.html').write_text('<html>LLVM coverage</html>')
        (report / 'html/lib.rs.html').write_text('<a name="L1">source</a>')
        metadata = {'run_id': run, 'run_attempt': 1, 'target': 'pr/12', 'head_sha': 'original',
                    'completed_at': (self.now - datetime.timedelta(days=days)).isoformat()}
        (report / 'metadata.json').write_text(json.dumps(metadata) + '\n')
        (report / 'lcov.info').write_text('SF:a.rs\nLF:10\nLH:10\nFNF:2\nFNH:1\nend_of_record\n'
                                        'SF:b.rs\nLF:90\nLH:0\nFNF:8\nFNH:1\nend_of_record\n')
        return report

    def compact(self):
        with contextlib.redirect_stdout(io.StringIO()):
            compact_site.compact(self.root, self.now)

    def test_expired_reports_keep_weighted_aggregates_original_metadata_and_lcov(self):
        report = self.report(12, 8)
        recent = self.report(13, 0)
        metadata = (report / 'metadata.json').read_bytes()
        lcov = (report / 'lcov.info').read_bytes()
        self.compact()
        self.assertEqual((report / 'metadata.json').read_bytes(), metadata)
        self.assertEqual(gzip.decompress((report / 'lcov.info.gz').read_bytes()), lcov)
        self.assertFalse((report / 'html/lib.rs.html').exists())
        self.assertIn('archive', json.loads((recent / 'details.json').read_text()))
        metrics = coverage_index.report_coverage(report)
        self.assertEqual(metrics['lines'], {'covered': 10, 'total': 100, 'percent': 10.0})
        self.assertEqual(metrics['functions']['percent'], 20.0)
        self.assertIsNone(metrics['branches']['percent'])
        # Rebuilding history uses the permanent summary even without the original artifact data.
        (report / 'lcov.info.gz').unlink()
        history = coverage_index.history(self.coverage)
        self.assertEqual(next(item['coverage'] for item in history if item['run_id'] == 12), metrics)
        coverage_index.regenerate(self.coverage)
        self.assertIn('10.00%', (self.coverage / 'index.html').read_text())
        self.compact()
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.compact()
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_missing_measurements_abort_before_source_expiration(self):
        report = self.report(12, 8)
        (report / 'lcov.info').unlink()
        with self.assertRaisesRegex(ValueError, 'missing aggregate measurements'):
            self.compact()
        self.assertTrue((report / 'html/lib.rs.html').exists())

    def test_gzip_lcov_fallback_preserves_legacy_counter_totals(self):
        report = self.report(12, 8)
        path = report / 'lcov.info'
        expected = coverage_index._coverage(path)
        path.with_suffix('.info.gz').write_bytes(gzip.compress(path.read_bytes(), mtime=0))
        path.unlink()
        self.compact()
        self.assertEqual(coverage_index.report_coverage(report), expected)

    def test_second_compaction_preserves_deployment_only_compressed_artwork(self):
        report = self.report(12, 8)
        self.compact()
        original = (report / 'page.html.gz').read_bytes()
        site_artwork.decorate(Path(__file__).resolve().parent.parent / 'docs/assets', self.root)
        decorated = (report / 'page.html.gz').read_bytes()
        self.assertNotEqual(original, decorated)
        self.compact()
        self.assertEqual((report / 'page.html.gz').read_bytes(), decorated)
        self.assertIn(site_artwork.MARKER.encode(), gzip.decompress(decorated))


if __name__ == '__main__':
    unittest.main()
