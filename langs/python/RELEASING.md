# Releasing the `vmx` Python package

This runbook documents how `vmx` is published to PyPI.

The release pipeline has two halves:

- **Routine releases.** `release-please` watches `main` for Conventional
  Commits and maintains a long-lived "release PR" that bumps the version
  in `langs/python/src/vmx/__about__.py` and writes the new section in
  `langs/python/CHANGELOG.md`. Merging that PR pushes a `python-v<X.Y.Z>`
  tag, which fires the publish pipeline.
- **Publish pipeline.** `.github/workflows/release.yml` runs four jobs on
  the new tag: `python-test` (full pytest matrix gate), `python-build-and-publish`
  (gated on the `pypi-python` GitHub environment for manual approval, then an
  exact-backend build, metadata check, fresh-environment install/smoke of the
  local wheel, and Trusted-Publishing-via-OIDC upload with Sigstore (PEP 740)
  attestations),
  `python-verify-published` (5-attempt fresh-venv `pip install` + smoke test),
  and `python-release-notes` (CHANGELOG-extracted GitHub Release).

No API tokens. No Test PyPI. Trusted Publishing only.

## 1. Prerequisites (one-time, done by the package owner)

### 1.1 PyPI Trusted Publisher

- A PyPI account at <https://pypi.org/account/register/> with 2FA enabled.
- On <https://pypi.org/manage/account/publishing/>, "Add a new pending publisher":

  | Field             | Value         |
  | ----------------- | ------------- |
  | PyPI Project Name | `vmx`         |
  | Owner             | `thekaveh`    |
  | Repository name   | `VMx`         |
  | Workflow name     | `release.yml` |
  | Environment name  | `pypi-python` |

### 1.2 GitHub environment `pypi-python`

- In the repo's Settings → Environments, create `pypi-python`.
- Under "Deployment protection rules", enable "Required reviewers" and add yourself.
- Leave "Allow self review" unchecked — every publish requires an explicit click after the test gate passes.
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

The same lesson applies to npm `package.json` `homepage`/`bugs`/`repository`, NuGet `<PackageProjectUrl>`/`<RepositoryUrl>`, and SwiftPM Index entries when those flavors uplift to the same pattern.

## 2. Cutting a release

### 2.1 Routine release (release-please-driven)

1. Land Conventional-Commit-style PRs on `main` (`feat: …`, `fix: …`, `docs: …`, etc.).
2. `release-please` opens a "chore(main): release vmx-python …" PR — review the version bump in `langs/python/src/vmx/__about__.py` and the matching `langs/python/CHANGELOG.md` entry.
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

### 2.2 Bootstrap release (manual tag, one-time)

For the very first release where `__about__.py` is already at the target version (so release-please won't propose a release PR for that version), push the tag manually:

```bash
git checkout main
git pull --ff-only origin main
grep '^__version__' langs/python/src/vmx/__about__.py    # confirm target version
version=$(python3 -c "exec(open('langs/python/src/vmx/__about__.py').read()); print(__version__)")
git tag "python-v${version}"
git push origin "python-v${version}"
```

The same four publish jobs run.

The `release-please` workflow deliberately pauses while the source version and
`.release-please-manifest.json` disagree. The manifest records the last version
actually published; never advance it merely to silence the guard. After the
bootstrap pipeline and public-install verification succeed:

1. Confirm PyPI and the GitHub release both report the exact source version.
2. Change `.release-please-manifest.json` to that verified published version in
   a normal reviewed PR.
3. Run `python3 tools/check-release-please-state.py`; it must report `OK`.
4. Merge the reconciliation PR. The next push to `main` can safely resume
   release-please automation.

If an existing release PR proposes a version below the source version, do not
merge it. Close it after the guard is present on `main`, delete only the bot's
release branch, then complete the bootstrap and reconciliation sequence above.

> **Tag-ordering gotcha for new flavors.** When wiring `release-please` for the first time on a flavor (current Python adoption; future C#/TypeScript/Swift uplifts), push the bootstrap tag **before** merging the PR that adds the release-please config. Otherwise `release-please-action`'s first run on `main` sees no matching `<component>-v<X.Y.Z>` tag in the new format, walks the full repo history, and proposes a wildly-oversized release PR (it happened during the Python adoption — bot proposed `2.7.0` built from years-old `feat: absorption-cycle-*` commits). The branch lingers indefinitely after later runs correctly say "No user facing commits found"; recover with `git push origin --delete release-please--branches--main--components--<component>`.

### 2.3 Pre-release (`alpha`, `beta`, `rc`)

PEP 440 segments are supported. Tag examples:

- `python-v2.7.0a1` → publishes `vmx==2.7.0a1` to PyPI.
- `pip install vmx` (no version pin) will NOT pick up a pre-release; users must `pip install --pre vmx` or pin explicitly.

The CHANGELOG section heading must match the version exactly (including the pre-release segment):

```
## [2.7.0a1] — 2026-07-15
```

For routine pre-releases via release-please, mark commits with `feat!:` / `fix!:` to drive the bump policy, or override the bump in the release-please PR before merging.

## 3. Verifying a release

```bash
# PyPI page renders:
curl -sS https://pypi.org/pypi/vmx/json | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['info']['name'], d['info']['version'])"
# → vmx 2.6.1

# Install in a fresh venv:
python3 -m venv /tmp/vmx-verify
/tmp/vmx-verify/bin/pip install --upgrade pip
/tmp/vmx-verify/bin/pip install vmx==2.6.1
/tmp/vmx-verify/bin/python langs/python/scripts/smoke_test.py 2.6.1
# → OK

# GitHub Release:
gh release view python-v2.6.1
```

## 4. Failure modes

### 4.1 `python-test` failed

The publish never reaches the build job. Fix the broken test on `main` and re-cut the tag — but since release-please-driven releases bump the version on the release PR, the tag for the same version will be different commits and the fix lands in a follow-up patch release.

### 4.2 `python-build-and-publish` approval declined

The environment publishes nothing. To recover: address whatever caused you to reject, land the fix, let release-please open a new release PR with a bumped version, merge.

The same job can also fail safely after approval but before upload if the pinned
build backend, Twine metadata check, local wheel installation, or lifecycle smoke
fails. No PyPI version exists yet; fix the defect on `main` and cut a new tag.

### 4.3 Publish succeeded but the release is broken

PyPI does not allow deletion of a published version. Yank it via <https://pypi.org/manage/project/vmx/release/X.Y.Z/> ("Options" → "Yank release"). Then publish a fix as a new patch version.

### 4.4 `python-verify-published` failed after publish

This means PyPI accepted the upload but the package can't be installed or imported. Diagnose the error in the workflow log. The published artifact is permanent — the fix is a new patch release with the import/install fault corrected. Consider yanking the bad version.

### 4.5 `python-release-notes` failed

If the GitHub Release didn't get created (e.g., CHANGELOG section missing), re-run that job alone from the Actions UI after fixing the CHANGELOG. The PyPI artifact is already live.

## 5. Tag scheme and multi-flavor coexistence

Python releases use `python-v<X.Y.Z>`. Other flavors will adopt the same flavor-prefixed convention (`csharp-v*`, `typescript-v*`, `swift-v*`); `release.yml` already filters by prefix per job, so adding more flavors does not change the Python pipeline.

`release-please-config.json` is monorepo-aware. When other flavors adopt release-please, add their package entries alongside `langs/python` — each gets its own component-prefixed tag and its own changelog.

## 6. Spec compatibility

`__min_spec_version__` in `langs/python/src/vmx/__about__.py` declares the minimum `spec/VERSION` this package implements. Bumping the spec major (e.g., 2.x → 3.0) requires a corresponding flavor major bump per the policy in `README.md` §6.1. The release pipeline does NOT enforce this — `.github/workflows/spec-discipline.yml` does, on the prep PR. release-please leaves `__min_spec_version__` untouched; bump it manually in the release PR review if a spec major bumps in the same window.
