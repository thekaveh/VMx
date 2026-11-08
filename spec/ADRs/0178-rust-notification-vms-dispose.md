# ADR 0178 — Rust notification VMs dispose their commands

- **Status:** Accepted
- **Date:** 2026-11-08
- **Spec version:** 3.30.0 (amends the Rust note in chapter 16 §8.1; `DISP-004`)

## 1. Context

C#, Python, TypeScript and Swift `NotificationVM` and `ConfirmationVM` have a
dispose member. Disposal cancels the lifespan timer and releases the pending
subscription. It also disposes `DismissCommand`, `ApproveCommand` and
`RejectCommand`. A disposed command reports `CanExecute` false and its execute
is inert, so a kept command no longer resolves the hub. Disposal does not
resolve the notification, and a first resolution stays authoritative
(`DISP-004`).

Rust `NotificationVm` and `ConfirmationVm` had no `dispose()` and no disposed
state (#1067). Each `dismiss_command()`, `approve_command()` and
`reject_command()` call built a new `RelayCommand` around a clone of the view
model. A kept command therefore kept the view model alive and still resolved
the hub after the host dropped the list entry. Chapter 16 §8.1 said that Rust
`NotificationVm` has no `dispose`, so dropping the list entry releases it. The
reproduction in #1067 shows that this is not true for a kept command.
Chapter 16 §8.1 did not mention `ConfirmationVm`.

The issue offered two options: add disposal, or document the drop model.

## 2. Decision

Decided under the owner's 2026-11-07 delegation: Rust adds `dispose()` to both
view models, because every other flavor has it and the chapter 16 §8.1 recipe
disposes each removed VM. The rules follow the other flavors and the Rust
`ModalVm::dispose` shape.

- `NotificationVm::dispose(&self)` and `ConfirmationVm::dispose(&self)` return
  `()`, as `ModalVm::dispose` does. The first call claims disposal. A second
  call has no effect.
- Disposal does not resolve the notification. A pending notification stays in
  the hub's pending list with the `Pending` reaction. A reaction that resolved
  before disposal stays authoritative.
- Disposal disposes the dismiss command and, for a confirmation, the approve
  and reject commands. Each disposed command reports `can_execute()` false,
  sends one `can_execute_changed` message, and ignores `execute()`.
- Decided under the owner's 2026-11-07 delegation: each command accessor
  returns a clone of one stable command that the view model owns, as the other
  flavors expose one command per property. Clones of the view model share the
  commands and the disposed state. A command holds only the shared
  notification state, never the view model, so a kept command creates no
  reference cycle.
- After disposal, `dismiss()`, `approve()`, `reject()` and `advance_by_ms()`
  are inert. The lifespan clock stops, as the other flavors cancel the timer.
- Decided under the owner's 2026-11-07 delegation: after disposal,
  `is_resolved()` keeps the value it had at disposal and no longer reads the
  hub. The other flavors release their pending subscription at disposal, so a
  later hub resolution does not change their `IsResolved` either.
- Disposal never disposes the hub, which is shared infrastructure.
- Dropping a view model without disposal keeps the earlier behavior: a kept
  command still resolves the hub. Chapter 16 §8.1 says so and tells the host
  to call `dispose()` when an entry leaves the list.

`DISP-004` already covers repeated rendering-VM disposal. No conformance ID is
added. The Rust conformance suite now tests both view models under that ID.

## 3. Consequences

- Rust gains public `dispose()` members on `NotificationVm` and
  `ConfirmationVm`. The change is additive.
- `dismiss_command()`, `approve_command()` and `reject_command()` now return
  clones of one command instead of a new command for each call. A caller that
  disposed one returned command now disposes the command that the view model
  owns.
- Chapter 16 §8.1 drops the sentence that Rust `NotificationVm` has no
  `dispose`. The Rust exception in the disposal contract no longer lists the
  two view models as non-disposable.
- C#, Python, TypeScript and Swift do not change.
