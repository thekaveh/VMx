# ADR 0076 — Correct Swift async command parity documentation

**Status:** Accepted (2026-07-01)
**Spec version:** introduced in 3.1.0

## 1. Context

Swift reached full library conformance parity in the v3.1.0 workstream, including
`AsyncRelayCommand` and `CMD-012`. The implementation uses Swift structured
concurrency for the cancellable body and Combine for reactive command channels.

The command chapter and conformance catalog still carried older v3.0 wording that
limited `AsyncRelayCommand` to C#, Python, and TypeScript and described Swift as
out of scope.

## 2. Decision

Update `spec/04-commands.md` and `spec/12-conformance.md` so `AsyncRelayCommand`
is documented as a full-parity primitive across C#, Python, TypeScript, and
Swift. Swift's cancellation channel is Swift `Task` cancellation; caller-supplied
external cancellation tokens remain flavor-specific.

## 3. Consequences

The spec now matches the current Swift source and tests. This is a documentation
correction only: it adds no new conformance ID and does not change runtime
behavior in any flavor.
