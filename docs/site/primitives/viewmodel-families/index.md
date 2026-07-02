# ViewModel Families

The core VM hierarchy stays intentionally small. Most design choices reduce to
one question: what kind of ownership and navigation relationship does this VM
have with its children, if any?

## Family Map

| Family                                               | Best fit                              | Owns children  | Owns selection      | Child shape                |
| ---------------------------------------------------- | ------------------------------------- | -------------- | ------------------- | -------------------------- |
| [Component](component-family.md)                     | Addressable leaf                      | No             | Through parent only | None                       |
| [Composite](composite-family.md)                     | Ordered selectable collection         | Yes            | Yes (`Current`)     | Homogeneous                |
| [Group](group-family.md)                             | Ordered peer collection               | Yes            | No                  | Homogeneous                |
| [Aggregate](aggregate-family.md)                     | Fixed dashboard/workspace shell       | Yes            | No                  | Heterogeneous, fixed arity |
| [Hierarchical](hierarchical-family.md)               | Recursive tree                        | Yes            | Consumer-defined    | Recursive homogeneous      |
| [Forwarding & Wrapper](forwarding-wrapper-family.md) | Instrumentation or selective override | Wraps inner VM | Inherited           | Same as wrapped VM         |

## Practical Rule Of Thumb

- Use the smallest primitive that matches the ownership model.
- Prefer composition over subclassing; the shipped VM types are designed to be
  composed, not turned into inheritance trees.
- Reach for specialized helpers only when the workflow itself is the primitive,
  not just a property on a leaf or container.

## Notes Workspace Cross-Check

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
