# 6.2.1. ViewModel Families

## When To Use It

The core VM hierarchy stays intentionally small. Most design choices reduce to
one question: what kind of ownership and navigation relationship does this VM
have with its children, if any?

Use this page when you have decided the problem is fundamentally about VM shape
and need to choose the right family before dropping to a specific primitive
page.

<img src="../../assets/diagrams/viewmodel-families.svg" alt="ViewModel Families Map" class="vmx-diagram" />

<p>
  <a href="../../assets/diagrams/viewmodel-families.html">HTML</a>
  &middot;
  <a href="../../assets/diagrams/viewmodel-families.svg">SVG</a>
  &middot;
  <a href="../../assets/diagrams/viewmodel-families.png">PNG</a>
</p>

## Shape And Ownership

The family map is the quickest ownership comparison:

| Family                                               | Best fit                              | Owns children  | Owns selection      | Child shape                |
| ---------------------------------------------------- | ------------------------------------- | -------------- | ------------------- | -------------------------- |
| [Component](component-family.md)                     | Addressable leaf                      | No             | Through parent only | None                       |
| [Composite](composite-family.md)                     | Ordered selectable collection         | Yes            | Yes (`Current`)     | Homogeneous                |
| [Group](group-family.md)                             | Ordered peer collection               | Yes            | No                  | Homogeneous                |
| [Aggregate](aggregate-family.md)                     | Fixed dashboard/workspace shell       | Yes            | No                  | Heterogeneous, fixed arity |
| [Hierarchical](hierarchical-family.md)               | Recursive tree                        | Yes            | Consumer-defined    | Recursive homogeneous      |
| [Forwarding & Wrapper](forwarding-wrapper-family.md) | Instrumentation or selective override | Wraps inner VM | Inherited           | Same as wrapped VM         |

## Lifecycle And Messaging

- Use the smallest primitive that matches the ownership model.
- Prefer composition over subclassing; the shipped VM types are designed to be
  composed, not turned into inheritance trees.
- Reach for specialized helpers only when the workflow itself is the primitive,
  not just a property on a leaf or container.

At the family-selection level, the key lifecycle question is which VM owns
children directly and therefore owns their construction, destruction, and
property-change propagation. The linked family pages cover those rules in
detail.

Every family that exposes disposal follows one shared at-most-once rule; parent
cascades remain depth-first. See the [Disposal Contract](../disposal-contract.md).

## Cross-Language Surface

The conceptual family map is shared across all five source flavors. The main
cross-language differences are the usual casing rules and the modeled-type
spellings called out on each concrete page.

This index intentionally stays above the API level: it points you to the right
family first and leaves method and builder details to the leaf pages.

## Example

A practical decision path for common cases:

- choose [Component](component-family.md) for a leaf that owns one model or one
  view concern
- choose [Composite](composite-family.md) when you need an ordered collection
  with a current child
- choose [Aggregate](aggregate-family.md) when the parent owns a fixed set of
  heterogeneous child roles
- choose [Hierarchical](hierarchical-family.md) when the VM tree is recursive

The flagship Notes Workspace portfolio exercises most of the family map, but
the notebooks tree is intentionally a flat adapter in every flavor today:

- flat `ComponentVM`-based notebooks adapters (`NotebooksRootVM` plus
  `NotebookVM`) that expose `Roots` / `ChildrenOf` / `Walk` or idiomatic
  equivalents and publish `TreeStructureChangedMessage`, rather than direct
  `HierarchicalVM` subclasses
- `CompositeVM` for the notes list and tab-like current selection
- `AggregateVM6` for the workspace shell
- `ComponentVM` leaves for notebooks, notes, status, and capability actions
- `FormVM`, `DiscriminatorVM`, and `NotificationVM` in the editor and
  notifications flows

Use `HierarchicalVM` when the recursive VM tree is itself the right model. Use
the Notes Workspace READMEs and parity tables when you want the current
flat-adapter example shape.

## Common Pitfalls

- Choosing a larger container primitive before checking whether a leaf or
  simpler list shape already fits.
- Treating wrapper or specialized primitives as replacements for the core
  ownership families.
- Reading the Notes Workspace examples as the only allowed shape rather than one
  worked example portfolio.

## Related Primitives

- [Specialized ViewModels & Coordinators](specialized/index.md)
- [Command Families](../command-families.md)
- [Builders, Collections & Tree Utilities](../builders-collections-tree-utilities.md)
- [VM Collection Contract](../vm-collection-contract.md)
