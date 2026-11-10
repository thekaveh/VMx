# ADR 0224 — A population that fails before its commit disposes its unowned candidates

- **Status:** Accepted
- **Date:** 2026-11-09
- **Spec version:** 3.30.0 (chapter 08 §2 and §4, chapter 06 §6 and §9)
- **Related:** [ADR-0125](0125-specify-aggregate-reconstruction-transactions.md),
  [ADR-0107](0107-atomic-container-ownership-transfer.md),
  [ADR-0084](0084-cross-cutting-disposal-invariant.md), #1324, #1519.

## 1. Context

A container population builds its candidates before it commits them. An
aggregate calls every slot factory and then runs the ownership preflight. A
`CompositeVMOf` projects every model to a child and then attaches the
population. Chapter 08 §2 and §4 said that a failed factory or preflight keeps
the old slots and parent links. They did not say what happens to the
candidates that the failed population built. Chapter 08 §4 disposed candidates
only on terminal abort.

C#, Python and TypeScript dropped those candidates without disposing them
(#1324). After a second factory threw, the first candidate stayed
`Destructed`. After a projector threw on the second model, the first child
stayed `Destructed`. A `FilteredCompositeVM` subscribed to its source before
its first recompute. When the predicate threw there, the subscription stayed
active, and later source changes ran the predicate of an unreachable filter.
`ScoredFilteredCompositeVM` has the same constructor and runs its scorer in the
first recompute.

A candidate can belong to someone else. A factory can return a component that
another container owns, or the aggregate's own owner. The cleanup must not
dispose such a component.

PR #1519 fixed C#, Python and TypeScript and the Swift preflight. Swift
factories, projectors and filter predicates cannot throw, so only the
preflight part applies to Swift. Rust factories return values, and only a lazy
slot produces a fresh candidate. Rust does not apply the cleanup yet.

## 2. Decision

Decided under the owner's 2026-11-07 delegation: the rule that C#, Python,
TypeScript and Swift implement becomes the spec rule.

1. A population fails before its commit when a slot factory or a projector
   throws, or when the reservation or ownership preflight refuses it. This
   covers aggregate `construct()` and `reconstruct()` and the `CompositeVMOf`
   projection.
1. The failed population disposes each candidate that it built and that nobody
   owns. It skips a candidate that has a parent, a candidate that another
   ownership transaction holds, and a candidate that is an owner on the
   container's ancestor chain. It disposes each canonical ownership identity
   once.
1. The cleanup is best-effort. A disposal failure does not replace the
   population's failure. The original failure propagates.
1. The old slots and parent links stay unchanged, as chapter 08 §2 and §4 and
   `AGG-007` already require. A `CompositeVMOf` whose projector throws keeps no
   children.
1. A `FilteredCompositeVM` or `ScoredFilteredCompositeVM` whose first
   recompute throws detaches from its source before the failure propagates. A
   later source change runs neither the predicate nor the scorer. In C#, a
   null scorer has the same result.
1. Swift applies rules 2 and 3 to a refused aggregate preflight. Rust does not
   yet dispose the fresh lazy-slot candidates of a refused preflight. An eager
   Rust slot keeps its existing value. The Rust parity ledger (§12.13) records
   the gap.
1. The rule is normative. This ADR adds no conformance ID. A catalog ID needs
   a test in all five flavors, and Rust does not apply the rule yet. The C#,
   Python and TypeScript unit tests from #1519 cover it until the Rust cleanup
   lands with its ID.

## 3. Consequences

- A failed population leaks no live candidate in C#, Python, TypeScript or
  Swift.
- A component that a factory borrows from another owner keeps its status and
  its parent.
- A failed filtered view leaves no subscription on its source.
- Chapter 08 and chapter 06 state the rule, and the Rust gap is recorded.

## 4. Rejected alternatives

- **Leave the candidates to the caller.** The caller never receives them,
  because the population throws before it returns.
- **Dispose every candidate.** A factory can return a component that another
  container owns, or the aggregate's own owner. Disposing it would break that
  owner.
- **Add a conformance ID now.** Rust would fail the test until its cleanup
  lands. The catalog-complete rule requires a passing test in every flavor.
