# ADR 0017 — Null-object service convention

**Status:** Accepted (2026-05-25)
**Spec version:** introduced in 2.0.0

## 1. Context

The 2012 VMx predecessor used the null-object pattern for service
implementations (`NullObjects/NullMessagingService.cs`). A "null" service was a
shared, stateless implementation whose every operation was a safe no-op: a
sentinel that satisfied the contract without doing any work.

The current VMx has no such convention. Tests that want a hub-less VM either
inject a real `MessageHub` and ignore it, or build a one-off mock. Tests that
want an immediate dispatcher use `RxDispatcher.immediate()`, which is *almost*
the same as a null dispatcher but exists for a different reason (testing
synchronously, not "I don't care").

## 2. Options considered

1. **Skip the convention.** Continue to use ad-hoc mocks or real instances.
   Simplest, but tests stay heavier than needed and there's no canonical "I
   don't want a hub here" sentinel.
1. **Add `Null<X>` types per service contract (`NullMessageHub`,
   `NullDispatcher`).** Idiomatic null-object pattern. Each is a shared,
   stateless implementation whose operations are safe no-ops or empty
   observables.
1. **Add a single `Services.Null` factory that returns null variants of
   every service.** More dynamic but less discoverable than per-contract
   `Null<X>` types.

## 3. Decision

Option 2. Every core service contract gets a per-contract null variant whose
name is `NullX` where `X` is the contract's short name:

- `IMessageHub` → `NullMessageHub`
- `IDispatcher` → `NullDispatcher`
- `INotificationHub` (added in ADR-0013) → `NullNotificationHub`

The convention is normative: any new service contract added to the core spec
MUST come with a paired null variant. The same rule extends to the
notifications sub-package added in spec 2.0.

## 4. Consequences

- Two new public types per flavor today (`NullMessageHub`, `NullDispatcher`);
  a third (`NullNotificationHub`) in ADR-0013.
- Spec extensions to chapters 03 and 11 describe the null variants in their
  respective sections.
- Three new conformance IDs (`NULL-001..NULL-003`) verify the contract per
  variant and the existence of the convention itself.
- Tests across the codebase can simplify by using the null variants
  wherever a real service's behavior is irrelevant to the assertion.
- The null variants are stateless and may be shared via singleton-like access
  (a `Instance` property in C#, a module-level singleton in Python and TS).
