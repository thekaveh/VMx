# ADR 0122 — Defer container disposal through membership transactions

**Status:** Accepted (2026-07-18)
**Spec version:** clarified in 3.22.0
**Extends:** [ADR-0118](0118-isolate-container-membership-transactions.md)

## 1. Context

Atomic ownership transfer temporarily removes a child from its old parent while
the destination runs attachment and auto-construction hooks. A hook can request
disposal of that old parent before the transfer commits or rolls back.

Disposing immediately takes a snapshot of the staged, childless old parent. A
later rollback then either restores a live child into a disposed parent or
orphans it to avoid that invalid state. Both outcomes violate the transaction's
exact-state guarantee. Disposal racing from another thread has the same problem
if it can snapshot the old parent during the staged interval.

## 2. Decision

- A container disposal request made by the thread that owns an active
  membership transaction becomes a terminal deferred request. It executes only
  after that transaction commits or rolls back.
- A disposal request from another thread waits until the active membership
  transaction has finished before taking its child snapshot.
- Once a deferred request exists, further structural admission fails as a
  disposal-in-progress operation. The active transaction may only finish its
  existing commit or rollback path.
- After a successful transfer, old-parent disposal excludes the child that has
  committed to the destination. After a failed transfer, rollback first restores
  the old membership and parent metadata, then old-parent disposal includes the
  restored child in its normal depth-first cascade.
- Destination disposal requested from an attachment hook continues to reject
  that attachment: pending terminal disposal is not a live admission state.
- `COMP-040` covers both the successful-commit and failed-rollback ordering. No
  new conformance ID or public API is introduced.

## 3. Consequences

- A child cannot be restored into an already-disposed old parent.
- Disposal snapshots observe only committed container membership.
- The five flavors use their idiomatic synchronization facilities, while the
  language-neutral ordering and terminal state are identical.
- This is a correctness clarification within the existing v3.22.0 ownership and
  disposal contracts; package versions and fixtures do not change.

## 4. Rejected alternatives

- Dispose the staged old-parent snapshot immediately: rollback cannot then
  satisfy exact state or lifecycle ownership.
- Cancel disposal when transfer fails: terminal disposal requests must not be
  silently discarded.
- Reject disposal as re-entrant structural mutation: disposal is a public,
  terminal lifecycle request and must complete once the protected transaction
  reaches a stable boundary.
