# ADR-0066 — Swift `ComponentVMBase` cross-module subclassing visibility

- **Status:** Accepted
- **Date:** 2026-06-30
- **Flavor:** Swift only (no spec change, no conformance change)

## Context

The other three flavors expose the viewmodel base class's messaging surface to subclasses with the language's "subclass-but-not-public" access level: C# `protected Hub` / `protected RaisePropertyChanged`, Python's convention of underscore-prefixed-but-reachable members, TypeScript `protected`. Consumers routinely subclass `ComponentVM`/`ComponentVMBase` in their own assembly/package to build application viewmodels (every flagship example app does exactly this).

Swift's `ComponentVMBase` (`langs/swift/Sources/VMx/Lifecycle/ComponentVMBase.swift`) declared its subclass-facing messaging surface — the injected `hub`, the injected `dispatcher`, and `_raisePropertyChanged(_:)` — as `internal`. Swift has **no `protected`**, and `internal` does **not** cross the module boundary. The base was therefore only subclassable *inside the `VMx` module* (by the library's own viewmodels). A consumer in another module could call `construct()`/`destruct()`, read `status`/`propertyChanged`/`isCurrent`, and override the `open _onConstruct()`/`_onDestruct()` hooks — but could **not** publish a message on its own `hub` or fire the `propertyChanged` (INPC) side-channel that view bindings subscribe to.

This was surfaced while building the Swift notes-showcase flagship (`examples/swift/notes-showcase/`), whose viewmodels subclass `ComponentVMBase` in a separate package. A VM framework whose base viewmodel class cannot be meaningfully subclassed by consumers in their own module is broken for its primary use case; this was a latent gap that no in-repo code hit because Swift `ComponentVMBase` had only ever been subclassed in-module.

## Decision

Widen the cross-module-subclassing surface of `ComponentVMBase` from `internal` to `public` — the Swift analogue of the other flavors' `protected`:

- `public let hub: MessageHubProtocol` (read-only; subclasses publish via `hub.send(...)`).
- `public let dispatcher: Dispatcher` (read-only; subclasses marshal via the foreground scheduler).
- `public func _raisePropertyChanged(_ propertyName: String)` (subclasses fire the in-process `propertyChanged` publisher; the cross-module analogue of C#'s `protected RaisePropertyChanged`).

The underscore on `_raisePropertyChanged` is retained (the established internal-callsite naming) and documented as the subclass-facing emit. `_setIsCurrent`/`_setStatus`/`_parent` stay `internal` — they are library-internal mechanics (driven by `CompositeVM` selection, etc.) that consumer subclasses do not call.

This is a **purely additive** access widening: it adds to the public API surface and breaks no existing code (internal → public never invalidates a caller). No spec change, no conformance change (the library coverage gate stays at 237/237).

## Consequences

- External consumers — and the Swift flagship example — can now subclass `ComponentVMBase` and build idiomatic application viewmodels that publish hub messages and drive view bindings, matching the C#/Python/TypeScript subclassing model (ADR-0006 idiomatic parity).
- **Swift package version → 3.1.0** (SemVer minor: additive public API), `minSpecVersion` unchanged at 3.0.0 (no spec dependency change). The Swift `CHANGELOG.md` records it; `compatibility-matrix.md` updates the Swift cell. The Swift flavor is unpublished, so this is an in-repo version marker only.
- The flagship example's `ThemeVM` (and the other showcase viewmodels) use the now-`public` `hub`/`_raisePropertyChanged` directly instead of a private hub workaround.
- The other flavors are unaffected (their bases were already consumer-subclassable).

## Alternatives considered

- **Keep the library frozen; have each example VM hold a private hub + a parallel `propertyChanged` subject.** Rejected: the example's own `propertyChanged` would then differ from the base's public publisher, so view bindings (which subscribe to `vm.propertyChanged`) would not see the subclass's mutations unless every view bound to the shadow publisher — a divergence from the library contract and from the other flavors' faithful subclassing. It also leaves the real library gap unfixed for every external consumer.
- **Introduce a new public `raisePropertyChanged` wrapper, keep `_raisePropertyChanged` internal.** Marginal cosmetic gain (drops the underscore) for an extra indirection; deferred — widening the existing member is the minimal change and the doc comment already described it as the subclass API.
