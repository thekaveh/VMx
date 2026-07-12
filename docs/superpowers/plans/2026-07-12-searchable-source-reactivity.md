# SearchableState Source Reactivity Implementation Plan

> Execute task by task with test-driven development and fresh verification at
> each commit boundary.

**Goal:** Make `SearchableState` react to an optional source-change signal in
all five flavors without breaking existing supplier-only callers.

**Architecture:** The existing lazy supplier remains authoritative. An optional
payload-free trigger is merged beside term debounce and explicit search; each
trigger immediately re-reads the supplier with the current term. Upstream
batching is preserved transparently, failure/completion is isolated, and the
helper owns only its subscription.

**Reviewed design:**
`docs/superpowers/specs/2026-07-12-searchable-source-reactivity-design.md`

## Global constraints

- Target spec/C#/Python/TypeScript/Swift 3.19.0 and Rust 0.19.0.
- Add exactly `SRCH-001..007`; final coverage is 380 library / 385 total.
- Keep existing constructors/options source compatible and preserve explicit
  `search()` behavior when no signal is supplied.
- Source pulses bypass but do not reset/cancel term debounce.
- Do not add internal batch timing, equality suppression, collection ownership,
  source replacement, or a dynamic-member registry.
- Error-capable signals isolate errors; Swift/Rust use non-failing signals.
- Canonical docs generate the MkDocs `.io` site and native GitHub wiki.

## Task 1: Normative contract and red coverage gate

- Create `spec/ADRs/0099-searchable-source-reactivity.md` and add its ledger row.
- Update `spec/06-composite-vm.md` with the optional trigger, setup reconciliation,
  timing, batching, failure, completion, and ownership semantics.
- Update `spec/12-conformance.md` with `SRCH-001..007` and revise COMP-018 so
  explicit refresh remains the compatibility path when no signal is supplied.
- Run the five-flavor coverage tool and confirm all seven IDs are missing.
- Format and commit the spec-first red state.

## Task 2: C# TDD and implementation

- Add seven `SRCH` facts to `SearchFilterConformanceTests.cs` using `Subject<Unit>`
  and `TestScheduler` where pending debounce must be observed.
- Confirm focused tests fail against the absent constructor parameter.
- Add trailing `IObservable<Unit>? sourceChanged = null`; map pulses to the
  current term, isolate errors with an empty continuation, merge independently,
  and perform post-subscription reconciliation.
- Verify focused/full xUnit suites, both TFMs, Release build, and format.
- Commit referencing #98.

## Task 3: Python TDD and implementation

- Add seven `@pytest.mark.conformance("SRCH-NNN")` cases using `Subject` and
  `TestScheduler`, including error isolation and idempotent disposal.
- Confirm focused red tests.
- Add trailing `source_changes`; map to current term, catch errors to an empty
  observable, merge independently, and reconcile after subscription.
- Run focused/full pytest, Ruff check/format, and strict mypy.
- Commit referencing #98.

## Task 4: TypeScript TDD and implementation

- Add seven `describe("SRCH-NNN")` cases with RxJS `Subject`, virtual/fake time,
  error isolation, completion, and ownership guards.
- Confirm focused red tests.
- Add `sourceChanges?: Observable<unknown>`; use `map`, `catchError`, and `EMPTY`
  beside existing term/force streams, then reconcile after subscription.
- Remove the VMX-093 snapshot-only warning and replace it with the new contract.
- Run focused/full Vitest, source/test typechecks, lint, build, and audit.
- Commit referencing #98.

## Task 5: Swift TDD and implementation

- Add seven `SRCH` XCTest markers/cases with `PassthroughSubject<Void, Never>`;
  use expectations for the independent debounce case and completion isolation.
- Confirm the focused test target fails to compile before the API exists when a
  full Xcode toolchain is available; otherwise record the local XCTest limitation.
- Add trailing erased non-failing `sourceChanges`, merge its current-term mapping
  independently, reconcile after attachment, and retain only the cancellable.
- Run debug/release builds, focused/full XCTest on CI, and source parse checks.
- Commit referencing #98.

## Task 6: Rust TDD and implementation

- Add seven `SRCH` test functions/doc markers using a `MessageHub` trigger and
  `filtered_changed()` observations.
- Confirm focused compile failures for the missing constructors/disposal.
- Add `new_with_changes` / `from_items_with_changes`, store the source
  `Subscription` behind shared state, emit one filtered invalidation per source
  pulse, reconcile by live pull, and add idempotent `dispose()`.
- Preserve `new` / `from_items` behavior and document the existing synchronous
  Rust term-notification mapping.
- Run fmt, clippy with warnings denied, focused/full tests, docs, and package.
- Commit referencing #98.

## Task 7: Docs, examples, versions, and generated surfaces

- Update canonical state/reactive-helper docs with direct collection and #136
  aggregate composition examples plus timing/failure/ownership guidance.
- Update affected example guidance for paging/search and tag autocomplete.
- Bump spec and stable flavors to 3.19.0, Rust to 0.19.0; update minimum-spec
  declarations, manifests/locks, compatibility matrix, changelogs, READMEs, and
  380/385 counts.
- Regenerate and verify in-repo docs, `generated/site`, `generated/wiki`, links,
  drift, diagrams if affected, and MkDocs strict.
- Commit release/docs changes referencing #98.

## Task 8: Cross-cutting verification and consumer evidence

- Run all five full language gates, tools tests, version consistency, fixture
  checks, 380/380 conformance coverage, pre-commit, and `git diff --check`.
- Review the complete diff for unrelated changes, secrets, API drift, ownership,
  and cross-flavor semantics.
- Pilot only in disposable consumer clones where SearchableState is actually
  used; record applicability and exact tests without mutating consumer repos.
- Fix findings with focused regression tests and repeat affected gates.

## Task 9: Git-flow publication

- Push the feature branch and open a PR to `develop` with issue/design/spec,
  flavor, tests, docs, pilots, risks, and exact verification evidence.
- Resolve CI/review findings only on the branch; squash-merge after green.
- Open a separate `develop` to `main` PR containing only #98; merge after green.
- Verify post-main workflows and live repository/Pages/wiki documentation.
- Comment on #98 with both PRs and evidence, set Done/Completed, clear ordering
  fields, close it, remove the clean worktree/branch, then re-read the board.
