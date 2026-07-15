# ADR 0109 — Propagate lifecycle failures through C# async entry points

**Status:** Accepted (2026-07-15)
**Spec version:** clarified in 3.22.0
**Supersedes:** the completion-only implementation detail in
[ADR-0008](0008-async-lifecycle-methods.md) and the C# error-routing wording in
[ADR-0047](0047-v3-lifecycle-threading-semantics.md)

## 1. Context

ADR-0008 makes `ConstructAsync`, `DestructAsync`, and `ReconstructAsync`
C#-specific TAP affordances. ADR-0047 later made lifecycle hook failure
transactional: the VM rolls back to its prior settled state before reporting
the original failure.

The C# implementation completed every registered lifecycle waiter successfully
whenever it observed any settled state. A failed background hook therefore
rolled back correctly but made the returned `Task` look successful. The same
loss occurred when a container deferred its terminal transition until an async
child cascade that later failed. This violated normal TAP expectations and
made the only C# outcome-bearing lifecycle surface unable to report failure.

Swift has no async lifecycle entry point. Its background scheduler accepts a
non-throwing closure, so a background hook error can only trigger rollback and
cleanup; it cannot be redelivered to the already-returned caller. That
flavor-specific limitation remains the divergence recorded by ADR-0053.

## 2. Decision

The C# async lifecycle methods report the operation outcome, not merely the
arrival of a settled status:

- A successful or idempotent transition completes its `Task` successfully.
- A hook or deferred child-cascade failure publishes the transactional rollback
  first, clears the in-flight guard, and then faults every waiter for that
  transition with the original exception.
- Cancellation of a deferred lifecycle task cancels its registered waiters.
- If terminal disposal wins the race, existing waiters complete at `Disposed`;
  the abandoned transition cannot overwrite that terminal outcome.
- The synchronous and fire-and-forget entry points retain their existing error
  routes. This decision only ensures that callers choosing the C# async surface
  can observe the same failure.

No cross-flavor conformance ID is added because the async entry points remain a
C#-only calling convention under ADR-0008. Python, TypeScript, Swift, and Rust
gain no artificial parity API.

## 3. Consequences

- `await vm.ConstructAsync()` can no longer report success after construction
  rolled back.
- Parent tasks preserve failures from background-enabled children instead of
  completing at the parent's rollback state.
- Rollback messages remain ordered before task continuations resume.
- Swift's background error-reporting limitation is explicit rather than
  described inconsistently as both rethrown and discarded.

## 4. Rejected alternatives

- Complete successfully after rollback: hides the operation failure and makes
  the task's result disagree with the requested terminal state.
- Fault before publishing rollback: lets an awaiter observe a transient or stale
  status after resumption.
- Add async lifecycle methods to every flavor: reverses ADR-0008 for a
  flavor-specific bug and introduces unrelated public APIs.
- Trap on Swift's background queue: converts a recoverable lifecycle failure
  into process termination without giving the original caller an awaitable.
