# ADR 0118 — Isolate container membership transactions

**Status:** Accepted (2026-07-18)
**Spec version:** clarified in 3.22.0
**Clarifies:** [ADR-0107](0107-atomic-container-ownership-transfer.md)

## 1. Context

Atomic child transfer already reserved each child, but the destination and old
parent remained open to re-entrant structural mutation while auto-construction
hooks or population callbacks ran. A candidate could remove itself, invalidate
a replacement index, or change selection before rollback. Concurrent bulk
transfers could also acquire child or container guards in opposing order.

The previous wording additionally promised exact lifecycle rollback even when
the compensating lifecycle hook itself raises. No implementation can guarantee
that state after consumer compensation code has failed.

## 2. Decision

- Add/insert/replace/population owns an exclusive destination membership
  transaction from preflight through hooks and commit or rollback. A staged old
  parent is protected for the same interval.
- Re-entrant structural mutation of either protected container is rejected
  before mutation. Reads remain available from a coherent snapshot.
- Child reservations use a deterministic cross-child acquisition strategy so
  reverse-order bulk operations cannot deadlock.
- Selection validation and assignment are one membership-gated operation;
  deferred selection revalidates membership when it executes, and competing
  current assignments serialize through the same gate so at most one retained
  child is flagged current.
- After auto-construction or another consumer hook returns, the transaction
  rechecks that its destination is still live before committing membership.
- Rollback locates the candidate by identity and never assumes its original
  replacement index still contains that candidate.
- Membership, parent, index, selection, event, and population-retry state are
  restored exactly. Required lifecycle compensation is attempted. If consumer
  lifecycle code makes compensation fail, that failure is surfaced alongside
  or in preference to the initiating failure; it is never swallowed, and the
  implementation does not falsely claim exact lifecycle restoration.

No new conformance ID or version bump is required. `COMP-040` and `GRP-011`
retain their catalog keys and gain transaction-isolation regression cases.

## 3. Consequences

- Hooks cannot make an outer mutation report success for a child now owned by a
  different parent.
- Failed replacement and population cannot corrupt an unrelated member.
- Consumers receive deterministic failure when rollback code they supplied
  prevents exact lifecycle compensation.

## 4. Rejected alternatives

- Permit re-entrant mutation and revalidate only at commit: intermediate hooks
  can already have published events or destroyed rollback state.
- Swallow compensation errors: callers would receive a false atomicity claim.
- Lock children in caller enumeration order: two reverse-order populations can
  retain one reservation each and wait forever.
