# ADR 0085 — Share the VM collection contract and preserve identity on move

**Status:** Accepted (2026-07-10)
**Spec version:** introduced in 3.5.0

## 1. Context

`CompositeVM` and `GroupVM` already expose nearly identical ordered child
collection surfaces, but consumers cannot depend on one public capability that
accepts either family. TypeScript UI adapters consequently narrow to
`CompositeVMBase`, and NNx Studio casts a `GroupVM` through `unknown` merely to
subscribe and iterate.

Reordering is also missing as a first-class operation. Clients remove and add,
or rebuild an entire collection. Both approaches misrepresent one logical
mutation and can clear selection, rewire parents, repeat construction, dispose
or reconstruct child instances, replace subscriptions, and lose UI identity.

## 2. Decision

VMx defines a shared ordered, observable, mutable VM collection capability for
`CompositeVM` and `GroupVM`. It includes count, indexed and iterable reads,
collection-change observation, add, insert, remove, indexed remove, replace,
clear, move, and batching. Selection is a separate capability implemented by
`CompositeVM`; `GroupVM` remains a peer container with no `Current` slot.

The idiomatic public names are:

| Concept               | C#                            | Python                        | TypeScript                    | Swift                    | Rust                         |
| --------------------- | ----------------------------- | ----------------------------- | ----------------------------- | ------------------------ | ---------------------------- |
| VM collection         | `IVmCollection<VM>`           | `VmCollectionProto[VM]`       | `IVmCollection<VM>`           | `VMCollection`           | `VmCollection<T>`            |
| Selectable collection | `ISelectableVmCollection<VM>` | `SelectableVmCollectionProto` | `ISelectableVmCollection<VM>` | `SelectableVMCollection` | `SelectableVmCollection<T>`  |
| Move                  | `Move(fromIndex, toIndex)`    | `move(from_index, to_index)`  | `move(fromIndex, toIndex)`    | `move(from:to:)`         | `move_item(from_index, ...)` |

`move` has one cross-flavor contract:

1. Both indices address the pre-move collection and MUST be in `[0, Count)`.
   An invalid index raises a flavor-idiomatic catchable bounds error before any
   mutation or notification.
1. After success, the moved child occupies `toIndex`; intervening children
   shift as they do for remove-then-insert at that final index.
1. Equal indices are a true no-op: no mutation, batch dirty flag, or event.
1. A non-no-op emits exactly one `Move` collection-change event containing the
   same child as old and new item plus both indices. A move inside a batch is
   suppressed and contributes to the single outer `Reset`.
1. Move changes ordering only. It MUST NOT reconstruct, replace, dispose,
   reparent, detach subscriptions from, or change the lifecycle/current flags
   of the child. A composite's `Current` reference remains the same object.
1. `AutoConstructOnAdd` does not apply because move is not add.

Replacement retains the pre-existing per-flavor surface and remove/add event
decomposition where already established; this ADR does not redefine it as
move. `Move` is added to the local VM collection event vocabulary. Rust's
VM-collection stream is hub-backed, so its `CollectionChangedMessage` carries
optional old/new indices; `Count` is not published for move.

Eight conformance IDs (`COL-032..039`) cover the capability split and every move
rule. The TypeScript React adapter accepts the shared capability. NNx Studio is
the pilot consumer: its sidebar cast is removed and hidden-layer reordering
uses the atomic move instead of rebuilding the canvas collection.

## 3. Consequences

- UI and infrastructure adapters can consume groups and composites without
  casts or selection assumptions.
- Reorder operations retain view identity, selection, lifecycle state, parent
  wiring, and subscriptions while producing one precise event.
- Swift gains the collection mutations previously absent from its public group
  and composite surfaces so both conform to the complete shared capability.
- Rust gains VM wrapper replacement methods and move indices on its collection
  message; existing add/remove/reset consumers remain source-compatible when
  they pattern-match the action non-exhaustively.
- The specification and stable flavors advance to 3.5.0; pre-1.0 Rust advances
  to 0.5.0.

## 4. Rejected alternatives

### 4.1 Put `Current` on the shared contract

Rejected. Selection is the defining semantic difference between composites and
groups. A nullable placeholder on groups would falsely advertise a capability.

### 4.2 Encode move as remove plus add

Rejected. Two events expose a transient absence, invite lifecycle/parent side
effects, and prevent consumers from recognizing a reorder as one mutation.

### 4.3 Rebuild the child collection

Rejected. Rebuilding loses object and subscription identity and can repeat
lifecycle work. Reorder is an in-place structural operation.

### 4.4 Allow Python-style negative indices for move

Rejected. Move needs one portable bounds contract. Existing insert/indexer
idioms remain unchanged; only move uses the explicit `[0, Count)` domain.
