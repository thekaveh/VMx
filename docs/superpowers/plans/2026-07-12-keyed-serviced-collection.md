# Keyed Serviced Collection Implementation Plan

Issue: #140\
Branch: `codex/issue-140-keyed-serviced-collection`\
Base: `01b17105cbc50ba6bd23039e5558a4ee0e0b123e`

Use subagent-driven development with a fresh implementer and read-only reviewer
for each task. Follow red-green TDD and commit each reviewed task.

## Task 1: Specify the contract

- Add ADR-0097 and its registry row.
- Extend chapter 21 with the distinct type, full common surface, captured-key
  rule, duplicate/atomicity/no-op behavior, complexity boundary, delivery,
  transactions, ownership, and `COL-056..064` mapping.
- Add nine real catalog cases (`COL-056..064`) and chapter references; update ADR-0009 only for
  true flavor divergences.
- Review for feasibility, additive compatibility, and unambiguous key/index
  semantics.

## Task 2: TypeScript reference implementation

- Write failing unit/conformance tests first, including projection-count
  evidence, duplicate and exception atomicity, index synchronization, message
  traces, reentrancy, and transactional-hub ordering.
- Add the keyed type and public export while preserving the unkeyed type.
- Run focused/full tests, source/test typechecks, lint, build, pack, and audit;
  request independent review.

## Task 3: Python parity

- Add failing behavioral markers for all nine IDs and focused unit coverage.
- Preserve Python sequence indexing/equality idioms while keeping the captured
  key index atomic across insert, slice, replacement, removal, move, and reset.
- Run focused/full pytest, Ruff, format, strict mypy, build, and Twine checks;
  request review.

## Task 4: C# parity

- Add failing conformance/unit coverage for the full contract.
- Reuse `ObservableCollection`/serviced local-event compatibility without ever
  exposing observers to a stale key index; preserve reentrancy behavior.
- Run locked restore, Release build/tests, format, pack, and compatibility
  checks; request review.

## Task 5: Swift parity

- Add failing conformance/unit coverage, including Hashable key constraints,
  duplicate failures, catchable move bounds, and publisher/hub ordering.
- Preserve the existing Swift serviced aliases and precondition divergences.
- Run Release build and XCTest on full Xcode where available; otherwise record
  parser/typecheck evidence and leave XCTest authoritative to macOS CI; review.

## Task 6: Rust parity

- Add failing conformance/unit coverage around one mutex-protected ordered
  store/index state, local/external delivery coordination, reentrancy, and
  concurrent mutation.
- Add the keyed type without changing `ObservableList`, unkeyed serviced
  semantics, or Rust's non-generic message payload.
- Run fmt, clippy with warnings denied, full tests, rustdoc, and package checks;
  request review.

## Task 7: Release metadata and catalog counts

- Advance spec/C#/Python/TypeScript/Swift to 3.17.0 and Rust to 0.17.0.
- Update manifests/locks, min-spec declarations, compatibility matrix, all five
  changelogs/READMEs, root/spec counts, release ledgers, and workflow comments.
- Verify 363/363 library IDs in all five flavors and 368 unique total IDs.
- Run version, fixture, generated-contract, tool-test, pre-commit, and drift
  checks; request review.

## Task 8: Three-surface documentation

- Update canonical collection, naming, service/message, and five flavor pages
  with selection guidance, API names, complexity, keys, messages, transactions,
  and ownership.
- Regenerate and verify in-repo docs, strict MkDocs `.io`, and native wiki
  exports; update examples/manifests/diagrams only where affected.
- Run docs tests, links, generated searches, and drift checks; request review.

## Task 9: DayDreams pilot

- Fingerprint the real checkout and use disposable clones only.
- Pin VMx to the final reviewed branch commit; replace all three `WorldVM`
  snapshot scans with keyed operations and keep explicit disposal.
- Strengthen keyed lookup and renderer event-trace tests; run focused
  viewmodel/renderer tests, typechecks, and the full workspace.
- Preserve patch/report evidence, delete clones, and prove the real checkout is
  unchanged; request review.

## Task 10: Full verification and final review

- Run every applicable language Release/test/lint/type/format/package gate.
- Run tools, versions, fixtures, exact conformance, contracts, docs/site/wiki,
  examples, pre-commit, diff hygiene, and clean-status checks.
- Request independent full-range review for compatibility, complexity claims,
  key/index atomicity, messages, reentrancy, ownership, docs, and pilot scope.
- Fix every Critical/Important finding and rerun affected/full gates.

## Task 11: Publish through Git flow

- Push and open a ready PR to `develop` with `Relates #140`; wait for green CI
  and zero unresolved threads, squash-merge, and delete the remote branch.
- Open the single-ticket `develop -> main` PR with `Closes #140`; wait for the
  full second matrix and merge with a merge commit.
- Wait for all post-main workflows, verify live `.io` and wiki content, comment
  exact evidence, set Done/Completed, clear queue fields, remove only the owned
  worktree/local branch, and continue to #136.
