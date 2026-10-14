# Contributing to PulseCrawl

PulseCrawl's public package combines a safety-governed crawl engine with a
portable local SDK. Changes must preserve the documented network, crawl-policy,
data-integrity, and public-source boundaries.

## Before opening a change

1. Create a focused branch from the default branch.
2. Do not commit credentials, third-party page bodies, private crawl data,
   signed URLs, sensitive logs, generated virtual environments, or build outputs.
3. Add or update tests next to the behavior they cover.
4. Preserve the documented top-level API when changing `pulsecrawl.core`.
5. Update public documentation when behavior, security assumptions, or
   compatibility changes.
6. Sign every commit with `git commit -s` to certify the
   [Developer Certificate of Origin 1.1](DCO.md).

## Development installation

Ordinary users install `pulsecrawl` or `pulsecrawl[workspace]` from PyPI; they
do not need a source checkout. Contributors testing unreleased code should
clone the public repository and install it in an isolated environment:

```bash
git clone https://github.com/pulsecrawl/PulseCrawl.git
cd PulseCrawl
python -m venv .venv
```

Activate it with `source .venv/bin/activate` on macOS/Linux, or
`.venv\Scripts\Activate.ps1` in Windows PowerShell. Then:

```bash
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

The `dev` extra includes the workspace runtime and test/lint tools. Editable
installation intentionally selects this checkout rather than the published wheel.

## Local checks

Run the checks relevant to the change:

```bash
python -m pytest
python -m ruff check . scripts
python scripts/check-secrets.py
python scripts/export-oss.py --output <outside-repository-path>
```

The exporter requires a clean worktree unless `--allow-dirty` is used for a
local diagnostic. Release exports must always come from a clean reviewed
commit.

## Pull-request expectations

- Explain the behavior and failure mode, not only the edited files.
- State which checks were run and which platform or network checks were not.
- Include migration and compatibility notes for public APIs or persisted data.
- Add boundary tests for URL fetching, redirects, robots handling, SQL,
  manifests, credentials, or recovery behavior when those areas change.
- Follow the [Code of Conduct](CODE_OF_CONDUCT.md) and
  [responsible-crawling policy](docs/ResponsibleCrawling.md).

## Licensing

PulseCrawl is licensed under the [GNU Affero General Public License v3.0](LICENSE). By signing off
a commit under the DCO, contributors confirm that they have the right to
submit the contribution under that license. License changes require maintainer
approval.
