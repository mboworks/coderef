# SPDX-FileCopyrightText: Copyright (c) M. Boerger, the MBO Works authors
# SPDX-License-Identifier: Apache-2.0
"""Retained Rust coverage with LLVM-style named source anchors."""

import datetime
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from compact_site import compact
from coverage_index import history, regenerate


def build(root):
    now = datetime.datetime.now(datetime.timezone.utc)
    for run, age in ((2, 0), (3, 0), (1, 8)):
        report = root / f'coverage/runs/{run}/1'
        (report / 'html/coverage/src').mkdir(parents=True)
        (report / 'metadata.json').write_text(json.dumps({
            'run_id': run, 'run_attempt': 1, 'target': 'pr/12',
            'completed_at': (now - datetime.timedelta(days=age)).isoformat(), 'head_sha': 'actual-commit'}))
        (report / 'lcov.info').write_text('SF:src/lib.rs\nLF:10\nLH:9\nFNF:10\nFNH:9\nBRF:10\nBRH:9\nend_of_record\n')
        (report / 'html/index.html').write_text(
            '<html><body><a href="coverage/src/lib.rs.html#L100">Source</a></body></html>')
        lines = ''.join(f'<tr><td><a name="L{line}" href="#L{line}"><pre>{line}</pre></a></td>'
                        f'<td class="code"><pre>return {line};</pre></td></tr>' for line in range(1, 121))
        (report / 'html/coverage/src/lib.rs.html').write_text(
            '<html><head><link rel="stylesheet" href="../../style.css">'
            '<script src="../../control.js"></script></head><body>'
            '<span class="control"><a href="javascript:next_line()">Next uncovered line</a></span>'
            '<a href="../../index.html">Source index</a><table>' + lines + '</table></body></html>')
        (report / 'html/style.css').write_text('body{color:rgb(1,2,3)}tr{height:24px}')
        (report / 'html/control.js').write_text('throw new Error("Report scripts must never run")')
    history(root / 'coverage')
    regenerate(root / 'coverage')
    compact(root, now)
    history(root / 'coverage')
    regenerate(root / 'coverage')
    compact(root, now)


if __name__ == '__main__':
    build(Path(sys.argv[1]))
