# ADR 0207 — Rust filtered views and heterogeneous tree walks

- **Status:** Accepted
- **Date:** 2026-11-09
- **Spec version:** 3.30.0 (amends chapter 06 §9, chapter 13 §4 and §6, and
  chapter 18 §9; supersedes the `TreeNode` signature in ADR-0170 §2)

## 1. Context

Three Rust gaps were open in the spec and in the Rust parity ledger.

- Chapter 06 §9 lists `Changed` in the `FilteredCompositeVM` contract. Rust
  `FilteredCompositeVm` had no change stream, and it did not subscribe to its
  source. It applied a source membership change only when a caller read
  `current()` (#1259).
- C#, Python, TypeScript and Swift take the cursor policy at construction. A
  `Clear` or `PreserveIfVisible` view starts with no current item. Rust `new`
  and `scored` always started under `SnapToFirst`, so the same Rust view
  started on the first visible item (#1260, ledger §12.12).
- Chapter 13 §2 and §5 walk the children of `CompositeVM` and `GroupVM` and
  the present slots of `AggregateVMN`, and §6 stops `walk_expanded` at a
  collapsed `HierarchicalVM` that composes `ExpandableState`. Rust
  `TreeNode::children_nodes` returned `Vec<Self>`, so a node could list only
  children of its own type. `CompositeVm` listed no children, and `GroupVm`
  and the aggregates did not implement `TreeNode`. `HierarchicalVm` had no
  place for an `ExpandableState`, so `walk_expanded` never stopped at it
  (#1262).

## 2. Decision

Decided under the owner's 2026-11-07 delegation. Each choice is the simplest
one that matches the other flavors.

### 2.1. `FilteredCompositeVm` change stream

- `changed()` returns a hot `ValueStream<()>`, the crate's own stream type
  (ADR-0103). It sends `()` once after each recompute: a source membership
  change, `set_predicate`, `refresh` and `refresh_scores`. It sends `()` once
  when `set_current`, `move_next_visible` or `move_previous_visible` changes
  the current item, and nothing when the item stays the same. A subscriber
  reads the new state from `visible()` and `current()`.
- The view subscribes to the source's local collection-change stream, the
  one that `AggregateChangeStream` uses. The handler holds only a weak
  reference to the view state, so the source never keeps a dropped view
  alive. `current()` still reconciles a membership change that published
  nothing, for example after the source's disposal closed its publication.
- `dispose()` freezes the projection as before, releases the source
  subscription and completes the stream. Later calls send nothing.
- No conformance ID is added. A `Changed` conformance ID needs tests in all
  five flavors and is a separate decision.

### 2.2. Cursor policy at construction

- `with_cursor_policy(source, predicate, policy)` and
  `scored_with_cursor_policy(source, scorer, policy)` take the policy. `new`
  and `scored` keep their signatures and use `SnapToFirst`, the default of the
  other flavors.
- The first reconciliation runs under the given policy. A `Clear` or
  `PreserveIfVisible` view therefore starts with no current item.
  `set_cursor_policy` stays and applies at the next reconciliation.
- Chapter 06 §9 now states that the policy is a construction argument and
  sets the start state, as the five flavors behave.

### 2.3. `TreeNode` lists type-erased children

- `TreeNode::try_children_nodes` returns `VmxResult<Vec<TreeNodeRef>>`.
  `TreeNodeRef` is a cloneable, type-erased handle to any `TreeNode`. It
  exposes `id()`, `status()`, `type_name()`, `try_children_nodes()`,
  `expandable()`, `is::<T>()`, `downcast_ref::<T>()` and `downcast::<T>()`.
  Two handles are equal when their node identities are equal. The default
  lists no children. `TreeNode::children_nodes` is removed.
- `walk` and `walk_expanded` return `VmxResult<Vec<TreeNodeRef>>`, and `find`
  takes a `Fn(&TreeNodeRef) -> bool` predicate and returns
  `VmxResult<Option<TreeNodeRef>>`. This matches the other flavors, which
  return the base component type.
- `CompositeVm`, `ModeledCompositeVm` and `GroupVm` list their children when
  the child type implements `TreeNode`. `AggregateVm1` to `AggregateVm6` list
  their present components in `component_1`, `component_2`, … order and skip
  an empty slot. `HierarchicalVm` lists its children. `ForwardingComponentVm`
  joins the other leaves with the default.
- A Rust container holds one child type, so a tree that mixes VM types uses
  a consumer enum that implements `VmNode` and `TreeNode` by forwarding. A
  handle wraps the container's child type, so `downcast` to the enum returns
  such a child.

### 2.4. `HierarchicalVm` composes `ExpandableState`

- `HierarchicalVm::compose_expansion(state)` stores the state once. A second
  call returns `VmxError::InvalidArgument` and keeps the first state.
  `expansion()` returns it, and `TreeNode::expandable` returns it, so
  `walk_expanded` yields a collapsed node but not its descendants.
- The node does not implement `Expandable` itself, and it does not dispose
  the state. Capabilities stay opt-in (ADR-0010).

### 2.5. `TreeSelection` releases the retained node at disposal

The same pass fixes #1286. `TreeSelection::dispose` resets the value that its
`current_changed()` stream retains to `None` before it completes the stream.
A kept stream clone therefore no longer keeps the last selected node alive.
Other `ValueStream` owners are unchanged.

## 3. Consequences

- `FilteredCompositeVm` gains `changed()`, `with_cursor_policy` and
  `scored_with_cursor_policy`. A source membership change now reconciles the
  current item when the source publishes it, not at the next read.
- The `TreeNode` change is breaking for 0.36.0. A custom `TreeNode`
  implementation that overrode `children_nodes` or `try_children_nodes` now
  returns `TreeNodeRef` handles, and a caller of `walk`, `walk_expanded` or
  `find` reads nodes through `TreeNodeRef`.
- The test-only expandable wrapper in the Rust conformance suite is removed.
  `HIER-012` and `EXP-005` compose `ExpandableState` with `HierarchicalVm`.
  `UTIL-001` to `UTIL-003` walk the catalog `CompositeVm` tree, a `GroupVm` and
  an `AggregateVm3`.
- Chapter 06 §9, chapter 13 §6 and chapter 18 §9 drop their open Rust gaps.
  The Rust parity ledger closes §12.12 and the `FilteredCompositeVm` part of
  §12.4.7, and §12.3.4 cites the new walk evidence.
- C#, Python, TypeScript and Swift do not change.
