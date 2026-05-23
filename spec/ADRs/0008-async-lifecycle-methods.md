# ADR-0008 — Async lifecycle methods are a C#-specific affordance

## Status

Accepted, 2026-05-23. Supersedes nothing.

## Context

`IComponentVM` in the C# flavor exposes three async lifecycle entry points
alongside the synchronous ones:

- `Task ConstructAsync()`
- `Task DestructAsync()`
- `Task ReconstructAsync()`

Each returns a `Task` that completes when the corresponding terminal
`ConstructionStatusChangedMessage` arrives on the hub. They are convenience
wrappers around the synchronous methods that simply subscribe to the hub and
complete the task when the expected status is observed; they do not introduce
new lifecycle semantics.

The Python and TypeScript flavors do not expose async equivalents. The
question is whether to add them for parity or to document the asymmetry as
intentional.

## Decision

The async wrappers ship in the C# flavor only. They are not part of the
language-neutral spec and are not required for cross-flavor parity.

## Rationale

- **No new lifecycle semantics.** `Background(true)` already drives
  asynchronous construction on every flavor; `ConstructAsync` is purely a
  syntactic convenience that wraps a hub subscription in a `Task`.
- **TAP is .NET-idiomatic.** The Task-based Async Pattern is a foundational
  .NET API convention. Omitting `ConstructAsync` from C# would be
  surprising to .NET developers.
- **Python and TypeScript have their own asynchronous idioms** (asyncio
  futures, native Promises) that consumers can wrap around a hub
  subscription in two or three lines. Adding a static convenience here
  would either pick a winner among multiple equally-idiomatic patterns or
  introduce a thin wrapper that consumers can write themselves.
- **Cross-flavor conformance does not require them.** The 75-ID conformance
  catalog tests observable behavior (state transitions, hub emissions,
  collection events); it does not test the calling convention of the
  trigger.

## Consequences

- Consumers wanting "await until Constructed" in Python or TypeScript
  subscribe to `hub.messages` filtered on
  `ConstructionStatusChangedMessage` for their sender, then resolve their
  own future / promise.
- A future flavor that wants Task/Promise-style sugar adds its own
  wrappers, idiomatic to that language. No spec change required.
- ADR-0006 ("idiomatic API per language") is the parent rationale. This
  ADR is a specific application of that principle.

## Rejected alternatives

- **Adding `construct_async()` / `constructAsync()` to Python and
  TypeScript.** Workable but each language has multiple plausible patterns
  (asyncio.Future vs anyio.Event for Python; new Promise vs firstValueFrom
  for TypeScript). Picking one risks fighting the host project's
  convention.
- **Removing the C# async methods.** Would surprise .NET consumers who
  expect TAP-shaped wrappers on every cancellable / awaitable operation.
