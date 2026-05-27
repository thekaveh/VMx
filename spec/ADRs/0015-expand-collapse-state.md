# ADR 0015 — Expand / collapse state on VMs

**Status:** Accepted (2026-05-25)
**Spec version:** introduced in 2.0.0

## Context

The 2012 VMx predecessor put `IsExpanded` on every VM, plus
`Expand`/`Collapse`/`ToggleExpansion` commands. The new VMx kept the VM
surface minimal — there is no expand/collapse state on any core VM.

The absorption goal calls for bringing expand/collapse forward, but Item 1
established that capability-based behaviors are opt-in. So expand/collapse
should land as `IExpandable` (which already exists from cycle 1), plus a
default-implementation helper for VMs that opt in, plus a tree-traversal
helper that respects the state.

## Options considered

1. **Add IsExpanded to every VM by default.** Symmetric with the legacy
   predecessor but violates the opt-in rule from chapter 14 and grows the
   default VM surface for every consumer.
1. **Provide a small `ExpandableState` helper + `walk_expanded` tree utility;
   leave the base VM types untouched.** Consumers wire `ExpandableState` into
   any VM that needs expand/collapse; trees rendered with `walk_expanded`
   automatically observe the state.
1. **Skip — leave expand/collapse to consumers entirely.** Misses the
   legacy parity goal and forces every consumer to invent the same wheel.

## Decision

Option 2. The cycle ships:

- Documentation in chapter 05 explaining the `IExpandable` integration
  point.
- A small `ExpandableState` helper per flavor that bundles state +
  `IExpandable` + `ICollapsible` + `IExpansionTogglable` + a change
  observable.
- A new `walk_expanded` tree utility (chapter 13) that descends into
  children only when their parent reports as expanded.

## Consequences

- Five conformance IDs `EXP-001..EXP-005` cover the helper contract, the
  tree-walk behavior, and the rule "non-`IExpandable` nodes are treated as
  always-expanded".
- The base VM types are unchanged (still no `IsExpanded` member). Opt-in
  is via `ExpandableState` composition.
- `walk_expanded` is the canonical traversal for tree-view consumers that
  need to render the visible portion only.
- Existing `walk` continues to descend unconditionally — its behavior is
  unchanged.
- Consumers wanting to "expand all" can simply iterate the tree with
  `walk` and call `Expand` on every `IExpandable`.
