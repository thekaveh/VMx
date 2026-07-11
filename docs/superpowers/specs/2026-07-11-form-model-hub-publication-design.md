# FormVM Model Hub Publication Design

## Context

`FormVM.setModel` is the public edit path used by controlled UI fields. In C#,
Python, TypeScript, and Swift it currently replaces the model, reruns validation,
and may invalidate the approve command without publishing any model property
message on the injected hub. A hub-backed UI store therefore cannot observe an
ordinary form edit. Tableau worked around that gap by wrapping every genesis edit
in a command that calls both `setModel` and an application-wide refresh.

Rust is not actually silent: `FormVm` delegates to an embedded `ComponentVm`, so
ordinary assignment publishes before form validation and command state settle.
That delegation also makes deny/revert publish two differently cased model
messages and makes `reset_on_approved` publish a model message that chapter 20
does not specify. Issue #128 therefore requires a portable FormVM contract rather
than four isolated sends.

## Decision

An accepted, unequal `SetModel` / `set_model` call publishes exactly one
flavor-idiomatic model `PropertyChangedMessage` on the configured hub. Publication
is the final step of the synchronous form-edit transaction, after the live model,
validation errors, validity, dirty state, and approve-command state are current.

The operation sequence is normative:

1. reject a call that begins after disposal, before inspecting the candidate;
1. reject a null candidate in flavors whose public contract permits a null check;
1. compare the candidate with the live model using the same equality mechanism
   used by that flavor's dirty tracking;
1. return without mutation, validation, command work, or notification when equal;
1. capture the previous dirty and valid state;
1. replace the live model;
1. rerun validation and publish `ErrorsChanged` only for an effective error-map
   change;
1. invalidate the approve command when the existing strict/validity rules require
   it; and
1. publish one model property message on the hub.

The property name follows ADR-0006: `"Model"` in C# and `"model"` in Python,
TypeScript, Swift, and Rust. The sender remains the `FormVM` identity. No new local
`propertyChanged` surface is added to FormVM.

## Equality and compatibility

No-op detection reuses the form's configured or idiomatic equality:

- C#: `object.Equals` through the model's value equality;
- Python: `__eq__`;
- TypeScript: the configured `equals` predicate, or the existing structural
  deep-equal default;
- Swift: the configured `equals` predicate, including the `Equatable` convenience
  initializer's `==`; and
- Rust: `PartialEq`.

This means an equal replacement object is retained rather than installed. Its
validators do not rerun and it emits nothing. This is an intentional compatibility
change from the four standalone implementations, which previously replaced equal
values silently. It aligns FormVM assignment with ordinary modeled-VM equality
gating and leaves an explicit equal-value republish API to #89. #128 does not add
`force`, `touch`, or `republishModel`.

## Observable ordering and re-entrancy

Hub publication occurs last so a synchronous subscriber that reads the form sees
the accepted model and its settled validation and command state. A subscriber may
re-enter `setModel` with another unequal value. The nested call completes its own
validation and command work and publishes once; the outer call performs no state
work after its hub send returns. The final model is therefore the nested value,
with one model message for each accepted unequal assignment.

Validators retain their current failure behavior. The change does not attempt to
make validation transactional: if a validator throws after assignment, the
exception propagates under the existing flavor behavior and the final hub message
is not sent. Adding validator rollback would be a separate contract change.

The null/default hub remains a null-object path. An accepted assignment still
settles local form state and does not throw; sending through the null hub produces
no externally delivered message. Rust's non-nullable default isolated
`MessageHub` is the language-idiomatic equivalent.

## Deny and approval reset boundaries

`DenyCommand` keeps its existing chapter 20 contract: restore and revalidate,
then publish exactly one `FormRevertedMessage` followed by exactly one model
property message. Its existing command-invalidation position is unchanged. Rust
will use a silent internal model replacement for the restore so the embedded
component cannot emit an early `"model"` message before the explicit form pair.

`resetOnApproved` also keeps its existing contract. Approval reports through
`OnApproved`, `ApproveErrors`, validation/error signals, and command state; it does
not acquire a new model hub message. Rust will use the same silent internal
replacement for the authoritative reset, removing its accidental component-level
publication. Direct Rust `set_model`, by contrast, explicitly notifies only after
form state is settled.

The Rust-only implementation seam is a private `ComponentVm` model replacement
helper that returns whether the value changed. Public `ComponentVm.set_model`
continues to use that helper and preserves its current notification contract;
`FormVm` uses it only where the form owns notification timing. No public API or
new abstraction is introduced in the other flavors.

## Disposal and concurrency boundary

The #141 admission rule remains first: a call that begins after disposal performs
no null/equality check, mutation, validation, command work, or notification. A
call admitted before disposal remains synchronous and completes its ordinary
transaction. #128 introduces no new locks or cross-runtime concurrency model.

## Specification, versions, and conformance

ADR-0092 records the decision and advances the spec from 3.11.0 to 3.12.0. C#,
Python, TypeScript, and Swift advance to 3.12.0; Rust advances to 0.12.0 and
declares spec 3.12.0. This is a minor behavioral addition and equality convergence.

One new catalog entry, `FORM-030`, covers:

- exactly one model hub message for an unequal assignment;
- equality-gated silence without validator or command work;
- settled validation/command visibility at hub publication;
- synchronous re-entrant assignment and exact counts;
- inert post-dispose assignment;
- null/default hub behavior;
- exactly ordered, non-duplicated deny messages; and
- no model hub publication from `resetOnApproved`.

Every full-parity flavor supplies a real test with exactly one `FORM-030` marker.
The library catalog moves from 340 to 341 IDs and the total including five
`THEME-00x` scenarios moves from 345 to 346.

## Documentation and consumer proof

The canonical FormVM and disposal documentation will explain equality gating,
notification order, property-name idioms, deny/reset boundaries, and when #89's
future explicit republish is appropriate. Generated in-repo documentation, the
MkDocs `.io` site, and the GitHub wiki must remain synchronized. No architecture
diagram changes because component boundaries do not change.

A no-push Tableau pilot will use the VMx worktree, remove the
`setGenesisModel` refresh wrapper and its obsolete explanation, route controlled
inputs directly through `genesis.setModel`, and rerun the real CreatePanel
reactivity regression plus the relevant workspace typechecks/tests. Application
refreshes that recompute unrelated shell projections remain out of scope.

## Alternatives considered

1. **Prepare/commit/notify last in the existing FormVMs (selected).** Gives hub
   subscribers settled state, handles re-entrancy cleanly, and needs only surgical
   changes plus one private Rust seam.
1. **Append a send to the four silent implementations.** Rejected because it
   preserves Rust's early publication, duplicate revert messages, reset leak, and
   observable cross-flavor ordering differences.
1. **Make every FormVM inherit or compose the full ComponentVM implementation.**
   Rejected because C#, Python, TypeScript, and Swift intentionally ship FormVM as
   a standalone edit lifecycle. Refactoring that architecture would be much
   broader than the notification bug.

## Acceptance mapping

- ADR-0092 and chapter 20 define unequal/equal/disposed behavior and exact order.
- `FORM-030` exercises every accepted edge case in all five flavors.
- Rust's private replacement seam removes its deny duplication and approval-reset
  leak without changing public ComponentVM behavior.
- Version, changelog, compatibility, count, and three-surface documentation
  updates make the compatibility effect visible.
- The Tableau pilot proves a hub-backed controlled form no longer needs the
  bespoke refresh wrapper.
