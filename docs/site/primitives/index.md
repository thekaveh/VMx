# Framework Primitives

VMx is one language-neutral framework surface expressed through four idiomatic
flavors. These pages are the practical map of that surface: which primitive to
reach for, what it owns, how it participates in lifecycle and messaging, and
where the flagship Notes Workspace examples use it.

## How To Read This Section

- Start with [ViewModel Families](viewmodel-families/index.md) when you are
  choosing the shape of a new VM.
- Use [Command Families](command-families.md) and
  [Capability Families](capability-families.md) when you need behavior without
  changing the core hierarchy.
- Use [State & Reactive Helpers](state-reactive-helpers.md) and
  [Services, Messages & Dispatching](services-messages-dispatching.md) when the
  question is about coordination, reactivity, or host wiring.
- Use [Builders, Collections & Tree Utilities](builders-collections-tree-utilities.md)
  when the question is construction ergonomics, observable collections, or
  traversal helpers.

## What "Parity" Means Here

The conceptual shape is identical across C#, Python, TypeScript, and Swift. The
surface idiom changes:

| Concept            | C#                        | Python             | TypeScript                | Swift                     |
| ------------------ | ------------------------- | ------------------ | ------------------------- | ------------------------- |
| Casing             | PascalCase                | snake_case         | camelCase                 | camelCase                 |
| Modeled leaf       | `ComponentVM<M>`          | `ComponentVMOf[M]` | `ComponentVMOf<M>`        | `ComponentVMOf<M>`        |
| Null hub singleton | `NullMessageHub.Instance` | `NULL_MESSAGE_HUB` | `NullMessageHub.INSTANCE` | `NullMessageHub.INSTANCE` |

The goal of these pages is not to restate the spec chapter by chapter. The goal
is to help you pick the right primitive quickly and then follow through with the
correct lifecycle, services, and related helpers.

## Choosing A Starting Point

If the VM is:

- a leaf that owns a single model or view concern, start with
  [Component Family](viewmodel-families/component-family.md)
- a selectable ordered list, start with
  [Composite Family](viewmodel-families/composite-family.md)
- a non-selectable peer list, start with
  [Group Family](viewmodel-families/group-family.md)
- a fixed tuple of heterogeneous children, start with
  [Aggregate Family](viewmodel-families/aggregate-family.md)
- a recursive tree, start with
  [Hierarchical Family](viewmodel-families/hierarchical-family.md)
- a specialized workflow such as edit/revert, active-mode switching, toast
  rendering, or modal completion, start with
  [Specialized ViewModels & Coordinators](viewmodel-families/specialized/index.md)
