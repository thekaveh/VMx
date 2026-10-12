# ADR 0144 — FormVM model updates are failure-atomic

- **Status:** Accepted
- **Date:** 2026-10-12
- **Spec version:** 3.28.0
- **Related:** [ADR-0092](0092-form-model-hub-publication.md) (model assignment
  transaction), [ADR-0087](0087-formvm-reset-on-approved.md) (prepared reset),
  [ADR-0071](0071-form-validation.md) (declarative validation),
  [ADR-0143](0143-formvm-single-flight-approval.md) (approval admission)

## 1. Context

In C#, Python, TypeScript, and Rust, `SetModel` installed the candidate before
running validators (#337). A throwing validator therefore left the new model in
place with the old errors, the old command state, and no notification: a new
model with old validity. Chapter 20 §5.2 said "Validator failures retain their
existing flavor behavior; this contract does not add rollback", so consumers
could rely on neither a completed nor a reverted update. Persistence and the
approval reset were already failure-atomic (FORM-007, FORM-026).

## 2. Options considered

1. **Prepare, then commit.** Run every fallible callback on the candidate first
   and commit only a completed preparation. A failure propagates with the form
   unchanged.
1. **Commit and mark invalid.** Install the model and turn the exception into a
   validation error. This hides application bugs as user-facing validation and
   needs a designed error key; the issue warns against it.
1. **Status quo.** Document each flavor's partial state.

## 3. Decision

Option 1. Chapter 20 §5.4 defines it:

1. **Preparation.** `SetModel` and `DenyCommand` run the equality comparison,
   the field and model validators, and (for deny) the snapshotter before any
   commit. Preparation changes no form state.
1. **Failure.** A failing callback propagates unchanged to the caller. Model,
   snapshot, errors, dirty and valid state, and command state keep their
   values, and nothing is published. A failure is never turned into a
   validation error. Construction runs the same preparation, so a failing
   validator fails construction.
1. **Serialization and re-entrancy.** Updates stay serialized: another
   thread's update, approval commit, or disposal waits for an update in
   progress, so an admitted update completes normally (chapter 02 §7) and a
   concurrent edit is never silently dropped. A callback that re-enters the
   form from the preparing thread can still dispose it or commit another
   update; the outer preparation is then stale and commits and publishes
   nothing, and the newest committed state stands. Each flavor tracks this
   with a commit generation or an equivalent check.
1. **Flavor boundaries.** A Rust panic in a callback is the failure and unwinds
   with the form unchanged and leaves no lock poisoned or held.
   Swift callbacks cannot throw, so only the re-entrancy and disposal rules
   apply there.

## 4. Consequences

- `FORM-035..038` cover field-validator, model-validator, equality, and deny
  failures, a nested assignment from a validator, and disposal during
  preparation, in all five flavors. The existing error-deduplication,
  captured-payload, and reset tests (`FORM-021`, `FORM-024..029`) are unchanged.
- **Compatibility.** A consumer that caught a validator exception and then read
  the form saw the new model with stale errors; it now sees the previous model.
  A validator that reads the form's `Model` during an update now sees the
  previous model rather than the candidate; validators receive the candidate as
  their argument and should read it there. A validator that re-enters
  `SetModel` now has its outer call abandoned rather than applied after the
  nested one. No public member is added. This is a minor
  spec bump to 3.28.0.
