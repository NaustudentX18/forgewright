# Release process (for maintainers)

> **Audience:** forgewright maintainers cutting a release. Contributors
> looking for the high-level loop should read
> [`CONTRIBUTING.md` § Release process](../CONTRIBUTING.md#release-process)
> instead.

This is the operational runbook for shipping a `forgewright` release end to
end. It mirrors the bullets in `CONTRIBUTING.md` and goes deeper on the
checklist, the rollback procedure, hotfixes, and how to yank a release
from PyPI if something goes wrong.

---

## 0. Pre-flight

A release should not be cut unless **all** of the following are true:

- [ ] `main` is green on the full CI matrix (lint, mypy, unit,
      integration).
- [ ] `pip-audit --strict` is clean.
- [ ] `forgewright audit verify` passes on `main`.
- [ ] All PRs tagged for the release have been merged.
- [ ] At least one other maintainer has signed off in the tracking
      discussion / PR.
- [ ] The release notes draft is in `docs/release-notes/v0.X.Y.md`
      (or as a PR description).

If any of those is red, fix it before tagging. **Do not** tag a brown
release to "save time" — the rollback cost is higher than the wait.

---

## 1. The release checklist

### 1.1 Bump the version

Two files must agree:

- `src/forgewright/__init__.py` — the `__version__` string.
- `pyproject.toml` — the `version = "..."` field under `[project]`.

Use the next `0.X.Y` SemVer for compatibility-breaking changes. For
routine releases use CalVer `YYYY.MM.PATCH`. The CI does not enforce a
particular scheme; consistency with the previous tag is what matters.

```bash
# Sanity check before bumping
git fetch --tags
git tag --sort=-v:refname | head -3   # remember the last tag
```

Then edit both files, commit:

```bash
git checkout -b release/v0.2.0
# edit src/forgewright/__init__.py
# edit pyproject.toml
git add src/forgewright/__init__.py pyproject.toml
git commit -m "chore(release): bump to 0.2.0"
git push -u origin release/v0.2.0
```

Open a PR. Wait for green CI. Merge.

### 1.2 Update `CHANGELOG.md`

Move everything under `## [Unreleased]` into a new dated section:

```markdown
## [Unreleased]

## [0.2.0] - 2026-07-15

### Added
- (the things that were under Unreleased)

### Changed
- ...

### Fixed
- ...
```

Leave an empty `## [Unreleased]` stub at the top. Keep the format
[Keep-a-Changelog](https://keepachangelog.com/) compatible.

Commit, push, merge.

### 1.3 Tag

```bash
git checkout main
git pull --rebase
git tag -s v0.2.0 -m "Release 0.2.0 — <one-line summary>"
git push origin v0.2.0
```

The `-s` flag signs the tag with your GPG key. Unsigned tags are
rejected by the release pipeline.

### 1.4 Watch the pipeline

`.github/workflows/release.yml` is the single source of truth. It runs
these jobs in order:

1. `build-wheels` — `cibuildwheel` builds
   `linux/amd64`, `linux/arm64`, `macos x86_64`, `macos arm64` wheels
   and the sdist.
2. `publish-pypi` — uploads via OIDC. **This is the gate.** If it
   fails, the rest still runs but the release is held.
3. `build-docker` — multi-arch image, pushed to
   `ghcr.io/forest/forgewright:0.2.0` and `:latest`.
4. `sign-artifacts` — `cosign sign` for the wheel, sdist, and Docker
   image; SBOM generated with `cyclonedx-py`.
5. `update-homebrew` — opens a PR in `forest/homebrew-tap` with the
   new formula version and SHA256.
6. `release-notes` — drafts the GitHub release, attaches the SBOM
   and the cosign signatures.

You should be watching this run in real time. If a job fails, **do not
re-tag**; either push a fix or follow the rollback section below.

### 1.5 Verify

End-to-end checks the releasing maintainer runs (typically in a fresh
shell on a clean machine):

```bash
# 1. PyPI is reachable
pip download forgewright==0.2.0 --no-deps --dest /tmp/fw-check
test -f /tmp/fw-check/forgewright-0.2.0-*.whl

# 2. The wheel runs
python -m venv /tmp/fw-venv
/tmp/fw-venv/bin/pip install /tmp/fw-check/forgewright-0.2.0-*.whl
/tmp/fw-venv/bin/forgewright --version

# 3. Docker image runs
docker run --rm ghcr.io/forest/forgewright:0.2.0 --version

# 4. Homebrew tap PR is open and mergeable
gh pr list --repo forest/homebrew-tap --search "forgewright 0.2.0"

# 5. Cosign signatures are valid
cosign verify ghcr.io/forest/forgewright:0.2.0 \
  --certificate-identity-regexp 'https://github.com/forest/forgewright' \
  --certificate-oidc-issuer 'https://token.actions.githubusercontent.com'

cosign verify-blob \
  --signature forgewright-0.2.0-py3-none-any.whl.sig \
  forgewright-0.2.0-py3-none-any.whl
```

If any of these fail, follow the rollback procedure.

### 1.6 Announce

- Post in `#releases` on
  [Discord](https://discord.gg/forgewright) with a link to the GitHub
  release.
- If notable, post a summary to r/LocalLLaMA, r/MachineLearning, and
  r/opensource.
- Pin the release as the latest in the GitHub UI.
- Update the "Looking for contributors" callouts in `README.md` if the
  release closes long-running gaps.

---

## 2. Hotfix procedure

A hotfix is a release that bypasses the normal `main` flow because the
bug is critical (security, data loss, or a release-blocker). The order
of operations is the same; what changes is **which branch you tag**.

```bash
# Branch from the affected tag
git fetch --tags
git checkout -b hotfix/v0.1.1 v0.1.0

# Cherry-pick or apply the fix
git cherry-pick <sha-of-the-fix>
# or commit the fix directly on this branch

# Bump
# edit src/forgewright/__init__.py and pyproject.toml to 0.1.1
# edit CHANGELOG.md — add a [0.1.1] - <date> section under Unreleased

git commit -am "fix: <short description>"
git push -u origin hotfix/v0.1.1

# Open a PR into main. Fast-merge once CI is green.
gh pr create --base main --head hotfix/v0.1.1 \
  --title "hotfix(v0.1.1): <short description>" \
  --body "Hotfix for v0.1.0. See <issue link> for context."

# After merge, tag main
git checkout main
git pull --rebase
git tag -s v0.1.1 -m "Hotfix 0.1.1 — <short description>"
git push origin v0.1.1
```

Hotfixes get the same pipeline treatment as a normal release. The
release notes should clearly mark the fix as a hotfix and link the
issue it addresses.

---

## 3. Rollback

Sometimes the verification step in §1.5 reveals a problem that isn't
worth a hotfix. For example: a typo in the version string, a missing
artifact, a cosign signature with the wrong identity, or a yanked
dependency. The right response is a **rollback**, not a re-tag.

### 3.1 The release is up on GitHub but bad

- Edit the GitHub release to mark it as a **pre-release** and rename
  it (`v0.2.0-BAD`). This keeps the tag but signals that it shouldn't
  be used.
- Re-tag the previous good commit as `v0.2.0` (delete the bad tag
  first):

  ```bash
  git tag -d v0.2.0
  git push origin :refs/tags/v0.2.0
  git checkout <good-sha>
  git tag -s v0.2.0 -m "Release 0.2.0"
  git push origin v0.2.0
  ```

  Only do this if no-one could have downloaded the bad artifact yet.
  Once it has been installed by anyone, you need to yank.

### 3.2 The release is on PyPI

Yank the bad release. Yanking hides it from `pip install forgewright`
by default but keeps the file accessible for reproducibility.

```bash
# Install twine in a venv
python -m venv /tmp/twine-venv
/tmp/twine-venv/bin/pip install twine

# Yank
/tmp/twine-venv/bin/twine yank forgewright 0.2.0 \
  --reason "Re-tagged: <short explanation>"
```

After yanking:

- Edit the GitHub release to add a **Yanked** banner.
- If the version is fundamentally broken (e.g. wrong code), cut a
  follow-up `0.2.1` patch release ASAP.
- If only the metadata is wrong (e.g. wrong `Summary` string), a fresh
  re-upload with `--skip-existing` is acceptable.

### 3.3 The Docker image is bad

Delete the bad tag from GHCR (this is irreversible, but only the tag
is removed — the digest stays valid for reproducibility):

```bash
# Delete the tag (keeps the underlying image accessible by digest)
gh api -X DELETE \
  /user/packages/container/forgewright/versions/<version-id>
```

Then either re-tag and re-push, or cut a patch release. The bad
digest should be mentioned in the GitHub Security Advisory if it's a
security issue.

### 3.4 The Homebrew tap PR is bad

Close the PR without merging. If it was already merged, revert the
merge commit and push a follow-up PR restoring the previous version.
A bot will open a new PR on the next release tag.

### 3.5 Notification

If the release was announced before the rollback, post a follow-up in
the same channels with:

- The new (correct) version to install.
- A one-sentence reason for the rollback.
- A link to the GitHub issue tracking the problem.

---

## 4. Yanking a release (last resort)

`twine yank` is the right tool for a release that **must not be
installed** by anyone — e.g. a release that shipped with a vulnerable
dependency that can't be patched in place, or one that leaks secrets.

```bash
# Yank
twine yank forgewright 0.2.0 --reason "Reason here"

# If you also need to remove the file from the index
# (rare; PyPI staff can do this — file an issue)
```

A yanked release is hidden from `pip install forgewright` by default
but is still listed on PyPI for reproducibility. Users who have
already installed it can keep using it (and will get a warning on
`pip install --upgrade`).

**A yanked release is not a deletion.** If you need the artifact
gone, you have to file a takedown request with PyPI staff via
`security@pypi.org`. That is a 1-2 week process and reserved for
severe cases (credential leaks, malicious code in the wheel).

---

## 5. Audit

After every release, regardless of outcome:

- Update [`CHANGELOG.md`](../CHANGELOG.md) with what actually shipped
  (sometimes the pipeline drops a job; document it).
- File a retro issue in the `forest/forgewright` repo with what went
  well and what to fix in the pipeline. Tag it `release/retro`.
- Add a row to the **Releases** table in
  [`docs/RELEASE.md` § History](#history) below.

---

## History

| Version | Date | Lead | Notes |
|---|---|---|---|
| 0.1.0 | 2026-06-02 | Forest Pi | First public release. |
