# ADR 0079 — Pin maintenance parity clarifications

**Status:** Accepted (2026-07-01)
**Spec version:** introduced in 3.1.0

## 1. Context

The v3.1 maintenance audit found two parity gaps that were visible to users but
not pinned clearly enough by the spec catalog.

First, Swift still documented the common positional-options construction form as
deferred even though C#, Python, and TypeScript exposed it for the common
`ComponentVM`, modeled component, `CompositeVM`, and `GroupVM` types. Second,
`GroupVM` children are peers with no group-level current slot, but C#,
TypeScript, and Swift could report a constructed group child as selectable while
selection itself remained a no-op.

## 2. Decision

Swift ships options-value factories for the same common VM types covered by the
C#, Python, and TypeScript options construction forms. The factories delegate to
the existing builders so required-field validation and defaulting stay identical.
The catalog adds `BLD-006` to pin this shared contract.

`GroupVM` children are explicitly non-selectable peers. A child whose parent is a
group MUST report `can_select` / `CanSelect()` / `canSelect()` as `false`, and its
inherited select command MUST be disabled. The catalog adds `GRP-011` to pin this
behavior across all flavors.

## 3. Consequences

All full-parity flavors now carry conformance markers for `BLD-006` and
`GRP-011`. Existing Python behavior becomes the group-selection reference point;
C#, TypeScript, and Swift align with it.

Swift gains additive API surface without removing the builder path. The builder
remains canonical for validation, defaults, and less-common VM types whose
options forms are still not part of the spec.
