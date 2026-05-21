# ADR 0002 — Rx is the reactive primitive

**Status:** Accepted (2026-05-19)
**Spec version:** introduced in 1.0.0

## Context

VMx is built around a hot stream of `IMessage` events (the message hub) and observable command triggers (`IObservable<Unit>` re-evaluating `CanExecute`). The legacy library used System.Reactive 2.2.5. We need a reactive primitive that is available, mature, and semantically consistent across C#, Python, and future TypeScript / Kotlin / Swift.

## Options considered

1. **Native async/events first; optional Rx adapter package.** Core API uses C# `async`/`Task`/`IAsyncEnumerable`, Python `asyncio`/`AsyncIterator`, etc. A separate Rx adapter is published for users who want richer operators.
1. **A custom in-house observer abstraction (`IObservable<T>`-like) with no operator library.** Zero external dependencies, predictable cross-language behavior, but reinvents what Rx already provides.
1. **Standardize on Rx in every language.** System.Reactive (C#), reactivex (Python), rxjs (TypeScript), kotlinx.coroutines.flow or RxKotlin (Kotlin), Combine or RxSwift (Swift).

## Decision

Option 3. Rx ports exist and are stable in every language we care about. The operator library (Where, Select, Throttle, ObserveOn, …) is industry-standard for reactive MVVM, and we get it for free in each flavor instead of re-implementing or omitting.

## Consequences

- Every active language flavor depends on its language's Rx port (mandatory in `pyproject.toml` / `Directory.Packages.props` / `package.json`).
- A new language flavor cannot be added unless a comparable Rx port exists; the playbook (§13 of the design doc) calls this out as the first gate. Languages without an Rx port (e.g., Rust, Go) require an ADR documenting the semantic mapping before they can join.
- Conformance tests pin Rx-specific semantics (hot streams, no replay, scheduler-aware delivery) so language ports cannot drift on these.
