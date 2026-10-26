# ADR 0154 — Chapter 04 §8.3.1 defers the awaited inner invocation to §8.3.2

- **Status:** Accepted
- **Date:** 2026-10-25
- **Spec version:** 3.30.0 (clarification)
- **Clarifies:** [ADR-0145](0145-confirmation-awaits-async-inner.md)

## 1. Context

ADR-0145 added chapter 04 §8.3.2. On the awaited `ExecuteAsync()` path, the
decorator invokes an asynchronous inner command through its awaitable entry
point. The awaited call then completes when the inner operation finishes.

§8.3.1 still said that `ExecuteAsync()` "runs the same flow" as the synchronous
`Execute`. That flow is the `confirm()` → `inner.Execute()` continuation. A
reader of §8.3.1 alone expects the awaited call to complete when an asynchronous
inner starts. That reader also expects inner failures on the inner's error
channel (#757).

## 2. Decision

§8.3.1 says that `ExecuteAsync()` awaits `confirm()` and then invokes the inner
command as §8.3.2 defines. The synchronous `Execute` keeps the fire-and-forget
`confirm()` → `inner.Execute()` continuation.

## 3. Consequences

- The chapter no longer contradicts itself. No behavior changes: every flavor
  already implements §8.3.2 (ADR-0145).
- No conformance ID changes. `CMDD-010` still covers the `errors` channel, and
  `CMDD-014` to `CMDD-017` still cover the awaited asynchronous inner.
