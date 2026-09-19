# SPDX-FileCopyrightText: Copyright (c) M. Boerger, the MBO Works authors
# SPDX-License-Identifier: Apache-2.0
"""Pin CI resource policy and release/publisher integration."""

from pathlib import Path
import json
import os
import re
import subprocess
import tempfile
import textwrap
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
        self.assertIn('needs: [release-site-tests, version, rust, coverage, wasm, extension, npm-wrapper, schema, docs]', text)

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

    def workflow_script(self, workflow, step):
        text = (ROOT / f".github/workflows/{workflow}.yml").read_text()
        body = text.split(f"      - name: {step}\n", 1)[1].split("\n      - ", 1)[0]
        self.assertIn("        run: |\n", body, "Shell continuations require a YAML literal block")
        return textwrap.dedent(body.split("        run: |\n", 1)[1])

    def test_coverage_download_shell_preserves_exact_arguments(self):
        script = self.workflow_script("pages", "Download immutable coverage attempt")
        result = subprocess.run(["bash", "-c", 'gh() { printf "%s\\0" "$@"; };\n' + script],
                                env={**os.environ, "RUN_ID": "123", "RUN_ATTEMPT": "2",
                                     "GITHUB_REPOSITORY": "mboworks/coderef"},
                                capture_output=True, check=True)
        self.assertEqual(result.stdout.decode().split("\0")[:-1],
                         ["run", "download", "123", "--repo", "mboworks/coderef",
                          "--name", "coverage-123-2", "--dir", "report"])
        job = (ROOT / ".github/workflows/pages.yml").read_text().split("\n  coverage:\n", 1)[1]
        permissions = job.split("    permissions:\n", 1)[1].split("    environment:", 1)[0]
        self.assertIn("      actions: read\n", permissions)
        self.assertIn("      pull-requests: read\n", permissions)

    def test_coverage_generation_shell_produces_expected_layout(self):
        script = self.workflow_script("ci", "Generate LCOV and HTML coverage")
        script = re.sub(r"\$\{\{.*?\}\}", "123", script)
        mock = '''cargo() {
          if [[ "$2" == report ]]; then
            mkdir -p "${@: -1}/html"
            echo report > "${@: -1}/html/index.html"
          else
            echo coverage > coverage/lcov.info
          fi
        }
        '''
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run(["bash", "-c", mock + script], cwd=directory, check=True)
            self.assertTrue((Path(directory) / "coverage/html/index.html").is_file())
            self.assertTrue((Path(directory) / "coverage/lcov.info").is_file())

    def test_coverage_metadata_events_classify_main_and_prs(self):
        script = self.workflow_script("pages", "Add target and reference metadata")
        cases = [("push", "main", "", "refs/heads/main", "main"),
                 ("pull_request", "feature", "42", "refs/pull/42/merge", "pr/42"),
                 ("pull_request", "feature", "", "refs/pull/43/merge", "pr/43"),
                 ("pull_request", "feature", "", "refs/heads/main", None),
                 ("push", "feature", "", "refs/heads/feature", None)]
        for event, branch, number, reference, target in cases:
            with self.subTest(event=event, reference=reference), tempfile.TemporaryDirectory() as directory:
                report = Path(directory) / "report"
                report.mkdir()
                metadata = report / "metadata.json"
                metadata.write_text(json.dumps({"reference": reference}))
                env = {**os.environ, "RUN_EVENT": event, "HEAD_BRANCH": branch, "PR_NUMBER": number,
                       "RUN_ID": "123", "RUN_ATTEMPT": "2", "HEAD_SHA": "abc",
                       "CREATED_AT": "2026-01-01T00:00:00Z", "COMPLETED_AT": "2026-01-01T00:01:00Z"}
                result = subprocess.run(["bash", "-c", script], cwd=directory, env=env,
                                        capture_output=True, text=True)
                if target is None:
                    self.assertNotEqual(result.returncode, 0)
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    actual = json.loads(metadata.read_text())
                    self.assertEqual(actual["target"], target)
                    self.assertEqual(actual["run_id"], "123")
                    self.assertEqual(actual["run_attempt"], "2")
                    self.assertEqual(actual["head_sha"], "abc")

    def test_coverage_publish_archive_push_and_stage_preserve_site(self):
        script = self.workflow_script("pages", "Index and archive coverage history")
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            (work / "source").symlink_to(ROOT, target_is_directory=True)
            site = work / "site"
            site.mkdir()
            (site / "schema").mkdir()
            (site / "schema/v1.json").write_text('{"title":"schema"}')
            (site / "index.html").write_text('<html><head></head><body>release</body></html>')
            report = work / "report"
            (report / "html").mkdir(parents=True)
            (report / "html/index.html").write_text('<html><head></head><body>coverage</body></html>')
            (report / "lcov.info").write_text('SF:src/lib.rs\nDA:1,1\nend_of_record\n')
            (report / "metadata.json").write_text(json.dumps({"run_id": "7", "run_attempt": "2",
                                                            "target": "main"}))
            remote = work / "remote.git"
            for command in (["git", "init", "--bare", str(remote)],
                            ["git", "init", "-b", "coverage-pages", str(site)],
                            ["git", "-C", str(site), "config", "commit.gpgsign", "false"],
                            ["git", "-C", str(site), "config", "user.name", "Test"],
                            ["git", "-C", str(site), "config", "user.email", "test@example.invalid"],
                            ["git", "-C", str(site), "add", "."],
                            ["git", "-C", str(site), "commit", "-m", "Existing release site"],
                            ["git", "-C", str(site), "remote", "add", "origin", str(remote)]):
                subprocess.run(command, check=True, capture_output=True)
            env = {**os.environ, "RUN_ID": "7", "GITHUB_REPOSITORY": "mboworks/coderef"}
            command = 'gh() { printf "[]\\n"; };\n' + script
            subprocess.run(["bash", "-c", command], cwd=work, env=env, check=True, capture_output=True)
            self.assertTrue((work / "public/coverage/runs/7/2/html/index.html").is_file())
            self.assertIn('href="runs/7/2/html/index.html"', (work / "public/coverage/index.html").read_text())
            self.assertIn('release', (work / "public/index.html").read_text())
            self.assertEqual((work / "public/schema/v1.json").read_text(), '{"title":"schema"}')
            retained = subprocess.check_output(["git", "--git-dir", str(remote), "show",
                                               "coverage-pages:coverage/runs/7/2/metadata.json"], text=True)
            self.assertEqual(json.loads(retained)["run_id"], "7")
            self.assertNotIn("mboworks favicons", (site / "index.html").read_text())
            self.assertIn("mboworks favicons", (work / "public/index.html").read_text())


if __name__ == '__main__':
    unittest.main()
