# ADR 0261 — A token pager load or refresh fails and rolls back when an auto-construct fails

- **Status:** Accepted
- **Date:** 2026-11-27
- **Spec version:** 3.30.0 (chapter 21 §6.2 and §8; chapter 12 `COL-075`)
- **Extends:** [ADR-0069](0069-token-paged-composition.md). Related:
  [ADR-0123](0123-preserve-container-causality-and-forwarding-ownership.md),
  [ADR-0200](0200-each-lifecycle-failure-reaches-one-reporting-route.md),
  [ADR-0224](0224-failed-population-disposes-unowned-candidates.md), #1907,
  #1894.

## 1. Context

With auto-construction on (ADR-0069, chapter 21 §6.2), a
`TokenPagedComposition` constructs the items of a fetched page one by one before
it publishes the `Reset` event. Chapter 21 §6.2 defined the failure of a fetch
and of an equality hook. It did not say what happens when an item's construct
hook fails.

Reproduced at develop with a page of three component VMs whose second construct
hook throws. C#, Python, TypeScript and Swift fail the load, but they leave the
first item `Constructed`, outside `Items`, with no owner that destructs it. Rust
discards the construct result, commits the page and publishes `Reset`, so a
`Destructed` item enters `Items` and the caller sees no error (#1907).

Containers already have a rule for this case. ADR-0123 restores each child that
a failed add, insert, replacement or population auto-constructed to its original
`Destructed` state, and it surfaces a failure of that compensation as the
rollback failure. ADR-0224 disposes the unowned candidates that a failed
population built, and ADR-0200 requires each lifecycle failure to reach one
reporting route.

## 2. Decision

Decided by the owner, who chose the candidate that applies the ADR-0123 rule to
the pager.

1. A construct failure during a load or a refresh fails that operation like a
   fetch failure. `Items`, `CurrentToken` and `HasMore` stay unchanged, and the
   operation publishes no `Reset` and no property notification.
1. The operation destructs each item that it constructed back to `Destructed`,
   in reverse order. An item that was `Constructed` before the operation keeps
   its status. An item that the operation did not construct is not disposed,
   including an item that the operation never reached.
1. When a compensating `destruct()` also fails, the operation fails with the
   rollback failure. It carries both failures: the construct failure that started
   the rollback, and the first compensation failure. Each flavor uses its
   container rollback form (ADR-0123): a C# `AggregateException` of both, a
   Python `raise` of the compensation failure `from` the original, a TypeScript
   and Swift `ContainerRollbackError`, and a Rust `VmxError::ContainerRollback`.
   The operation reports that one failure to its command's error route (ADR-0200).
1. A stale or disposed operation keeps its existing rules. It still stops at
   once, constructs nothing more and commits nothing. This rule does not compensate
   the items that a superseded operation had already constructed.
1. The public signatures of the load and refresh operations do not change. In
   Rust, the `load_more_command` and `refresh_command` tasks return the error
   with `?`. `execute()` reports it on `error_stream()`, and `execute_async()`
   returns it in the joined result. `load_next()` and `refresh()` keep their
   signatures and still discard the joined result, until #1894 decides the route.

## 3. Consequences

- On an ordinary construct failure, every item that the failed load or refresh
  constructed is destructed, so none stays `Constructed` outside `Items`. When a
  compensating destruct also fails, that failure is the rollback failure (§2 rule 3):
  the item whose destruct failed is left as that failure leaves it, and the other
  constructed items are still destructed. Items of a superseded operation are out
  of scope (#1627).
- A successful load or refresh still constructs every item before the `Reset`
  (`COL-030`).
- A refresh that keeps the accumulator constructs nothing, so it cannot fail this
  way.
- The rule is normative and adds the conformance ID `COL-075`. Every
  catalog-complete flavor covers it with a test of the same scenario.
- Rust's `load_next()` and `refresh()` still discard a construct failure until
  #1894 decides their route. The command routes already report it.

## 4. Rejected alternatives

- **Dispose each unowned item of the failed page (ADR-0224).** A fetched item may
  be held by the caller or by another container. Disposing an item that the
  operation did not construct would end a life that the pager never started. The
  owner chose the narrower rule.
- **Leave constructed items constructed and report only the failure.** That is
  the behavior of four flavors before this ADR and of Rust's committed page. It
  leaves live view-models that no list holds, against the exact restoration that
  ADR-0123 requires of containers.
- **Report the last compensation failure.** ADR-0123 keeps the failure that
  started the rollback first, and the other flavors already report it that way.
