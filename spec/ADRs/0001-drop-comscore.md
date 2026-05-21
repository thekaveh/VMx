# ADR 0001 — Drop the comScore.Services dependency

**Status:** Accepted (2026-05-19)
**Spec version:** introduced in 1.0.0

## Context

The legacy VMx (`/Users/kaveh/repos/dotnet-tag/src/DotNetTag/VMx/`) depended on `comScore.Services` for its service-locator pattern: every `ComponentVM` accepted an `SL : IVMxServiceLocator` generic parameter and retrieved `IMessageHub`, `TaskScheduler`, and `IConstants` from it. `comScore.Services` is an internal library not suitable for an open-source release.

## Options considered

1. **Vendor a minimal slice of comScore.Services into the new repo.** Preserves the legacy API but ships private code under a new name.
1. **Re-implement a thin in-repo locator.** Re-creates the locator pattern under a VMx-owned namespace.
1. **Eliminate the locator entirely; use constructor injection.** VMs receive `IMessageHub` and `IDispatcher` via constructor arguments (and via the builder for fluent users).

## Decision

Option 3. Constructor injection is idiomatic in modern .NET (`Microsoft.Extensions.DependencyInjection` and similar), idiomatic in Python (explicit dependencies via `__init__`), and removes a class of "where does this come from" ambiguity. The locator generic parameter goes away, simplifying the heaviest type signatures.

## Consequences

- Public VM constructors and builders gain explicit `IMessageHub` / `IDispatcher` arguments.
- The `ComponentVMBase<SL, …>` generic parameter `SL` disappears across all base classes.
- An optional `VMx.Extensions.DependencyInjection` companion package wires `IMessageHub` + `IDispatcher` into Microsoft.Extensions.DependencyInjection for users who want the convenience.
- The Python flavor's equivalent companion is left for Phase 3 (it has fewer DI conventions to integrate with; explicit constructor args suffice).
