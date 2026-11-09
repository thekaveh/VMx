# ADR 0196 — Command enablement notifications for form updates and notification-VM disposal

- **Status:** Accepted
- **Date:** 2026-11-09
- **Spec version:** 3.30.0 (chapter 20 §5.2; chapter 16 §6.2)
- **Related:** [ADR-0031](0031-notification-rendering-vms.md),
  [ADR-0068](0068-disposed-relay-commands-are-inert.md),
  [ADR-0092](0092-form-model-hub-publication.md),
  [ADR-0143](0143-formvm-single-flight-approval.md),
  [ADR-0178](0178-rust-notification-vms-dispose.md), #1327, #1458.

## 1. Context

Two command-enablement notifications have no rule, and the flavors differ.

- **Approve notification for a form update (#1327).** Chapter 20 §5.2 step 9
  says only that `SetModel` invalidates `ApproveCommand` "when the existing
  strict/validity rules require it". C#, Python, TypeScript and Swift raise
  `ApproveCommand.CanExecuteChanged` when the update changes `IsValid`, or
  `IsDirty` in strict mode. Deny uses the same predicate. Rust computes the
  approve eligibility before and after the update. It raises the event only
  when that result flips, and never while an approval is in flight. Two cases
  differ. A strict-mode `SetModel` from a dirty, invalid model to a clean,
  valid model leaves `CanExecute` `false`; four flavors raise the event, and
  Rust does not. A `SetModel` that makes the form invalid during an approval
  raises the event in four flavors, and not in Rust. `FORM-032` fixes only
  the admission and settlement events.
- **Commands during notification-VM disposal (#1458).** `ConfirmationVM`
  disposal marks the VM disposed, then disposes `DismissCommand`,
  `ApproveCommand` and `RejectCommand` one at a time. Each disposed command
  raises one final `CanExecuteChanged` (chapter 04 §5). The commands have no
  predicate, so a command that is not yet disposed reports `CanExecute == true` inside that notification, while its `Execute` does nothing because
  the VM is disposed. All five flavors have this window. Chapter 04 §5
  defines only the state after disposal. The disposal order also differs:
  Python disposes approve, reject and then dismiss, and the other flavors
  dispose dismiss first.

## 2. Decision

Decided under the owner's 2026-11-07 delegation: each rule takes the simplest
option that is uniform across the five flavors.

### 2.1 A form update raises the approve notification when a gate input changes

An accepted unequal `SetModel`, a deny, and a Rust validator registration's
revalidation each raise `ApproveCommand.CanExecuteChanged` exactly once when
the update changes `IsValid`. In strict mode they also raise it exactly once
when the update changes `IsDirty`. An update that changes both raises it once,
and an update that changes neither raises nothing.

- The rule compares the two gate inputs, not the computed `CanExecute`
  result. An update can therefore raise the event while `CanExecute` stays
  `false`. This is allowed by chapter 04 §4: the event asks the consumer to
  re-read `CanExecute`, and it does not promise a change.
- An approval in flight does not suppress the event. The event adds to the
  admission and settlement events of `FORM-032`.

This is the four-flavor rule, and it is the simplest one: it reads two values
that the update already computes. Only Rust changes.

### 2.2 Commands report `CanExecute == false` from the start of VM disposal

`Dispose()` of a `NotificationVM` or `ConfirmationVM` first marks the VM
disposed. From that moment, each command that the VM owns reports
`CanExecute == false`. This holds also inside a `CanExecuteChanged`
notification that a command raises while `Dispose()` disposes the commands,
and also for a command that is not yet disposed. `Execute` stays a no-op, and
disposal does not resolve the notification. The order in which a VM disposes
its commands is not specified.

Each flavor gives each command a predicate that returns `false` once the VM is
disposed. A change of the disposal order alone cannot close the window,
because each command notifies before the next one is disposed. The predicate
changes nothing before disposal: the commands report `true` until then, as
before. The state after a resolution is out of scope.

## 3. Flavor impact

| Rule                          | C#        | Python    | TypeScript | Swift     | Rust    |
| ----------------------------- | --------- | --------- | ---------- | --------- | ------- |
| §2.1 approve notification     | test only | test only | test only  | test only | changes |
| §2.2 commands during disposal | changes   | changes   | changes    | changes   | changes |

## 4. Conformance

- `FORM-043` — an update raises `ApproveCommand.CanExecuteChanged` exactly once
  when it changes `IsValid`, or `IsDirty` in strict mode, and otherwise not,
  also during an approval.
- `NOTIF-018` — every command of a notification VM reports `CanExecute == false` in each notification raised during `Dispose()`, and disposal does
  not resolve the notification.

## 5. Consequences

- A Rust consumer receives more approve notifications than before: one for
  each gate change, also during an approval.
- A bound control reads every command of a disposing notification VM as
  disabled, so it never offers an action that does nothing.
- A consumer that called a notification-VM command from a disposal
  notification sees the same no-op result as before.

## 6. Rejected alternatives

- **Raise the approve notification only when `CanExecute` flips (the Rust
  rule).** It sends fewer events. But it changes four flavors, and it needs
  the in-flight state at every update.
- **Dispose the commands before the VM marks itself disposed.** A command
  disposed early would still notify while its siblings report `true`, so the
  window would stay open.
