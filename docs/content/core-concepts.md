# 4. Core Concepts

## One Spec, Five Source Flavors

VMx is defined once in `spec/` and implemented idiomatically in C#, Python,
TypeScript, Swift, and Rust. The conceptual model stays aligned even when
naming changes by flavor.

## Lifecycle-Aware ViewModels

Every VM participates in the same construction state machine:
`Destructed`, `Constructing`, `Constructed`, `Destructing`, and terminal
`Disposed`. Construction, destruction, reconstruction, and disposal are part of
the framework contract rather than host-app convention.

## Message Hub and Dispatcher

Each VM receives a message hub and dispatcher. The hub carries property and
lifecycle messages across the tree, while the dispatcher centralizes foreground
and background scheduling for reactive work.

## Parent-Child Ownership

Leaf `ComponentVM`s model a single node. `CompositeVM`, `GroupVM`, and
`AggregateVM1..6` define ownership and traversal rules for children. Parent
references, depth-first lifecycle cascades, and current-selection semantics are
part of the shared shape.

## Idiomatic Naming by Flavor

| Flavor     | Naming style                              |
| ---------- | ----------------------------------------- |
| C#         | PascalCase                                |
| Python     | snake_case                                |
| TypeScript | camelCase                                 |
| Swift      | camelCase                                 |
| Rust       | snake_case methods, Rust-style type names |

Message payload property names follow the local idiom, with the documented
`Count` channel exception for collection messages.

## Conformance Catalog

The spec defines 292 conformance IDs: 287 library IDs plus 5 `THEME-00x`
scenario IDs. Every full-parity flavor carries the 287 library IDs in its own
conformance suite, and repository tooling checks coverage before CI passes.
