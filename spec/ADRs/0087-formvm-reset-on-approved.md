# ADR 0087 — Add declarative FormVM reset after approval

**Status:** Accepted (2026-07-10)
**Spec version:** introduced in 3.7.0

## 1. Context

Submit-then-clear is a common form lifecycle. A consumer can currently express
it only by capturing the `FormVM` variable before the form exists and mutating
that instance from its persister closure. Tableau used this pattern to clear a
consumed genesis `imagePayload`; without the reset, that transient payload could
silently seed the next submission.

Passing the mutable form back into its persister would remove the capture but
would also permit arbitrary re-entrant state changes during persistence and
would complicate the persister signature in every flavor. The reset transition
itself is the reusable behavior.

## 2. Decision

Every flavor adds an optional immutable-builder setting named idiomatically as
`resetOnApproved` / `ResetOnApproved` / `reset_on_approved`. The callback accepts
the model captured before persistence and returns the desired next pristine
model. Rust returns `VmxResult<M>` so callback failure remains explicit and
idiomatic; Swift marks its callback `throws`.

After persistence succeeds and the disposal guard passes, VMx calls the reset
callback once, applies the configured snapshotter twice to prepare independent
live and snapshot values, validates the prepared live value, and commits the
reset atomically. Only after that commit does `OnApproved` publish the captured
persisted model. An observer therefore receives the persisted payload while
reading an already-pristine, revalidated form. Strict approval is disabled by
that pristine state.

The reset is authoritative over a `SetModel` racing the persistence wait. This
matches the existing end-of-persister Tableau reset and makes the declarative
option deterministic: the callback input, reset result, and event payload all
derive from the captured persisted model, never the racing edit.

A callback or snapshot-preparation failure happens after persistence already
succeeded. Prepared values are not committed, `OnApproved` does not fire, and
the failure follows exactly one existing path: it propagates from the awaitable
approve operation, or the fire-and-forget command emits it once on
`ApproveErrors`. Retrying may repeat an already-successful persistence and must
be treated accordingly.

Invalid approval, persister failure/cancellation, disposal before completion,
and deny/revert never invoke the reset. Omitting the option preserves existing
approval behavior. Six conformance IDs (`FORM-024..029`) cover ordering,
snapshot/validation/strict integration, failure routing, skipped paths,
disposal, and racing mutation.

## 3. Consequences

- Consumers express submit-then-clear without temporal self-capture.
- Reset, dirty tracking, validation, and notification order are uniform across
  all five flavors.
- Snapshotters must remain consistent with model equality; reset calls them
  twice because the live model and snapshot must not alias.
- Callback failure clearly communicates the awkward but truthful state that the
  external persistence succeeded while local reset completion failed.
- The specification and stable flavors advance to 3.7.0; pre-1.0 Rust advances
  to 0.7.0.

## 4. Rejected alternatives

### 4.1 Pass a mutable form facade into the persister

Rejected. It invites re-entrant form mutation before persistence has settled,
couples persistence to FormVM state, and broadens five public persister
signatures for behavior better represented by one declarative callback.

### 4.2 Reset by assigning the callback result directly

Rejected. Direct assignment can alias the callback-owned value or the snapshot.
Applying the configured snapshotter twice preserves the form's declared copy
policy and prepares the transition before commit.

### 4.3 Preserve a model mutation that races persistence

Rejected for the configured-reset path. Conditional reset would make the option
timing-dependent and would not match the submit-then-clear behavior it replaces.
Consumers that need to preserve in-flight edits omit `resetOnApproved` and keep
the existing snapshot-advance semantics.

### 4.4 Emit both an awaited failure and `ApproveErrors`

Rejected. It would double-report one failure and violate the established
FormVM error split. The invocation surface determines the single observer.
