# ADR 0150 — Hierarchical expansion prose and Rust default hubs

- **Status:** Accepted
- **Date:** 2026-10-21
- **Spec version:** 3.29.0
- **Related:** [ADR-0009](0009-cross-flavor-divergence-catalogue.md)
  (cross-flavor divergence catalogue),
  [ADR-0015](0015-expand-collapse-state.md) (`IExpandable` and
  `ExpandableState`),
  [ADR-0028](0028-hierarchical-vm.md) (§3 item 1, lazy child loading),
  [ADR-0052](0052-v3-public-surface-breaking-removals.md) (required
  `HierarchicalVM` services in Python),
  [ADR-0149](0149-spec-prose-corrections-chapters-02-23.md) (chapter 23 §3,
  Rust default services)

## 1. Context

Issue #655 found two records that disagree with the code:

- Chapter 18 §9 said consumers compose `ExpandableState<TVM>` "to gate lazy
  child materialization on `Expand()`". `ExpandableState` is not generic in any
  flavor. Expansion gates `walk_expanded` traversal (chapter 13 §5 and §6),
  except in Rust, whose `HierarchicalVm` never reports collapse (chapter 13 §6
  open gap). No flavor materializes children on `Expand()`: children
  materialize on first `Children` access, or at construct time with the eager
  option (chapter 18 §4). ADR-0028 §3 item 1 also names `Expand()` as a
  materialization trigger.
- ADR-0009 records that the TypeScript `HierarchicalVM` raw constructor falls
  back to a private hub. It does not record that Rust conveniences build a
  private hub:
  - `ComponentVm::new`, `CompositeVm::new`, `GroupVm::new`,
    `HierarchicalVm::new` and `FormVm::new`;
  - `AggregateVm1::new` / `try_new` to `AggregateVm6::new` / `try_new`;
  - `AsyncResourceVm::new` and `AsyncResourceVm::with_options`;
  - `NotificationVm::new` and `ConfirmationVm::new`, which build a private
    `NotificationHub`.

## 2. Decision

Correct the records as the code ships:

- Chapter 18 §9 names a non-generic `ExpandableState` that gates
  `walk_expanded` traversal, notes the Rust gap, and states that expansion does
  not materialize children.
- ADR-0028 §3 item 1 keeps its text. Its status line, its registry row and a
  §5 amendment record that `Expand()` materialization is corrected by this
  ADR.
- ADR-0009 lists the Rust conveniences next to the TypeScript fallback. Each
  type also has a constructor that takes the shared hub: `with_services`,
  `try_with_services`, `with_services_and_options`, `with_children_factory`,
  `FormVm::with_options` or `with_hub`.

The change is editorial. It adds no conformance ID and no behavior, and the
spec version stays 3.29.0.

## 3. Consequences

- Chapter 18 §9 no longer promises a materialization hook that no flavor
  ships. A consumer that wants expansion to load children reads `Children` when
  it expands.
- Audits find the Rust private-hub conveniences in ADR-0009 instead of
  re-reporting them as accidental drift. A VM built through one of them
  publishes to its own hub, not the application hub.
