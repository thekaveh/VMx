# ADR 0190 — Disposed tree nodes refuse structural calls, and a disposing container stops hub publication

- **Status:** Accepted
- **Date:** 2026-11-09
- **Spec version:** 3.30.0 (chapter 01 §1.4; chapter 06 §4, §4.2 and §4.3;
  chapter 07 §1; chapter 18 §6 and §7.1)
- **Clarifies:** [ADR-0142](0142-vm-collections-publish-collection-changes-on-the-hub.md)
  and [ADR-0105](0105-atomic-hierarchy-attachment.md). Related:
  [ADR-0171](0171-failing-local-subscriber-does-not-suppress-the-hub-message.md),
  [ADR-0173](0173-selection-commits-without-a-membership-transaction.md),
  #1318, #1351.

## 1. Context

### 1.1. Structural calls on a disposed `HierarchicalVM` (#1318)

The disposal contract says that changes to a disposed `HierarchicalVM` are
inert. Chapter 18 gave no post-dispose rule for structural calls. At
`349ca128`, no flavor checks the node's status in `AddChild`, `RemoveChild`,
`ReparentChild`, `AttachMany`, `InvalidateChildren` or `InvalidateSubtree`.
Each call changes the child list and the parent links, and then sends hub
messages. The node does not own the hub, so the hub delivers them.

The #1318 Python probe disposed a parent and then called the structural
methods on it.
The hub received `Added`, `Reparented`, `Removed`, a `children` change and a
`parent` change for each moved child. A live node could also take a child out
of a disposed parent's list.

The container families refuse changes after disposal. For example, a C#
`CompositeVM` throws `ObjectDisposedException` when it admits a child after
disposal starts.

### 1.2. A disposal requested while a container publishes a change (#1351)

A container defers a `dispose()` call during a membership transaction (chapter
06 §4.2). It also defers one from a current publication until the last lease
ends (§4.3 rule 5). A local subscriber or an `OnCurrentChanged` callback can
make such a call while the container publishes a committed change. Chapter 01
§1.4 did not say whether the hub message for that change is still sent.

Three cases show the flavors at `349ca128`:

1. A transfer: `old` holds the current child `x`, and its
   `OnCurrentChanged(null)` disposes `old`. Then `new.Add(x)` runs.
1. An `Add` whose local subscriber disposes the container `p`.
1. A `Move` whose local subscriber disposes `p`.

| Flavor            | Case 1                  | Case 2    | Case 3    |
| ----------------- | ----------------------- | --------- | --------- |
| TypeScript        | `new:Add`               | (nothing) | (nothing) |
| C#, Python, Swift | `old:Remove`, `new:Add` | `p:Add`   | (nothing) |
| Rust              | `old:Remove`, `new:Add` | `p:Add`   | `p:Move`  |

The TypeScript and Python results come from the #1351 probe, and the Rust
results from a probe at `349ca128`. The C# and Swift results come from code
reading.

TypeScript skips the hub send while a disposal is requested or deferred. C#,
Python and Swift skip it only after the disposal starts. In C#, Python,
TypeScript and Swift, `Move` opens no membership transaction, so its
subscriber's disposal starts at once. Rust checks before the local delivery,
and its `move_item` opens a membership transaction, so the disposal is
deferred.

## 2. Decision

Decided under the owner's 2026-11-07 delegation: the simplest rule that gives
one observable result in all five flavors.

### 2.1. A disposed node's child list is frozen

Chapter 18 §7.1 states these rules.

1. **Receiver.** From the moment a node's `Status` is `Disposed`, `AddChild`,
   `RemoveChild`, `ReparentChild`, `InvalidateChildren`, `InvalidateSubtree`
   and `AttachMany` on that node refuse. They refuse also where the call would
   otherwise do nothing.
1. **Transfer source.** `AddChild` and `ReparentChild` on a live node refuse
   when the child's current parent is disposed. The child stays in that parent.
1. **Batch.** `AttachMany` also refuses when the structural root is disposed.
   On a live root, a candidate whose parent is disposed gets an
   `AttachmentFailed` rejection. It is not parked and is not an orphan.
1. **Subtree invalidation.** `InvalidateSubtree` on a live node skips each
   disposed descendant. That node keeps its cache and publishes nothing. The
   call still visits that node's materialized children.
1. **No effect.** A refused call changes no child list, parent link, path,
   cache or parked item, and it publishes no message.
1. **Channel.** A refused call reports the disposal on the channel that a
   structural re-entry uses (chapter 18 §4). C# throws
   `ObjectDisposedException`, Python raises `RuntimeError`, and TypeScript
   throws `Error`. Swift `addChild` and `removeChild` return
   `.failure(.disposed)`, and `reparentChild` throws `HierarchyError.disposed`.
   Rust returns `Err(VmxError::Disposed)`. Swift and Rust `attachMany` return
   every item as an `AttachmentFailed` rejection. Swift and Rust
   `invalidateChildren` and `invalidateSubtree` return without a change.
1. **Unchanged.** A live node can still remove, transfer or invalidate a
   disposed child. A read of `Children` on a disposed node still materializes
   lazy children silently (§4). Disposal still never detaches a child (§3).

The disposal contract's `HierarchicalVM` row now says that structural calls
refuse.

### 2.2. A container stops hub publication once its disposal is requested

Chapter 01 §1.4 states the rule, and chapters 06 and 07 refer to it.

1. **Rule.** A `CompositeVM` or `GroupVM` sends no `CollectionChangedMessage`
   once its disposal is requested. This includes a disposal that the container
   defers (chapter 06 §4.2, §4.3 rule 5). Rust's `Count` message follows the
   same rule.
1. **Timing.** The container checks after its local subscribers return. So a
   local subscriber or an `OnCurrentChanged` callback that disposes the
   container suppresses the hub message of the change it observes. The local
   event is still delivered.
1. **Transfers.** When the old container's disposal is requested before its
   `Remove` publication, the hub receives only the new container's `Add`. The
   old-`Remove`-before-new-`Add` order applies when both containers publish.
1. **Results.** Case 1 gives `new:Add`. Cases 2 and 3 give no message. The
   result does not depend on whether the disposal runs at once or is
   deferred.

### 2.3. Choices made under the owner's delegation

- **Refuse, not inert, for tree nodes.** The containers refuse changes after
  disposal, and chapter 18 already reports a re-entry on a channel in each
  flavor. A silent no-op would hide a lost `AddChild` from the caller.
- **Freeze the transfer source.** A transfer changes the old parent's child
  list. Refusing it keeps the rule to one sentence: no call changes a disposed
  node's child list.
- **Status as the threshold.** `Status` is readable in every flavor, and a
  `HierarchicalVM` disposes no children, so its disposal is short. A subclass
  dispose hook runs after `Disposed`, so it cannot change the node's children.
- **Requested, not started, for containers.** "Requested or deferred" is the
  threshold that chapter 06 §4.2 and §4.3 rule 3 already use to refuse
  admission and selection. It also gives one result for `Move` and for
  changes in a membership transaction.
- **New Swift error case.** `HierarchyError` gains `disposed`. A consumer
  `switch` over `HierarchyError` must handle it, as it had to for
  `invalidFactoryOutput`.

## 3. Flavor impact

### 3.1. `HierarchicalVM`

Every flavor adds the status checks of §2.1 to its structural methods and a
new conformance test.

- **C#.** `HierarchicalVM` throws `ObjectDisposedException`.
- **Python.** `HierarchicalVM` raises `RuntimeError`.
- **TypeScript.** `HierarchicalVM` throws `Error`.
- **Swift.** `HierarchyError` gains `case disposed`. `attachMany` and the
  invalidation methods use their re-entry channels.
- **Rust.** `HierarchicalVm` returns `VmxError::Disposed` and checks the
  transfer source under the topology gate. `attach_many` and the invalidation
  methods use their re-entry channels.

### 3.2. Container hub publication

- **C#.** `CompositeVMBase` and `GroupVMBase` also refuse publication while
  `_disposeDeferred` is set.
- **Python.** `deliver_collection_changed` also checks the container's
  pending disposal.
- **TypeScript.** No change. It already checks `#disposeRequested || #disposeDeferred`.
- **Swift.** `CompositeVM` and `GroupVM` pass a predicate that includes
  `disposeDeferred`.
- **Rust.** A deferred disposal closes the container's publication, and
  `publish` checks again after the local delivery.

## 4. Conformance

- `HIER-041` — a disposed node refuses every structural call, a transfer from
  a disposed parent refuses, and `AttachMany` and `InvalidateSubtree` treat
  disposed nodes as §2.1 states.
- `COMP-049` — the three cases of §1.2 for a composite, and an `Add` and a
  `Move` whose local subscriber disposes a group. Rust delivers its local event
  through `ObservableMembershipSource::subscribe_membership`, so its test
  covers all the cases.

The catalog grows from 451 to 453 library IDs (458 in total).

## 5. Consequences

- Chapter 18 gains §7.1, and §6 refers to it for batches.
- Chapter 01 §1.4 keeps "a disposed container publishes nothing" and adds the
  rule of §2.2 after it. Chapter 06 §4, §4.2 and §4.3 and chapter 07 §1 refer
  to it.
- `COMP-045` keeps its text: a disposed container still publishes nothing.
- The disposal contract describes both rules.
- A hub observer no longer sees a `Remove` from a container that disposes
  itself during a transfer. It sees that container's `Disposed` status message
  instead.

## 6. Rejected alternatives

- **Inert tree calls.** The disposal contract cell would stay true, but a
  caller could not tell that `AddChild` did nothing. The containers refuse.
- **Allow a transfer out of a disposed parent.** The rule would need a second
  clause, and a disposed node's child list would still change.
- **Send the hub message for every delivered local event.** Case 3 would then
  publish after the container's `Disposed` message, which contradicts
  `COMP-045`.
- **Suppress only after the disposal starts.** `Move` and the transactional
  changes would give different results, and Rust would differ from the other
  flavors in case 3.
