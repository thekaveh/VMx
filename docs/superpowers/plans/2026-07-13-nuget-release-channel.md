# NuGet Release Channel Implementation Plan

## 1. Package contract checker

- Add failing tests for exact `.nupkg`/`.snupkg` contents, metadata, framework
  groups, version pairing, and companion `VMx` dependency floors.
- Implement `tools/check-nuget-package.py` and run it against real packs.
- Wire the module into the tools test loader.

## 2. Clean consumer smoke

- Add failing renderer/poll/command tests.
- Implement local/public exact package selection, NuGet flat-container polling,
  disposable net8.0 runtime and netstandard2.0 compile consumers, and cleanup.
- Prove all three locally packed packages together.

## 3. Ordinary C# package CI

- Add workflow contract tests.
- Extend C# CI triggers for the package tools and add Linux package jobs for
  net8.0 and netstandard2.0 after a complete pack.
- Run the checker and local smoke in each cell.

## 4. Version and release notes

- Bump only `VMx.Extensions.DependencyInjection` 2.1.0 to 2.1.1 because the
  existing `csharp-v2.1.0` core tag is immutable.
- Update lockfile/project consistency and compatibility source note.
- Add package-qualified changelog sections for Notifications 1.2.0 and DI
  2.1.1; add release-pipeline notes to core 3.20.0.
- Add a tested release-note renderer that selects the exact package sections.

## 5. Trusted-publishing release workflow

- Split C# build/pack from protected authentication/publish.
- Before auth: verify main ancestry, exact tag project selection, locked
  restore, Release build/tests/format, all packs, allowlists, and both local
  consumers; upload only selected package/symbol pairs plus manifest.
- Publish from `nuget-csharp` with `id-token: write`, pinned `NuGet/login`, and
  environment `NUGET_USER`; do not support a long-lived API-key bypass.
- Poll exact public packages, run both consumer frameworks, then create the
  package-specific GitHub Release.
- Rewrite `langs/csharp/RELEASING.md` for OIDC, three-tag ordering, immutable
  recovery/unlisting, symbols, and post-verification docs.

## 6. Preparation verification and Git flow

- Run locked restore, Release build/tests/format, real packs/checker/consumers,
  all tools tests/current Ruff, version/fixture/conformance checks, docs/site/
  wiki, all-files pre-commit, diff and credential hygiene.
- Push a ready PR to develop with `Relates to #56`; fix CI until green and
  squash-merge.
- Promote only #56 preparation develop to main through a green merge-commit PR.

## 7. Account configuration and publication

- Create protected `nuget-csharp`, reviewer approval, no admin bypass, and only
  `csharp-v*` tags.
- Require an authenticated nuget.org owner to create the trusted-publishing
  policy and set environment `NUGET_USER` without exposing credentials.
- Confirm each tag/version is absent, then publish in order: core 3.20.0,
  Notifications 1.2.0, DI 2.1.1.
- Require public main/symbol artifacts, both clean consumers, and three GitHub
  Releases. Independently repeat exact public consumer verification.

## 8. Post-publication docs and completion

- Create a new docs branch from current develop.
- Update README, compatibility matrix, C# README/runbook, installation and C#
  flavor docs with verified versions, dependency floors, symbols, and OIDC.
- Regenerate and verify repo docs, MkDocs `.io`, and GitHub wiki.
- Merge docs to develop, then develop to main with `Closes #56`.
- Verify live NuGet, releases, Pages, and wiki; comment complete evidence, set
  Done/Completed, clear ordering, close, and remove worktrees/branches.
