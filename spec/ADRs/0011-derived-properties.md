# ADR 0011 — Derived properties with N-source dependency tracking

**Status:** Accepted (2026-05-25)
**Spec version:** introduced in 2.0.0

## 1. Context

The 2012 VMx predecessor exposed `TransformationProperty<S,P,V>` plus 1–5
source overloads (`TransformationProperty<S1,P1,S2,P2,V>` etc., each adding
a source). The 5-source ceiling was a C# artifact: extending to N sources
would require manually generating N overloads, which the predecessor did not
do.

The current VMx has no derived-property primitive at all. Properties are
plain language properties whose setters publish `PropertyChangedMessage` via
the hub. There is no way to express "value V is `f(A, B, C)` and must
recompute whenever A, B, or C changes" except by writing imperative
subscription code in the consuming VM.

The VMx.old absorption goal calls for absorbing derived properties as a
first-class primitive.

## 2. Options considered

1. **1–5 source overloads (legacy parity).** Same as the 2012 predecessor.
   Predictable arity ceiling; same limitation. C# would need 5 overloads;
   Python and TS would either follow the same shape or diverge.
1. **N-source builder with a single `Sources(...)` method taking a sequence.**
   One factory in each flavor accepts an arbitrary-length list of source
   observables and a transform. Symmetric across all three flavors.
1. **Builder per source count, capped at some larger N (e.g., 10).** A
   compromise that's easier on the type system (each arity has its own
   transform signature). Loses the simple "any N" story.

## 3. Decision

Option 2. Every flavor exposes a single derived-property factory that
accepts an unbounded list of source observables and a transform that takes
their values in order. The spec **requires** every flavor to support at
least 5 sources (matching legacy behavior) and **permits** more.

Per-flavor implementation notes:

- **C#**: `DerivedProperty<TValue>` plus a builder that accepts
  `IObservable<object?>[]` of sources and a `Func<object?[], TValue>`
  transform. A small overload set (`Build<T1,T2>(IObservable<T1>, IObservable<T2>, Func<T1,T2,TValue>)`, etc.) up to 5 sources provides
  strongly-typed convenience; beyond 5, callers use the untyped form.
- **Python**: `DerivedProperty[TValue]` with a factory
  `from_sources(*sources, transform)` (variadic `*sources`).
- **TypeScript**: `DerivedProperty<TValue>` plus a factory
  `fromSources(sources: Observable<unknown>[], transform, opts?)` re-exported
  from `vmx`. A rest-parameter signature was considered but rejected because
  it conflicts with the trailing options object (`canSet`/`setAction`) the
  factory accepts — TypeScript rest parameters must come last.

The factory internally uses each flavor's reactive `combineLatest` (or
equivalent) plus `distinctUntilChanged` to ensure recompute-on-source-change
and distinct emission.

## 4. Consequences

- A new chapter `15-derived-properties.md` defines the contract.
- A new fixture `spec/fixtures/derived-properties.json` encodes the
  cross-flavor scenarios used by `DPROP-012`.
- Twelve conformance IDs `DPROP-001..012` cover the contract surface,
  multi-arity, validator + write-back, distinct emission, and dispose.
- Each flavor exposes a `DerivedProperty<TValue>` class plus a builder in
  the appropriate directory (`Properties/` in C#, `properties/` in Python
  and TypeScript).
- The 5-source upper bound from the legacy predecessor is removed.
- The derived property is a self-contained primitive with no required
  dependency on VM types; it works with any `IObservable` source.
- This ADR does not modify the message hub. Sources may be hub-derived,
  but they do not have to be.
