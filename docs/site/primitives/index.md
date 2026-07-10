# Framework Primitives

## When To Use It

VMx is one language-neutral framework surface expressed through five idiomatic
source flavors. These pages are the
practical map of that surface: which primitive to reach for, what it owns, how
it participates in lifecycle and messaging, and where the flagship Notes
Workspace examples use it.

Use this overview when you are choosing a starting area rather than looking up a
single API. It is the top-level index for the primitive families.

## Shape And Ownership

The primitives catalog is organized by responsibility:

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

At this level, the ownership question is "which family owns this concern?" VM
families own hierarchy and child relationships; command and capability families
own behavior surfaces; the remaining sections cover coordination and utility
layers.

## Lifecycle And Messaging

Lifecycle and messaging rules are described on the family pages, but they follow
one common pattern here: choose the primitive family first, then confirm how it
constructs, destructs, publishes property changes, and participates in hub or
dispatcher wiring.

The overview pages deliberately stay at that routing level so they do not
invent surface APIs that belong on the concrete primitive pages.

## Cross-Language Surface

The conceptual shape is identical across C#, Python, TypeScript, Swift, and
Rust. The surface idiom changes:

| Concept            | C#                        | Python             | TypeScript                | Swift                     | Rust                    |
| ------------------ | ------------------------- | ------------------ | ------------------------- | ------------------------- | ----------------------- |
| Casing             | PascalCase                | snake_case         | camelCase                 | camelCase                 | snake_case methods      |
| Modeled leaf       | `ComponentVM<M>`          | `ComponentVMOf[M]` | `ComponentVMOf<M>`        | `ComponentVMOf<M>`        | `ComponentVm<M>`        |
| Null hub singleton | `NullMessageHub.Instance` | `NULL_MESSAGE_HUB` | `NullMessageHub.INSTANCE` | `NullMessageHub.INSTANCE` | `NullMessageHub::hub()` |

The goal of these pages is not to restate the spec chapter by chapter. The goal
is to help you pick the right primitive quickly and then follow through with the
correct lifecycle, services, and related helpers.

## Example

A typical reading path is:

1. start at [ViewModel Families](viewmodel-families/index.md) to choose the VM
   shape
1. jump to [Command Families](command-families.md) if the next question is how
   to expose executable behavior
1. finish with a utility page such as
   [Services, Messages & Dispatching](services-messages-dispatching.md) when the
   remaining work is host coordination

## Common Pitfalls

- Treating the overview as an API reference instead of a routing page.
- Starting with commands or helpers before choosing the owning VM shape.
- Assuming a surface-name difference across languages implies a conceptual
  difference.

## Related Primitives

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

From there, continue into:

- [Command Families](command-families.md)
- [Capability Families](capability-families.md)
- [State & Reactive Helpers](state-reactive-helpers.md)
