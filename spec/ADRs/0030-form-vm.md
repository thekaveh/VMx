# ADR 0030 — `FormVM<TM>` (snapshot/revert edit lifecycle, ORM-agnostic)

**Status:** Accepted (2026-05-28)
**Spec version:** introduced in 2.1.0

## 1. Context

VMx.old and My.Architecture.New both ship a `FormVM<TContext, TM, TVM>` coupled to
specific ORMs (WCF RIA `DomainContext` / EF `DbContext`). The pattern is real and
recurring: a ViewModel wraps a domain model with **edit lifecycle** — snapshot on
construct, allow mutation, then either Approve (persist) or Deny (revert).

v2.x VMx is presentation- and ORM-agnostic. The legacy coupling to an ORM context
must go.

## 2. Options considered

1. Skip — consumers reinvent the snapshot/revert pattern themselves.
1. Couple to a generic persister abstraction baked into VMx.
1. Decouple — persist is a consumer-supplied `Func<TM, Task>` delegate or an
   `IFormPersister<TM>` collaborator the consumer implements.

## 3. Decision

Option 3 (ORM-agnostic). `FormVM<TM>` members:

- `Model: TM` — live, editable
- `Snapshot: TM` — read-only after construct
- `IsDirty: bool` — derived from structural inequality of `Model` vs `Snapshot`
- `DenyCommand: ICommand` — reverts `Model` to `Snapshot`, raises hub messages
- `ApproveCommand: ICommand` — invokes persister delegate; on success updates
  `Snapshot` to current `Model` and raises `OnApproved`
- `OnApproved` event/observable — fires only after a successful persist

Snapshot policy: per-flavor idiomatic shallow copy (C# `with` expression on records;
Python `dataclass.replace` semantics or `Snapshotter<TM>` delegate; TypeScript
`structuredClone` for plain object models). Custom `Snapshotter<TM>` is opt-in
at construction time (constructor argument in C# / Python, `FormVMOptions`
field in TS).

Strict mode (opt-in): `Approve.CanExecute = IsDirty`. Default mode:
consumer-controlled (`Approve.CanExecute = true`).

## 4. Consequences

1. New chapter `spec/20-form-vm.md` defines the contract.
1. Ten conformance IDs `FORM-001..FORM-010`.
1. New `FormRevertedMessage` type per flavor.
1. Per-flavor `forms/` directory.
1. Integration with `IDialogService.Confirm` (ADR-0029) is a documented composition
   pattern, not a normative dependency. `FORM-010` exercises this integration via
   `DenyCommand` wrapped with `ConfirmationDecoratorCommand`.
