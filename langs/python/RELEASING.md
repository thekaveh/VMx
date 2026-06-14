# Releasing the `vmx` Python package

This runbook documents how to publish a new version of `vmx` to PyPI.

The release pipeline lives in `.github/workflows/release.yml` (three Python jobs:
`python`, `python-publish`, `python-release-notes`). It is triggered by pushing a
tag of the form `python-v<MAJOR>.<MINOR>.<PATCH>`.

## 1. Prerequisites (one-time, done by the package owner)

### 1.1 PyPI Trusted Publisher

- Create a PyPI account at <https://pypi.org/account/register/> if you don't have one.
- On <https://pypi.org/manage/account/publishing/>, "Add a new pending publisher" with:
  - PyPI project name: `vmx`
  - Owner: `thekaveh`
  - Repository: `VMx`
  - Workflow name: `release.yml`
  - Environment: `pypi-prod`

### 1.2 Test PyPI Trusted Publisher

Repeat the same registration at <https://test.pypi.org/manage/account/publishing/>:

- Test PyPI project name: `vmx`
- Owner / Repository / Workflow: same as above
- Environment: `pypi-test`

### 1.3 GitHub environments

In the repo's Settings → Environments:

- Create `pypi-test` — no protection rules.
- Create `pypi-prod` — add "Required reviewers" and put yourself on the list. This is the manual approval gate.

### 1.4 Verify

Push a `python-v0.0.0a0` tag to a throwaway commit — the `python` job should run, fail the version-match check (because `__about__.py` says the current version, not `0.0.0a0`), and stop. That confirms the trigger wires correctly without actually publishing.

Delete the bad tag locally and remotely:

```bash
git tag -d python-v0.0.0a0
git push origin :refs/tags/python-v0.0.0a0
```

## 2. Cutting a release

### 2.1 Release-prep PR

A release prep PR is the version-bump commit that lands the new version into `main`. Typical contents:

- Bump `langs/python/src/vmx/__about__.py` `__version__` and `__min_spec_version__`.
- Add a `## [<version>] — YYYY-MM-DD` section to `langs/python/CHANGELOG.md` (move items from `[Unreleased]`).
- Update `langs/python/README.md` if the version is mentioned (e.g., the v2.X.X status line).
- Per-spec-bump rules in `CLAUDE.md` may require additional updates (compatibility matrix, count claims). Follow the existing checklist for the bump magnitude.

Open the PR, wait for `python.yml` + `conformance.yml` + `spec-discipline.yml` CI to pass, merge to `main`.

### 2.2 Tag and push

After the prep PR merges:

```bash
git checkout main
git pull --ff-only origin main
# Verify the merge commit is what you want to publish:
grep '^__version__' langs/python/src/vmx/__about__.py
# Tag it (no prefix `v` — the tag is `python-v<version>`):
git tag python-v2.6.0
git push origin python-v2.6.0
```

### 2.3 Watch the workflow

Open <https://github.com/thekaveh/VMx/actions?query=workflow%3Arelease>. The newest run for the `release` workflow has three Python jobs:

1. **`python — build & test pypi`** — runs immediately. Builds, runs `twine check`, publishes to Test PyPI, pip-installs from Test PyPI, runs the smoke test. ~2 minutes.
2. **`python — publish to PyPI`** — waits for **your approval**. When you see it pending, click "Review pending deployments", check `pypi-prod`, approve. The job then publishes to prod PyPI with Sigstore attestations.
3. **`python — GitHub Release`** — runs after job 2 succeeds. Extracts the matching CHANGELOG section, posts a GitHub Release.

### 2.4 Verify

After the workflow completes:

```bash
# Verify prod PyPI page renders:
curl -sS https://pypi.org/pypi/vmx/json | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['info']['name'], d['info']['version'])"
# Expected: vmx 2.6.0 (or whichever version)

# Verify install in a fresh venv:
python3 -m venv /tmp/vmx-verify
/tmp/vmx-verify/bin/pip install --upgrade pip
/tmp/vmx-verify/bin/pip install vmx==2.6.0
/tmp/vmx-verify/bin/python langs/python/scripts/smoke_test.py 2.6.0
# Expected: OK

# Verify the GitHub Release exists:
gh release view python-v2.6.0
```

## 3. Failure modes

### 3.1 Test PyPI publish failed

Symptom: Job 1 ends red at the "Publish to Test PyPI" step.

Likely causes:

- The Test PyPI Trusted Publisher is not yet registered for environment `pypi-test`. Re-register per §1.2.
- The same version already exists on Test PyPI from a prior failed attempt. `skip-existing: true` should make this a no-op; if it doesn't, the issue is propagation lag — retry the workflow.

### 3.2 Smoke test failed after Test PyPI install

Symptom: Job 1 succeeds through the publish step but fails at "Smoke test from Test PyPI".

Likely causes:

- A required runtime import is missing or moved. Look at the error: `ImportError: cannot import name X from vmx`. Fix the `vmx/__init__.py` exports or update the smoke test to match the new public surface.
- The package version was correctly tagged but `__about__.py` was not bumped before tagging — the smoke test catches this with the explicit `version` arg.

The fix is a new release-prep PR + a new tag (e.g., `python-v2.6.1`). PyPI does NOT allow overwriting a published version, even on Test PyPI in many cases.

### 3.3 Prod publish approval declined

Symptom: Job 2 is pending; you click Review and choose Reject.

Effect: Job 2 fails immediately, Job 3 does not run, nothing is published to prod PyPI. Test PyPI still has the version uploaded.

To recover: address whatever issue caused you to reject, prep a new release with a new version (bump patch or minor), tag, push.

### 3.4 Prod publish succeeded but the release is broken

PyPI does not allow deletion of a published version. You can **yank** a release via the web UI at <https://pypi.org/manage/project/vmx/release/X.Y.Z/> ("Options" → "Yank release").

After yanking, `pip install vmx` will not install the yanked version unless the user pins it exactly. Then publish a fix as a new patch version.

### 3.5 GitHub Release creation failed

Symptom: Jobs 1 and 2 succeed, Job 3 fails at "Extract CHANGELOG section" or "Create GitHub Release".

Most common cause: the CHANGELOG doesn't have a `## [<version>] — <date>` section for the version being released. Add the section to `langs/python/CHANGELOG.md` on `main` (small follow-up PR), then re-run Job 3 from the Actions UI.

## 4. Pre-release versions (alpha, beta, rc)

PEP 440 supports pre-release segments: `2.7.0a1`, `2.7.0b2`, `2.7.0rc1`. The release pipeline tolerates these automatically (the tag-vs-version check just compares strings; the CHANGELOG section heading must match the version exactly, including the pre-release segment).

Tag examples:

- `python-v2.7.0a1` → publishes `vmx==2.7.0a1` to Test PyPI and prod PyPI.
- `pip install vmx` (no version pin) will NOT pick up a pre-release; users must `pip install --pre vmx` or pin explicitly.

The CHANGELOG section heading for a pre-release should also include the pre-release segment, e.g.,:

```
## [2.7.0a1] — 2026-07-15
```

## 5. Spec compatibility

`__min_spec_version__` in `langs/python/src/vmx/__about__.py` declares the minimum
`spec/VERSION` this package implements. Bumping the spec major (e.g., 2.x → 3.0)
requires a corresponding flavor major bump per the policy in `README.md` §6.1.
The release pipeline does NOT enforce this — the spec-discipline GHA does, on the
prep PR.
