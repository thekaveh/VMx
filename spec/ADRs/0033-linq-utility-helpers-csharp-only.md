# ADR 0033 — LINQ utility helpers (C# only)

**Status:** Accepted (2026-05-28)
**Spec version:** introduced in 2.1.0

## 1. Context

The legacy `Extensions/System.Linq.cs` in GuideArch ships three small LINQ helpers
used by domain code:

- **`CartesianProduct`** — cartesian product of two `IEnumerable<T>` sequences as
  `IEnumerable<(TA, TB)>`.
- **`Sample`** — every Nth element from an `IEnumerable<T>` (extension method).
- **`Product`** — multiplicative aggregate of `IEnumerable<int>` (extension method);
  empty sequence returns 1.

In C#, `IEnumerable<T>` / LINQ is the idiomatic way to work with in-memory sequences
and all three helpers are natural extension methods on the `IEnumerable<T>` contract.

In Python, the standard library covers the same ground natively:

- `itertools.product(a, b)` for cartesian product.
- `seq[::n]` (slice with step) or a list comprehension for every-Nth.
- `math.prod(seq)` (Python 3.8+) or `functools.reduce(operator.mul, seq, 1)`.

In TypeScript, consumers implement trivially using `flatMap` / `filter`+modulo / `reduce`.

Adding these helpers to Python and TypeScript would duplicate built-ins and add noise
to the public API without benefit. Per ADR-0006 (idiomatic per-language surface), the
asymmetry is deliberate.

## 2. Options considered

1. **Skip** — consumers implement themselves where needed.
1. **Add to all three flavors** — duplicates Python and TypeScript built-ins.
1. **Add to C# only** — records the asymmetry per ADR-0006.

## 3. Decision

Option 3. C# gets the three helpers in `langs/csharp/src/VMx/Extensions/LinqHelpers.cs`
as a single public static class. Python and TypeScript do not receive equivalents.

## 4. Consequences

- A new `Extensions/` module in the C# project with `LinqHelpers.cs`.
- Unit tests in `langs/csharp/tests/VMx.Tests/Extensions/LinqHelpersTests.cs`.
- ADR-0009 (cross-flavor divergence catalogue) gains a new row recording the asymmetry.
- No conformance IDs (utility helpers, not behavioral contract).
- Python and TypeScript consumers that need the same operations use their language's
  built-ins; no migration path is required.

## 5. Rejected alternatives

- **Cross-flavor parity**: Would require exporting `itertools`-style wrappers in Python
  and adding boilerplate functions to TypeScript for no ergonomic gain. Already
  rejected in principle by ADR-0006.
- **Skip entirely**: The helpers are present in legacy codebases and useful for C#
  consumers; skipping would require every consumer to re-implement. C# LINQ's
  expressiveness makes small static helpers more idiomatic than in other flavors.
