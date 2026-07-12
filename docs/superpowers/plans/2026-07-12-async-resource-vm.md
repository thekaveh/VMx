# AsyncResourceVM Implementation Plan

> Execute task by task with test-driven development and fresh verification at
> each commit boundary.

**Goal:** Add a reusable one-value asynchronous presentation state machine with
latest-start-wins cancellation, optional retention/cleanup, and five-flavor
conformance.

**Architecture:** `AsyncResourceVM<T>` is a component viewmodel whose immutable
`state` snapshot is the canonical binding surface. Existing async relay commands
delegate into one serialized operation core. A monotonic identity admits only
the latest completion, while an optional callback owns each acquired value.

**Reviewed design:**
`docs/superpowers/specs/2026-07-12-async-resource-vm-design.md`

## Global constraints

- Target spec/C#/Python/TypeScript/Swift 3.20.0 and Rust 0.20.0.
- Add exactly `ARES-001..011`; final coverage is 391 library / 396 total.
- Use ordinary component property/hub notification for canonical `state` only.
- Compose the existing `AsyncRelayCommand`, cancellation, and owned teardown
  surfaces; do not introduce another command, event, or cancellation protocol.
- Default to `DiscardPrevious`; retention and cleanup are explicit options.
- Keep routing, caching, pagination, transport, factories, and scheduling out.
- Canonical docs generate the MkDocs `.io` site and native GitHub wiki.

## Task 1: Normative contract and red coverage gate

- Create `spec/23-async-resource-vm.md`, ADR-0100, and the ADR ledger row.
- Add `ARES-001..011` to `spec/12-conformance.md` with exact state, command,
  cancellation, overlap, cleanup, and disposal assertions.
- Add the chapter to the spec navigation/count claims.
- Run the five-flavor coverage tool and confirm all eleven IDs are missing.
- Format and commit the spec-first red state.

## Task 2: TypeScript TDD and implementation

- Add eleven `describe("ARES-NNN")` cases with deferred loaders and abort probes.
- Confirm focused compile/test failure before the state module exists.
- Add `state/asyncResourceVM.ts` with discriminated snapshots, linked
  `AbortController`, operation identity, command composition, and cleanup.
- Export the surface from the state and package entry points.
- Run focused/full Vitest, source/test typechecks, lint, build, pack, and audit.
- Commit referencing #139.

## Task 3: C# TDD and implementation

- Add eleven `[Trait("Conformance", "ARES-NNN")]` tests using task completion
  sources, cancellation probes, INPC, and hub observations.
- Confirm focused red compilation before the types exist.
- Add immutable state/status/retention types and `AsyncResourceVM<T>` under
  `VMx.State`, linking cancellation tokens and serializing completion admission.
- Run focused/full xUnit suites for both TFMs, locked Release build, format, and
  package validation.
- Commit referencing #139.

## Task 4: Python TDD and implementation

- Add eleven `@pytest.mark.conformance("ARES-NNN")` async cases using controlled
  futures/tasks, cancellation-resistant loaders, and cleanup counters.
- Confirm focused red import/collection failure.
- Add `vmx.state.async_resource_vm` with frozen state snapshots, asyncio task
  cancellation, operation identity, existing commands, and idempotent teardown.
- Export public names and run focused/full pytest, Ruff check/format, build, and
  strict mypy.
- Commit referencing #139.

## Task 5: Swift TDD and implementation

- Add eleven XCTest cases/markers using continuations, cancellation-aware and
  cancellation-resistant tasks, Combine state observations, and cleanup probes.
- Confirm focused compile failure when full Xcode is available; otherwise record
  the local XCTest limitation before implementation.
- Add `State/AsyncResourceVM.swift` with immutable enum-backed state, task
  cancellation, locked identity admission, command composition, and cleanup.
- Run debug/release library and public-consumer builds, source/test parse checks,
  and focused/full XCTest on macOS CI.
- Commit referencing #139.

## Task 6: Rust TDD and implementation

- Add eleven conformance functions/doc markers using channels/barriers,
  cancellation-resistant actions, hub observations, and atomic cleanup counts.
- Confirm focused red compile failure before the public types exist.
- Add `async_resource_vm.rs`; compose `ComponentVm`, `AsyncRelayCommand`,
  `CancellationToken`, mutex-protected operation state, and acquisition cleanup.
- Re-export from `lib.rs`; run fmt, clippy with warnings denied, focused/full
  tests, rustdoc, and `cargo package`.
- Commit referencing #139.

## Task 7: Docs, versions, and generated surfaces

- Add canonical primitive guidance with state tables, command bindings,
  retention/cleanup examples, race diagrams, and flavor-specific signatures.
- Bump spec and stable flavors to 3.20.0, Rust to 0.20.0; update min-spec
  declarations, manifests/locks, compatibility matrix, changelogs, READMEs,
  AGENTS counts, and 391/396 catalog claims.
- Regenerate and verify in-repo docs, generated site/wiki, links, navigation,
  diagrams where affected, and strict MkDocs.
- Commit release/docs changes referencing #139.

## Task 8: DayDreams no-push pilot

- Clone DayDreams to a disposable directory at its audited commit.
- Install the VMx TypeScript tarball and move GalleryView and DreamscapeView load
  lifecycle/race state into `AsyncResourceVM` without changing routing/services.
- Run the affected view/viewmodel suites plus full feasible TypeScript gates.
- Record before/after ownership, behavior, LOC, commands, and exact test evidence
  in `docs/superpowers/reports/2026-07-12-issue-139-daydreams-pilot.md`.
- Delete the disposable clone; never push or mutate the user checkout.

## Task 9: Cross-cutting verification and git flow

- Run all five full language gates concurrently, then tools tests, version and
  fixture checks, 391/391 conformance coverage, docs checks, pre-commit, and
  `git diff --check`.
- Review the diff for unrelated files, secrets, compatibility, race safety,
  exactly-once cleanup, and post-dispose notifications.
- Push and open the feature PR to `develop`; resolve only branch findings and
  squash-merge after every required check is green.
- Open a separate `develop` to `main` PR containing only #139; merge after green.
- Verify post-main workflows and live repo/Pages/wiki docs; finalize the issue
  and board, remove the clean worktree/branch, and immediately begin #97.
