# ADR 0179 — A foreign dispose publishes `Disposed` before the children

- **Status:** Accepted
- **Date:** 2026-11-08
- **Spec version:** 3.30.0 (chapter 02 §7 and §7.1; chapter 06 §5; chapter 07
  §2; chapter 08 §5)
- **Clarifies:** [ADR-0126](0126-coordinate-admitted-hooks-with-disposal.md)
  and [ADR-0162](0162-supported-child-transition-helper.md) §2.2

## 1. Context

An admitted hook is a construct or destruct hook that the lifecycle guard has
started and that has not returned (chapter 02 §2.4). A *foreign dispose* is a
`dispose()` call on one thread while an admitted hook of the same view-model
runs on another thread.

ADR-0126 and chapter 02 §2.4 say that a foreign dispose publishes `Disposed` and
then waits for the hook. Three PRs moved container and aggregate cascades behind
that wait, so they run after `Disposed`.
[PR #888](https://github.com/thekaveh/VMx/pull/888) moved the C# and Python
containers. [PR #1120](https://github.com/thekaveh/VMx/pull/1120) (issue #1062)
moved the Rust and Swift containers and the Rust aggregates.
[PR #1122](https://github.com/thekaveh/VMx/pull/1122) (issue #1063) moved the
Python and Swift aggregates. None of them changed the C# `AggregateVM1` to
`AggregateVM6`. [PR #1216](https://github.com/thekaveh/VMx/pull/1216) (ADR-0175)
moved those later, as the list below records. The guide pages state this order,
but chapters 02, 06, 07 and 08 did not (issue #1165). They said that a container
disposes its children or slots, and a leaf its members, before it publishes
`Disposed`, with no exception. ADR-0162 §2.2 says the same for members and
applies the admitted-hook rule without the resulting order.

The reproduction in issue #1165 shows both orders in Python, Swift and Rust.
Inspection shows the same two branches in C#. With no admitted hook on another
thread, `c1` and `c2` publish `Disposed` before the container. During a foreign
dispose, the container publishes `Disposed` first, and its children stay
`Destructed` until the hook returns.

Issue #1165 named two known gaps that kept the children-first order during a
foreign dispose. Both are closed on `develop`:

- **C# `AggregateVM1` to `AggregateVM6` (issue #1166).** They disposed their
  slots before `base.Dispose()` until
  [PR #1216](https://github.com/thekaveh/VMx/pull/1216) (ADR-0175) moved them
  to the base cascade at the hook boundary (`DisposeWithChildrenFrom`). The
  same PR removed open decision §2.11 from
  `docs/maintenance/2026-10-18-open-cross-flavor-decisions.md`.
- **Rust leaf `ComponentVm` (issue #1164).** It disposed its `own_member`
  members before the core disposal and its hook wait. PR #1216 moved the
  members into `dispose_with_cascade_then`. The same PR removed §12.13 from
  `docs/maintenance/2026-07-16-rust-capability-parity.md`.

## 2. Decision

Decided under the owner's 2026-11-07 delegation: the spec states the order
that all five flavors already follow. No behavior changes.

1. **No hook admitted on another thread.** `dispose()` disposes the children,
   then the registered members, inline. Each child and member reaches
   `Disposed` before the view-model publishes `Disposed` (`LIFE-013`,
   `LIFE-018`). The inline cascade rules of chapter 02 §7.2 (ADR-0175) apply.
1. **Foreign dispose.** The view-model publishes `Disposed` first. It then
   waits for the admitted hook, or defers its terminal cleanup to the hook's
   completion when the wait would close a cycle (chapter 02 §2.4, ADR-0172).
   After that, it disposes its children and then its members. This happens
   before its subclass dispose hook runs (`LIFE-015`).
1. **Same rule for every container.** Rules 1 and 2 cover `CompositeVM`,
   `GroupVM`, the `ComponentN` slots of `AggregateVM1` to `AggregateVM6`, and a
   leaf's registered members. Chapter 06 §5, chapter 07 §2 and chapter 08 §5
   refer to chapter 02 §7.
1. **Unchanged steps.** In both orders, the subclass dispose hook, the owned
   registrations, stream completion and command teardown run after the
   cascade. A dispose on the hook's own thread is not foreign and follows
   rule 1.

TypeScript runs its hooks on one thread, so a foreign dispose cannot occur
there. Rule 1 always applies in TypeScript.

Decided under the owner's 2026-11-07 delegation: the spec keeps both orders
rather than one. Children first in the foreign case would clean up the
children while the parent's hook still runs, which `LIFE-015` forbids (#888).
`Disposed` first in every case would change `LIFE-013` and `LIFE-018` in five
flavors.

## 3. Conformance

No conformance ID changes. `LIFE-013`, `LIFE-018`, `COMP-046` and `GRP-014`
dispose with no hook admitted, so rule 1 covers them. `LIFE-015` covers the
wait of rule 2. The catalog stays at 449 library IDs (454 in total).

## 4. Consequences

- Chapter 02 §7 defines a foreign dispose and states both orders. Chapter 02
  §7.1 states them for registered members.
- Chapter 06 §5, chapter 07 §2 and chapter 08 §5 limit their children-first
  sentence to a dispose that is not foreign.
- The disposal-contract and component-family guides use the same two orders.
- No flavor code changes. No known gap remains.
