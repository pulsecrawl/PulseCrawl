# PyPI release preparation

This guide applies to the **public** `pulsecrawl/PulseCrawl` repository, whose
root contains `pyproject.toml`. Version `0.1.0` is the initial published alpha
release. Published version `0.1.1` updates the local-use description and examples
without changing crawler behavior. Version `0.2.0` standardizes Pending URLs
terminology and upgrades workspace SQLite state to schema 5. Low-level adapter
imports and engine dependency keywords change; top-level `crawl` and `Workspace`
calls remain unchanged. Stop older package processes before upgrading a
workspace, and retain the automatic pre-migration backup for downgrades.
Version `0.3.0` adds successful time-bounded executions, five-minute-or-slower
fixed schedules, non-overlap and skipped-occurrence accounting, and upgrades
workspace SQLite state to schema 6.
Version `0.4.0` separates broad link discovery from record publication with
template `requiredFields` and optional record, navigation, or ignore page roles.
Preparation is not
publication: no account, publisher, GitHub environment, tag, or upload is
created by these local files.

The repository owner authorized one-time manual production uploads of `0.1.1`
and `0.2.0` using the existing project API token, directly to PyPI.
These release-specific exceptions did not configure Trusted
Publishing or attestations, do not weaken branch/tag protections, and do
not authorize future uploads. Full CI on the exact release commit, clean-source
builds, archive/privacy checks, and fresh-install verification remain required.
Keep the token outside the public repository and never log it. The standard
automated process below remains the intended path for subsequent releases.

## Account and ownership — manual setup required

1. Register at [PyPI](https://pypi.org/account/register/) using the project
   mailbox `info@pulsecrawl.com`. Proposed username: `pulsecrawl`; availability
   is checked by PyPI, and a username is separate from a project name.
2. Choose and save a strong password in a password manager, complete the
   CAPTCHA, review and accept PyPI's terms, and verify the email.
3. Enable two-factor authentication and securely retain recovery codes.
   Do not commit credentials or recovery codes or paste them into chat.
4. Arrange continuity/recovery access through the project mailbox and,
   once the project exists, another authorized owner. An email inbox alone
   does not recover lost two-factor authentication.

See [PyPI account help](https://pypi.org/help/#twofa) for current requirements.
Account creation, security setup, and legal acceptance require the account
holder's participation. No personal maintainer identity is added to metadata.

## Protected GitHub environments — required before uploading

In `pulsecrawl/PulseCrawl`, create an environment named exactly `pypi`.
Restrict it to the protected `main` branch, since dispatch runs from
`main` and checks out a reviewed release tag for its build. This is a
single-maintainer repository, so the environment does not require a second
reviewer. The environment must allow **protected branches only**; the upload
preflight checks that setting, confirms that `main` is protected, and rejects a
required-reviewer rule that would make publication impossible for the sole
maintainer. Do not rely on a workflow's `environment` declaration to install
the branch restriction: GitHub can create an unprotected environment
automatically.

Require the **Release validation complete** check and reviewed changes on `main`;
this aggregates the full platform matrix, minimum dependency tests/security
audit, distribution checks, container checks, and public boundary. The upload
preflight requires every mandatory job to succeed in the latest OSS CI push
run/attempt for the **exact tagged SHA** on `main`, not merely an ancestor of it.
It also requires the OSS repository to be public. Protect release tags
against unauthorized creation, movement, or deletion. If the repository plan
does not support the needed environment branch restriction, keep upload targets
unused until an equivalent control is reviewed.

## Token-free Trusted Publishers

Use the PulseCrawl project's PyPI **Publishing** settings to add this GitHub
publisher:

| Field | Value |
| --- | --- |
| Project name | `pulsecrawl` |
| Repository owner | `pulsecrawl` |
| Repository name | `PulseCrawl` |
| Workflow filename | `oss-release.yml` |
| Environment | `pypi` |

Use the workflow **filename**, not its display name or full path. Verify these
values against the actual public Git remote before configuring trust. Do not
configure the private monorepo as a publisher. Adding this trust grants the
workflow publishing access and must be approved by the account owner.

A pending publisher creates the project on first successful upload; it does
**not** reserve the project name. An unavailable or prohibited name is a launch
blocker, not permission to silently rename the distribution. If the project
already exists under your ownership, add a normal publisher in its settings.
See PyPI's [first-project instructions](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)
and [GitHub publisher configuration](https://docs.pypi.org/trusted-publishers/adding-a-publisher/).

The release workflow uses short-lived OIDC credentials and PyPI attestations,
not a stored API token. Only isolated upload jobs receive `id-token: write`;
they download the tested archives rather than building or checking out code.
See [PyPI's publishing documentation](https://docs.pypi.org/trusted-publishers/using-a-publisher/).

## Local candidate checks

From a reviewed public checkout, using fresh output directories:

```bash
python -m pip install -e '.[dev]'
python -m pip install build twine
python scripts/check-release.py
python -m pytest
python scripts/check-doc-links.py
python scripts/check-secrets.py
python -m build --sdist --outdir dist .
```

Extract the sdist into a fresh temporary directory, build its wheel into the
same `dist/`, then run:

```bash
python -m twine check --strict dist/*
python scripts/check-distributions.py dist
```

The checker verifies version/metadata, the PyPI-specific description, all
package modules, extras, CLI entry point, license files, and archive boundaries.
The in-tree PEP 517 backend strips builder uid/gid, user/group names, PAX
metadata, and gzip filenames from every source archive; no post-build cleanup
command is needed. The archive checker rejects non-neutral ownership and
personal author/maintainer fields, and scans filenames and contents for the
local builder login. For additional names/aliases, pass repeatable
`--private-identity` arguments locally; never commit the identities to a public
configuration or paste them into public CI logs. Check source, staged changes,
and commit author/committer identities separately before the first push.
Use a project-owned Git name/email for release commits: clean package metadata
does not anonymize Git history or GitHub account activity.
The wheel installs only `pulsecrawl`; source archives also contain examples,
tests, docs, and release helpers. `PYPI_README.md` uses absolute public links
because a package-index description is not rendered inside the GitHub tree.

In a **fresh non-editable virtual environment**, install the wheel without
extras, run `python -I scripts/smoke-distribution.py`, then install that same
wheel with `[workspace]` and run the script with `--workspace`. Also run
`pip check` and `pulsecrawl --help`. The smoke script uses fictional HTML only;
it checks extraction, persistence, SQL, validation, and workspace reopening
without crawling live websites. Its isolated mode prevents `PYTHONPATH` or the
checkout from masking missing installed modules.

## Standard release runbook

1. Review, commit, and push the public source. Confirm full OSS CI on the exact
   commit; local testing is not evidence of the full platform matrix. Uploads
   fail closed until the latest exact-SHA CI run and all required jobs pass.
2. Review the AGPL license, alpha support promises, version in
   `src/pulsecrawl/__init__.py`, `CITATION.cff`, and `CHANGELOG.md`. Create the
   reviewed `vX.Y.Z` tag on that commit only after publication is authorized.
3. Run **Prepare and publish OSS release** from `main` with target `build` and
   the release tag. Review its wheel, sdist, test results, and metadata.
4. After publisher and environment setup, dispatch target `pypi` with the same
   reviewed tag. The workflow builds once, runs the full candidate tests and
   clean-install checks, and uploads those exact archives directly to PyPI.
5. The post-upload job downloads the production wheel without dependencies,
   compares it byte-for-byte with the tested artifact, installs it with the
   workspace extra, and reruns the smoke checks. No API token secret is required.
6. Verify the production page, files, and attestations, then install
   `pulsecrawl==X.Y.Z` and `pulsecrawl[workspace]==X.Y.Z` in fresh environments.
   Run smoke checks and `pip check`; record the released hashes and run URL.
7. Publish reviewed release notes and update descriptions that still say the
   package is unpublished. Do not mark launch tasks complete before verification.

If a post-upload job fails, rerun **failed jobs**, not the whole workflow; never
delete/reuse a released version or enable `skip-existing` to hide a mismatch.
The current stable-tag validator accepts `vX.Y.Z`; prerelease versions require
an explicit validator/citation/version policy update first.

## Launch checklist (not yet completed)

- [ ] PyPI account verified, 2FA and recovery access configured.
- [ ] Public source reviewed, committed, pushed; required CI checks pass.
- [ ] Protected environments, main branch, and release tags configured.
- [ ] PyPI Trusted Publisher configured with the exact values above.
- [ ] Reviewed tagged candidate built and its artifacts approved.
- [ ] Source, Git identities, wheel contents, and sdist ownership/content privacy checked.
- [ ] Production upload, exact-byte comparison, attestations, and fresh PyPI installs verified.
- [ ] Release notes published and unpublished-install wording updated.
