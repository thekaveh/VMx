# ADR 0078 — Clarify TokenPagedComposition dispose races

**Status:** Accepted (2026-07-01)
**Spec version:** introduced in 3.1.0

## 1. Context

`TokenPagedComposition` fetches pages asynchronously. The initial ADR-0069 text
specified load and refresh mutation semantics, but did not state what happens
when `dispose()` lands while a fetch is suspended.

The four flavors now guard this path so an in-flight fetch that resumes after
disposal does not mutate `Items`, advance `CurrentToken`, or publish reset /
property notifications. Without that rule, a disposed composition can appear to
resurrect in host UI after its subjects or commands have been torn down.

## 2. Decision

Chapter 21 now states that disposal is terminal for token-paged load/refresh
completion. After `dispose()` wins the race, any suspended load or refresh
completion must return without mutating state or publishing notifications.

This clarifies the existing `COL-024..031` contract and regression tests; it
does not add a new conformance ID.

## 3. Consequences

Implementations must serialize post-await mutation against disposal using the
flavor's normal concurrency primitive: locks for C# / Python where relevant,
the event loop for TypeScript, and a serial state guard for Swift.
