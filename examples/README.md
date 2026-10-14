# PulseCrawl examples

The examples use the single `pulsecrawl` package. Start with an offline example;
live website selectors and access policies are not validated by the offline tests.
Nothing creates resources, starts a crawl, or opens a socket merely on import.

## Standalone package examples (no clone)

Install the public package with Python 3.11 or newer:

```bash
python -m pip install 'pulsecrawl[workspace]'
```

Save either linked Python file on its own in any directory. Both import only
the installed top-level `pulsecrawl` API and Python's standard library; neither
requires a source checkout, `PYTHONPATH`, or the rest of `examples/`.

- [workspace_setup.py](installed_package/workspace_setup.py): creates a fresh
  local workspace and dataset, validates it, and exits without HTTP traffic.
- [crawl_page.py](installed_package/crawl_page.py): a bounded live crawl;
  requires `--live`, an authorized URL, and an operator-contact user agent.
  With no arguments it only prints help. The base `pulsecrawl` install is sufficient.

```bash
python workspace_setup.py --workspace ./package-demo
python crawl_page.py --help
```

After reviewing site authorization and replacing the contact placeholder,
the following command opts in to network requests, including robots checks:

```bash
python crawl_page.py --live --url https://example.com/ \
  --user-agent 'YourCrawler/1.0 (+https://your-domain.example/contact)'
```

`pip install pulsecrawl` installs the library and CLI, not an `examples` module.
The standalone files can be copied independently; the module commands below
need the repository's examples tree. Published versions are immutable, so
examples for a newer API must be used with a matching released package.

## Repository demos (offline first)

Download or clone the [public repository](https://github.com/pulsecrawl/PulseCrawl)
for its shared fixtures and recipe libraries. From its root:

```bash
python -m pip install 'pulsecrawl[workspace]'
python -m examples.local_quickstart
python -m examples.workspace_quickstart --workspace ./quickstart-workspace
python -m examples.hosted_quickstart
```

These commands use the installed package, not `src/`. The direct-script
compatibility bootstraps locate only the examples tree; they do not add `src/`
or replace the installed library. For developing unreleased code instead,
use the editable setup in [CONTRIBUTING.md](../CONTRIBUTING.md).

| Example | Default behavior |
| --- | --- |
| `local_quickstart` | In-memory extraction from fictional HTML; no network or files |
| `workspace_quickstart` | Fictional input through real SQLite, Parquet, manifests and SQL |
| `hosted_quickstart` | Print a plan; `--apply` creates resources, `--run` starts crawling |
| `local_cases` | Provision local definitions only; `--run` starts live crawling |
| `hosted_cases` | Provision hosted resources; credentials and an explicit endpoint required |
| `marketplace.premium_commerce.local` | Two offline executions demonstrating price history |

Quickstart workspace demonstrations require a fresh or empty directory and
never overwrite an existing workspace. The in-memory quickstart needs only
base dependencies; durable examples need the `workspace` extra.

## Shared structure

```text
examples/
├── shared/
│   ├── catalog.py            Pure case descriptions and limits
│   ├── recipes.py            Recipe loading and normalization
│   ├── local.py              LocalCaseProvisioner using Workspace
│   ├── hosted.py             HostedCaseProvisioner using PulseCrawl
│   ├── cli.py                Argument parsing and client ownership
│   ├── fixtures.py           Fictional, network-free transport
│   └── validation.py         Saved-HTML checks and governed live sampling
├── jobsearch/                20 company and ATS job boards
├── news/{chihuahua,mexico,stocks}/
└── marketplace/{clothes,supermarkets,mro,other_industries,premium_commerce}/
```

Recipe modules contain data and pure builders. Thin per-category entry points
reuse shared provisioners; local code does not depend on the hosted runner.
The Chihuahua compatibility command uses the same case definition rather
than maintaining a second set of limits and provisioning steps. Ordinary
examples use public APIs; advanced fixture and validation adapters use the
canonical domain/inbound/outbound extension points, not legacy `core` bridges.
See the [package architecture](../docs/PackageArchitecture.md).

## Local multi-source cases

Each of the eight established categories creates one job for all twenty
sources, with final-host/URL-scoped templates. Provisioning does not fetch
those sites:

```bash
python -m examples.local_cases --workspace ./workspace --all
python -m examples.news.stocks.local --workspace ./stock-workspace
```

Compatible definitions are reused. A changed dataset, template stack, seed
list or budget is reported as a conflict; existing jobs are not silently
archived or replaced. Use a separate workspace/organization for incompatible
recipes, or explicitly review and migrate existing resources.

Before live crawling, recheck robots, terms and authorization, and set a user
agent with a working operator contact. `--run` and `--schedule` require it;
`PULSECRAWL_USER_AGENT` is also accepted. Supply it when first provisioning a
workspace intended for later live use, since local jobs freeze their settings.
The following commands are opt-in network workflows, **not offline demos**:

```bash
python -m examples.news.stocks.local --workspace ./live-stock-workspace \
  --user-agent 'YourCrawler/1.0 (+https://your-domain.example/crawler-contact)' --run
python -m examples.news.stocks.local --workspace ./live-stock-workspace \
  --user-agent 'YourCrawler/1.0 (+https://your-domain.example/crawler-contact)' \
  --schedule '7 * * * *' --timezone UTC
pulsecrawl -w ./live-stock-workspace schedule start
```

Replace the placeholder contact with your own. Schedules are at most hourly;
setting one authorizes future crawls when a scheduler runs. Each execution
starts a fresh seed frontier. Cases admit at most 1,000 unique URLs per run
and use depth six. Jobsearch, Chihuahua, stocks and clothes allow ten million
lifetime page attempts; the other cases allow one million. Local and hosted
runners use the same case limits and a conservative one-request/second policy.

Docker is optional. Run Docker commands from the repository directory that
contains `docker-compose.local.yml`; native Python examples do not need Redis,
Azure, Firebase, or Docker.

## Hosted use

Set `PULSECRAWL_API_KEY` and `PULSECRAWL_BASE_URL` yourself; there is no default
service endpoint. These commands create remote resources, so use a test
organization. `--run` is separate from provisioning:

```bash
python -m examples.hosted_cases --all
python -m examples.news.stocks.hosted --run \
  --user-agent 'YourCrawler/1.0 (+https://your-domain.example/crawler-contact)'
python -m examples.hosted_quickstart --apply --run --url https://example.com/ \
  --user-agent 'YourCrawler/1.0 (+https://your-domain.example/crawler-contact)'
```

The hosted quickstart discovers the seeded meta-page template's schema rather
than assuming a hard-coded schema version. It closes its client on exit and
reports terminal failure instead of treating every completed wait as success.
Each `--apply` creates a new dataset and job; use the category provisioners
when you want compatible resources to be reused across runs.
Hosted-only authentication, billing, dispatch and UI remain outside this repo.

## Checking recipe mappings

Validators are offline unless `--live` is supplied. List source slugs, then
supply authorized HTML samples named `<slug>.html` in a local directory:

```bash
python -m examples.jobsearch.validate_recipes --list
python -m examples.jobsearch.validate_recipes --saved-dir ./samples --source openai
python -m examples.marketplace.clothes.validate_recipes --saved-dir ./samples
python -m examples.marketplace.other_industries.validate_recipes --saved-dir ./samples
```

Saved HTML is evaluated against its recipe sample URL. A capture from a
redirected URL needs its final URL checked separately; this is a selector
smoke check, not a complete extraction oracle. Literal-only matches do not
count as extracted content. No checked samples is **inconclusive** (exit 2),
not success; unmatched content exits 1, checked matches exit 0.

`--live --user-agent CONTACT` uses the real crawler for bounded in-memory
sampling, including robots, redirect reauthorization, pacing, response limits
and private-network blocking. It does not use a separate unrestricted HTTP
path and does not archive responses. Review site authorization first. Live
URLs can expire, and skip counts never establish current selector accuracy.

## Controlled commerce and verification

The controlled commerce demo runs against the published `workspace` extra:

```bash
python -m examples.marketplace.premium_commerce.local --workspace ./commerce-demo --summary
```

For contributor tests, first install the development dependencies as described
in [CONTRIBUTING.md](../CONTRIBUTING.md), then run:

```bash
python -m pytest tests/test_example_workflows.py tests/test_hosted_examples.py \
  tests/test_premium_commerce_example.py tests/test_live_commerce_example.py --no-cov
```

The [premium commerce guide](marketplace/premium_commerce/README.md) separates
fictional price history from its disabled, access-review-gated live plan.
No synthetic result is evidence of a live product run. Tests inject transports
or inspect local files; no cloud credentials or live website crawl is needed.

Module execution (`python -m examples.…`) is preferred. Root quickstarts and
per-category local/hosted/validation scripts also support direct file execution
for compatibility. Premium commerce uses module entry points because it has
package-relative imports.
