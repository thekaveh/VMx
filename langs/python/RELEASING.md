# Releasing the `vmx` Python package

This runbook documents how `vmx` is published to PyPI.

The release pipeline has two halves:

- **Routine releases.** `release-please` watches `main` for Conventional
  Commits and maintains a long-lived "release PR" that bumps the version
  in `langs/python/src/vmx/__about__.py` and writes the new section in
  `langs/python/CHANGELOG.md`. Merging that PR pushes a `python-v<X.Y.Z>`
  tag, which fires the publish pipeline.
- **Publish pipeline.** `.github/workflows/release.yml` runs five jobs on
  the new tag: `release-metadata` (version, tag, and changelog preflight),
  `python-test` (full pytest matrix gate), `python-build-and-publish`
  (gated on the `pypi-python` GitHub environment for manual approval, then an
  exact-backend build, metadata check, fresh-environment install/smoke of the
  local wheel, and Trusted-Publishing-via-OIDC upload with Sigstore (PEP 740)
  attestations),
  `python-verify-published` (5-attempt fresh-venv `pip install` + smoke test),
  and `python-release-notes` (CHANGELOG-extracted GitHub Release).

No API tokens. No Test PyPI. Trusted Publishing only.

Every release follows the shared
[release invariants](../../CONTRIBUTING.md#43-release-invariants): protected
environment, trusted publisher, immutable tags, fix-forward patches, and
documentation updates. This runbook adds only the Python steps.

## 1. Prerequisites (one-time, done by the package owner)

### 1.1 PyPI Trusted Publisher

- A PyPI account at <https://pypi.org/account/register/> with 2FA enabled.
- On <https://pypi.org/manage/account/publishing/>, "Add a new pending
  publisher" with PyPI Project Name `vmx`, the shared trusted-publisher fields,
  and environment `pypi-python`.

### 1.2 GitHub environment `pypi-python`

- In the repo's Settings → Environments, create `pypi-python` as the release
  invariants describe, restricted to `python-v*` tags. The required reviewer
  makes every publish wait for explicit approval after the test gate passes.
- (Optional) Set "Environment URL" to `https://pypi.org/p/vmx`.

### 1.3 Pre-publish URL + metadata validation

Every URL in `langs/python/pyproject.toml` `[project.urls]` becomes a clickable link in the PyPI project sidebar at <https://pypi.org/project/vmx/>. A 404 there is visible to every consumer and **requires a patch release to fix** (PyPI freezes metadata at upload time per version). Before tagging, validate:

```bash
python3 -c "import tomllib; d=tomllib.load(open('langs/python/pyproject.toml','rb')); [print(k, v) for k,v in d['project']['urls'].items()]" \
  | while read key url; do
      code=$(curl -sS -o /dev/null -w '%{http_code}' "$url")
      printf '%s %s -> HTTP %s\n' "$key" "$url" "$code"
    done
```

Anything not 200 must be fixed before tagging — either point at a real URL or drop the entry from `[project.urls]` entirely. Safe defaults when no dedicated docs site exists: `Documentation = "https://github.com/thekaveh/VMx#readme"` (anchor renders the README) or any `https://github.com/thekaveh/VMx/tree/main/…` folder URL.

Apply the same check to npm `package.json` `homepage`/`bugs`/`repository`, NuGet `<PackageProjectUrl>`/`<RepositoryUrl>`, and SwiftPM Index entries.

## 2. Cutting a release

### 2.1 Routine release (release-please-driven)

release-please pauses while `.release-please-manifest.json` and the source
version disagree; `tools/check-release-please-state.py` reports the mismatch.
Until the manifest is reconciled, release through
[§2.2](#22-manual-tag-release-when-release-please-is-paused).

1. Land Conventional-Commit-style PRs on `develop` (`feat: …`, `fix: …`, `docs: …`, etc.), then promote `develop` to `main` through a separate PR.
2. `release-please` opens a "chore(main): release python X.Y.Z" PR — review the version bump in `langs/python/src/vmx/__about__.py` and the matching `langs/python/CHANGELOG.md` entry.
3. If the spec version also bumped, update `__min_spec_version__` in the same PR (release-please does not auto-bump that — see the comment in `__about__.py`).
4. Merge the release PR. release-please pushes a `python-v<X.Y.Z>` tag on the merge commit.
5. Watch <https://github.com/thekaveh/VMx/actions?query=workflow%3Arelease> — the publish pipeline fires on the tag.
6. The `python-build-and-publish` job pauses for **your approval** on the `pypi-python` environment. Click "Review pending deployments" → `pypi-python` → "Approve and deploy".
7. Before upload, `python-build-and-publish` installs the exact wheel from
   `dist/` into a fresh environment and runs the version/lifecycle smoke test.
   A failure stops before the irreversible PyPI action.
8. `python-verify-published` independently installs `vmx==<X.Y.Z>` from PyPI in
   a fresh venv with retry-on-CDN-lag (5 attempts × 30s backoff) and runs the
   same smoke test.
9. `python-release-notes` posts the matching CHANGELOG section as a GitHub Release.

### 2.2 Manual tag release (when release-please is paused)

Use this path when `__about__.py` already holds the target version, so
release-please proposes no release PR. Push the tag manually:

```bash
git checkout main
git pull --ff-only origin main
grep '^__version__' langs/python/src/vmx/__about__.py    # confirm target version
version=$(python3 -c "exec(open('langs/python/src/vmx/__about__.py').read()); print(__version__)")
git tag -a "python-v${version}" -m "vmx ${version}"
git push origin "python-v${version}"
```

The same five publish jobs run.

The `release-please` workflow pauses while the source version and
`.release-please-manifest.json` disagree. The manifest records the last version
that the release pipeline tagged; never advance it merely to silence the guard.
The manifest holds 3.23.1, the last tag; its PyPI upload failed, so PyPI's
latest is 3.23.0. After the manual release and public-install verification
succeed:

1. Confirm PyPI and the GitHub release both report the exact source version.
2. Change `.release-please-manifest.json` to that verified published version in
   a normal reviewed PR.
3. Run `python3 tools/check-release-please-state.py`; it must report `OK`.
4. Merge the reconciliation PR. The next push to `main` can safely resume
   release-please automation.

If an existing release PR proposes a version below the source version, do not
merge it. Close it after the guard is present on `main`, delete only the bot's
release branch, then complete the manual release and reconciliation sequence
above.

> **Warning.** Before you add a component to release-please, push its first `<component>-v<X.Y.Z>` tag. Without that tag, the first run proposes an oversized release PR from the full history. If that occurs, delete the bot branch with `git push origin --delete release-please--branches--main--components--<component>`.

### 2.3 Stable version policy

Stable SemVer releases only (`X.Y.Z`) are accepted by the repository version,
compatibility-matrix, tag, and changelog checks. PEP 440 pre-release segments
are intentionally unsupported; introduce them only through a reviewed policy
change that updates every release validator and workflow together.

## 3. Verifying a release

```bash
# PyPI page renders:
curl -sS https://pypi.org/pypi/vmx/json | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['info']['name'], d['info']['version'])"
# → vmx X.Y.Z

# Install in a fresh venv:
python3 -m venv /tmp/vmx-verify
/tmp/vmx-verify/bin/pip install --upgrade pip
/tmp/vmx-verify/bin/pip install vmx==X.Y.Z
/tmp/vmx-verify/bin/python langs/python/scripts/smoke_test.py X.Y.Z
# → OK

# GitHub Release:
gh release view python-vX.Y.Z
```

## 4. Failure modes

### 4.1 `python-test` failed

The publish never reaches the build job. Leave the failed tag immutable, fix
the broken test on `main`, and release a new patch version with a new tag.

### 4.2 `python-build-and-publish` approval declined

The environment publishes nothing. Land the fix for the rejection cause on `main`, then release a new patch version with a new tag.

The same job can also fail safely after approval but before upload if the pinned
build backend, Twine metadata check, local wheel installation, or lifecycle smoke
fails. No PyPI version exists for that tag; fix the defect on `main` and cut a new tag.

### 4.3 Publish succeeded but the release is broken

PyPI does not allow deletion of a published version. Yank it via <https://pypi.org/manage/project/vmx/release/X.Y.Z/> ("Options" → "Yank release"). Then publish a fix as a new patch version.

### 4.4 `python-verify-published` failed after publish

This means PyPI accepted the upload but the package can't be installed or imported. Diagnose the error in the workflow log. The published artifact is permanent — the fix is a new patch release with the import/install fault corrected. Consider yanking the bad version.

### 4.5 `python-release-notes` failed

If the GitHub Release was not created, first determine whether the immutable
tag commit already contains the correct changelog section. Re-run the job only
for a transient failure when that tagged content is correct. If the tag itself
has incomplete notes, use an audited manual GitHub Release recovery from the
published version's notes or fix forward; a later `main` edit cannot change the
tagged workflow input. The PyPI artifact is already live.

## 5. Tag scheme and multi-flavor coexistence

Python releases use `python-v<X.Y.Z>`. The release invariants list the other prefixes; another package's tag does not start the Python pipeline.

`release-please-config.json` is monorepo-aware. To add another package, add its entry alongside `langs/python`; each package gets its own component-prefixed tag and changelog.

## 6. Spec compatibility

`__min_spec_version__` in `langs/python/src/vmx/__about__.py` declares the minimum `spec/VERSION` this package implements. `tools/check-version-consistency.py` enforces that `__min_spec_version__` equals `spec/VERSION`; it runs in the conformance workflow on every PR and in the release workflow's `release-metadata` preflight. release-please leaves `__min_spec_version__` untouched; bump it manually in the release PR review if a spec major bumps in the same window.
