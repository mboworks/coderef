# coderef

[Release website](https://mboworks.github.io/coderef/)

Regex-driven references in source code — resolved, click-opened, and
verified identically from VSCode and from CI. A `.coderef.jsonc` config
declares the patterns; the same engine runs inside the editor (via WASM,
in-process) and inside the Rust CLI binary (for `pre-commit` and CI).

The working specification is [`DESIGN.md`](./DESIGN.md); this README is
the elevator pitch.

```python
# Click-to-open in VSCode; verified by pre-commit; same regex engine in both.
#
# TODO(@marcus): swap to argon2id — JIRA(SEC-87) tracks it.
# DOCREF(/docs/security/hashing) explains the threat model.
# RFC(8259) is the JSON spec.

# IfChange / ThenChange enforces co-modification across files:
# IfChange('hash-params')
HASH_PARAMS = {"memory_kib": 19456, "iterations": 2, "parallelism": 1}
# ThenChange(/docs/security.md:hash-params, /tests/test_auth.py:hash-params)
```

Patterns declare their regex, the URL or local-file they resolve to,
how they're verified, what category they belong to, and what should
happen on hover. Same regex flavour, same semantics, in both hosts.

## Planning horizon

| Version  | Theme                                                                                                                                                                                                                              |
| -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **v0.1** | Minimum viable: pattern engine + HTTP verifier + click-to-open. WASM-shared core (no engine divergence between editor and CLI).                                                                                                    |
| **v0.2** | Coupled-change (`IfChange`/`ThenChange`) + categories + references browser + commit-message linting + anchor verification for in-repo Markdown + block-on-marker (`DO NOT COMMIT` / `NOCOMMIT` source guards via `kind: "block"`). |
| **v0.3** | Multi-target references + full network profiles + auto-upgrade codemod (`coderef upgrade`) + visual config editor + external-URL anchor verification.                                                                              |
| **v0.4** | LSP server mode + composable coupled-change IDs + git-submodule pass-through.                                                                                                                                                      |

Anything past v0.4 is deliberately not planned in detail (see
[`DESIGN.md` §20.5](./DESIGN.md)). The full per-version scope is in
[`DESIGN.md` §20](./DESIGN.md).

## Repo layout

- [`DESIGN.md`](./DESIGN.md) — the working spec. Source of truth.
- [`AGENTS.md`](./AGENTS.md) — conventions every contributor (human or
  AI agent) follows. Includes the markdown table-alignment rule and a
  pointer to the script that enforces it.
- [`CLAUDE.md`](./CLAUDE.md) — entry-point for Claude Code; redirects
  to `AGENTS.md`.
- [`tools/align-md-tables.py`](./tools/align-md-tables.py) — the
  table-alignment script.
- [`.coderef.jsonc`](./.coderef.jsonc) — the project's own coderef
  config; the engine dogfoods against this on every CI run.
- [`LICENSE`](./LICENSE) — Apache 2.0.

## Pre-commit hooks (v0.1)

The `.pre-commit-hooks.yaml` declares the hook *shape* consumers
will install once the npm wrapper ships a binary (v0.2). For v0.1
the dogfood-able path is `language: system` against a locally-built
binary; see [`.pre-commit-config.yaml`](./.pre-commit-config.yaml)
for the working example used by this repo's own CI:

```yaml
- id: coderef-doctor
  entry: cargo run --quiet --release --bin coderef -- doctor --no-scan .
  language: system

- id: coderef-check
  entry: cargo run --quiet --release --bin coderef -- check .
  language: system
```

## What `coderef` is *not*

- Not a TODO tracker — it resolves the references you put in source,
  it doesn't manage them.
- Not a tag-uniqueness enforcer ([`tagref`](https://github.com/stepchowfun/tagref)
  already covers that niche).
- Not a generic markdown link checker
  ([`lychee`](https://github.com/lycheeverse/lychee) covers that).
- Not an AST-aware refactoring tool — `coderef upgrade` is regex-only
  by design; for AST work, use jscodeshift / ast-grep / comby.

See [`DESIGN.md` §23](./DESIGN.md) for the full out-of-scope list and
the reasoning.

## License

Apache License 2.0. See [`LICENSE`](./LICENSE).

## Release website

Release notes use `.github/release-notes.md.template`, rendered by
`tools/release_notes.sh TAG`, to link to that tag's versioned website and related
release resources, including the changelog and versioned JSON schema.

The [website](https://mboworks.github.io/coderef/) forwards to the latest published
stable release at `site/tag/<tag>/`, preserving the exact Git tag name.
Each release keeps its converted HTML, images, and configured files. Retrying
publication leaves an existing snapshot unchanged; a different commit cannot
replace it. Older versions remain directly accessible.

[`release-site.json`](release-site.json) defines the layout. Source names are
relative to the repository root; destinations are relative to that release's
site directory. For example:

```json
{
  "pages": {
    "README.md": "index.html",
    "docs/guide.md": "guide/index.html"
  },
  "files": {
    "schema/example.json": "schema/v1.json"
  },
  "links": [
    {
      "label": "Release",
      "href": "https://github.com/{owner}/{repo}/releases/tag/{tag}"
    }
  ]
}
```

Use existing source files in the actual configuration. `pages` converts Markdown;
optional `files` copies other files unchanged. `README.md` must map to `index.html`.
The generated `documents.html`, `release.json`, `release-site.json`, and `assets/`
paths are reserved. Destination paths cannot have hidden components (names starting
with a dot), because the Pages artifact uploader excludes them. Hidden source
paths remain valid; for example, `.github/workflows/README.md` maps to
`workflows/index.html`.
Navigation links support `{owner}`, `{repo}`, `{tag}`, `{version}`, and `{commit}`.
`{version}` omits a leading `v` for compatibility with coverage report paths.
By default, the configuration and content come from the release tag. Every linked
local Markdown page (including directory README links) must have a `pages` mapping.
Publication fails for an omitted mapping, a missing generated file, or a broken
anchor within the snapshot. Links to configured pages follow their destination
mappings; other local source links use the exact release commit. Embedded images are copied, including remote badges. Markdown
conversion uses the [GitHub Markdown API](https://docs.github.com/en/rest/markdown/markdown)
at publication time; browsing the result requires no Markdown renderer or CDN.

After the Release workflow succeeds, `Publish release site` retains the snapshot
on `coverage-pages` and deploys the complete Pages tree. Coverage and site
publication share a concurrency group to preserve both trees. GitHub's latest
stable release selects the root redirect; backfilling an older release does not
make it latest. The workflow can also be dispatched with a published tag to retry
publication. Enable GitHub Pages with
**GitHub Actions** as its source, and set the repository's About website to
`https://mboworks.github.io/coderef/`.

### Backfill a historical release

No new release or tag change is needed. Manually dispatch `Publish release site`
with `tag` set to the historical release and `config_path` set to a tracked JSON
file on `main`. Leave `config_path` empty to use a configuration already in the tag.
For example, after selecting a compatible configuration and an existing tag:

```sh
gh workflow run pages.yml --repo mboworks/coderef --ref main \
  -f tag="$RELEASE_TAG" -f config_path=release-site.json
```

The override controls only publication layout; all Markdown and copied files come
from the selected tag. Each new snapshot retains the exact configuration as
`release-site.json`, with its SHA-256, origin, and source commit in `release.json`.
A configuration can serve several historical tags when its sources exist in each.
For another layout, commit another configuration and select its path. Missing
sources or links fail publication instead of using newer content. Retrying a
published tag preserves its original HTML and configuration.

Local regression tests: `python3 -m unittest discover -s tools -p release_site_test.py`.
CI also converts the configured documentation and checks the generated links in
a disposable runner directory. It never commits, retains, or deploys that preview.

Main-branch pushes continue to update `/coderef/schema/v1.json`; each release
also retains and links to its own frozen schema copy inside its site directory.
