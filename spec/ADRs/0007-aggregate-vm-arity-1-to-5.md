# ADR 0007 — `AggregateVM` covers arities 1 through 5

**Status:** Accepted (2026-05-19)
**Spec version:** introduced in 1.0.0

## Context

`AggregateVM<VM1..VMN>` represents a fixed tuple of heterogeneous child VMs. The legacy library exposed arities 1 through 5. We need to decide the upper bound for v1.0 and whether to use variadic generics where the language supports them.

## Options considered

1. **Arities 1–5 (legacy parity), explicit per-arity classes.** Same as legacy. Predictable, no language-specific tricks.
1. **Variadic generics in languages that support them.** C# 13+ does not support variadic generics natively; Python 3.11+ does (`TypeVarTuple`). Asymmetric across languages.
1. **A single `AggregateVM<VM*>` with runtime arity.** Loses compile-time type safety in C#; not idiomatic in either language.

## Decision

Option 1. Five explicit classes per language. The arity cap of 5 is a soft signal: when more than 5 heterogeneous children are needed, the right answer is usually a `CompositeVM<VM>` or `GroupVM<VM>` with homogeneous children. C# cannot express variadic generics, so the asymmetric option (2) would break the symmetric-spec goal stated in ADR-0006.

## Consequences

- `AggregateVM1` through `AggregateVM5` exist in every language flavor.
- Beyond arity 5, users compose multiple aggregates or switch to composite/group.
- The conformance catalog covers representative arities and cross-cutting behaviors via
  `AGG-001` through `AGG-005` (arity-1 factory, arity-2 children-reach-Constructed,
  arity-5 ordering, `ComponentN` property-changes, destruct waits for all). Arities 3
  and 4 are implied by the arity-N generalization and not separately enumerated.
  Spec/08 §Construction / §Destruction documents that the reference implementations
  drive the slots sequentially; the spec leaves ordering unspecified to allow a
  future implementation to dispatch via `IDispatcher.Background`.
- Any language flavor added under the new-language gate (ADR-0002) must implement all five arities before it can be considered conformant.
- A future spec major version could lift the cap; that would be a v2.0 change.
