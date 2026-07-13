# NuGet Release Channel Design

## Objective

Publish the three C# packages through a protected, tag-driven NuGet trusted
publishing channel, with package allowlists and clean-consumer verification
before any public documentation claim.

## Revalidated state

- `VMx`, `VMx.Notifications`, and `VMx.Extensions.DependencyInjection` all
  return NuGet 404.
- Locked restore, Release build, 935 tests, format, and all three packs pass.
- Every package contains DLL/XML assets for `netstandard2.0` and `net8.0`, a
  repository commit, Apache-2.0 metadata, README, and a matching `.snupkg`.
- Companions pack with an exact `VMx >= 3.20.0` dependency in both frameworks.
- No NuGet environment, repository secret, or account identity is configured.
- `csharp-v2.1.0` already exists as an immutable historical core tag. The DI
  companion therefore moves from 2.1.0 to the packaging-only patch 2.1.1.

## Package and tag sequence

One tag publishes only projects whose declared version equals the tag version:

1. `csharp-v3.20.0` publishes `VMx` 3.20.0.
1. `csharp-v1.2.0` publishes `VMx.Notifications` 1.2.0 after core is public.
1. `csharp-v2.1.1` publishes `VMx.Extensions.DependencyInjection` 2.1.1 after
   core is public.

The tags are created only from verified `main`. No accepted version or release
tag is moved, replaced, or silently skipped.

## Package validation and consumers

`tools/check-nuget-package.py` validates exact main/symbol archive allowlists,
IDs, versions, license/readme/repository metadata, frameworks, and companion
VMx dependency floors. Unexpected files, missing XML/PDB assets, mismatched
symbol metadata, or loose/incorrect core dependencies fail CI.

`tools/smoke-nuget-consumer.py` consumes either a local package directory or
the public NuGet feed. It restores exact versions into disposable `net8.0` and
`netstandard2.0` projects, compiles root, Notifications, and DI APIs, and runs
the net8.0 probe. Public mode polls the flat-container API before restore.

## Workflow

The unauthenticated build job verifies tag ancestry/version selection, locked
restore, Release build/tests/format, packs all packages, validates them, and
runs both local consumers. It uploads only the tag-selected `.nupkg`, matching
`.snupkg`, and a release manifest.

The publish job uses protected environment `nuget-csharp`, `id-token: write`,
and `NuGet/login` pinned to the v1.2.0 commit. The account profile name is read
from the environment secret `NUGET_USER`; there is no long-lived API key. The
OIDC exchange occurs immediately before `dotnet nuget push`.

After upload, a `net8.0`/`netstandard2.0` matrix polls and consumes the exact
public artifacts. Only then does a final job create a GitHub Release from the
matching core or package-qualified C# changelog section.

## External account gate

Create `nuget-csharp` with maintainer approval, no administrator bypass, and a
`csharp-v*` tag policy. An authenticated nuget.org owner must configure trusted
publishing for owner/profile, `thekaveh/VMx`, `release.yml`, and environment
`nuget-csharp`, then place only the non-secret profile name in `NUGET_USER`.

If account policy is unavailable, land repository preparation, leave #56
Todo/Ready with evidence, and do not create any tag.

## Documentation phase

Before publication, update only source/version and operational runbook facts.
After all three packages, symbols, consumers, and GitHub Releases are public,
replace unpublished claims in canonical repo docs, regenerate the `.io` site
and wiki, and merge that evidence through develop and main.
