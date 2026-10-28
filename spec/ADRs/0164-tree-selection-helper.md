# ADR 0164 — `TreeSelection` tracks one current node of a hierarchy

- **Status:** Accepted
- **Date:** 2026-10-27
- **Spec version:** 3.30.0 (additive)

## 1. Context

A `HierarchicalVM` node cannot be the current item of its tree. Its inherited
`Select()` delegates to the container back-reference (chapter 05 §6.1). Tree
nodes never set that reference, so `CanSelect()` is false. The C#, Python and
TypeScript notes showcases keep a flat list and a hand-written `current`
instead of a hierarchy. The React tree also walks `parentId` links by hand to
find the ancestors of the current notebook. Heimdall reports its own
`SelectableTreeNodeVM` for the same need (#667, plan §1.8.1 of
`spec/proposals/2026-10-20-heimdall-upstream-candidates-plan.md`).

Two facts constrain the design:

- Capabilities are opt-in (ADR-0010, ADR-0015, ADR-0028 §3 item 6). New
  `HierarchicalVM` members would collide with subclass members in TypeScript,
  C# and Swift. Rust's `HierarchicalVm<M>` has no subclass hook.
- Leaving the tree is not announced by the old parent. A transfer publishes
  one `Reparented` message from the new parent (chapter 18 §7). Invalidation
  publishes a `Children` property change and detaches the dropped nodes
  silently (§5). Those nodes stay live with a null parent (ADR-0156). Node
  disposal does not detach (§3).

## 2. Decision

### 2.1 A helper composed on a root

`TreeSelection` is a helper constructed on a tree node, its root. It adds no
member to `HierarchicalVM` and implements no capability on the nodes. Chapter
18 §10 specifies it. The surface follows ADR-0006:

| Flavor     | Type                         | Rejection of a non-member        |
| ---------- | ---------------------------- | -------------------------------- |
| C#         | `TreeSelection<TModel, TVM>` | `InvalidOperationException`      |
| Python     | `TreeSelection[TVM]`         | `ValueError`                     |
| TypeScript | `TreeSelection<TVM>`         | `Error`                          |
| Swift      | `TreeSelection<TModel, TVM>` | `TreeSelectionError.notInTree`   |
| Rust       | `TreeSelection<M>`           | `Err(VmxError::InvalidArgument)` |

Each type exposes `Current`, `CanSelect(node)`, `Select(node)`, `Clear()`,
`CurrentChanged` and `Dispose()` in its flavor's idiom. C# and Swift carry the
model type because `HierarchicalVM<TModel, TVM>` needs it to name the node
type: C# cannot declare a generic constructor, and Swift cannot express the
recursive bound (chapter 18 §2). Swift's `select(_:)` throws (ADR-0053). Rust
returns `VmxResult<()>` and reports changes through a `ValueStream` that does
not replay. The rejection plays the role of COMP-009 for trees. C#, Python
and TypeScript raise the same error as a non-child `Current` assignment on a
`CompositeVM`. Swift and Rust do not: their composites report
`CompositeMembershipError` and `VmxError::NonChild`, which name a container
child. A tree has no container, so Swift throws `TreeSelectionError.notInTree`
and Rust returns `VmxError::InvalidArgument`, as Rust's other tree operations
do (HIER-018).

### 2.2 Members of the selectable tree

A node can be selected when walking its `Parent` links reaches the root and no
node on that path is disposed. The walk reads no child list. A non-null
`Parent` exists only while the node is in that parent's materialized child
list. So the walk covers exactly the root's materialized tree, and it never
invokes a children factory.

So the design needs no `IsChildrenMaterialized` member, and this ADR adds none
(#667 criterion 3). Rust keeps its existing `is_children_materialized()`.

Disposed nodes are excluded because a disposed node stays attached (§3), and
a disposed VM accepts no further interaction (chapter 02 invariant 3). Status
is otherwise ignored. A lazy child is not constructed on first access
(ADR-0156), so requiring `Constructed`, as `ComponentVM.CanSelect()` does,
would make every lazy tree unselectable.

### 2.3 Leaving the tree: the helper watches the path

The selection clears when the current node leaves the tree: a removal, a
transfer out, an ancestor invalidation, or the disposal of the node or an
ancestor. A move inside the tree keeps it.

The helper detects these events by watching the path from the current node to
the root. It subscribes to the hub of each node on the path. When any node on
the path publishes a message, the helper repeats the §2.2 check. It clears the
selection when the check fails. When the check passes, it watches the path
again, because a move inside the tree changes the ancestors.

This is complete without a new message, because a node on the path publishes
every leave-tree event on its own hub:

| Event                               | Publisher on the path    | Message                                               |
| ----------------------------------- | ------------------------ | ----------------------------------------------------- |
| Removal of the node or an ancestor  | the removed node         | `Parent` property change (§7, HIER-010)               |
| Transfer out, also to another hub   | the moved node           | `Parent` property change, on the moved node's own hub |
| Invalidation of an ancestor         | the invalidated ancestor | `Children` property change (§5, HIER-022)             |
| Disposal of the node or an ancestor | the disposed node        | `ConstructionStatusChangedMessage` with `Disposed`    |

The transfer row is the critical one. Only the new parent publishes
`Reparented`, and it may publish on a hub the helper does not watch. The moved
node publishes its `Parent` change on its own hub, and the moved node is on the
watched path. So the helper sees the transfer without the destination's hub.
No cross-hub limitation remains: nodes of one tree can even use different hubs.

The helper clears when it receives the message. Inside a hub transaction or a
re-entrant drain (chapter 03 §7), that is when the hub delivers the queued
message. Until then `Current` still names the departed node. A helper whose
path includes a hub that delivers nothing, such as a null or disposed hub,
sees no message from that hub, so it cannot detect a node there leaving.

The cost is one hub subscription per distinct hub on the path, and one
identity check per message on those hubs. A re-check walks the path, so it is
proportional to the depth of the current node.

### 2.4 Change stream and ownership

`CurrentChanged` emits once for every effective change, with the new value or
null. It does not replay. A subscriber may select or clear while it receives a
value. The helper queues that change until every subscriber has received the
value, so all subscribers see the changes in order and end on the final
`Current`. Without the queue, a later subscriber of a synchronous stream would
see the new value before the old one. The helper publishes nothing to a hub. Like
`ExpandableState` (chapter 05 §8, ADR-0159), the VM that owns the helper
forwards the stream to its own property-change notification (chapter 14
rule 6).

The helper owns its hub subscriptions. `Dispose()` releases them, sets
`Current` to null without emitting, and completes the stream. It runs every
step and rethrows the first failure (#768); Rust resumes the first panic.
After disposal the helper is inert: `CanSelect` is false and `Select` and
`Clear` do nothing. Disposal never touches a node.

Swift holds the root weakly and the current node strongly. A root can then
own its helper without a retain cycle while the root itself is not current.
Once the root is deallocated, `canSelect` is false for every node, but
`current` keeps its value until `clear()` or `dispose()`: no message announces
a deallocation, and a getter that clears would have a side effect.

The Rust helper is `Send + Sync` and guards its state with a mutex, like the
tree. A revision counter keeps a stale re-check from clearing a newer
selection. The other flavors' trees are used from one thread, and so are their
helpers.

### 2.5 Selection does not navigate

`Select` and `Clear` change only the helper. They do not materialize, expand,
construct or move a node, and do not change `IsCurrent`. A host maps `Current`
to a route or a detail view. A node that wants `ISelectable` can delegate to
the helper; VMx does not do it for the node.

### 2.6 Conformance

`HIER-033` through `HIER-040` cover selection, rejection, the four leave-tree
events, the cross-hub transfer, no navigation, and disposal.

## 3. Consequences

- A tree gets one current node without a flat side list or a hand-written
  ancestor walk. The TypeScript React notes showcase uses the helper for its
  notebooks tree.
- Chapter 18 §7 is unchanged. No flavor publishes a new message, and no
  existing ID changes.
- The library conformance catalog grows from 436 to 444 IDs.
- The disposal inventory lists `TreeSelection`.

## 4. Rejected alternatives

- **An old-parent notification in §7.** The old parent would publish a
  `Removed` or `Reparented` message on a transfer. This is a behavior change
  for every hub subscriber and needs its own IDs. It also leaves invalidation
  and disposal uncovered, so the helper would still need the other events.
- **Watching only the current node.** The current node publishes nothing when
  an ancestor is removed, transferred or invalidated.
- **Watching the root's hub only.** The moved node's hub, and the hubs of other
  nodes in a mixed-hub tree, would go unwatched.
- **New `HierarchicalVM` members** (`IsCurrent` in the tree, `SelectInTree`).
  They collide with subclass members and break capability opt-in.
- **Validating on every read of `Current`.** A getter that clears and emits has
  a side effect, and the stream would stay silent until someone reads.
- **Requiring `Constructed` status.** It rejects every lazy node (§2.2).

## 5. Owner review

These choices are recorded for the owner's review of #667:

1. Leaving the tree is detected by watching the path (owner question 6 of the
   plan, option "the helper watches ancestors"). Spec 18 §7 gains no message.
1. Disposal clears the selection, but other statuses do not matter.
1. `Dispose()` drops `Current` without emitting null.
1. C# and Swift take two type parameters, unlike the one-parameter sketch.
1. The helper does not set `IsCurrent` on nodes and implements no
   `ISelectable`.
