# ADR 0139 — Give Rust `FormVm` approval callbacks a detachable subscription

- **Status:** Accepted
- **Date:** 2026-10-04
- **Spec version:** 3.25.0 (Rust mapping; no normative change)
- **Clarifies:** [ADR-0048](0048-v3-form-vm-semantics.md)

## 1. Context

Chapter 20 exposes `OnApproved` as an event or observable. C#, Python,
TypeScript, and Swift return an observable whose subscriptions dispose
individually, and their completed approval channels retain nothing registered
after disposal.

Rust's `FormVm::on_approved` appended an `Arc<dyn Fn(M)>` to a plain vector
and returned nothing. A shorter-lived view could not detach its callback, the
callback lived as long as the form, and a callback registered after disposal
was retained forever (#357). The method's return type cannot become an RAII
guard without detaching every existing call site that ignores the result.

## 2. Decision

- `FormVm::subscribe_approved(callback)` returns an `ApprovalSubscription`.
  `dispose()` or dropping the handle removes only that registration and
  releases the callback's captures, unless an approval is invoking it at that
  moment. Repeated disposal is inert, and `is_active()` reports whether the
  registration still receives approvals.
- Callbacks run in registration order, after the approval state is published,
  with the persisted model, as before. A callback registered during an
  approval starts with the next one. A callback detached, or whose form is
  disposed, during an approval before its turn does not receive that approval.
  Later subscribers do not receive earlier approvals.
- Form disposal releases every remaining callback. Registration after
  disposal, through either method, keeps nothing: `subscribe_approved` returns
  an inactive handle and drops the callback at once. Disposal and registration
  serialize on one lock, so a registration racing disposal cannot be retained.
- `on_approved` keeps its registration-until-disposal behavior for existing
  callers and is deprecated in favor of `subscribe_approved`.
- Callback panics still propagate out of `approve` as before; this decision
  does not change approval error handling.

## 3. Consequences

- Rust approval callbacks have the per-subscriber lifetime the other flavors'
  observables already provide. No other flavor changes.
- Callers of `on_approved` see a deprecation warning. The method can be removed
  in a later breaking Rust release.
- The change is additive except that a post-disposal `on_approved` registration
  is now dropped instead of retained. It ships in the unreleased Rust 0.31.0.

## 4. Rejected alternatives

Returning a guard from `on_approved` would detach every existing registration
whose result is ignored, at the end of the statement.

A `ValueStream`-backed approval stream would isolate callback panics. That
would change the existing rule that a panicking callback propagates out of
`approve`, and it would need an initial value or an `Option` wrapper.

Weak-reference callbacks would make lifetime depend on hidden ownership
conventions instead of an explicit handle.
