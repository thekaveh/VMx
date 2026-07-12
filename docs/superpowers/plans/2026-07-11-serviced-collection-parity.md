# Serviced Collection Parity Implementation Plan

Issue: #90\
Branch: `codex/issue-90-serviced-collection-parity`\
Base: `9731fd1150df99da85a6208dc1582a335acb8306`

Use subagent-driven development with a fresh implementer and read-only reviewer
for each task. Follow red-green TDD and commit each completed task.

## Task 1: Specify the contract

- Add ADR-0096 and registry row.
- Correct chapter 21's serviced shape, edge cases, Move message fields,
  ordering, ownership, and conformance list.
- Add real `COL-048..055` catalog entries and chapter references.
- Update ADR-0009 only where a former divergence is removed or newly required.
- Reserve the eight-ID mapping; each flavor task adds recognized markers on
  real failing behavioral tests before its implementation (no parked stubs).
- Review the specification for additive compatibility and unambiguous index
  semantics.

## Task 2: TypeScript parity first

- Write focused failing tests for `remove`, `removeAt`, `replace`, `replaceAll`,
  `move`, empty clear, message old/new indices, and local-before-hub order.
- Extend `CollectionMutationAction`/message factories without breaking existing
  predicates or `setAt`/splice callers.
- Implement the smallest complete serviced surface.
- Run focused tests, full TypeScript tests, typechecks, lint, build, pack dry-run,
  and audit; request review.

## Task 3: Python parity

- Add failing conformance/unit tests for named operations and message positions.
- Preserve existing list-style value-removal return/error behavior and Python
  negative indexed-operation semantics; keep move indices strict.
- Snapshot replace-all before mutation; suppress empty clear/replacement.
- Run focused/full pytest, Ruff, strict mypy, package build/Twine; review.

## Task 4: C# parity

- Add failing tests for atomic ReplaceAll, forwarded Move, same-index no-op,
  empty clear, message positions, ordering, and ownership.
- Override the required ObservableCollection hooks without duplicating local
  events or publishing before them.
- Preserve inherited public methods and direct-construction compatibility of
  `CollectionChangedMessage<T>`.
- Run focused/full Release tests, build, pack, and dotnet format; review.

## Task 5: Swift parity

- Add failing conformance tests for indexed remove, named replace, ReplaceAll,
  Move, empty behavior, positions, ordering, and ownership.
- Retain `setAt`/`removeLast`; reuse `VMCollectionIndexError` for catchable Move
  bounds and document established precondition behavior elsewhere.
- Run Release build plus XCTest when full Xcode is available; otherwise perform
  parser/typecheck evidence and leave XCTest authoritative to macOS CI; review.

## Task 6: Real Rust serviced collection

- Replace the borrowed ObservableList `COL-001..004` setup with a distinct
  `ServicedObservableCollection<T>`.
- Add a local MessageHub stream, optional external hub, complete mutation
  surface, strict move/index errors, boolean value removal, snapshot replace-all,
  and local-before-hub publication.
- Test subscriber isolation, no hub, ordering, edge cases, message indices, and
  non-ownership. Do not change ObservableList semantics.
- Run focused/full cargo tests, fmt, clippy with warnings denied, docs, and
  package verification; review.

## Task 7: Release metadata and catalog counts

- Advance spec/C#/Python/TypeScript/Swift to 3.16.0 and Rust to 0.16.0.
- Update compatibility matrix, five changelogs, package manifests/locks,
  min-spec declarations, root/spec/flavor count claims, AGENTS guidance, and
  any current-facing workflow comments.
- Verify 354/354 in all five flavors and 359 unique total IDs.
- Run version, fixture, generated-contract, tool-test, and pre-commit gates;
  review.

## Task 8: Three-surface documentation

- Extend canonical cross-language naming and collection-utility pages with the
  serviced surface, edge cases, Move payload, ownership, and choice guidance.
- Update relevant flavor pages/READMEs and examples without hand-editing
  generated site/wiki output.
- Run canonical generation/checks, docs tests, links, diagrams, strict MkDocs,
  and generated site/wiki searches; review.

## Task 9: DayDreams pilot

- Snapshot the real checkout, then use a disposable clone only.
- Pin the clone's VMx submodule to the final branch commit.
- Replace world cell eviction's index/splice ceremony with value removal while
  preserving explicit caller disposal and behavior.
- Add/adjust focused tests and run affected/full workspace gates.
- Preserve a patch/report, delete the clone, and prove the real checkout is
  byte-for-byte unchanged; review.

## Task 10: Full verification and final review

- Run all flavor Release/test/lint/type/format/package gates.
- Run tools, versions, fixtures, exact conformance, contracts, docs/site/wiki,
  diagrams, examples, pre-commit, diff hygiene, and clean-status checks.
- Request an independent review of `9731fd1..HEAD` for API compatibility,
  payload accuracy, atomicity, equality/index behavior, ordering, ownership,
  Rust type separation, docs drift, and pilot scope.
- Fix every Critical/Important finding and rerun affected/full gates.

## Task 11: Publish through Git flow

- Push and open a ready PR to `develop` with `Relates #90` and exact evidence.
- Wait for green CI and zero unresolved threads; squash-merge/delete branch.
- Open the single-ticket `develop -> main` PR with `Closes #90`; wait for the
  full second matrix and merge with a merge commit.
- Wait for all post-main workflows; verify live `.io` and wiki pages.
- Comment exact PR/commit/check/pilot evidence, set Done/Completed, clear
  priority/work order, remove only the owned worktree/local branch, and continue
  to #140.
