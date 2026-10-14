# PyPI release preparation

This guide applies to the **public** `pulsecrawl/PulseCrawl` repository, whose
root contains `pyproject.toml`. Version `0.1.0` is the initial published alpha
release. Version `0.1.1` updates the local-use description and examples without
changing crawler behavior. Preparation is not
publication: no account, publisher, GitHub environment, tag, or upload is
created by these local files.

The repository owner authorized a one-time manual production upload of `0.1.1`
using the existing project API token, without TestPyPI rehearsal or a separate
publishing-environment approval. This exception does not configure Trusted
Publishing or attestations, does not weaken branch/tag protections, and does
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
4. Create a separate account on [TestPyPI](https://test.pypi.org/account/register/)
   and complete its email verification and security setup too. PyPI and
   TestPyPI accounts and publisher configurations are separate.
5. Arrange continuity/recovery access through the project mailbox and,
   once the project exists, another authorized owner. An email inbox alone
   does not recover lost two-factor authentication.

See [PyPI account help](https://pypi.org/help/#twofa) for current requirements.
Account creation, security setup, and legal acceptance require the account
holder's participation. No personal maintainer identity is added to metadata.

## Protected GitHub environments — required before uploading

In `pulsecrawl/PulseCrawl`, create environments named exactly `testpypi` and
`pypi`. Restrict both to the protected `main` branch, since dispatch runs from
`main` and checks out a reviewed release tag for its build. Configure required
reviewers, **prevent self-review**, and disallow protection-rule bypass for the
production environment. Both environments must allow **protected branches
only**, have required reviewers, and prevent self-review; the upload preflight
checks those settings and that `main` is protected. Do not rely on a workflow's `environment` declaration to install
these protections: GitHub can create an unprotected environment automatically.

Require the **Release validation complete** check and reviewed changes on `main`;
this aggregates the full platform matrix, minimum dependency tests/security
audit, distribution checks, container checks, and public boundary. The upload
preflight requires every mandatory job to succeed in the latest OSS CI push
run/attempt for the **exact tagged SHA** on `main`, not merely an ancestor of it.
It also requires the OSS repository to be public. Protect release tags
against unauthorized creation, movement, or deletion. If the repository plan
does not support the needed environment protection, keep upload targets unused
until an equivalent approval mechanism is reviewed.

## Token-free Trusted Publishers

After both accounts are ready, use each index's account **Publishing** page
to add a pending GitHub publisher:

| Field | TestPyPI | PyPI |
| --- | --- | --- |
| Project name | `pulsecrawl` | `pulsecrawl` |
| Repository owner | `pulsecrawl` | `pulsecrawl` |
| Repository name | `PulseCrawl` | `PulseCrawl` |
| Workflow filename | `oss-release.yml` | `oss-release.yml` |
| Environment | `testpypi` | `pypi` |

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
   reviewed tag. This builds once, tests, uploads to TestPyPI, downloads its
   exact wheel **without dependencies**, compares its bytes to the artifact,
   and installs it with dependencies resolved from production PyPI only.
5. Inspect TestPyPI rendering and results while the `pypi` environment awaits
   approval. Approve production only when satisfied. The production job uploads
   the **same** archives, not a rebuild. No API token secret is required.
6. Verify the production page, files, and attestations, then install
   `pulsecrawl==X.Y.Z` and `pulsecrawl[workspace]==X.Y.Z` in fresh environments.
   Run smoke checks and `pip check`; record the released hashes and run URL.
7. Publish reviewed release notes and update descriptions that still say the
   package is unpublished. Do not mark launch tasks complete before verification.

Target `testpypi` stops after rehearsal and its verification. It is useful for
a disposable rehearsal version, but uploads are immutable: a later `pypi` run
reuploads to TestPyPI first and **will fail if that version is already there**.
For a production candidate, prefer the single `pypi` run and approval pause.
If a post-upload job fails, rerun **failed jobs**, not the whole workflow; never
delete/reuse a released version or enable `skip-existing` to hide a mismatch.
The current stable-tag validator accepts `vX.Y.Z`; prerelease versions require
an explicit validator/citation/version policy update first.

## Launch checklist (not yet completed)

- [ ] PyPI and TestPyPI accounts verified, 2FA and recovery access configured.
- [ ] Public source reviewed, committed, pushed; required CI checks pass.
- [ ] Protected environments, main branch, release tags, and reviewers configured.
- [ ] Both Trusted Publishers configured with the exact values above.
- [ ] Reviewed tagged candidate built and its artifacts approved.
- [ ] Source, Git identities, wheel contents, and sdist ownership/content privacy checked.
- [ ] TestPyPI upload, exact-byte comparison, and clean-install checks pass.
- [ ] Production approval, upload, attestations, and fresh PyPI installs verified.
- [ ] Release notes published and unpublished-install wording updated.
