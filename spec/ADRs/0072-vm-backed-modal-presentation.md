# ADR 0072 — Add VM-backed modal presentation

**Status:** Accepted (2026-07-01)
**Spec version:** introduced in 3.1.0

## 1. Context

`IDialogService` covered file pickers, two-way confirmation, and notifications,
but consumers also need host-presented modals whose result is domain-specific:
resume/discard/keep decisions, first-run flows, and other VM-backed dialogs.

The aws-tui adoption feedback showed that those cases can compose existing VMx
primitives internally, but still need a host seam that can present an arbitrary
modal VM and return its typed result.

## 2. Decision

Add a small result-bearing modal VM contract and a modal presentation capability:

- modal VMs expose `CancellationResult`, `Result`, `IsDismissed`, completion,
  `Dismiss(result)`, and disposal;
- dismissal is idempotent and the first result wins;
- disposal completes with the cancellation result;
- null modal presentation immediately resolves with the cancellation result;
- existing file/confirm/notify methods remain source-compatible.

Where a language can add a default `Present` method without breaking existing
implementers, it does. C# and TypeScript expose a modal-capable service extension
interface/capability so existing `IDialogService` implementations remain valid.

## 3. Consequences

Consumers can keep domain modal state in ViewModels and route host presentation
through one service seam. Binary yes/no confirmation remains the simpler
`Confirm` method; `Present` is for richer result types.

The modal primitive intentionally does not prescribe a view registry, widget
factory, or persistence behavior. Host adapters decide how a modal VM maps to UI.

## 4. Rejected alternatives

Expanding `Confirm` into an N-way choice API was rejected because it still would
not cover multi-step or form-backed modals.

Adding `Present` as a mandatory method on every C#/TypeScript `IDialogService`
implementation was rejected because it would break existing implementers.
