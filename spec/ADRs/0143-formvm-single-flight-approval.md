# ADR 0143 — FormVM admits one approval at a time

- **Status:** Accepted
- **Date:** 2026-10-12
- **Spec version:** 3.27.0
- **Related:** [ADR-0048](0048-v3-form-vm-semantics.md) (captured `OnApproved`
  payload, `ApproveErrors`), [ADR-0087](0087-formvm-reset-on-approved.md)
  (authoritative reset), [ADR-0092](0092-form-model-hub-publication.md)
  (model assignment transaction), [ADR-0038](0038-spec-accuracy-corrections-and-form-014.md)
  (inert disposed form)

## 1. Context

`FormVM` has two approve entry points, `ApproveAsync` and the fire-and-forget
`ApproveCommand`. Neither had an admission rule. Each call captured the model,
released any state lock, and awaited the persister, so a second approval could
start while the first was still persisting (#327). A slower earlier persist
could then advance the snapshot, or install its reset, after a later one had
already finished. C#'s `_approvalPrePublishing` gate ordered publication only
after the await, and Rust called the persister holding no lock, so two threads
sharing a form overlapped.

Chapter 20 settled a persist racing `SetModel` or `Dispose`, but never two
approvals.

## 2. Options considered

1. **Single flight.** While an approval is in flight, the approve command is
   disabled and any other approve call does nothing. This matches the
   `AsyncRelayCommand` drop rule of chapter 04 §10.2 and needs no new public
   member.
1. **Queue.** A second approval waits for the first, then persists the model
   current at that point. Saves stay ordered, but the form needs a queue, the
   queued save may persist stale or unintended data, and disposal must drain
   it.
1. **Latest wins.** Overlapping persists are allowed and only the newest may
   commit. The earlier persist still wrote to storage, but its success would be
   hidden, and every flavor would need a commit generation.

## 3. Decision

Option 1. Chapter 20 §5.3 defines it:

1. **Admission.** An approve call through either entry point is admitted when
   the form is not disposed, is valid, and has no approval in flight.
   Admission is synchronous: mark the approval in flight, capture the model,
   raise `ApproveCommand.CanExecuteChanged` once, then invoke the persister. An
   admission observer that disposes the form prevents the persister call.
1. **Refusal.** While an approval is in flight, `ApproveCommand.CanExecute()`
   is `false` and any other approve call completes without persisting,
   mutating, throwing, or emitting. A refused call looks the same as approving
   an invalid form, wherever it comes from: the persister, a
   `CanExecuteChanged` handler, or another thread.
1. **Edits are not blocked.** `SetModel` and `DenyCommand` keep their existing
   racing-edit semantics: the approval commits its captured value, and a
   configured reset stays authoritative.
1. **Settlement.** After the post-persist commit, a persister failure or
   cancellation, or a failed post-persist commit (reset or snapshot
   preparation), the form clears the in-flight mark, then
   publishes `ErrorsChanged` if needed, raises `CanExecuteChanged` exactly once,
   and routes the outcome to exactly one channel. Every settlement observer
   therefore sees an idle form, and an approval it starts is admitted.
1. **Disposal.** Disposal during an in-flight approval suppresses settlement,
   as it already suppressed the post-persist work.

No public member is added. A bindable submission state (an `IsApproving` or
progress flag) is left to the submission-state design in #365, which builds on
this admission rule.

## 4. Consequences

- `FORM-031..034` cover refusal from every source, the command's
  `CanExecute` and notifications, settlement order and reentrancy, and edits,
  deny, and disposal during an approval, in all five flavors.
- All five flavors add an in-flight mark set at admission and cleared at
  settlement. No state lock is held while the persister runs or while
  observers are notified.
- **Compatibility.** Executing `ApproveCommand` twice quickly now persists once.
  A direct `ApproveAsync` made while another approval is in flight now returns
  without persisting, where before it started a second persist. Callers that
  need a save after the current one completes should await the in-flight
  `ApproveAsync` and approve again, or react to `OnApproved`.
  `ApproveCommand.CanExecuteChanged` now also fires on admission and settlement.
  This is a minor spec bump to 3.27.0.
