# Post-Dispose Modeled Assignment Design

## Context

VMx treats disposal as a terminal lifecycle transition, but modeled assignment is
not yet uniformly terminal. `ComponentVMOf` in C#, Python, TypeScript, Swift, and
Rust can still evaluate equality, replace the retained model, recompute the modeled
hint, or invoke a consumer callback after disposal. `FormVM` already rejects such
assignments in C#, Python, and Rust, while TypeScript and Swift still mutate and
revalidate. This allows a late async completion to reactivate retained state after
the owning screen has been torn down.

Issue #141 makes terminal behavior explicit and portable: an assignment that
starts after disposal is a complete no-op.

## Contract

For every publicly or internally settable modeled VM, the disposal check occurs
before any candidate-value work. When the VM is already disposed, assignment:

- does not evaluate model equality or a configured equality callback;
- does not replace the model or snapshot;
- does not recompute a modeled hint or run validation;
- does not update command state;
- does not invoke `onModelChanged` or another consumer callback; and
- emits no local notification or hub message.

The terminal check is an admission rule. An assignment admitted before disposal
retains the existing property-change contract and completes normally; an assignment
that begins after the terminal state is visible does nothing. This matches the
existing notification-helper rule without introducing a new cross-flavor locking
or cancellation abstraction. Upstream operations should still be cancelled when
practical because cancellation controls application resources; the VM guard is the
last line of defense against a late result.

## Affected surfaces

- `ComponentVMOf` / modeled `ComponentVM` setters in all five flavors gain an
  early terminal guard before equality.
- TypeScript and Swift `FormVM.setModel` gain the guard already present in C#,
  Python, and Rust.
- Swift `ReadonlyComponentVMOf._setModel` inherits the modeled-component guard;
  no separate implementation is required.
- Modeled composites are audited but unchanged: their model type feeds a child
  factory and they expose no settable retained model.
- Forwarding wrappers are unchanged because they delegate to guarded instances.

No new public API is introduced.

## Specification and conformance

The spec advances from 3.10.0 to 3.11.0 through ADR-0091. Stable flavors advance
from 3.10.0 to 3.11.0; Rust advances from 0.10.0 to 0.11.0 while declaring spec
3.11.0. The change is a minor contract convergence because portable post-disposal
mutation was never specified and conflicts with the terminal lifecycle invariant.

One new cross-cutting catalog entry, `DISP-014`, covers both modeled components
and forms. Every flavor's real test must prove retained state, hint/snapshot,
validation, callbacks, equality/validator counters, notifications, and command
signals remain unchanged after disposal. Tests also exercise a late assignment
scheduled from a callback or async-completion-shaped closure after disposal.

The catalog moves from 339 to 340 library IDs and from 344 to 345 total IDs when
the five `THEME` scenarios are included.

## Documentation and consumer proof

Canonical documentation will update the disposal contract, component-family page,
and FormVM page. Generated in-repo documentation, MkDocs site, and GitHub wiki must
remain byte-for-byte reproducible from those sources. Architecture diagrams do not
change because no component boundary or data flow is added.

A no-push DayDreams pilot will point at the ticket worktree, preserve cancellation
needed for network/renderer resource control, and remove or simplify only the
VMx-specific zombie-model defense. Existing consumer tests must remain green, and
the pilot evidence will be recorded on #141 rather than committed to VMx.

## Alternatives considered

1. **Early guards in each real setter (selected).** Smallest change, prevents all
   user work before it starts, and matches existing FormVM practice.
1. **A new lifecycle mutation helper.** Rejected because it would add protected
   API and cross-runtime locking semantics for a single terminal check, while
   risking external callbacks under lifecycle locks.
1. **Rely on property-notification suppression.** Rejected because notification
   occurs after equality, mutation, hint recomputation, validation, and callbacks;
   it cannot enforce inert state.

## Acceptance mapping

- Normative lifecycle/component/form wording and ADR-0091 define the rule.
- `DISP-014` provides real five-flavor conformance coverage.
- Setter guards cover modeled components and forms; audits document why modeled
  composites, forwarding wrappers, and read-only variants need no distinct code.
- Version, compatibility, changelog, count, and three-surface documentation updates
  make the compatibility effect visible.
- The DayDreams pilot demonstrates that framework-specific zombie-state reasoning
  can be removed without weakening application-level cancellation.
