# ADR 0187 — A membership change fails at once during another thread's transaction

- **Status:** Accepted
- **Date:** 2026-11-09
- **Spec version:** 3.30.0 (chapter 06 §4.2; chapter 07 §1.1)
- **Extends:** [ADR-0118](0118-isolate-container-membership-transactions.md)
  to other threads. Related:
  [ADR-0122](0122-defer-container-disposal-through-membership-transactions.md),
  [ADR-0153](0153-cyclic-cross-thread-container-disposal-defers-to-the-owner.md),
  [ADR-0165](0165-initial-current-uses-committed-membership.md),
  [ADR-0172](0172-one-wait-for-graph-per-flavor.md),
  [ADR-0173](0173-selection-commits-without-a-membership-transaction.md),
  #551, #718, #756, #1314.

## 1. Context

A *membership transaction* covers one add, insert, index replacement or
population of a container, from preflight to commit or rollback. When a child
moves, the transaction also holds the old parent's transaction during the
detach. ADR-0118 makes the transaction exclusive and rejects a re-entrant
mutation on the owner thread. It did not say what a call from another thread
does.

Chapter 06 §4.2 makes a disposal from another thread wait for the
transaction boundary, and refuses a wait that would close a wait-for cycle
(ADR-0122, ADR-0153). Selections never wait (§4.3, ADR-0173). No rule covered
admission or removal from another thread. At `349ca128`, the threaded flavors
gave these results:

| Flavor | Composite admission                       | Group admission                           | `remove`, `removeAt`, `clear`                                                           |
| ------ | ----------------------------------------- | ----------------------------------------- | --------------------------------------------------------------------------------------- |
| C#     | Throws `InvalidOperationException`.       | Waits, with cycle refusal (#718).         | Throw `InvalidOperationException`.                                                      |
| Python | Raises `RuntimeError`.                    | Raises `RuntimeError`.                    | Raise `RuntimeError`.                                                                   |
| Rust   | Returns `OwnershipTransactionInProgress`. | Returns `OwnershipTransactionInProgress`. | `remove` and `remove_at` return the error. `clear` returns with no change and no error. |
| Swift  | Waits, with cycle refusal (#551).         | Waits, with cycle refusal.                | Wait. A refused wait leaves the container unchanged. `remove` returns `false`.          |

TypeScript runs on one thread, so only the same-thread case occurs. `Move`
fails at once in every flavor while a transaction is open. Open decision
§2.10 recorded the split (#756).

## 2. Decision

### 2.1. Owner decision

The owner delegated #1314 on 2026-11-07. It is decided under that delegation:
all flavors follow the same rules as far as possible, and the simplest,
most common-sense rule wins. The rule is option 2, *fail at once*, for
admission and for removal.

### 2.2. Rules

Chapter 06 §4.2 states these rules, and chapter 07 §1.1 applies them to
groups.

1. **No wait.** A *membership change* is `Add`, `Insert`, index replacement,
   population, the detach of a child that moves out of the container,
   `Remove`, `RemoveAt` and `Clear`. A membership change never waits for
   another thread's membership transaction of the same container.
1. **Fail before mutation.** While any thread holds the container's
   transaction, a membership change on that container fails before it changes
   anything. It fails in the same way on the owner thread (ADR-0118) and on
   any other thread. The membership, the parent links, `Current` and the
   event stream stay unchanged.
1. **A refused detach fails the transfer.** When the old parent refuses the
   detach, the add that moves the child fails and rolls back like any failed
   transfer (§4.2). The destination and the old parent stay unchanged.
1. **The existing error.** A refusal uses the "membership transaction in
   progress" error that the flavor raises for a re-entrant change:
   - C# throws `InvalidOperationException`.
   - Python raises `RuntimeError`.
   - TypeScript throws `Error`.
   - Swift returns `ContainerOwnershipError.attachmentFailed` from the result
     forms (`addResult`, `insertResult`, `replaceResult`). A population
     failure propagates from `construct()`. `remove(_:)` returns `false`.
     `add(_:)` keeps its debug assertion: a refused call traps in a debug
     build and returns with no change in a release build. `insert(_:at:)`,
     `replace(at:with:)`, `removeAt(_:)` and `clear()` cannot throw, so a
     refused call returns with no change.
   - Rust returns `VmxError::OwnershipTransactionInProgress`. `clear()`
     returns `VmxResult<()>`, and a refused `clear()` returns that error.
1. **Disposal still waits.** A disposal from another thread waits for the
   transaction boundary, as chapter 06 §4.2, ADR-0122 and ADR-0153 say.
   Selection keeps the rules of §4.3. A structural change that waits for a
   child's ownership gate keeps its wait (chapter 03 §4.1).

### 2.3. Choices made under the owner's delegation

- Decided under the owner's 2026-11-07 delegation: fail at once, not wait. A
  transaction runs consumer code: attachment and construct hooks, and its
  `CollectionChanged` publication. That code can wait for another thread in a
  way that no wait-for graph sees. ADR-0165 §1 rejected a wait for this
  reason, and ADR-0173 extended it to every selection. A wait can then
  deadlock two threads with no refusal. A failure cannot. Disposal keeps its
  wait, because it cannot fail and it has a deferral escape.
- Decided under the owner's 2026-11-07 delegation: the rule is the same on
  every thread. A thread that calls during another thread's transaction gets
  the error that a re-entrant call gets. No caller needs a second case.
- Decided under the owner's 2026-11-07 delegation: removal follows admission.
  `Remove`, `RemoveAt` and `Clear` open the same exclusive transaction, so one
  rule covers every membership change. Before, the C# group waited for an
  add but threw for a removal.
- Decided under the owner's 2026-11-07 delegation: a refused `clear` reports
  its refusal wherever the surface has an error channel. Rust `clear()`
  therefore returns `VmxResult<()>`, like `remove` and `remove_at`. Swift
  `removeAt(_:)` and `clear()` have no error channel. Adding one is a Swift
  API decision. Open decision §3 lists them with the other Swift signatures
  that cannot throw.
- Decided under the owner's 2026-11-07 delegation: this rule does not change
  the ownership-gate wait of chapter 03 §4.1. That wait is a separate
  resource, and no issue reproduces a defect in it.
- Decided under the owner's 2026-11-07 delegation: `COMP-048` and `GRP-016`
  cover the rule. In C#, Python, Swift and Rust, the change comes from another
  thread. In TypeScript, it comes from the owner's call chain, the only way
  that a TypeScript container has an open transaction.

## 3. Flavor impact

- **C#.** `GroupVMBase.BeginMembershipTransactionLocked` drops the
  `Monitor.Wait` loop and calls `EnsureChildAdmission`, as
  `CompositeVMBase.BeginMembershipTransactionLocked` does. The group then
  fails at once for add, insert, replacement, population and transfer detach.
  `WaitForForeignTransactionLocked` stays for disposal. The composite keeps
  its behavior.
- **Python.** No change. The tests for the new IDs confirm the rule.
- **TypeScript.** No change. The tests for the new IDs confirm the rule.
- **Swift.** `tryEnterMembershipTransaction` in `CompositeVM` and `GroupVM`
  throws `ContainerOwnershipError.attachmentFailed(ContainerMembershipTransactionError())`
  when another thread owns the transaction. It records no membership wait.
  `remove`, `removeAt` and `clear` then fail at once. The disposal wait stays.
  The doc comment of `enterMembershipTransaction` states the rule.
- **Rust.** `CompositeVm::clear` and `GroupVm::clear` return `VmxResult<()>`.
  They return `OwnershipTransactionInProgress` when the transaction does not
  open, and the error that `remove_at` returns when the container is disposed.
  Admission and removal already fail at once.

Tests that assert a wait change. They are the C# group test
`Cross_Thread_Add_Without_Cycle_Waits_Then_Succeeds` and the Swift tests that
expect a cross-thread population to succeed after a wait, for example
`testReversedConcurrentPopulationCompletesWithoutSplitOwnership`. Each now
expects one change to fail at once and both containers to keep single
ownership.

## 4. Conformance

- `COMP-048` covers the rule for `CompositeVM`.
- `GRP-016` covers the rule for `GroupVM`.

This ADR adds these two library IDs, after the two of ADR-0186.

## 5. Consequences

- A cross-thread add, insert, replacement or population no longer waits in a
  C# group or in Swift. It fails at once, and the caller can retry after the
  other transaction ends.
- A Swift `add(_:)` that another thread's transaction refuses now traps in a
  debug build. Before, it waited and then succeeded. In a release build, it
  returns with no change and no signal, as `insert(_:at:)` and
  `replace(at:with:)` do. A caller that can meet another thread's
  transaction uses `addResult`, `insertResult` or `replaceResult` to see the
  refusal and retry.
- A cross-thread `remove`, `removeAt` or `clear` no longer waits in Swift.
- Rust `clear()` reports a refusal. A caller that ignored the unit return now
  handles a `VmxResult<()>`.
- No membership change can deadlock on another thread's transaction.
- Open decision §2.10 in
  `docs/maintenance/2026-10-18-open-cross-flavor-decisions.md` is decided.

## 6. Rejected alternatives

- **Wait** (option 1). It deadlocks when consumer code in the transaction
  waits for the waiting thread, and ADR-0165 already rejected that wait for
  selection. It also adds waits and graph edges to C# composites, Python and
  Rust.
- **Leave it flavor-defined** (option 3). A two-thread population would keep
  succeeding in Swift and in a C# group and failing elsewhere.
