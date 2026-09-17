# SPDX-FileCopyrightText: Copyright (c) M. Boerger, the MBO Works authors
# SPDX-License-Identifier: Apache-2.0
"""Pin CI resource policy and release/publisher integration."""

from pathlib import Path
import unittest

ROOT = Path(__file__).parents[1]


class InfrastructureTest(unittest.TestCase):
    def test_rust_caches_all_callers_restrict_saves_to_main(self):
        for name in ('ci', 'release', 'vscode_marketplace'):
            text = (ROOT / f'.github/workflows/{name}.yml').read_text()
            self.assertEqual(text.count('uses: Swatinem/rust-cache@v2'),
                             text.count("save-if: ${{ github.ref == 'refs/heads/main' }}"))

    def test_ci_profiles_and_required_jobs_remain_wired(self):
        text = (ROOT / '.github/workflows/ci.yml').read_text()
        self.assertIn('cargo build --release --locked --timings', text)
        artifact = text.split('      - name: Preserve Cargo build timings')[1].split('      - name:')[0]
        self.assertIn('if: always()', artifact)
        self.assertIn('retention-days: 7', artifact)
        self.assertIn('if-no-files-found: warn', artifact)
        self.assertIn("cancel-in-progress: ${{ github.event_name == 'pull_request' }}", text)
        self.assertIn('needs: [release-site-tests, version, rust, wasm, extension, npm-wrapper, schema, docs]', text)

    def test_release_complete_publication_precedes_downstream_channels(self):
        text = (ROOT / '.github/workflows/release.yml').read_text()
        self.assertIn('python3 tools/publish_release.py "${GITHUB_REF_NAME}" _dist release-notes.md', text)
        self.assertIn('cancel-in-progress: false', text)
        self.assertIn('    needs: release', text)
        self.assertIn('    needs: npm', text)
        self.assertNotIn('gh release upload', text)

    def test_pages_artwork_preserves_live_schema_endpoint(self):
        text = (ROOT / '.github/workflows/pages.yml').read_text()
        self.assertIn('cp source/schema/coderef.schema.json site/schema/v1.json', text)
        self.assertIn('python3 source/tools/site_artwork.py source/docs/assets public', text)


if __name__ == '__main__':
    unittest.main()
