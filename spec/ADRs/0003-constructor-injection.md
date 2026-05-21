# ADR 0003 — Constructor injection over service locator

**Status:** Accepted (2026-05-19)
**Spec version:** introduced in 1.0.0
**Related:** ADR-0001

## Context

Independent of dropping comScore (ADR-0001), we need to decide *how* VMs receive their cross-cutting dependencies (`IMessageHub`, `IDispatcher`). The legacy locator pattern centralizes lookup but couples VMs to a runtime registry and complicates testing.

## Options considered

1. **Built-in minimal service locator.** Ship a `VMxContext` or ambient locator that VMs default to. Closer to the legacy API; convenient for quick starts.
1. **Constructor injection only.** VMs accept dependencies as explicit constructor arguments (and via the builder fluent API). The user wires them up — directly, through their DI container, or via the optional `VMx.Extensions.DependencyInjection` package.
1. **Both.** Constructor injection primary, optional locator helper.

## Decision

Option 2. Constructor injection is testable, explicit, and removes the ambient-state failure mode where a forgotten registration produces a confusing null reference deep in a VM's lifecycle. Modern .NET and modern Python both treat constructor injection as the default; we follow the convention.

## Consequences

- All builders include `Services(IMessageHub, IDispatcher)` (or equivalent per language) as a required call before `Build()`.
- The conformance catalog includes `BLD-002` (required-field validation) covering missing `IMessageHub` / `IDispatcher` at `build()` time.
- An optional companion package per language registers the services with the host's DI container as a convenience.
