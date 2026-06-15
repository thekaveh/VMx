# ADR 0041 — Single disposable lifecycle via `OnDestruct` / `OnDispose` overrides (no two-tier bags)

**Status:** Accepted (2026-06-13)
**Spec version:** 2.6.0 (teaching ADR; no code change)
**Related:** ADR-0008, ADR-0018, `spec/proposals/2026-06-13-vmx-absorption-audit-followup.md` §6 L3

## 1. Context

The 2012 predecessors (`My.Architecture.New/Core/Unit.cs`, `GuideArch.Older/VMx/Core/Unit.cs`) exposed two `CompositeDisposable` bags on the lifecycle base:

- `Destructables`: cleared on every `Destruct()` (and re-cleared on the destruct phase of `Reconstruct`).
- `Disposables`: cleared only on `Dispose()`. Survives `Reconstruct`.

Subclasses registered subscriptions in the appropriate bag based on lifetime intent. Long-lived subscriptions (e.g., parent-collection observations) went in `Disposables`; per-construct subscriptions (e.g., child-VM hub subscriptions) went in `Destructables`.

The `dotnet-tag/VMx` ancestor collapsed this to a single `_disposables: List<IDisposable>` field cleared in `OnDestruct`. Current VMx kept the single-field model and exposes the lifecycle separation via virtual `OnDestruct` and `OnDispose` method overrides.

## 2. Decision

VMx retains the single disposable lifecycle. Subclasses with mixed-lifetime cleanup express the separation via method overrides:

- `OnDestruct(virtual)`: release per-construct subscriptions. Called by `Destruct()` and by the destruct phase of `Reconstruct()`.
- `OnDispose(virtual)`: release long-lived resources (instance fields, hub subscriptions, factory-injected services). Called once by `Dispose()`.

## 3. Rationale

- **Functional equivalence.** Method overrides express the same separation as two bags: cleanup A in `OnDestruct`, cleanup B in `OnDispose`. The hooks are already published API per `spec/02-lifecycle.md`.
- **No documentation burden.** Two-bag idiom requires the subclass author to know which bag for which subscription — a recurring footgun in the predecessors. Method overrides put the lifetime intent next to the cleanup code.
- **Precedent set by `dotnet-tag`.** The immediate structural predecessor (closest to current VMx) already collapsed to a single bag. The collapse predates v2.0 and has not surfaced consumer complaints.
- **`Reconstruct` semantics preserved.** `Reconstruct()` fires `OnDestruct` then `OnConstruct` (spec/02 §5); long-lived state held by instance fields survives this naturally without a second bag.

## 4. Consequences

- `ComponentVMBase` exposes virtual `OnConstruct`, `OnDestruct`, `OnDispose` hooks in every flavor.
- Subclasses with per-construct subscriptions register them in `OnConstruct`, store the `IDisposable` (or equivalent) in a local field, and dispose it in `OnDestruct`.
- Subclasses with long-lived subscriptions register them in the constructor (where they truly run once) and dispose them in `OnDispose`.
- If a future consumer pattern repeatedly forgets `OnDestruct` cleanup, revisit as a `RegisterPerConstruct(IDisposable)` ergonomic helper rather than reintroducing a second bag.
