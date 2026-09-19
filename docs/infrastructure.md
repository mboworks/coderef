# Infrastructure and publishing

Adapted from [proto PR 100](https://github.com/mboworks/proto/pull/100) and xff PRs 835–848,
excluding 841, for this Rust/WASM/TypeScript workspace.

## Build resources and CI

Use `CARGO_BUILD_JOBS=2` when local compilation needs a conservative worker bound. Cargo compiler
jobs, test threads, and coderef's runtime workers are distinct; this is not a machine-wide CPU or
memory quota. No C++ clang-tidy or Bazel cache machinery is introduced.

Retain Swatinem/rust-cache's Cargo-aware dependency/toolchain keys and the existing host, WASM,
extension, wrapper, and release-target separation. Only main saves; PR/tag runs restore compatible
entries when available. Release-only keys may have no main seed and therefore build cold. The final
CI job reports compressed repository cache inventory, including other refs, before choosing size
budgets. Its snapshot may precede post-job uploads; compare later runs before claiming savings.

Only superseded PR runs are cancelled. Main's integration record completes, and every existing
Rust, WASM, extension/runtime/package, wrapper, schema, docs, version, and release-site job remains
in the final required gate. Cargo's release smoke build writes HTML timing reports, retained for
seven days even after failure. Missing reports warn. These reports describe Cargo compilation;
they do not measure npm installation or all network preparation time.

The Rust coverage job bounds compiler workers with `CARGO_BUILD_JOBS=2`, generates LCOV and HTML
reports with `cargo-llvm-cov`, and uploads each run and retry as an immutable artifact named from
`github.run_id` and `github.run_attempt`. The Pages workflow consumes those artifacts, archives
each run and attempt under `coverage/runs/`, and rebuilds an overview ordered by reference time.
It queries all pull-request states so closed unmerged reports are hidden from the overview while
remaining directly available in the archive; reopened reports become visible again.
CI requires both `lcov.info` and `html/index.html` before uploading. The publisher has explicit
Actions and pull-request read permissions, preserves the rest of the retained Pages tree, and
normalizes older artifacts containing `html/html/index.html`. Each overview link resolves to
`coverage/runs/<run>/<attempt>/html/index.html`. PR runs without an associated PR in the event
payload use the artifact's `refs/pull/<number>/merge` reference; unidentified PR runs fail instead
of being mislabeled as main. Regression tests execute the workflow shell commands, archive and
index reports, push to a temporary Git remote, and verify the staged site and report links.
The overview uses the same report table columns as the C++ repositories: Report, Data, Source,
Completed, Commit, Workflow, Lines, Branches, and Functions. Coderef's Python generator computes
rates from summed LCOV counters, links each immutable report and its LCOV/metadata downloads,
and displays completion times in UTC. Zero or unavailable metric totals display `n/a`, including
branch coverage when Rust instrumentation produces no branch measurements. Existing archives
are read without modification. The overview shows the latest run per target, with main first;
`history.html` retains every run and retry, including closed PRs. Run creation time determines
which run is latest, so retrying an older run cannot replace a newer run. Attempts within a run
are compared numerically. PR rows retain their own PR CI result, sorted by merge time after merging;
the main row contains the latest main CI result. Open PRs follow merged PRs. The coverage figures
describe Rust, not the Python or TypeScript scripts.

## Release publication

Keep `vX.Y.Z` tags and GitHub → npm → VSCode Marketplace ordering. Four platform archives plus
four checksum files must exist and agree before upload. The publisher creates or resumes a mutable
draft, uploads assets, checks every remote digest and upload state, then publishes once. An exact
already-published release needs no mutation; an incomplete or changed published release fails.
Release candidates remain prereleases and do not replace latest. A failed API query is an error,
not evidence that a release is absent. Release runs for the same ref serialize without cancellation.

Downstream npm and Marketplace retries remain independent. Never move a published tag or overwrite
immutable assets to repair a release. Publish a corrected version instead. No release, registry,
or Marketplace publication occurs during PR validation.

## Site and contributor rules

The schema endpoint `/schema/v1.json` and versioned release schema copies remain intact. Add the
shared 64-pixel README logo and decorate only the staged complete Pages copy with favicons; retained
release snapshots remain unchanged. Nested links and repeated decoration have regression tests.

`DESIGN.md` retains authority over product semantics and testing. `AGENTS.md` links shared Git/PR
rules in `GIT_RULES.md` and shell conventions in `STYLE_SH.md`, while Rust formatting/Clippy and
TypeScript validation keep their current tools. No C++ style rules or module version changes apply.

Run `python3 -m unittest discover -s tools -p '*_test.py'`, `pre-commit run --all-files`, and the
existing Cargo and extension checks appropriate to a change. Publishing orchestration is tested
with mocked GitHub commands, including corrupt/missing assets, existing drafts, immutable retries,
and failed remote verification. Live publication remains a tag-triggered external integration.
