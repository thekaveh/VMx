# ADR 0146 — Tree-utility and fluent-command surfaces name all five flavors

- **Status:** Accepted
- **Date:** 2026-10-17
- **Spec version:** 3.29.0
- **Related:** [ADR-0006](0006-idiomatic-api-per-language.md) (idiomatic API per
  language), [ADR-0027](0027-fluent-command-extensions.md) (fluent command
  extensions), [ADR-0121](0121-current-five-flavor-contract-clarifications.md)
  (current prose names all five flavors)

## 1. Context

ADR-0121 requires current spec prose either to stay language-neutral or to name
all five flavors. Two per-flavor surface descriptions did not:

- Chapter 13 §4 listed the tree-utility surface for C#, Python, TypeScript, and
  Swift, with no Rust row.
- Chapter 04 §9 described the fluent helpers for C#, Python, and TypeScript
  only, although Swift ships free functions and Rust ships the `CommandExt`
  trait.

## 2. Decision

Add the missing flavors to both descriptions, as the code ships them:

- Chapter 13 §4 gains a Rust row. Rust exposes `walk`, `walk_expanded`, and
  `find` as crate-level functions over a `TreeNode` implementor. They return a
  materialized `Vec<T>` and an `Option<T>`.
- Chapter 04 §9 names the Swift free functions and the Rust `CommandExt`
  trait methods.

The change is editorial. It adds no normative behavior and no conformance ID.

## 3. Consequences

- The two sections satisfy ADR-0121.
- Chapter 13 still requires traversal through composite, group, and aggregate
  children. The Rust functions traverse only `TreeNode` implementors, which
  today means `HierarchicalVm` trees. This ADR records that gap and does not
  change it; closing it needs a separate behavioral change with its own tests.
