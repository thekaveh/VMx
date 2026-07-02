# ADR 0077 — Correct Swift FormVM snapshot default documentation

**Status:** Accepted (2026-07-01)
**Spec version:** introduced in 3.1.0

## 1. Context

Chapter 20 described the `FormVM` default snapshotter as a deep value-copy in
all active flavors. That is accurate for C#, Python, and TypeScript after the v3
snapshot hardening, but it overstates what Swift can provide for an unconstrained
generic `Model`.

Swift value types already copy on assignment, so the identity snapshotter is
correct for ordinary struct/enum models. For arbitrary class models, however,
Swift has no universal, type-safe deep-copy protocol that `FormVM<Model>` can
invoke without adding constraints that would break existing generic use.

## 2. Decision

Document Swift's default `FormVM` snapshotter as identity copy, relying on Swift
value semantics for value models. Reference models that need deep isolation or
revert of nested mutable state must supply an explicit `snapshotter`, such as a
domain copy initializer, `NSCopying` bridge, or `Codable` round-trip owned by the
consumer.

The `equals` default is likewise documented as Swift idiom: `==` for `Equatable`
models through the constrained initializer/build path; otherwise the existing
VMx fallback treats identical class instances as equal and non-`Equatable` value
models as changed unless callers inject `equals`.

## 3. Consequences

The spec now matches the shipped Swift source and README. This is a documentation
correction only: no conformance ID is added, and the cross-flavor API shape stays
identical because every flavor already exposes an injectable snapshotter.
