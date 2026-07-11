# ADR 0090 — Add disposal-lifetime ownership registration and public hub exposure

**Status:** Accepted (2026-07-10)
**Spec version:** introduced in 3.10.0
**Related:** ADR-0003, ADR-0006, ADR-0041, ADR-0084, issue #83

## 1. Context

ADR-0041 rejected two lifetime bags and kept explicit `OnConstruct`,
`OnDestruct`, and `OnDispose` hooks. A later NNx Studio audit supplied material
consumer evidence that was absent in 2026: long-lived Rx subscriptions repeatedly
needed a storage field plus an `OnDispose` override, and public hub forwarding
getters were repeated across viewmodels solely because the TypeScript base kept
the injected hub protected.

The omission creates a silent leak class: forgetting one field or one cleanup
line compiles successfully and fails only as ghost updates or retained memory.
The consumer also repeated `type` getters, but that case is materially different:
the discriminator describes the subclass's semantic family and cannot always be
derived correctly.

The implementation pilot used NNx Studio commit
`d304336799d4f377c9dd34a465072dd697a8fd7b`. Pointing its local VMx dependency
at this change removed 16 inherited hub getters, two subscription-handle fields,
two manual disposal overrides, and the two-case framework hub-getter regression
test. The resulting consumer diff was 10 additions and 104 deletions; package
typecheck passed and all 319 remaining viewmodel tests passed. The pilot was
validation-only and was not pushed to the consumer repository.

## 2. Decision

1. Add one VM-disposal-lifetime registration helper to the common component
   base in all five flavors: `Own`, `_own`, or `own` per language idiom.
1. Accept only the documented native shapes: C# `IDisposable`/`Action`; Python
   callable/`dispose()`; TypeScript function/`dispose()`/`unsubscribe()`; Swift
   closure/Combine `Cancellable`; Rust `FnOnce() + Send + 'static`.
1. Drain exactly once in LIFO order after the subclass disposal hook. Swallow
   each cleanup failure independently. A registration after or racing disposal
   cleans immediately once.
1. Keep per-construct resources explicit in `OnConstruct`/`OnDestruct`.
   Reconstruct and destruct never drain disposal-lifetime resources. Do not add
   two mutable bags.
1. Expose the injected hub as a public read-only baseline member. Exposure does
   not transfer ownership: a VM never disposes the shared hub.
1. Keep `type` abstract/required for custom subclasses where the language
   supports it; preserve Swift's existing language-specific default.

## 3. Consequences

- The missing-cleanup class becomes harder to write for long-lived resources,
  while teardown order and failure isolation are portable and conformance-tested.
- Forwarding decorators delegate the public hub member, so wrappers preserve the
  baseline contract.
- C#, Python, and TypeScript expose registration only to subclasses. Swift and
  Rust use public methods because their inheritance/access models do not provide
  a portable protected analogue.
- Consumers still own the injected hub and dispose it separately when the
  application scope ends.

## 4. ADR-0041 refinement and rejected alternatives

This ADR refines, rather than replaces, ADR-0041. Its core rejection of two
public lifetime bags stands. New consumer evidence justifies one narrow helper
for the disposal lifetime; it does not hide the reconstruct boundary.

Rejected alternatives:

- **Two public bags:** recreates the ambiguous lifetime-selection footgun.
- **FIFO cleanup:** conflicts with stack-like acquisition and dependency order.
- **Aggregate cleanup errors:** disposal APIs differ too much across flavors and
  cleanup must continue reliably during terminal teardown.
- **Default `type`:** can silently misclassify consumer subclasses.
- **VM-owned hub disposal:** breaks shared constructor-injected infrastructure.
