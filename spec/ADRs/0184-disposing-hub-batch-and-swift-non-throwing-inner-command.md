# ADR 0184 — A `Batch` on a disposing hub opens no scope; a Swift inner command cannot throw

- **Status:** Accepted
- **Date:** 2026-11-09
- **Spec version:** 3.30.0 (chapter 03 §3.3 and §4.2; chapter 04 §8.3.1 and
  §8.4; chapter 20 §5.4; `CMDD-010`, `CMDD-013`)
- **Clarifies:** [ADR-0172](0172-one-wait-for-graph-per-flavor.md) §2.1 rule 4 and
  [ADR-0062](0062-swift-forms-commands-hub-divergences.md) §2.2

## 1. Context

This ADR records two clarifications. In each, the spec stated a rule for a
path that the flavors do not take. No flavor changes behavior.

### 1.1 A `Batch` on a disposing hub (#1428)

Chapter 03 §4.2 rule 3 and ADR-0172 §2.1 rule 4 say that a borrower's own `Batch`
nests another borrowed scope. They give no exception for a disposed hub.
Chapter 03 §3.3 item 6 says that sends on a disposed hub are no-ops. It does
not say what a `Batch` on a disposed hub does.

[PR #1226](https://github.com/thekaveh/VMx/pull/1226) (issues #1224 and #1230)
made the four threaded hubs follow one rule. After a disposal is requested, a
`Batch` runs its body with no scope:

- C# opens a scope only inside a loop that stops at `_disposed` or
  `_disposeRequested` (`MessageHub.Batch`).
- Python records a scope only while `_disposed` is false, and `dispose()` sets
  `_disposed` also when it only records terminal intent.
- Swift opens a borrowed scope only while `disposed` is false, and `dispose()`
  sets `disposed` also when it only records terminal intent.
- Rust runs the closure with no scope when the hub is disposed or its disposal
  is requested.

A borrower's `Batch` therefore opens no new borrowed scope once a disposal is
requested. TypeScript runs on one thread. Its `batch` counts nesting depth on a
disposed hub too, but its sends are no-ops and no call waits.

### 1.2 A throwing inner command in Swift (#1315)

`CMDD-010` requires that a throwing `inner.Execute()` reaches the
confirmation decorator's `errors` channel, and it claims full parity in Swift.
`CMDD-013` requires that a decorator runs its post-action once when the inner
command throws, with no flavor exception. Swift `Command.execute()` has no
`throws`, so a Swift synchronous inner command cannot throw. Neither clause can
occur in Swift. The Swift tests recorded the gap only in source comments.

ADR-0062 §2.2 says that a failure "in principle, from a throwing inner
command" routes to the Swift `errors` channel. A synchronous inner command
cannot throw in Swift. An asynchronous inner reports its own failures on its
own channel (chapter 04 §8.3.2), so it does not reach the decorator's `errors`
either.

Chapter 20 §5.4 makes the deny snapshotter a preparation callback. Its Swift
note names only validators and `equals` as non-throwing. The §5.3 Swift note
and the Swift `FORM-035` and `FORM-036` tests already treat the snapshotter as
non-throwing.

## 2. Decision

Decided under the owner's 2026-11-07 delegation: the spec states what the
flavors already do.

1. **A `Batch` on a disposing hub.** Chapter 03 §3.3 item 6 says that a
   `Batch` on a disposed hub, or on a hub whose disposal is requested, runs its
   body. The body holds no scope that another call waits for. Chapter 03 §4.2
   rule 3 says that a borrower's `Batch` nests another borrowed scope only while
   no disposal is requested. After a disposal is requested, the body runs with
   no new scope. The statement covers the observable result, not the internal
   nesting depth, so TypeScript also conforms.
1. **A Swift inner command cannot throw.** Chapter 04 §8.3.1 says that the
   throwing-inner rule does not apply to Swift, and §8.4 says that in Swift the
   inner command adds no throwing exit path. `CMDD-010` and `CMDD-013` exempt
   Swift from their throwing-inner clauses only. Their other clauses stay
   required for Swift. The Swift `Command` protocol keeps its non-throwing
   `execute()`. This ADR corrects ADR-0062 §2.2: in Swift, only a throwing
   `confirm` reaches the decorator's `errors` channel.
1. **The Swift deny snapshotter cannot throw.** The chapter 20 §5.4 Swift note
   names the snapshotter together with validators and `equals`.

## 3. Consequences

- No flavor changes behavior, and no conformance ID is added or removed.
- A reader of chapter 03 §4.2 no longer expects a nested borrowed scope that
  no flavor opens.
- The Swift `CMDD-010` and `CMDD-013` test comments cite this ADR. Swift keeps
  testing the throwing-`confirm` clause of `CMDD-010` and the disposal clauses
  of `CMDD-013`.
- The open cross-flavor decisions ledger closes its §3 Swift items.

## 4. Rejected alternatives

- **Make Swift `Command.execute()` throw.** A `throws` on `execute()` would
  break every Swift `Command` conformer. A documented exemption is the smaller
  change, as for `FORM-035` and `FORM-036`.
- **Make a borrower's `Batch` on a disposing hub open a scope.** A scope that
  outlives a requested disposal would hold the disposal open, which chapter 03
  §4.2 rule 3 already forbids for a drainer.
