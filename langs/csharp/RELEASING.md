# Releasing the `VMx` C# packages

This runbook documents how `VMx` (and its companion packages
`VMx.Notifications` and `VMx.Extensions.DependencyInjection`) are published
to NuGet.

The release pipeline is **manual tag-driven**: push a `csharp-v<X.Y.Z>` tag
on `main` and `.github/workflows/release.yml` handles the rest. There is no
automated version-bump PR (release-please is not yet wired for the C#
component — a follow-up when adopting it, see `langs/python/RELEASING.md`
§2.2 for the tag-ordering gotcha).

## 1. Prerequisites (one-time, done by the package owner)

### 1.1 NuGet API key

- A NuGet account at <https://www.nuget.org/users/account/LogOn> with 2FA
  enabled.
- Create an API key at <https://www.nuget.org/account/apikeys> scoped to the
  `VMx*` package glob with "Push" permission and a suitable expiration.
- In the repo's Settings → Secrets and variables → Actions, add the secret
  as `NUGET_API_KEY`.

> **Why token-based instead of OIDC?** NuGet Trusted Publishing (OIDC) is
> not yet available for all publisher configurations. The pipeline uses
> `--api-key "$NUGET_API_KEY"` for now; uplift to OIDC when NuGet supports
> it, and update `release.yml:csharp` accordingly.

### 1.2 Pre-publish metadata validation

Every URL in the `.csproj` files (`<PackageProjectUrl>`, `<RepositoryUrl>`,
`<PackageLicenseExpression>`) is rendered on the NuGet package page. Before
tagging, verify:

```bash
grep -r "PackageProjectUrl\|RepositoryUrl" langs/csharp/src/**/*.csproj
```

Check each URL is reachable. Also confirm `<Version>` matches the intended tag
version in every package project you plan to release.

### 1.3 Companion package versioning

`VMx.Notifications` and `VMx.Extensions.DependencyInjection` version
independently from `VMx` (per ADR-0009 / ADR-0013). The release workflow finds
all C# package projects whose `<Version>` equals the `csharp-v*` tag version
and packs only those projects. Update a companion package's `<Version>` only
when it has changes to ship.

## 2. Cutting a release

### 2.1 Routine release (manual)

1. Land all intended changes on `main`.
2. Update `<Version>` in the relevant `.csproj` file(s) under
   `langs/csharp/src/`.
3. Update `MinSpecVersion` in the same area if the spec version also bumped.
4. Add a `## [X.Y.Z] — YYYY-MM-DD` section to `langs/csharp/CHANGELOG.md`.
5. Commit and push directly to `main` (or via a PR).
6. Tag and push:

   ```bash
   git checkout main
   git pull --ff-only origin main
   grep '<Version>' langs/csharp/src/VMx/VMx.csproj   # confirm version
   git tag csharp-v2.6.1
   git push origin csharp-v2.6.1
   ```

7. Watch <https://github.com/thekaveh/VMx/actions?query=workflow%3Arelease> —
   the publish pipeline fires on the tag.
8. The workflow verifies the tag commit is reachable from `origin/main` before
   it builds. If `NUGET_API_KEY` is missing, the job fails before publish rather
   than green-skipping the release.
### 2.2 What the pipeline does

The `csharp` job in `release.yml` runs only when the tag starts with
`csharp-v`. It:

1. Checks out the repository and verifies the tag commit is reachable from
   `origin/main`.
2. Sets up .NET 8.0.x and 9.0.x, restoring from the packages lockfile.
3. Runs `dotnet restore VMx.sln --locked-mode`.
4. Runs `dotnet build VMx.sln -c Release`.
5. Runs `dotnet test VMx.sln -c Release` (full test suite incl. conformance).
6. Finds package projects under `langs/csharp/src/*/*.csproj` whose `<Version>`
   matches the tag and runs `dotnet pack` for those projects only.
7. Fails if `NUGET_API_KEY` is absent.
8. Runs `dotnet nuget push /tmp/nupkgs/*.nupkg --source https://api.nuget.org/v3/index.json`
   with `--skip-duplicate`.

There is no separate verify-published or release-notes job for C# yet;
add them alongside adoption of release-please.

### 2.3 Pre-release (`alpha`, `beta`, `rc`)

Use NuGet pre-release SemVer segments in the `.csproj`:

- `<Version>2.7.0-alpha.1</Version>` → `dotnet nuget push`
  will push a pre-release package. `dotnet add package VMx` (no version pin)
  will NOT pick it up by default; users must pin or pass `--prerelease`.

## 3. Verifying a release

```bash
# NuGet page renders:
curl -s "https://api.nuget.org/v3-flatcontainer/vmx/index.json" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['versions'][-1])"

# Install in a test project:
mkdir /tmp/vmx-cs-verify && cd /tmp/vmx-cs-verify
dotnet new classlib -n Verify
cd Verify
dotnet add package VMx --version X.Y.Z
```

## 4. Failure modes

### 4.1 `dotnet test` failed

The pack and push steps are in the same job and run sequentially; a test
failure causes the job to abort before push. Fix the failing test on `main`,
cut a new tag with a bumped patch version.

### 4.2 `NUGET_API_KEY` not set / expired

The job fails before publish when the secret is absent or expired. Regenerate
the API key on NuGet, update the `NUGET_API_KEY` Actions secret, and re-run the
failed workflow. If the tag itself was wrong, delete and recreate it on `main`:

```bash
git push origin --delete csharp-v2.6.1
git tag -d csharp-v2.6.1
git tag csharp-v2.6.1
git push origin csharp-v2.6.1
```

> **`--skip-duplicate`**: the push uses `--skip-duplicate` so re-running after
> fixing a secret issue does not fail if the package was partially uploaded.

### 4.3 Publish succeeded but the release is broken

NuGet allows unlisting but not deletion. Unlist the bad version at
<https://www.nuget.org/packages/VMx/X.Y.Z/> (Manage → Unlist). Then publish
a fix as a new patch version.

## 5. Tag scheme and multi-flavor coexistence

C# releases use `csharp-v<X.Y.Z>`. Each flavor tag prefix is independent;
`release.yml` filters by prefix, so pushing a `csharp-v*` tag never affects
the Python, TypeScript, or Swift jobs. See `langs/python/RELEASING.md` §5
for the multi-flavor scheme overview.

The companion packages (`VMx.Notifications`, `VMx.Extensions.DependencyInjection`)
share the `csharp-v<X.Y.Z>` tag prefix but version independently. If a companion
package needs a hotfix without bumping the core package, update only that
project's `<Version>` and push `csharp-v<X.Y.Z>` for the companion version; the
workflow packs the matching project and does not repack unrelated C# packages.

## 6. Spec compatibility

`MinSpecVersion` in the C# source declares the minimum `spec/VERSION` this
package implements. Bump it manually in the same PR that implements a new spec
version's behavior. A spec major bump requires a corresponding flavor major
bump per `README.md` §6.1.
