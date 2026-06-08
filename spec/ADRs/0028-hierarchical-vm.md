# ADR 0028 — `HierarchicalVM<TModel, TVM>` (recursive composite specialization)

**Status:** Accepted (2026-05-28)
**Spec version:** introduced in 2.1.0

## 1. Context

The 2012 VMx predecessor included a commented-out `HierarchicalViewModel<...>`
research draft (`ToDo/HierarchicalViewModel*.cs`) — a first-class tree-structured
VM whose nodes were themselves containers of the same type. A prior `hierarchical-vm`
proposal (subsumed by `spec/proposals/2026-05-27-vmx-absorption-audit.md` and
removed during the v2.1 absorption) captured the draft but deferred six
design questions to v2.1.

In v2.0, consumers achieve tree shape by manually recursing
`CompositeVM<M, VM>`. The recursion works but lacks "this is a tree node" semantic,
doesn't compose with `walk`/`walk_expanded`, and forces consumers to re-invent
parent / depth / path bookkeeping.

The v2.1 absorption audit (see
`spec/proposals/2026-05-27-vmx-absorption-audit.md` item C1) elevates
HierarchicalVM to a first-class chapter, resolving the six open questions.

## 2. Options considered

1. **Skip** — keep recursive `CompositeVM<M, VM>` as the workaround.
1. **Add `HierarchicalVM<TModel, TVM>` with eager child loading and
   breadth-first construction** (the 2012 draft's apparent intent).
1. **Add `HierarchicalVM<TModel, TVM>` with lazy child loading and
   depth-first construction** (mirroring `LIFE-013` dispose order).

## 3. Decision

Option 3, with the following six specific resolutions:

1. **Lazy child loading by default.** Children are not materialized until
   `Children` is first accessed or `Expand()` is invoked (if the VM also
   implements `IExpandable`). A constructor option (`eagerChildren` in
   C# / TS, `eager_children` in Python) enables eager loading for
   consumers who want it.
1. **Recursive generic constraint.** Per-flavor: C#
   `where TVM : HierarchicalVM<TModel, TVM>`, Python
   `TVM = TypeVar("TVM", bound="HierarchicalVM[Any, Any]")` (the weaker
   bound — `TypeVar` cannot express self-referential parameter binding), TS
   `TVM extends HierarchicalVM<TModel, TVM>`. Cross-flavor divergence is
   noted in ADR-0009.
1. **Depth-first construction order.** A parent transitions to `Constructed`
   only after every descendant reaches `Constructed`. Mirrors `LIFE-013`
   depth-first dispose order; preserves invariant "children exist before
   parent reports ready".
1. **Hub messages.** Parent changes emit a standard `PropertyChangedMessage`
   (per chapter 03 §2.1 rules). Structural changes (add/remove/reparent
   of descendants) emit a dedicated `TreeStructureChangedMessage` with
   `(Source, Change: Added | Removed | Reparented, Affected, Index)` payload.
1. **Path materialized + cached.** `Path` returns a read-only snapshot of
   `root → … → self`. It is computed lazily on first access and invalidated
   only when the path actually changes (i.e., when `Parent` reference changes
   anywhere on the chain to root).
1. **No auto-implementation of `IExpandable`.** Per ADR-0010 capabilities are
   opt-in. `HierarchicalVM` does NOT implement `IExpandable` by default;
   consumers compose `ExpandableState` if they want tree-expansion semantics.
   This preserves the audit-time guarantee that no capability is implicit.

## 4. Consequences

1. New chapter `spec/18-hierarchical-vm.md` defines the contract.
1. Fourteen conformance IDs `HIER-001..HIER-014` cover identity, recursion,
   parent/depth/path invariants, lazy-vs-eager, depth-first construct, hub
   messages, and integration with `walk`/`walk_expanded`, `ExpandableState`,
   `SearchableState`, `ModeledCrudCommands`.
1. New `TreeStructureChangedMessage` type per flavor.
1. Per-flavor implementations in `langs/<flavor>/<src>/hierarchical/`.
1. The prior `hierarchical-vm` proposal was removed during the v2.1
   absorption (superseded by chapter 18 and this ADR).
1. Cross-flavor recursive-generic-constraint divergence is noted in ADR-0009.

## 5. Amendments

- **ADR-0035** (2026-05-28, spec v2.3.0) added `HIER-015..HIER-017` covering
  `HierarchicalVMBuilder.validate` (HIER-015), default-on-`build()` semantics
  (HIER-016), and repeat-`build()` immutability (HIER-017). The family is now
  17 conformance IDs.
