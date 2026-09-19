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

    def test_coverage_job_gate_only_successful_source_attempt_is_eligible(self):
        script = self.workflow_script("pages", "Check coverage job result")
        for conclusion in ("success", "failure", "cancelled", "skipped", None, "missing"):
            with self.subTest(conclusion=conclusion), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                jobs = [{"name": "Rust workspace", "conclusion": "failure"}]
                if conclusion != "missing":
                    jobs.append({"name": "Rust coverage", "conclusion": conclusion})
                # Exercise pagination: the coverage job is on the second page.
                (root / "jobs.json").write_text(json.dumps([{"jobs": jobs[:1]}, {"jobs": jobs[1:]}]))
                mock = 'gh() { printf "%s\\n" "$@" > arguments; cat jobs.json; };\n'
                subprocess.run(["bash", "-c", mock + script], cwd=root, check=True,
                               env={**os.environ, "RUN_ID": "123", "RUN_ATTEMPT": "2",
                                    "GITHUB_REPOSITORY": "mboworks/coderef",
                                    "GITHUB_OUTPUT": str(root / "outputs")})
                self.assertEqual((root / "outputs").read_text(),
                                 f"eligible={str(conclusion == 'success').lower()}\n")
                self.assertEqual((root / "arguments").read_text().splitlines(), [
                    "api", "--paginate", "--slurp",
                    "repos/mboworks/coderef/actions/runs/123/attempts/2/jobs?per_page=100"])
                # API errors must fail closed, never consume an artifact.
                (root / "outputs").unlink()
                result = subprocess.run(["bash", "-c", 'gh() { return 1; };\n' + script],
                                        cwd=root, env={**os.environ, "RUN_ID": "123", "RUN_ATTEMPT": "2",
                                            "GITHUB_REPOSITORY": "mboworks/coderef",
                                            "GITHUB_OUTPUT": str(root / "outputs")})
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((root / "outputs").exists())

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
        refresh = self.workflow_script("pages", "Refresh metadata and publish retained reports")
        script = self.workflow_script("pages", "Archive incoming coverage report") + "\n" + refresh
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
                                                            "target": "pr/12"}))
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
            snapshots = {path.relative_to(site): path.read_bytes()
                         for path in (site / "coverage/runs").rglob("*") if path.is_file()}
            report.rename(work / "original-input")
            # Refresh must work without a downloaded artifact or triggering CI identity.
            env.pop("RUN_ID")
            for state, merged_at, visible in (("closed", "2026-01-02T00:00:00Z", True),
                                               ("closed", None, False), ("open", None, True)):
                (work / "api-pulls.json").write_text(json.dumps([[{
                    "number": 12, "state": state, "merged_at": merged_at}]]))
                command = 'gh() { cat api-pulls.json; };\n' + refresh
                subprocess.run(["bash", "-c", command], cwd=work, env=env,
                               check=True, capture_output=True)
                row = json.loads((site / "coverage/history.json").read_text())[0]
                self.assertEqual(row["visible"], visible)
                self.assertEqual(row["reference_time"], merged_at)
                self.assertEqual("PR 12" in (work / "public/coverage/index.html").read_text(), visible)
                self.assertEqual({path.relative_to(site): path.read_bytes()
                                  for path in (site / "coverage/runs").rglob("*") if path.is_file()},
                                 snapshots)


    def test_coverage_refresh_workflow_routes_events_to_trusted_publisher(self):
        text = (ROOT / ".github/workflows/pages.yml").read_text()
        self.assertIn("pull_request_target:\n    types: [closed, reopened]", text)
        self.assertIn("  group: coverage-pages\n  queue: max\n  cancel-in-progress: false", text)
        self.assertIn("      coverage_refresh:\n", text)
        gates = {}
        for job in ("publish", "coverage"):
            body = text.split(f"\n  {job}:\n", 1)[1]
            gates[job] = body.split("    if: >-\n", 1)[1].split("    runs-on:", 1)[0]
        for event, name, conclusion, source, manual, expected in (
            ("push", "", "", "", False, (True, False)),
            ("pull_request_target", "", "", "", False, (False, True)),
            ("pull_request", "", "", "", False, (False, False)),
            ("workflow_dispatch", "", "", "", False, (True, False)),
            ("workflow_dispatch", "", "", "", True, (False, True)),
            ("workflow_run", "CI", "success", "pull_request", False, (False, True)),
            ("workflow_run", "CI", "failure", "push", False, (False, True)),
            ("workflow_run", "CI", "cancelled", "push", False, (False, True)),
            ("workflow_run", "Release", "success", "push", False, (True, False)),
            ("workflow_run", "Other", "success", "push", False, (False, False)),
        ):
            with self.subTest(event=event, name=name, conclusion=conclusion, manual=manual):
                values = {"github.event_name": event, "github.event.workflow_run.name": name,
                          "github.event.workflow_run.conclusion": conclusion,
                          "github.event.workflow_run.event": source, "inputs.coverage_refresh": manual}
                actual = []
                for gate in gates.values():
                    expression = re.sub(r"(?:github|inputs)\.[a-z_.]+", lambda m: repr(values[m[0]]), gate)
                    expression = expression.replace("&&", " and ").replace("||", " or ").replace("!", " not ")
                    # Evaluate only trusted repository job conditions with literal event values.
                    actual.append(eval(" ".join(expression.split()), {"__builtins__": {}}))
                self.assertEqual(tuple(actual), expected)
        coverage = text.split("\n  coverage:\n", 1)[1]
        self.assertIn("          ref: main\n          path: source", coverage)
        self.assertNotIn("github.event.pull_request.head", coverage)
        for step in ("Download immutable coverage attempt", "Add target and reference metadata",
                     "Archive incoming coverage report"):
            self.assertIn(f"      - name: {step}\n        if: steps.coverage-result.outputs.eligible == 'true'", coverage)
        refresh = coverage.split("      - name: Refresh metadata and publish retained reports", 1)[1]
        self.assertNotIn("workflow_run", refresh)
        self.assertNotIn("--incoming", refresh)
        self.assertIn("pulls?state=all&per_page=100", refresh)
        self.assertLess(refresh.index("coverage_index.py history"), refresh.index("coverage_index.py regenerate"))
        self.assertLess(refresh.index("coverage_index.py regenerate"), refresh.index("git -C site push"))


if __name__ == '__main__':
    unittest.main()
