# Releasing the VMx C# packages

This runbook covers `VMx`, `VMx.Notifications`, and
`VMx.Extensions.DependencyInjection`. Releases are tag-driven from `main` by
`.github/workflows/release.yml`; each `csharp-v<X.Y.Z>` run publishes only
projects whose declared version exactly equals the tag version.

## 1. One-time owner setup

### 1.1 Protected GitHub environment

Create `nuget-csharp` in `thekaveh/VMx` with:

- only `csharp-v*` tag deployments;
- required maintainer approval; and
- administrator bypass disabled.

Add the nuget.org profile name—not an email address—as the environment secret
`NUGET_USER`. Although the profile name is not a credential, the environment
secret keeps account identity and approval in the same protected boundary.

### 1.2 NuGet trusted-publishing policy

From the authenticated nuget.org account, create a trusted-publishing policy
owned by the intended individual or organization:

- repository owner: `thekaveh`;
- repository: `VMx`;
- workflow filename: `release.yml` (filename only);
- environment: `nuget-csharp`.

The publish job has `id-token: write` and uses `NuGet/login` v1.2.0 to exchange
GitHub OIDC for a one-use, one-hour API key immediately before upload. No
long-lived NuGet API key belongs in GitHub.

If trusted publishing is unavailable to the account, stop. A least-privilege,
short-expiry API-key fallback requires a separate reviewed workflow change and
must be limited to the exact `VMx*` IDs; never add an undocumented token path.

## 2. Independent package versions

The current first-publication sequence is deliberate:

1. `csharp-v3.20.0` publishes `VMx` 3.20.0.
2. `csharp-v1.2.0` publishes `VMx.Notifications` 1.2.0 after core verifies.
3. `csharp-v2.1.1` publishes `VMx.Extensions.DependencyInjection` 2.1.1 after
   core verifies.

Both companions pack with `VMx >= 3.20.0` for net8.0 and netstandard2.0. DI
uses packaging-only patch 2.1.1 because `csharp-v2.1.0` is already an immutable
historical core tag. Never move or reuse that tag.

## 3. Cutting a release

1. Land the intended package version and matching core or package-qualified
   `langs/csharp/CHANGELOG.md` section on `main` through develop/main PRs.
2. From a clean current `origin/main`, confirm the tag and NuGet version are
   absent. For example:

   ```bash
   git ls-remote --exit-code --tags origin refs/tags/csharp-v3.20.0 || true
   curl -fsS https://api.nuget.org/v3-flatcontainer/vmx/index.json || true
   ```

3. Create the immutable tag on verified main and push it:

   ```bash
   git tag csharp-v3.20.0 origin/main
   git push origin csharp-v3.20.0
   ```

4. Approve the `nuget-csharp` deployment and watch the Release workflow.
5. Require the public consumer and GitHub Release to pass before creating the
   next companion tag.

### 3.1 Pre-publish gates

Before entering the protected environment, CI verifies main ancestry and exact
tag/project selection, locked restore, Release format/build/tests, every public
project pack, exact `.nupkg` and `.snupkg` allowlists, metadata, repository SHA,
framework assets, dependency floors, and clean local net8.0 and netstandard2.0
consumers. Only the tag-selected main/symbol pairs enter the publish artifact.

The protected job downloads that immutable artifact, validates `NUGET_USER`,
exchanges OIDC, and pushes without `--skip-duplicate`. An existing version is
an error, not something to hide.

### 3.2 Post-publish gates

Separate net8.0 and netstandard2.0 jobs poll NuGet for the exact selected
version. They restore into disposable package-only projects, compile core and
selected companion APIs, and run the net8.0 assembly-version probe. Only after
both pass does CI create a GitHub Release from the exact matching changelog
section. Main-package upload also publishes the adjacent `.snupkg`.

Pre-releases require a matching SemVer pre-release tag and an explicit workflow
change because the current stable-tag selector accepts only `X.Y.Z`.

## 4. Independent verification

Repeat public checks outside the release job:

```bash
python3 tools/smoke-nuget-consumer.py \
  --package VMx=3.20.0 --framework net8.0 --poll-timeout 900
python3 tools/smoke-nuget-consumer.py \
  --package VMx=3.20.0 --framework netstandard2.0 --poll-timeout 900
gh release view csharp-v3.20.0 --repo thekaveh/VMx
```

For a companion, pass its exact package/version; the tool pins core 3.20.0 as
well. Verify the NuGet package page and symbol availability before changing
documentation or the roadmap item to Done.

## 5. Failure and recovery

### 5.1 Failure before upload

Fix through the normal PR flow. If no NuGet version or GitHub Release exists,
an unpublished bad tag may be deleted and a new tag created on corrected main.
Never move a tag after an artifact has been accepted.

### 5.2 OIDC or account failure

Confirm `NUGET_USER` is the profile name and that the policy matches owner,
repository, `release.yml`, and `nuget-csharp` exactly. A pending policy may have
a limited activation window; activate it through a successful authorized
publish. Do not bypass the environment or add a long-lived key.

### 5.3 Upload succeeded but verification failed

NuGet versions are immutable. Diagnose the public artifact, fix forward, and
publish a new patch. If necessary, unlist the broken version from its NuGet
management page and explain the replacement in release notes. Never silently
replace a package or reuse its tag.

## 6. Documentation and compatibility

`MinSpecVersion` declares the feature/spec level while companion package
versions remain independent. A spec major bump requires a core flavor major
bump under `README.md` §6.1.

After all three public artifacts, symbols, exact consumers, and GitHub Releases
verify, update canonical repository docs and regenerate the MkDocs `.io` site
and GitHub wiki through develop and main PRs. Publication claims must never
precede public evidence.
