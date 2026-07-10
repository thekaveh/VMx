# ADR 0084 — Make disposal a cross-cutting idempotency invariant

**Status:** Accepted (2026-07-10)
**Spec version:** introduced in 3.4.0

## 1. Context

VMx already specified idempotent disposal for lifecycle VMs, relay commands,
forms, notification hubs, modal VMs, derived properties, and several collection
helpers. The guarantees were scattered across type chapters and conformance
IDs, so consumers could not safely treat disposal as one framework-wide rule.
The audit for issue #107 also found two Rust gaps: one lifecycle disposal
published the terminal `Disposed` state twice, and `NotificationHub.dispose`
checked and set its disposed flag in separate critical sections, allowing
concurrent callers to repeat terminal publication.

Hosts commonly reach teardown from independent paths such as navigation,
window unload, hot reload, and test cleanup. Requiring those paths to coordinate
solely to prevent duplicate disposal adds client state and still leaves races.

## 2. Decision

Every public VMx-owned type that exposes `dispose` / `Dispose` follows one
cross-cutting invariant:

1. The first call is safe from every valid state supported by that type.
1. Later or re-entrant calls return normally and perform no additional
   observable terminal work.
1. Stream completion, terminal notification, cancellation, and owned-resource
   teardown occur at most once.
1. Parent/child cascades remain depth-first where already specified, while a
   child reachable through multiple teardown paths has only one observable
   terminal transition.
1. Types documented as thread-safe make the dispose check-and-claim atomic;
   callers may race disposal without duplicate terminal work.

This invariant does not invent one universal use-after-dispose policy. Existing
type-specific behavior remains authoritative: an API may become inert, retain
its last readable value, resolve an in-flight waiter with a safe result, or
raise a documented disposed error. Ownership also remains type-specific;
non-owning decorators and serviced collections do not start owning their inputs.

Six top-up conformance IDs (`DISP-001..006`) cover VM cascades, commands and
in-flight cancellation, hubs and concurrent disposal, interaction owners,
reactive helpers, and collection/projection helpers. They complement rather
than replace the existing `LIFE`, `CMD`, `HUB`, `NOTIF`, `DIA`, `FORM`,
`DPROP`, `COMP`, `GRP`, and `COL` contracts.

Rust now publishes one lifecycle `Disposed` transition and atomically claims
notification-hub disposal before terminal work. No other flavor required a
runtime change after the public-disposable audit.

## 3. Consequences

- Consumer teardown paths can call disposal independently without guard flags
  or unregister/re-register choreography.
- Documentation publishes a five-flavor inventory covering every public
  disposable, its completion behavior, owned resources, and permitted
  post-dispose calls.
- Implementers must add a disposable type to that inventory and one of the six
  conformance families when introducing a new public disposal surface.
- The specification advances to 3.4.0. C#, Python, TypeScript, and Swift advance
  to 3.4.0; pre-1.0 Rust advances to 0.4.0.

## 4. Rejected alternatives

### 4.1 Require consumers to serialize teardown

Rejected. It duplicates framework state in every host and does not protect
against independent unload, navigation, and test-cleanup paths.

### 4.2 Standardize every post-dispose method as a no-op

Rejected. Last-value reads, safe waiter resolution, inert commands, and explicit
disposed errors serve different contracts. Only disposal itself is unified.

### 4.3 Make disposal universally thread-safe

Rejected. Some flavors and helpers are intentionally single-threaded. Atomic
race guarantees apply only where the type already advertises thread safety.

### 4.4 Add reference counting to parent cascades

Rejected. Idempotent child disposal already makes multiple ownership paths
safe. Reference counting would change ownership and lifetime semantics.
