# Core Concepts

## One Spec, Four Flavors

`spec/` is the source of truth. C#, Python, TypeScript, and Swift keep the same
conceptual contract while adopting native naming conventions.

## Lifecycle-Aware ViewModels

Every VM participates in the same state machine: `Destructed`,
`Constructing`, `Constructed`, `Destructing`, and `Disposed`.

## Message Hub And Dispatcher

The hub carries framework messages across the VM tree, and the dispatcher owns
foreground/background scheduling for reactive work.

## Parent-Child Ownership

Leaf `ComponentVM`s model one node. Container families such as
`CompositeVM`, `GroupVM`, `AggregateVM`, and `HierarchicalVM` own child
structure and lifecycle cascades.

## Related Pages

- \[[Architecture Map|Architecture/Architecture-Map]\]
- \[[Framework Primitives|Framework-Primitives/Framework-Primitives]\]
- \[[Specification & Conformance|Specification-and-Conformance/Specification-and-Conformance]\]
