#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) M. Boerger, the MBO Works authors
# SPDX-License-Identifier: Apache-2.0
"""Lossless storage for generated Pages data; measurements keep their original bytes."""

import gzip
import json

from coverage_index import render_summary, report_coverage


def compact_json(path):
    original = path.read_bytes()
    destination = path.with_suffix(path.suffix + '.gz')
    destination.write_bytes(gzip.compress(original, mtime=0))
    path.unlink()


def compact_page(page, root, data):
    if not page.exists():
        return
    if 'data-packed-page=' not in page.read_text():
        page.with_name('page.html.gz').write_bytes(gzip.compress(page.read_bytes(), mtime=0))
    prefix = '/'.join(['..'] * len(page.parent.relative_to(root).parts))
    page.write_text('<!doctype html><meta charset="utf-8"><title>Report</title>'
                        '<p id="loading" role="status">Loading report...</p>'
                        f'<script src="{prefix}/site-page.js" data-packed-page="page.html.gz"></script>'
                        f'<noscript>This report requires JavaScript. <a href="{data}">Download data</a>.</noscript>\n')


def prepare_summaries(root):
    """Capture aggregates before expiring any original LLVM HTML source pages."""
    for metadata in sorted(root.glob('runs/*/*/metadata.json')):
        report = metadata.parent
        summary = report / 'coverage-summary.json'
        if not summary.exists() and not summary.with_suffix('.json.gz').exists():
            if not any((report / name).is_file() for name in ('lcov.info', 'lcov.info.gz')):
                raise ValueError(f'missing aggregate measurements: {report}')
            summary.write_text(json.dumps({'schema': 1, 'coverage': report_coverage(report)}) + '\n')
        if not (report / 'index.html').exists():
            (report / 'index.html').write_text(render_summary(json.loads(metadata.read_text()),
                                                            report_coverage(report)))


def compact_summaries(root):
    for name in ('coverage-summary.json', 'lcov.info'):
        for path in root.rglob(name):
            compact_json(path)
    for page in root.rglob('*.html'):
        if 'html' in page.relative_to(root).parts[:-1]:
            continue
        text = page.read_text().replace('lcov.info"', 'lcov.info.gz"')
        page.write_text(text)
        if page.name == 'index.html' and page.with_name('metadata.json').exists():
            compact_page(page, root.parent, 'coverage-summary.json.gz')
