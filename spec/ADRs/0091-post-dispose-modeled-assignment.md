# ADR 0091 — Make post-dispose modeled assignment inert

**Status:** Accepted (2026-07-11)
**Spec version:** introduced in 3.11.0
**Related:** ADR-0006, ADR-0009, ADR-0053, ADR-0083, ADR-0084, issue #141

## 1. Context

Disposal is VMx's terminal lifecycle state, and the common property-notification
helper already rejects calls that begin after disposal. Modeled setters did not
share one portable admission rule. A modeled component could still evaluate
equality, replace its model, recompute its modeled hint, or invoke a consumer
callback after disposal in every flavor. `FormVM.SetModel` was already guarded
in C#, Python, and Rust, but still mutated and revalidated in TypeScript and
Swift.

That divergence is observable when an async completion arrives after its screen
or workflow has been torn down. Suppressing only the final notification is too
late: consumer equality, hinting, validation, callbacks, command requery, and
retained-state mutation may already have occurred.

## 2. Decision

1. When modeled assignment begins after the VM is disposed, it returns before
   candidate equality, retained-state mutation, hint or snapshot work,
   validation, command-state work, consumer callbacks, local notifications, or
   hub messages.
1. An assignment admitted before disposal completes under the existing property
   mutation contract. This decision adds no cross-flavor lock or cancellation
   primitive.
1. Apply the early guard to modeled components in all five flavors and to
   `FormVM.SetModel` in TypeScript and Swift. Retain the existing C#, Python,
   and Rust form guards.
1. Swift's internal read-only modeled-component update inherits the guarded
   setter. Forwarding wrappers inherit the guarded target. Modeled composites
   remain unchanged because their model input configures a child factory and is
   not retained through a settable model property.
1. Add `DISP-014` as one cross-cutting conformance scenario covering modeled
   components and forms in every full-parity flavor.

## 3. Consequences

- A late completion cannot reactivate retained modeled state or run consumer
  code after terminal teardown.
- Upstream cancellation remains necessary for network, task, renderer, and
  other application resource control. The VM guard is only the final state
  admission boundary.
- No public API or dependency changes. Existing assignments admitted before
  disposal keep their ordering and notification behavior.
- The specification and stable packages advance to 3.11.0. Rust advances to
  0.11.0 while declaring minimum spec 3.11.0. This is a minor contract
  convergence: portable post-disposal mutation was previously unspecified and
  conflicts with the existing terminal lifecycle invariant.

## 4. Rejected alternatives

- **Add a lifecycle mutation helper and lock:** unnecessary protected API and
  cross-runtime locking semantics for one terminal check, with added risk of
  running consumer callbacks while a lifecycle lock is held.
- **Suppress only notifications:** cannot undo equality, mutation, hinting,
  validation, command-state work, or callbacks that happen first.
- **Require consumer cancellation only:** cancellation controls resources but
  cannot guarantee that an already-completed callback will not attempt a late
  assignment.
