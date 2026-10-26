# ADR 0155 — C# `PagedComposition` enumerates its source again on each read

- **Status:** Accepted
- **Date:** 2026-10-26
- **Spec version:** 3.30.0 (clarification)

## 1. Context

Chapter 21 §5.2 said that C#, Swift and Rust take a repeatable collection, so a
one-shot source cannot occur there. Swift takes an array and Rust takes a
`Vec`, so the claim holds for them. C# `PagedComposition` accepts any
`IEnumerable<TVM>`. When paging is on, each `PageCount`, `Items` and `Count`
read enumerates the source again.

A consuming source, such as `BlockingCollection<T>.GetConsumingEnumerable()`,
yields its items only once. A reader-backed iterator behaves the same way. With
such a source, `PageCount` returned 3, `Items` was then empty, and `PageCount`
then returned 0 (#758).

## 2. Decision

§5.2 says that C# accepts any `IEnumerable<TVM>` and enumerates it again on each
read. Materialize a one-shot C# source first, for example with `ToList()`. The C# constructor documentation and the documentation site state
the same requirement.

## 3. Consequences

- The text matches the C# behavior. No behavior changes.
- A C# snapshot of one-shot sources, as Python and TypeScript take at
  construction, would change behavior. It needs a separate decision.
