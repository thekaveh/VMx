# ADR 0173 — Selection commits without a membership transaction

- **Status:** Accepted (extended by 0188 and 0189)
- **Date:** 2026-11-07
- **Spec version:** 3.30.0 (clarification of chapter 06 §3, §3.1, §3.2, §4.2,
  §4.3 and §5)
- **Extends:** [ADR-0165](0165-initial-current-uses-committed-membership.md)

## 1. Context

ADR-0165 made the construct walk's `Current(selector)` assignment a commit
with no membership transaction. The other paths that change `Current` kept
per-flavor rules, and several of them break the spec:

- **Another thread's transaction (#1145).** In C# and Python, the public
  `Current` setter, `SelectComponent`, `DeselectComponent` and the child
  `Select` and `Deselect` paths open a membership transaction. They raise
  while another thread holds one, also with `AsyncSelection(true)`. A
  construct hook that selects can therefore roll its composite back. Swift
  waits for the other transaction, which can deadlock (ADR-0165 §1). Rust
  returns `OwnershipTransactionInProgress`.
- **Unadmitted children (#1146, #1148).** On the add owner's thread, the C#
  and Python setter reuses the add's transaction and commits a child that the
  add has attached but not admitted. A failed add then leaves `Current` on a
  child that is not a member. A staged population has the same defect, also
  in the walk's assignment.
- **The same thread's transaction (ledger §2.9).** C# and Python let a
  selection reuse the composite's own transaction, both during the add's
  hooks and during its `CollectionChanged` publication. TypeScript, Swift and
  Rust reject both.
- **The destruct clear (#1144, #1201).** `destruct()` clears `Current`
  first (§5, `COMP-005`). C# and Python run the clear through the strict
  path, so it throws while another thread holds a transaction or while
  disposal is deferred, and destruct rolls back. TypeScript throws when
  destruct runs inside the composite's own add. Swift skips the clear without
  an error and reaches `Destructed` with `Current` set. Rust clears with no
  publication lease, so a disposal from `OnCurrentChanged(null)` runs inside
  the callback.
- **The walk's assignment (#1149, #1150, #1151).** TypeScript, Swift and Rust
  do not follow ADR-0165 yet (ADR-0165 §3).

The owner decided #1145 on 2026-11-07: option 3, commit with no transaction.
A target that an add attached but has not admitted gets the existing
non-member error. A call on a composite with a requested disposal is refused.
Publications from two threads can interleave. The `AsyncSelection(true)`
setter is covered too. The owner delegated every other design question to
this principle: all flavors follow the same rules as far as possible, and the
simplest, most common-sense rule wins.

## 2. Decision

The **selection paths** are the public `Current` setter, `SelectComponent`,
`DeselectComponent`, the child `Select` and `Deselect` paths, the
`AsyncSelection(true)` setter and its delivery, the construct walk's
assignment, the destruct clear, and the clear that a detach commits. The
**selection calls** are the setter, synchronous or asynchronous,
`SelectComponent`, `DeselectComponent` and the child `Select` and `Deselect`
paths. Eight rules apply in every flavor.

1. **No transaction.** No selection path opens, joins or waits for a
   membership transaction, on any thread. Each path validates and commits
   `Current` and both `IsCurrent` flags under the coordination lane and the
   membership gate (§4.2). It publishes after it releases both. It waits only
   for those two locks, which no consumer code holds. Another thread's open
   transaction neither fails nor delays it.
1. **Committed membership.** A child that an `Add`, `Insert`, index
   replacement or population has attached but not yet admitted is not a
   member for selection, on any thread. Population covers factory, bulk and
   subclass calls (C# `AttachPopulation`, TypeScript `_attachPopulation`). The
   setter raises the existing non-member error, and `can_select_component`
   returns false. The child becomes selectable when the add admits it: after
   the last viability recheck, before `CollectionChanged` publishes. When the
   add moves the child from another parent, it admits the child after that
   parent's detach commit. Every rollback path also clears the marker.
1. **Disposal.** From the moment disposal is requested or deferred until
   `Disposed`, a non-null selection is refused. A null clear is never refused
   because of disposal. The null clears are `Current = null`,
   `DeselectComponent`, the child `Deselect`, the destruct clear and the
   detach clear. After `Disposed`, each flavor keeps its documented
   post-dispose behavior (chapter 01 §4).
1. **The caller's own uncommitted transaction.** A transaction is
   uncommitted while its rollback could still undo a staged change: a child
   attached but not admitted, a staged population, or a child detached for a
   transfer whose commit has not run. On the thread that owns such a
   transaction of the composite, every selection call on that composite
   fails before it changes anything. This also covers a null clear. The call
   raises the existing "membership transaction in progress" error. The walk's
   assignment in that window is a silent no-op. From the commit on, including
   the transaction's `CollectionChanged` publication, the owner thread's
   selection commits under rule 1 like any other.
1. **Publication lease.** Every selection path that changes `Current` holds
   the current-publication lease while it publishes `Current` and `IsCurrent`
   and runs `OnCurrentChanged`. Leases nest, so a selection from those
   callbacks commits under rule 1. A disposal requested on a thread that
   holds a lease returns at once and is deferred. A disposal requested on
   another thread first follows §4.2 for a foreign membership transaction. If
   a lease is still active after that, the disposal is deferred. A deferred
   disposal starts when the last lease ends and no membership transaction is
   open. The deferral stays set until the disposal starts, so no transaction
   and no non-null selection is admitted in between.
1. **Detach clear.** A transaction that detached the current child clears
   `Current` only while that child is still current (ADR-0165 rule 5). This
   covers remove, `RemoveAt`, `Clear`, replacement and transfer out.
1. **Asynchronous selection.** With `AsyncSelection(true)`, the setter
   validates at call time under rules 2, 3 and 4 and raises as the
   synchronous setter does. Another thread's transaction never fails it. It
   then schedules the change on `IDispatcher.Foreground` and returns. The
   delivery commits under rules 1 and 5 and revalidates membership and rules
   2, 3 and 4. A delivery that is no longer valid is a silent no-op. The
   walk's assignment and the destruct clear stay synchronous with
   `AsyncSelection(true)`.
1. **Destruct clear.** `destruct()`, including the destruct phase of
   `reconstruct()`, clears a non-null `Current` under rules 1 and 5. The
   clear is not a selection call. Rules 3 and 4 never refuse it, and it never
   raises, waits or is skipped. `COMP-005` therefore holds while another
   thread holds a transaction, inside the composite's own transaction, and
   while disposal is deferred. A rollback does not restore a `Current` that
   the destruct cleared.

The construct walk's assignment keeps ADR-0165 rules 1 to 5 in all five
flavors, with the rule 4 window above. Chapter 06 lists no open gap for it.

Each surface reports a refusal through the channel it already uses for that
case. No flavor adds an error type. Rule 2 uses the non-member error. Rule 3
uses the disposal error that an admission raises while the container is
disposing, such as C# `ObjectDisposedException` and Python `RuntimeError`.
Rule 4 uses the "membership transaction in progress" error. The Swift
`current` property setter cannot throw, so it keeps its trap (ADR-0009), and
`setCurrent(_:)` is its catchable form; Swift throws
`CompositeMembershipError` for every refusal. Swift `selectChild` and
`deselectChild` keep their silent no-op. Rust returns `VmxError::NonChild`,
`VmxError::Disposed` and `VmxError::OwnershipTransactionInProgress`.
`SelectComponent` raises its existing predicate error for every refusal.

### 2.1. Decided under the owner's 2026-11-07 delegation

- **Rule 1 on the owner thread too.** The owner decided the non-owner case.
  One rule for every thread is simpler than two, so a selection never reuses
  a transaction either. Chapter 06 §4.2 drops "MAY reuse that transaction".
- **Selection from the composite's own structural transaction (ledger
  §2.9).** Rule 4 splits the transaction at its commit. Before the commit,
  the owner thread's selection is refused, as TypeScript, Swift and Rust do
  today. From the commit on, it succeeds, as in C# and Python, so a
  `CollectionChanged` subscriber can select the child that was just added.
  TypeScript, Swift and Rust change for the publication phase. C# and Python
  change for the hook phase.
- **Admitted-sibling and null selection before a failed admission (#1146).**
  Rule 4 refuses them. The rollback then needs no `Current` restore, the
  §4.2 exact-restoration rule holds, and no reversal is published. The other
  option, a snapshot restored on rollback, publishes the change and its
  reversal and would need a new event-stream rule. The walk's assignment
  becomes a silent no-op in the same window, for the same reason.
- **Null clears and disposal.** The owner's refusal applies to non-null
  selections only. A null clear stays legal while disposal is pending,
  because chapter 06 §3 already says "always legal" and `COMP-005` needs it.
  Rule 4 is its only refusal.
- **`can_select_component` answers whether `SelectComponent` would succeed
  now.** It returns false for an unadmitted child, while disposal is pending
  and inside the caller's uncommitted transaction. `SelectComponent` then
  raises its existing predicate error for every refusal. Swift
  `canSetCurrent(_:)` follows the same rules for the setter.
- **A transfer admits the moved child after the old parent's detach
  commit.** The destination admits the child after the old parent's detach
  commit, after the last viability recheck and before `CollectionChanged`.
  If it admitted the child first, another thread could select the child in
  the destination while its `IsCurrent` flag was still set from the old
  parent. The old parent's detach clear would then reset the flag, and the
  destination would keep the child current with `IsCurrent` false, which
  breaks `COMP-006`. Swift reproduced this race before it moved the
  admission. C#, Python and TypeScript also admitted the child before the
  commit and now admit it after it. Rust already admitted it after the
  commit. Until the admission, the moved child is unadmitted in the
  destination, so the old parent's commit callbacks on the adding thread
  cannot select it there either (rule 4).
- **Disposal from another thread during a publication.** The order is the
  current C# order: first the foreign-transaction rule of §4.2, then the
  lease check. A thread that holds a lease is checked before any wait, so it
  never waits for itself.
- **`AsyncSelection(true)`.** The call-time check and the delivery use the
  same rules, so a valid call is never refused for a transaction it cannot
  see.
- **A selection during `Destructing`.** Consumer code that selects after the
  destruct clear, from a child hook or from another thread, is not refused.
  `COMP-005` assumes no consumer selects while the composite destructs. A
  status check would need the lifecycle status under the membership gate,
  which no flavor has. ADR-0188 replaces this bullet: a non-null selection
  while the composite is `Destructing` changes nothing and raises nothing.
- **No conformance ID.** As in ADR-0165, every rule is observable only while
  another operation is in flight. Each flavor covers the rules with its own
  tests. `COMP-005`, `COMP-025`, `COMP-026` and `COMP-040` keep covering the
  ordinary paths.

## 3. Flavor work

- **C# and Python:** rule 1 for the selection calls (the setter stops
  opening a transaction), rule 2 with a marker that also covers population,
  rules 3 and 4, the rule 8 clear helper, and the rule 7 call-time check
  (#1144, #1145, #1146, #1148).
- **TypeScript:** rules 2 to 8, including the population marker. Rule 4
  replaces the current refusal inside any open transaction. Rule 1 has no
  cross-thread case in TypeScript (#1149 and its 2026-11-07 scope comment).
- **Swift:** all eight rules. The setter stops waiting. `dispose()` checks
  the lease before any foreign wait. The walk's assignment becomes
  synchronous with `AsyncSelection(true)` (#1150, #1201, Swift part of
  #1145).
- **Rust:** all eight rules. `set_current` stops returning
  `OwnershipTransactionInProgress` for another thread's transaction and for
  the add's `CollectionChanged` publication. The two ignored `COMP-026` Rust
  tests are re-enabled (#1151, Rust parts of #1144 and #1145).
- **Every flavor:** a transfer's destination admits the moved child after
  the old parent's detach commit (§2.1). C#, Python and TypeScript move the
  admission in add, insert, replacement and population, and Swift does the
  same. Rust already followed this order. Each flavor has a regression test.

## 4. Consequences

- No selection call raises or waits because another thread holds a
  membership transaction. A construct hook that selects on another thread no
  longer rolls its composite back. Swift no longer waits, which reverses the
  wait that PR #647 added.
- In C#, Python and Swift, another thread can no longer select a transferred
  child in the destination until the destination admits it, which is now
  after the old parent's commit (§2.1, rule 2). In that window, a construct
  walk of the destination that picks the moved child is a silent no-op, and
  `Current` keeps its prior value. Before, C# and Python committed the pick,
  and Swift committed it after a wait. A selection call in that window raises
  the non-member error. Before, C# and Python raised the transaction error,
  and Swift waited and then committed. Rust already admitted the child after
  the commit, so the window is not new in Rust. TypeScript runs on one thread
  and has no cross-thread case.
- In C# and Python, a selection from a hook on the add owner's thread now
  raises before the add commits. It used to commit, and a failed add then
  left `Current` stale.
- In TypeScript, Swift and Rust, a `CollectionChanged` subscriber can now
  select in the composite that is publishing its add.
- `destruct()` always reaches `Destructed` with `Current` null, and a
  disposal from `OnCurrentChanged(null)` is deferred in every flavor.
- Publications from two threads can interleave, as ADR-0165 §4 accepts.
- Chapter 06 §3.2 no longer lists open gaps. Ledger §2.9 is decided, and the
  ledger's parked `COMP-026` Rust tests return to the suite.
