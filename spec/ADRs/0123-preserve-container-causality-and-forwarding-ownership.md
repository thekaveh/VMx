# ADR 0123 — Preserve container causality and forwarding ownership

**Status:** Accepted (2026-07-18)
**Spec version:** clarified in 3.22.0
**Extends:** [ADR-0118](0118-isolate-container-membership-transactions.md), [ADR-0122](0122-defer-container-disposal-through-membership-transactions.md)

## 1. Context

The container transaction contract still left three observable edges ambiguous:

- a destination could auto-construct a previously destructed child and then
  reject admission because a construction hook disposed the destination;
- a current-changed callback could observe the destination already disposed,
  and opposing callbacks on two composites could acquire membership guards in
  reverse order;
- a forwarding component satisfied the public component contract but some
  flavors did not expose the internal ownership surface required to use the
  decorator as a composite or group child.

Late deferred-disposal failures also risked replacing the attachment failure
that caused rollback, obscuring the causal error.

## 2. Decision

- Failed add, insert, replacement, and population restore a child that was
  auto-constructed by that attempt to its original destructed state. A failure
  of that compensation is surfaced as the rollback failure.
- The first operation failure remains the reported failure. Deferred disposal
  still runs, but its later failure cannot replace an earlier attachment or
  publication failure.
- Current state and notifications commit before `OnCurrentChanged` runs.
  Same-container disposal requested by the callback remains deferred until the
  callback returns and the membership transaction closes. Cross-composite
  current callbacks use a shared re-entrant coordination lane and never invoke
  consumer callbacks while holding a per-container membership guard.
- A `ForwardingComponentVM` is a valid homogeneous container child. Ownership,
  lifecycle, selection flags, and built-in selection commands remain
  transparent to the wrapped component while the collection retains the
  decorator instance supplied by the caller.
- Existing `COMP-026`, `COMP-040`, and `FWD-001` scenarios cover these clarified
  edges; no new public API or conformance identifier is introduced.

## 3. Consequences

- Failed attachment no longer leaks a constructed orphan.
- Callbacks observe committed current state before any deferred terminal
  cascade, and opposing callback graphs make progress.
- Forwarding decorators compose with composites and groups in all five flavors.
- This is a correctness clarification within the existing 3.22.0 contracts;
  package versions and fixtures do not change.

## 4. Rejected alternatives

- Leave auto-constructed children constructed after rollback: this violates
  exact pre-call restoration.
- Report the last cleanup failure: this hides the operation that initiated
  rollback and makes equivalent flavors disagree on causality.
- Exclude forwarding decorators from child collections: their advertised
  component contract and transparent-decorator use case provide no such limit.
