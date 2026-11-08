# ADR 0170 — Tree walks report invalid factory output as a recoverable error

- **Status:** Accepted
- **Date:** 2026-11-07
- **Spec version:** 3.30.0 (clarification of chapter 13 §4 and §6, and chapter 18 §4)

## 1. Context

ADR-0127 made `HierarchicalVM` factory hydration atomic and retryable. Swift
and Rust kept their `children` accessors fail-fast for source compatibility and
added the fallible `tryChildren()` and `try_children()`. C#, Python, and
TypeScript raise their ordinary invalid-operation errors from `children`.

The tree utilities read children through the fail-fast accessor in Swift and
Rust. A Swift probe built a root whose factory returned the same child twice.
`root.tryChildren()` returned `.failure(.invalidFactoryOutput)`. `walk(root)`,
`walkExpanded(root)`, and `find(root) { _ in false }` each stopped the test
process with `Fatal error: children factory returned structurally invalid output` (#1060). Rust `walk`, `walk_expanded`, and `find` panicked through
`TreeNode::children_nodes` in the same way. Python, C#, and TypeScript walks on
the same tree raise a catchable error.

Chapter 13 §6 stated no failure behavior. Chapter 18 §4 named only the Swift
and Rust `children` accessors as fail-fast. A tree-view consumer that walks a
user-supplied hierarchy had no way to recover in Swift or Rust.

## 2. Decision

Decided under the owner's 2026-11-07 delegation: all flavors follow the same
rule, with the simplest approach.

- `walk`, `walk_expanded`, and `find` report invalid factory output as the
  flavor's ordinary recoverable error in every flavor. They never trap or
  panic. The failing node keeps no children cache, so a later walk retries the
  factory (HIER-031).
- Swift `walk(_:)`, `walkExpanded(_:)`, and `find(_:where:)` become `throws` and
  throw `HierarchyError.invalidFactoryOutput`. The internal `_TreeContainer`
  requirement becomes the effectful property
  `var childComponents: [ComponentVMBase] { get throws }`. Only the
  `HierarchicalVM` conformance throws; it reads `tryChildren()`. The
  `CompositeVM`, `GroupVM`, and `AggregateVM1..6` conformances stay unchanged,
  and the aggregates keep their own non-throwing `childComponents` reads.
- Rust `walk` and `walk_expanded` return `VmxResult<Vec<T>>`, and `find`
  returns `VmxResult<Option<T>>`. `TreeNode` gains the provided method
  `try_children_nodes() -> VmxResult<Vec<Self>>`, which defaults to
  `Ok(children_nodes())`. `HierarchicalVm` overrides it with `try_children()`.
  The walks read children only through `try_children_nodes`.
- C#, Python, and TypeScript are unchanged. Their walks read the throwing
  `children` accessor, so the error already propagates when the lazy iteration
  reaches the node.
- The Swift `children` and `isLeaf` accessors and the Rust `children` and
  `is_leaf` accessors stay fail-fast. `isLeaf` / `is_leaf` reads `children`,
  so it follows the chapter 18 §4 accessor rule. A Boolean property cannot
  report the error without a source break, and `tryChildren()` /
  `try_children()` already give the fallible read. `isFirst` and `isLast` read
  the parent's children, which are always materialized once a node has a
  parent, so they cannot fail.
- Chapter 13 §4 shows the throwing Swift and `VmxResult` Rust signatures.
  Chapter 13 §6.1 states the failure surface for each flavor. Chapter 18 §4
  states the `isLeaf` rule and points to chapter 13 §6.1.

The rejected alternatives were to skip the failing subtree, which hides data
and differs from C#, Python, and TypeScript, and to keep and document the
trap, which leaves Swift and Rust consumers unable to recover.

This decision adds no conformance ID. Swift and Rust unit tests pin the
behavior. It changes no specification version.

## 3. Consequences

- A Swift caller writes `try walk(root)`, `try walkExpanded(root)`, and
  `try find(root) { … }`. A Rust caller handles the `VmxResult`. Both are
  source-breaking for existing callers; the Swift and Rust changelogs record
  them.
- A Rust `TreeNode` implementation whose children can fail overrides
  `try_children_nodes`. Existing implementations compile unchanged.
- A walk over a valid tree returns the same nodes in the same order as before.
