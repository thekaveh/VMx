# 13. Concurrency Test Audit

This ledger records the controlled-interleaving work for issue 348. It is a
source and test audit at the issue branch revision, not a claim that remote CI,
publication, or every possible runtime schedule has completed successfully.

## 13.1. Scope And Evidence Standard

The audit traced lifecycle publication, notification waiting, token-pager hub
draining, and command admission through the implementations and tests in all
five flavors. A deterministic regression must positively acknowledge the
boundary that establishes its ordering, retain ownership of spawned work and
errors, release its gates on failure, and observe completion. Time bounds are
diagnostics and external containment. They are forbidden as successful proof
that an operation entered a wait.

The selected negative controls alter the actual wait or cancellation-forwarding
operation, preserve a byte-exact original, run under a process-group watchdog,
and restore in `finally`. A control is rejected if it compiles no test, matches
no test, fails for another assertion, crashes, or times out when assertion-level
evidence is required. Deliberate deadlock mutants are recorded as externally
terminated outcomes, not as successful pending assertions.

## 13.2. Five-Flavor Disposition

| Flavor     | Exact location and schedule                                                                                                                                                                               | Disposition                                           | Evidence boundary and limit                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| C#         | `langs/csharp/tests/VMx.Tests/Components/ComponentVMLifecycleRaceTests.cs`, `Foreign_Dispose_Waits_For_Ordinary_Lifecycle_Publication`; `ComponentVMBase.AwaitLifecycleDeliveryUnlessCyclic`              | Fixed                                                 | The test observes waiter registration on the exact terminal delivery event before checking that disposal and terminal publication remain pending. Removing the production wait fails the selected regression. Reflection of `ManualResetEventSlim.Waiters` is validated by the net8.0, net9.0, and net10.0 test targets; it does not cover the separate lifecycle-hook wait.                                                                                                                                                    |
| Python     | `langs/python/tests/unit/components/test_lifecycle_race.py`, `test_foreign_dispose_waits_for_ordinary_lifecycle_publication`; `_ComponentVMBase._await_lifecycle_publication`                             | Fixed                                                 | A private test wrapper signals entry and delegates to the exact publication event wait. The coordinator waits for that signal, owns every future/error, and releases in cleanup. This proves VMx invoked the instance wait, not the standard library's internal implementation.                                                                                                                                                                                                                                                 |
| Rust       | `langs/rust/src/notifications.rs`, `post_waiter_remains_pending_until_resolve`; `langs/rust/src/token_paging.rs`, `token_cross_thread_hub_drainer_allows_reentrant_refresh_and_disposal`; `runtime::wait` | Fixed with explicit boundary                          | A scoped `cfg(test)` observer acknowledges the exact condition identity; command collectors retain real fire-and-forget handles and raw results. The pager proves foreign hub-owner waiting before enqueue, then active-commit-owner reentrant refresh/disposal. It does not prove the separate hub-delivery-context branches; branch-only removal survived and remains an unproved runtime hypothesis.                                                                                                                         |
| Swift      | `langs/swift/Tests/VMxTests/AsyncRelayCommandTests.swift`, `testCmd012ImmediateCancelDuringAdmissionIsNeverLost`; `AsyncRelayCommand.executeAsync`                                                        | Fixed, supported-Xcode delivery gate required         | Synchronous `canExecuteChanged` cancellation forces the window after executing state changes and before the body cancellation handle is installed. Before delivery, the supported-Xcode gate must record five normal passes, five selected assertion failures with pending forwarding removed, source restoration, and a rebuilt pass; the issue 348 delivery record is the place to record those observed outcomes. The lifecycle blocked-wait oracle and fire-and-forget wrapper completion remain follow-up robustness work. |
| TypeScript | `langs/typescript/tests/unit/lifecycleRace.test.ts`; notification and token-paging suites; command error-routing turn drains                                                                              | Valid controlled schedules with follow-up weak oracle | Deferred lifecycle scheduling, synchronous notification delivery, explicit fetch promises, and virtual scheduler advances control their modeled boundaries. Zero-delay command timers are event-loop drains, not native-thread proof. Positive error delivery can replace some drains; the no-error wrapper still lacks a terminal error-routing acknowledgment and remains follow-up robustness work.                                                                                                                          |

## 13.3. Comparable Tests And Remaining Work

The focused fixes do not turn every concurrent test into the same mechanism.
The items below are public, independently actionable follow-up records. A
bounded wait may diagnose a missing positive event; it does not establish that
another worker is blocked. None of the follow-up or weak-oracle items is a new
shipping defect without a reproduction at the named boundary.

### 13.3.1. C\#

1. **Follow-up robustness:**
   [`langs/csharp/tests/VMx.Tests/Components/ComponentVMLifecycleRaceTests.cs`](../../langs/csharp/tests/VMx.Tests/Components/ComponentVMLifecycleRaceTests.cs)
   `Opposing_Active_Lifecycle_Hooks_Cross_Dispose_Without_Deadlock` (line 39),
   `Concurrent_Construct_Is_Rejected_While_First_Construct_Is_In_Flight`
   (line 371), `Opposing_Lifecycle_Observers_Can_Dispose_Each_Other_Without_Deadlock`
   (line 569), and `ConstructAsync_Faults_When_Background_Child_Rolls_Back`
   (line 330) use genuine hook/barrier or release-gate ordering. Their limits
   are unchecked barrier/release results or scheduler errors and worker cleanup
   that can be skipped after a failed assertion. Make release and join ownership
   unconditional before strengthening their outcome assertions.
1. **Stress, not a forced schedule:** the same file's
   `Background_Construct_Racing_Dispose_Never_Resurrects_Or_Publishes_PostDispose`
   (line 494) and the 16-contender lifecycle stress case (lines 652--678) are
   useful invariant sampling, but a start gate does not select a buggy
   interleaving. Keep them as stress coverage; add a boundary observer only if
   a particular wait/order contract is being claimed.
1. **Weak oracle:**
   [`langs/csharp/tests/VMx.Tests/Commands/ConfirmationDecoratorCommandTests.cs`](../../langs/csharp/tests/VMx.Tests/Commands/ConfirmationDecoratorCommandTests.cs)
   `Dispose_Waits_For_InFlight_Error_Delivery` (line 34) signals before
   `Dispose` and infers contention from elapsed time. Its actual shared
   boundary is `_errorGate` in
   [`langs/csharp/src/VMx/Commands/ConfirmationDecoratorCommand.cs`](../../langs/csharp/src/VMx/Commands/ConfirmationDecoratorCommand.cs). It needs a
   monitor-admission strategy and `finally`-owned worker completion; the
   lifecycle event-waiter technique is not applicable to `Monitor.Enter`.
1. **Follow-up robustness:**
   [`langs/csharp/tests/VMx.Tests/Commands/AsyncRelayCommandTests.cs`](../../langs/csharp/tests/VMx.Tests/Commands/AsyncRelayCommandTests.cs)
   `Predicate_Can_Wait_For_Foreign_Dispose_Without_Deadlock` (line 27), and
   [`langs/csharp/tests/VMx.Conformance.Tests/CommandConformanceTests.cs`](../../langs/csharp/tests/VMx.Conformance.Tests/CommandConformanceTests.cs)
   `CMD_012_Cancel_Cancels_InFlight_Async_Task_NonThrowing` (line 284) and
   `CMD_012_Concurrent_ExecuteAsync_Does_Not_Double_Run` (line 405), use
   positive state/progress checks. Retain them, but collect raw worker errors
   and release awaited tasks on every failure path. The notification callback
   test `Opposing_Hub_Callbacks_Do_Not_Deadlock` (line 227) and token-pager
   tests `Refresh_Supersedes_An_Older_InFlight_LoadMore` (line 134) and
   `Refresh_PageComparer_DoesNotRunUnderStateGate` (line 253) likewise need
   failure-path task ownership; they are not evidence of a competing-thread
   drainer wait.

### 13.3.2. Python

1. **Weak oracle:**
   [`langs/python/tests/unit/components/test_lifecycle_race.py`](../../langs/python/tests/unit/components/test_lifecycle_race.py)
   `test_foreign_dispose_waits_for_ordinary_lifecycle_publication`
   is repaired, but the nearby disposer-from-`_set_status` case (lines 223--259)
   still treats an unobserved race as acceptable. Its retained limit is that a
   thread-start signal does not prove ownership-lock admission; add that exact
   boundary observer before treating it as a regression.
1. **Follow-up robustness:** the same module's opposing lifecycle
   observer/hook cases (lines 306--414), plus its 8,000-iteration stress loop,
   establish callback overlap or invariants but leave raw worker errors and
   failure-path joins incomplete. Keep the stress case as supplementary
   coverage; make barrier results, release, and joins owned by cleanup.
1. **Follow-up robustness:**
   [`langs/python/tests/unit/commands/test_async_relay_command.py`](../../langs/python/tests/unit/commands/test_async_relay_command.py) lines 182--224,
   260--405 and
   [`langs/python/tests/unit/commands/test_confirmation_decorator_command.py`](../../langs/python/tests/unit/commands/test_confirmation_decorator_command.py)
   lines 95--125 use positive completion/entry signals. The short sleeps are
   polling backoff or loop turns, not blocked-thread proof; capture worker
   exceptions and release/await tasks on assertion failure.
1. **Valid controlled schedule with cleanup follow-up:**
   [`langs/python/tests/conformance/test_col_024_to_031_token_paged_composition.py`](../../langs/python/tests/conformance/test_col_024_to_031_token_paged_composition.py)
   lines 138--167 explicitly gates fetch entry and release, so it controls the
   refresh-before-old-result order. Ensure both tasks release and finish in
   cleanup. Its lines 49--76 and 171--190 use `asyncio.sleep(0)` only to drain
   an event-loop turn; replace it with fetch-entry acknowledgment if an
   in-flight admission claim becomes material.
1. **Follow-up weak oracle:**
   [`langs/python/tests/conformance/test_commands.py`](../../langs/python/tests/conformance/test_commands.py) lines 306--394 and the
   selected confirmation tests use cancellation targets or event-loop drains,
   not native-thread synchronization. Directly await positive error/completion
   events where that is the intended assertion. The worker-posted and opposing
   callback cases in `test_notifications.py` lines 406--465 retain worker
   error/join ownership work; no runtime fault is established.

### 13.3.3. Rust

1. **Weak oracle:**
   [`langs/rust/tests/conformance/lifecycle.rs`](../../langs/rust/tests/conformance/lifecycle.rs)
   `foreign_disposal_waits_for_an_admitted_lifecycle_hook` (line 47) and
   `concurrent_admission_cannot_escape_disposal_snapshot` (line 719) use a
   thread-entry signal followed by a negative 50-ms receive. Add actual
   lifecycle-hook/disposal-admission boundary acknowledgments and a release
   guard. `disposed_parent_skips_post_hook_child_construction` (line 91) has
   stronger positive state evidence but still needs failure-path release/join;
   the opposing-hook/callback tests (lines 132--167 and 491--549) retain
   bounded cleanup work.
1. **Weak oracle:**
   [`langs/rust/tests/conformance/notifications.rs`](../../langs/rust/tests/conformance/notifications.rs)
   `concurrent_pending_delivery_matches_committed_snapshot_order` (line 128),
   `concurrent_resolve_returns_after_its_queued_snapshot_and_waiter_completion`
   (line 197), and
   `concurrent_dispose_returns_after_queued_terminal_publication_and_completions`
   (line 501) observe committed state before a negative receive. Observe
   `PendingPublicationCompletion::wait` in
   [`langs/rust/src/notifications.rs`](../../langs/rust/src/notifications.rs) directly, bound polling, and make gates
   releasable on failure. `concurrent_notification_hub_dispose_publishes_one_terminal_snapshot`
   (line 565) is stress/exclusivity coverage, while
   `post_racing_dispose_never_orphans_its_waiter` (line 593) leaves its waiter
   thread untracked; neither proves a selected schedule.
1. **Weak oracle or stress:**
   [`langs/rust/tests/conformance/collections.rs`](../../langs/rust/tests/conformance/collections.rs)
   `serviced_collection_foreign_publisher_waits_and_delivers_on_caller_thread`
   (line 448) starts the foreign publisher before inferring it is blocked;
   instrument the actual delivery-admission boundary. The 32-worker
   `keyed_serviced_concurrent_upserts_publish_each_committed_add_position`
   (line 1015) and
   `serviced_collection_concurrent_pushes_publish_in_committed_position_order`
   (line 1050) are stress tests. `token_paging_dispose_wins_against_an_in_flight_loader`
   (line 1613) has a real loader boundary but still needs a release/join guard.
1. **Weak oracle:**
   [`langs/rust/tests/conformance/token_paging.rs`](../../langs/rust/tests/conformance/token_paging.rs)
   `nested_commits_keep_foreign_disposers_waiting_for_the_outer_guard`
   (lines 625--665) needs acknowledgments for both `request_dispose` waits and
   outer-guard cleanup. In `commands.rs`,
   `async_relay_command_cancel_cancels_in_flight_task` (line 425) and
   `repeated_async_command_dispose_cancels_one_in_flight_execution` (line 656)
   use polling sleeps/unbounded `is_executing` spins; use entry/release channels
   and bounded cleanup. `async_relay_command_immediate_cancel_is_not_lost_during_admission`
   (line 452) is useful bounded stress, not a forced admission boundary, and
   the detached `can_execute` worker at lines 395--397 must be joined.
1. **Unproved runtime hypothesis:** the repaired pager test demonstrates the
   selected foreign-hub-owner wait and reentrant commit path only. Mutants that
   remove separate hub-delivery context remain outside that proof; deliberate
   cyclic-lock mutants require subprocess containment rather than an in-process
   join timeout.

### 13.3.4. Swift

1. **Weak oracle and cleanup follow-up:**
   [`langs/swift/Tests/VMxTests/LifecycleRaceTests.swift`](../../langs/swift/Tests/VMxTests/LifecycleRaceTests.swift)
   `testDisposeDuringReconstructDestructHookSkipsConstructPhase` (line 240)
   acknowledges the destruct hook but uses a completion-semaphore timeout for
   the disposer. Instrument the foreign-hook wait in
   [`langs/swift/Sources/VMx/Lifecycle/ComponentVMBase.swift`](../../langs/swift/Sources/VMx/Lifecycle/ComponentVMBase.swift), propagate the
   reconstruct result, and release/join both participants on every path. Its
   `testBackgroundConstructRacingDisposeNeverResurrectsOrPublishesPostDispose`
   (line 406) is bounded stress despite its loop, and
   `testOpposingLifecycleObserversDisposeEachOtherWithoutDeadlock` (line 80)
   plus `testOpposingActiveLifecycleHooksCrossDisposeWithoutDeadlock` (line 126)
   retain unbounded group waits and swallowed worker errors.
1. **Follow-up robustness:**
   [`langs/swift/Tests/VMxTests/AsyncRelayCommandTests.swift`](../../langs/swift/Tests/VMxTests/AsyncRelayCommandTests.swift) `CancellationRaceGate.waitUntilObserved`
   (line 77) and the external-first/command-first tests (lines 441--469) have
   real cancellation ordering but need bounded, independently releasable
   cleanup. `testCmd012ExecuteDoesNotRouteCancellationToErrorsWhenThrowOnCancelIsSet`
   (line 496) uses a 200-ms inverted error expectation (lines 499 and 517)
   before wrapper error routing is known; acknowledge the fire-and-forget
   wrapper's error decision, then count errors.
1. **Follow-up robustness:**
   [`langs/swift/Tests/VMxTests/NotificationHubConcurrencyTests.swift`](../../langs/swift/Tests/VMxTests/NotificationHubConcurrencyTests.swift)
   `testPostThenResolvePublishesInMutationOrder` (line 148) and
   `testPostThenDisposePublishesSnapshotBeforeCompletion` (line 199) correctly
   use `OneShotDrainGate` (line 28), `beforeDeliveryDrain`, and
   `afterDeliveryEnqueued`, but its waits and task completion need abort/release
   cleanup. `testOpposingHubCallbacksResolveWithoutDeadlock` (line 251) must
   retain/join its callback task; an irrecoverable deadlock mutant belongs in an
   externally bounded process.
1. **Valid controlled schedule with cleanup follow-up:**
   [`langs/swift/Tests/VMxTests/TokenPagedCompositionTests.swift`](../../langs/swift/Tests/VMxTests/TokenPagedCompositionTests.swift)
   `testRefreshSupersedesAnOlderInFlightLoadMore` (line 134) and
   `testRefreshDoesNotMutateOrNotifyWhenDisposedDuringFetch` (line 172) force
   fetch entry through continuations. Give their continuation owner an abort
   state so failure cannot strand registered or late waiters, then dispose and
   join outstanding work.
1. **Separate unproved runtime hypothesis:**
   [`examples/swift/notes-showcase/Tests/NotesShowcaseTests/NotesViewVMTests.swift`](../../examples/swift/notes-showcase/Tests/NotesShowcaseTests/NotesViewVMTests.swift)
   `testReconstruct_keeps_items_via_rebind` (line 337) is associated with a
   recorded index-out-of-range crash, but no application stack identifies the
   access. `ImmediateDispatcher` and zero-debounce search may overlap
   reconstruct with callback work; this is not a proven lifecycle-locking fix.
   A separate investigation must capture the application stack or force that
   overlap, then select one executor/scheduler policy and drain/cancel search
   work during cleanup. Do not mask it with retries, delays, or a disabled test.

### 13.3.5. TypeScript

1. **Valid controlled schedules:**
   [`langs/typescript/tests/unit/lifecycleRace.test.ts`](../../langs/typescript/tests/unit/lifecycleRace.test.ts)
   `ComponentVM – dispose during in-flight background construct` (line 28)
   controls a deferred dispatcher; [`langs/typescript/tests/unit/notifications/notificationHub.test.ts`](../../langs/typescript/tests/unit/notifications/notificationHub.test.ts)
   `NotificationHub pending delivery` (line 10) checks synchronous/reentrant
   ordering; and [`langs/typescript/tests/conformance/col-024-to-031-token-paged-composition.test.ts`](../../langs/typescript/tests/conformance/col-024-to-031-token-paged-composition.test.ts)
   uses explicit fetch promises for the load/refresh and reentrant-comparer
   cases (lines 48--69, 131--190). Preserve these schedules and add owned
   settlement/subscription cleanup when touching them.
1. **Follow-up weak oracle:**
   [`langs/typescript/tests/conformance/commands.test.ts`](../../langs/typescript/tests/conformance/commands.test.ts) CMD-012 cases at
   lines 604--669, and
   [`langs/typescript/tests/unit/confirmationDecoratorCommand.test.ts`](../../langs/typescript/tests/unit/confirmationDecoratorCommand.test.ts)
   `execute() is safe when confirm rejects` (line 8) plus the two VMX-009 error
   cases (lines 37 and 52), use zero-delay timers at lines 636, 665, 21, 48,
   and 65. These are event-loop-turn drains, not foreign-thread evidence.
   Subscribe to the expected positive error before `execute()` and await it
   with a diagnostic timeout where the error is expected. The no-error CMD-012
   case still needs a terminal wrapper/error-routing acknowledgment; idle state
   alone is not that acknowledgment because `asyncRelayCommand.ts` clears it
   before error routing. Do not replace the timers with an arbitrary single
   promise hop or add a public API solely for this test.

## 13.4. CI Evidence Contract

Ubuntu C#, Python, and Rust jobs run the selected command three times normally
and three times with `taskset` restricted to one CPU from
`os.sched_getaffinity(0)`. Each invocation has a 120-second command timeout and
five-second kill grace, prints its mode and run number, and fails the step on
the first unsuccessful run. Python retains the selected matrix interpreter
through `tools/check-python-interpreter.py`. C# targets the unit project across
all three target frameworks. Rust repeats the locked all-features full suite,
and the package matrix compiles and runs `cfg(test)` unit helpers with Rust
1.88.0 before preserving the existing package and consumer checks.

The macOS Swift workflow runs the focused test five times, removes only pending
admission-cancellation forwarding, and requires five exit-1 runs whose sole
XCTest diagnostic is the stable selected cancellation assertion. It restores
the exact production bytes in `finally`, rebuilds, and requires a final pass.
Every child starts in a new process group; a 120-second watchdog kills the whole
group and fails the experiment. Supported-Xcode execution is a mandatory
delivery gate: before publication, issue 348 must record its observed outcome
(including normal, mutant, restoration, parser, and watchdog evidence). This
ledger defines the required check and does not claim that a remote run has
already occurred.

## 13.5. Unchanged Contract And Cascade

The work changes test scheduling and CI evidence only. Public APIs, normative
behavior, the 403 library conformance IDs, five scenario IDs, specification
chapters and ADRs, `spec/VERSION`, flavor package versions and minimum-spec
declarations, compatibility matrix, changelogs, shared fixtures, package
dependencies, and package inventories are unchanged. Existing conformance
markers remain attached when the two Rust regressions move from integration to
unit scope; neither moved test owned a catalog marker.

No production caller or sample requires migration: the C# and Python wait
observers are private test mechanisms, Rust helpers and collectors compile only
under `cfg(test)`, and Swift uses existing public command behavior. The C#,
Python, TypeScript, Swift, and Rust examples therefore retain their APIs and
source. Documentation is canonical in `docs/content` and this maintenance
ledger; repository site and wiki projections are generated through the existing
manifest pipeline. Live site/wiki publication and remote rendered review remain
delivery steps after the branch gates pass.
