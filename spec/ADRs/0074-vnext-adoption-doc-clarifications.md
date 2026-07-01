# ADR 0074 — Clarify collection ownership and property-change binding docs

**Status:** Accepted (2026-07-01)
**Spec version:** introduced in 3.1.0

## 1. Context

The aws-tui adoption feedback surfaced two documentation issues rather than
runtime gaps:

- `ServicedObservableCollection<T>` can be misread as owning item lifecycle, but
  it only publishes collection-change messages to a hub.
- The current repo already exposes per-instance property-change surfaces, so
  adding another alias would duplicate existing API.

## 2. Decision

Clarify that `ServicedObservableCollection<T>` does not dispose, destruct,
construct, or otherwise own contained items. Ownership remains with the caller;
use VM containers such as `CompositeVM` / `GroupVM` when lifecycle cascade is
needed.

Document the already-supported per-instance property-change surfaces:
C# `INotifyPropertyChanged`, Python `property_changed`, TypeScript
`propertyChanged`, and Swift `propertyChanged`.

## 3. Consequences

Consumers get clearer guidance without a breaking rename and without redundant
aliases. The shared hub remains the cross-VM coordination path; per-instance
property-change streams are the binding-friendly path for a single VM.

## 4. Rejected alternatives

Renaming `ServicedObservableCollection<T>` was rejected for vNext because the
behavior is correct and a rename would be breaking.

Adding a new property-change alias was rejected because it would duplicate
existing surfaces and increase cross-flavor API noise.
