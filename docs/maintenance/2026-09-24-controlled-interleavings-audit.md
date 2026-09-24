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

| Flavor     | Exact location and schedule                                                                                                                                                                                      | Disposition                                           | Evidence boundary and limit                                                                                                                                                                                                                                                                                                                                                                                |
| ---------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| C#         | `langs/csharp/tests/VMx.Tests/Components/ComponentVMLifecycleRaceTests.cs`, `Foreign_Dispose_Waits_For_Terminal_Publication_Held_By_Constructing_Observer`; `ComponentVMBase.AwaitLifecycleDeliveryUnlessCyclic` | Fixed                                                 | The test observes waiter registration on the exact terminal delivery event before checking that disposal and terminal publication remain pending. Removing the production wait fails the selected regression. Reflection of `ManualResetEventSlim.Waiters` is validated by the net8.0, net9.0, and net10.0 test targets; it does not cover the separate lifecycle-hook wait.                               |
| Python     | `langs/python/tests/unit/components/test_lifecycle_race.py`, `test_foreign_dispose_waits_for_terminal_publication_held_by_constructing_observer`; `_ComponentVMBase._await_lifecycle_publication`                | Fixed                                                 | A private test wrapper signals entry and delegates to the exact publication event wait. The coordinator waits for that signal, owns every future/error, and releases in cleanup. This proves VMx invoked the instance wait, not the standard library's internal implementation.                                                                                                                            |
| Rust       | `langs/rust/src/notifications.rs`, `post_waiter_remains_pending_until_resolve`; `langs/rust/src/token_paging.rs`, `token_cross_thread_hub_drainer_allows_reentrant_refresh_and_disposal`; `runtime::wait`        | Fixed with explicit boundary                          | A scoped `cfg(test)` observer acknowledges the exact condition identity; command collectors retain real fire-and-forget handles and raw results. The pager proves foreign hub-owner waiting before enqueue, then active-commit-owner reentrant refresh/disposal. It does not prove the separate hub-delivery-context branches; branch-only removal survived and remains an unproved runtime hypothesis.    |
| Swift      | `langs/swift/Tests/VMxTests/AsyncRelayCommandTests.swift`, `testCmd012ImmediateCancelDuringAdmissionIsNeverLost`; `AsyncRelayCommand.executeAsync`                                                               | Fixed, CI mutation evidence pending                   | Synchronous `canExecuteChanged` cancellation forces the window after executing state changes and before the body cancellation handle is installed. CI must record five normal passes, five selected assertion failures with pending forwarding removed, source restoration, and a rebuilt pass. The lifecycle blocked-wait oracle and fire-and-forget wrapper completion remain follow-up robustness work. |
| TypeScript | `langs/typescript/tests/unit/lifecycleRace.test.ts`; notification and token-paging suites; command error-routing turn drains                                                                                     | Valid controlled schedules with follow-up weak oracle | Deferred lifecycle scheduling, synchronous notification delivery, explicit fetch promises, and virtual scheduler advances control their modeled boundaries. Zero-delay command timers are event-loop drains, not native-thread proof. Positive error delivery can replace some drains; the no-error wrapper still lacks a terminal error-routing acknowledgment and remains follow-up robustness work.     |

## 13.3. Comparable Tests And Remaining Work

The focused fixes do not convert every concurrency test into the same mechanism.
C# and Python lifecycle stress cases align workers and assert invariants, but
still sample the buggy schedule. Their lifecycle-hook, confirmation-decorator,
and several raw-thread cleanup paths need distinct boundary observers or better
failure-path ownership. Rust's notification and pager regressions now own their
selected workers; the surviving hub-delivery-context mutants delimit what the
pager case proves. Swift lifecycle, notification, token-paging, and
fire-and-forget command tests contain useful causal gates but still have
unbounded cleanup or weak terminal acknowledgment in the locations described by
the issue audit. TypeScript's promise gates and virtual scheduler tests remain
valid; event-loop-turn drains must not be described as thread synchronization.

These items are classified as follow-up robustness, weak oracle, or unproved
runtime hypothesis. They are not evidence of a new shipping defect without a
reproduction that reaches the relevant boundary.

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
group and fails the experiment. Remote CI execution is required before this
planned evidence can be reported as observed.

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
