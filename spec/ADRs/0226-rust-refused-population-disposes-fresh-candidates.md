# ADR 0226 — Rust applies the candidate cleanup, and AGG-008 covers it in all five flavors

- **Status:** Accepted
- **Date:** 2026-11-09
- **Spec version:** 3.30.0 (chapter 08 §2 and §8, `AGG-008`)
- **Amends:** [ADR-0224](0224-failed-population-disposes-unowned-candidates.md)
  Decision rules 6 and 7. Related:
  [ADR-0125](0125-specify-aggregate-reconstruction-transactions.md),
  [ADR-0107](0107-atomic-container-ownership-transfer.md), #1324.

## 1. Context

ADR-0224 makes a population that fails before its commit dispose the
candidates that it built and that nobody owns. C#, Python, TypeScript and Swift
apply the rule. ADR-0224 rule 6 recorded that Rust did not apply it yet, and
rule 7 deferred the conformance ID until Rust did.

Rust slot factories return values and cannot fail. Only the ownership
preflight can refuse a Rust population. In `AggregateVm1` to `AggregateVm6`,
`construct()` returned the preflight error before it disposed any candidate.
`reconstruct()` runs the same `construct()`. A lazy slot calls its factory on
each construct, so it builds a fresh candidate. An eager slot keeps the value
that the aggregate received at creation.

## 2. Decision

Decided under the owner's 2026-11-07 delegation: Rust applies the ADR-0224
rule, and the rule gets a conformance ID.

1. A refused Rust `construct()` or `reconstruct()` disposes each fresh
   lazy-slot candidate that nobody owns. The preflight error propagates.
1. The Rust cleanup skips a candidate that has a parent, a candidate that
   another ownership claim holds, and a candidate that is an owner on the
   aggregate's ancestor chain. It disposes each identity once.
1. The refused population releases its own ownership claims before the
   cleanup, so the claim check sees only other transactions.
1. An eager Rust slot keeps its existing value. The cleanup never disposes it.
1. The cleanup is best-effort. A candidate disposal failure does not replace
   the preflight error.
1. `AGG-008` covers the rule in all five flavors. A refused `construct()`
   disposes the fresh candidate and keeps the owned candidate's status and
   parent. A refused `reconstruct()` also keeps the old slots and parent
   links. The test uses an owned candidate, because only the preflight can
   refuse a population in every flavor.

This replaces ADR-0224 rules 6 and 7. The other ADR-0224 rules stay.

## 3. Consequences

- A refused population leaks no live candidate in any flavor.
- The Rust parity ledger closes §12.13.
- C#, Python and TypeScript keep their unit tests for the factory and
  projector failures that Swift and Rust cannot produce.

## 4. Rejected alternatives

- **Dispose the eager slot value too.** The aggregate received that value at
  creation and keeps it for the aggregate's lifetime. It is not a fresh
  candidate of the refused population.
- **Hold the candidate's claim during its disposal.** Disposal runs user
  hooks, and a hook can start another ownership transaction. A short check,
  as in Swift, keeps the cleanup free of a new lock order.
- **Cover the factory failure in AGG-008.** Swift and Rust factories cannot
  fail, so a test of that branch cannot run in all five flavors.
