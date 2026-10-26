# ADR 0156 — Hierarchy eager mode is per node, and child access does not construct

- **Status:** Accepted
- **Date:** 2026-10-26
- **Spec version:** 3.30.0 (clarification)

## 1. Context

Chapter 18 §3 said that lazy children "construct lazily on first access". The
code does not do that. First access to `Children` calls the children factory and
sets each parent. No flavor constructs a child at that point.

The eager-children API documentation in C#, Python, Swift and Rust said that the
option materializes the entire subtree or all descendants. Each eager hook
constructs only the direct children. Each child's own option decides the next
level (§4).

The hierarchy recipe said that reading `children` builds and constructs a lazy
level. It also said that a new owner disposes the nodes that
`invalidateChildren` drops. Those nodes stay live with a null parent (§5). The
disposal inventory said that disposing a hierarchy releases its children. Node
disposal never cascades (§3). A consumer who trusts those texts can leak live
children (#759).

## 2. Decision

§3 says that first access to `Children` builds the lazy children and sets their
parents. It does not construct them.

The eager-children API documentation in each flavor says that the option applies
to this node's children only. It also says that the option continues deeper
only through children that are eager themselves.

The hierarchy recipe says that reading `children` builds a lazy level without
constructing it. It says that the caller disposes the nodes that
`invalidateChildren` drops. The disposal inventory gives `HierarchicalVM` its
own row, which releases no children.

## 3. Consequences

- The text matches the behavior of every flavor. No behavior changes.
- No conformance ID changes. §4 already states the per-node rule.
