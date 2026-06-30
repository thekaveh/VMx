# ADR 0063 — Swift Phase-3 Inc-5 forced divergences (notifications / dialogs: NOTIF / DIA)

**Status:** Accepted (2026-06-30)
**Spec version:** 3.0.0 (subset — Phase 3, Increment 5)
**Relates-to:** [ADR-0006](0006-idiomatic-api-per-language.md) (idiomatic surface per
language), [ADR-0009](0009-cross-flavor-divergence-catalogue.md) (cross-flavor
divergence catalogue), [ADR-0013](0013-notification-service.md) (opt-in
`VMx.Notifications` sub-package), [ADR-0029](0029-dialog-service-in-core.md)
(`IDialogService` in core), [ADR-0031](0031-notification-rendering-vms.md)
(notification rendering VMs), [ADR-0037](0037-v2.5-maintenance-clarifications.md)
(Swift subset origin), [ADR-0056](0056-v3-async-command-cancellation.md)
(v3 async command cancellation — DIA-007 non-throwing default),
[ADR-0059](0059-swift-leaf-area-divergences.md) (Swift Phase-3 Inc-1 divergences),
[ADR-0060](0060-swift-collections-divergences.md) (Swift Phase-3 Inc-2 divergences),
[ADR-0061](0061-swift-hierarchical-threading-divergences.md) (Swift Phase-3 Inc-3
divergences), [ADR-0062](0062-swift-forms-commands-hub-divergences.md) (Swift
Phase-3 Inc-4 divergences)

## 1. Context

Phase 3, Increment 5 (`swift-parity-inc5`) ports the dialog service and the
opt-in notifications sub-package to Swift, expanding the Swift conformance
subset from 193 to 218 IDs:

| Area  | New IDs          | Delta |
| ----- | ---------------- | ----- |
| DIA   | `DIA-001..008`   | +8    |
| NOTIF | `NOTIF-001..017` | +17   |

All 25 new IDs have test markers in `langs/swift/Tests/VMxTests/` and entries
in `langs/swift/conformance-subset.txt`.

Swift's structured-concurrency model, Combine's non-throwing sink API, ARC
memory model, and the absence of a framework virtual-time scheduler require
idiomatic adaptations across both new areas. These are **forced divergences**,
not defects — each preserves the observable behavior mandated by the spec while
remaining idiomatic Swift. This ADR records them per ADR-0009 §2 so they are
not re-litigated as bugs in future maintenance passes.

## 2. Decision

Accept the following idiomatic divergences; they are normatively equivalent to
the canonical TypeScript reference implementation unless stated otherwise.

### 2.1 `DialogService` methods are `async`, not `throws` — `DIA-001..008`

**Divergence:** The four `DialogService` protocol methods (`pickFileToOpen`,
`pickFileToSave`, `notify`, `confirm`) are declared `async` rather than
`async throws`. A dialog that is cancelled or dismissed returns the safe
default (`nil` for file-picker results, `false` for `confirm`) instead of
throwing (DIA-007). This is the same design principle applied to
`AsyncRelayCommand` in ADR-0062 §2.1: the non-throwing cancellation path is
the default; throwing is an opt-in.

**`String?` path result (not `URL?`):** `pickFileToOpen` and `pickFileToSave`
return `String?` rather than `URL?`. This matches the cross-flavor fixture
contract, which represents file paths as strings. A `URL?` return would be
more idiomatic Swift but would require callers to serialize to a string before
using the result with spec-mandated `String`-typed parameters — a silent
divergence from the fixture shape. The `String?` surface is the deliberate
parity choice.

**No Combine publishers in the dialog contract:** `DialogService` is a
request/response async protocol (one call → one `await`-ed result). There are
no Combine publishers on the dialog surface. This is a deliberate
counterpart to the stream-based `NotificationHub` (§2.2–§2.4): dialogs are
ephemeral, directional, and have a single synchronous result; notifications are
long-lived, broadcast, and observer-driven.

**`confirmWithDialogService` fluent overload:** `FluentCommands.swift` gains a
`confirmWithDialogService(_:_:_:) -> Command` free function that wraps a
`ConfirmationDecoratorCommand` whose confirm gate is `await dialog.confirm(prompt, title: nil)`.
This is a convenience surface for DIA-008 (compose a dialog-confirmed command
without writing the lambda explicitly). The overload returns `Command` (the
non-parameterized type) and the downcast inside tests to
`ConfirmationDecoratorCommand` is unconditionally safe since the function
always constructs and returns one.

**`NullDialogService`:** `NullDialogService: DialogService` implements all
four methods with the safe default: file pickers return `nil`, `confirm`
returns `false`, `notify` is a no-op. The singleton is exposed as
`public static let INSTANCE = NullDialogService()` (matching the
`NullMessageHub.INSTANCE` precedent from ADR-0059 §2.2).

**Consequence:** Future maintenance passes that see `DialogService` methods
without `throws` must consult this ADR. The non-throwing `async` signature is
deliberate (DIA-007 alignment). File-path returns typed as `String?` are also
deliberate (cross-flavor fixture parity, not a Swift oversight).

### 2.2 Notifications sub-package is a directory in the single `VMx` module — `NOTIF-001..017`

**Divergence:** The other flavors express the opt-in notifications sub-package
in different ways: C# ships a separate `VMx.Notifications` assembly; Python
and TypeScript keep it as a sub-directory in the same distribution (`vmx/notifications/`
and `src/notifications/` respectively). Swift follows the Python/TypeScript
pattern: the notifications types live in a `Notifications/` directory under
`langs/swift/Sources/VMx/`, compiled as part of the single `VMx` library
target. There is no companion SwiftPM product or separate `Package.swift` entry.

The C# companion-assembly model is rejected for Swift because:

1. SwiftPM does not support companion libraries that share a module namespace
   with the parent package without a separate `Package.swift` target. Adding a
   second `VMx` target would create a module conflict.
1. Python and TypeScript already establish the pattern that a single-distribution
   opt-in sub-directory is conformance-equivalent to C#'s companion assembly
   (the spec does not mandate a specific packaging shape, only that the types be
   opt-in).

**Consequence:** Future maintenance passes that see notifications types in
`Sources/VMx/Notifications/` (rather than a separate SwiftPM product) must
consult this ADR. The co-location is deliberate and matches the Python/TypeScript
packaging model.

### 2.3 `Notification` is a `final class` (identity-keyed) — `NOTIF-001..008`

**Divergence:** `Notification` is a `final class`, not a `struct`. Waiters
(continuations inside `post`) are keyed by `ObjectIdentifier(notification)`:
each `Notification` instance must be reference-identical across its
`post`/`resolve` lifetime. A Swift struct would be copied on every assignment,
making `ObjectIdentifier`-based keying impossible.

**`post` suspends via `withCheckedContinuation`:** `NotificationHub.post(_:)`
stores the caller's `CheckedContinuation<NotificationReaction, Never>` in a
`[ObjectIdentifier: CheckedContinuation<NotificationReaction, Never>]` dictionary
(protected by `NSLock`) before emitting the updated pending snapshot. The
store-then-emit ordering guarantees that a subscriber that calls `resolve` in
response to the `pending` snapshot always finds the waiter registered.

**`pending` via Combine `CurrentValueSubject` (replay-latest):** The
`pending: AnyPublisher<[Notification], Never>` channel is backed by a
`CurrentValueSubject<[Notification], Never>`. This gives new subscribers the
current snapshot on subscription (replay-latest), matching the spec contract
(a subscriber that attaches after some notifications have been posted still
sees the current pending set).

**Snapshots emitted outside the `NSLock`:** All `subject.send` calls and
`continuation.resume` calls happen after the lock is released. This prevents
re-entrancy deadlock in the case where a sink attached via `pending.sink` calls
`hub.resolve` synchronously in response to a `send` (which would try to
re-acquire `NSLock` on the same thread if the send were inside the lock).

**Consequence:** Future maintenance passes that see `Notification` as a `final class` (not a struct) must consult this ADR. The reference-type choice is
load-bearing for NOTIF-001/008 (identity-keyed waiters). Future passes that see
`subject.send` outside the lock must not move it inside — the unlock-then-send
ordering prevents the re-entrancy deadlock described above.

### 2.4 Hand-rolled `VirtualTimeScheduler` — `NOTIF-011..016`

**Divergence:** Combine has no framework virtual-time scheduler. The other
flavors' reactive libraries provide one: rxjs has `TestScheduler`, reactivex
has `TestScheduler`, System.Reactive has `TestScheduler`. Swift uses a
hand-rolled `VirtualTimeScheduler: Combine.Scheduler` (in
`Sources/VMx/Services/VirtualTimeScheduler.swift`), following the same
rationale as the Inc-3 `ManualScheduler` (ADR-0061 §2.7).

`VirtualTimeScheduler` implements the full `Combine.Scheduler` protocol:

- `SchedulerTimeType: Strideable` wrapping `seconds: Double`; `distance` /
  `advanced` implemented.
- `SchedulerTimeType.Stride: SchedulerTimeIntervalConvertible, Comparable, SignedNumeric` wrapping `value: Double` — provides `seconds`/`milliseconds`/
  `microseconds`/`nanoseconds` conversions, arithmetic operators, and
  `Magnitude = Double` for `Numeric` conformance.
- `schedule(options:_:)` — enqueues immediate work at the current instant.
- `schedule(after:tolerance:options:_:)` — enqueues at a given future instant.
- `schedule(after:interval:tolerance:options:_:)` — single fire at `date`
  (virtual clock never re-fires autonomously), returns `Cancellable`.

A `schedule(at:_:) -> AnyCancellable` convenience is added (label `at:`, not
`after:`): Combine's `Scheduler` protocol extension already provides a
`schedule(after:_:) -> Void` convenience; a same-label `-> AnyCancellable`
overload would collide on overload-by-return-type. The `at:` label is
distinct, unambiguous, and gives the VM a cancel handle for its expiry timer.

`advance(to:)` pops every scheduled item with `dueTime ≤ target` in
stable order `(dueTime, seq)`, setting `now` to each item's due time just
before firing it (so work scheduled by a firing action is picked up in the
same advance), then sets `now = target`. An `NSRecursiveLock` guards the
queue and clock; `work()` runs with the lock released (re-entrancy safe).

**Time unit — seconds (`TimeInterval`) not milliseconds:** All timer
parameters in `NotificationVM` and `ConfirmationVM` (`lifespan`, `remaining`,
`opacity`) use `Double` seconds (`TimeInterval`). The TypeScript implementation
uses milliseconds (`lifespanMs`). This is an instance of the ADR-0009
time-property divergence (Swift follows the Combine/Foundation convention of
`TimeInterval` in seconds; TypeScript convention is milliseconds for DOM-
adjacent APIs).

**Single-resolution guard:** `NotificationVM` uses a plain boolean `resolved`
flag (no lock — see below). All resolution entry points (`dismiss()`,
`approveCommand`/`rejectCommand`, the expiry-timer callback, and the
external-resolve sink on `hub.pending`) funnel through a single
`markResolved(...)` method that sets `resolved = true` **before** it calls
`hub.resolve`. The guard makes every entry point idempotent — the first one
wins; subsequent calls are no-ops. Because `markResolved` flips the flag before
notifying the hub, the synchronous self-echo of the VM's own `hub.resolve`
(re-entering through the `pending` sink) also hits the guard and no-ops.

No lock is needed here: the conformance contract is single-threaded
run-to-completion — the `VirtualTimeScheduler` runs scheduled work synchronously
on the caller, and Combine sinks fire on the same thread — so the four entry
points cannot interleave. (The `NSLock` mentioned elsewhere in this ADR belongs
to `NotificationHub`, not `NotificationVM`.)

**`ConfirmationVM` never arms the expiry timer:** `NotificationVM.armsExpiryTimer()`
is an `open` method (default `true`). `ConfirmationVM` overrides it to return
`false`. The override is called via dynamic dispatch during `super.init`, so no
auto-dismiss timer is ever armed for confirmation notifications. `onExpire()` is
also overridden to a no-op for completeness.

**Consequence:** Future maintenance passes that see "no framework TestScheduler
in Swift" must consult ADR-0061 §2.7 and this ADR §2.4 before importing a
third-party scheduler. `VirtualTimeScheduler` is the single hand-rolled
scheduler for both threading (Inc-3) and notification-timer (Inc-5) tests.
Future passes that see `schedule(at:)` (not `schedule(after:)`) in VM code
must not rename it — the `at:` label is deliberate (Combine extension collision
avoidance, documented above).

### 2.5 NOTIF-017 dispose semantics

**Divergence:** `NotificationHub.dispose()` is implemented on the concrete
`NotificationHub` class (not on the `NotificationHubProtocol`), matching the
TypeScript shape where `INotificationHub` omits `dispose` and the concrete
class carries it. `NullNotificationHub` is therefore unaffected.

The dispose sequence:

1. Acquire `NSLock`; set `disposed = true`; drain all pending `waiters`
   (continuations) into a local copy; release lock.
1. Resume each captured continuation with `.pending` (in-flight `post` callers
   unblock with the safe default instead of hanging forever).
1. Call `subject.send(completion: .finished)` (outside the lock) to complete
   the `pending` `CurrentValueSubject`.

A `post` call racing with `dispose` is closed by a double-check: the initial
`guard !disposed` at the top of `post` is a fast path inside the lock; inside
the `withCheckedContinuation` closure, a second `guard !disposed` check detects
the case where `dispose` ran after the continuation was created but before it
was stored. In that race, the continuation is resumed immediately with `.pending`
(no continuation is enqueued), matching the "post-after-dispose returns
`.pending` without enqueuing" contract.

`dispose()` is idempotent: the `guard !disposed` at the top of `dispose()`
makes a second call a no-op.

**Consequence:** Future maintenance passes that see in-flight `post` callers
unblocked with `.pending` on dispose (not an error or `.reject`) must consult
this ADR. The `.pending` resume is the deliberate safe-default for callers that
lose the race with `dispose`.

### 2.6 `NullNotificationHub` — `NOTIF-009`

**Note (informative):** `NullNotificationHub.pending` is implemented as
`Just([Notification]()).eraseToAnyPublisher()` (a synchronous, always-empty
publisher). This is the idiomatic Swift null-object for a `CurrentValueSubject`-
backed `pending` channel: it emits the empty-list snapshot exactly once on
subscription and completes. `NullNotificationHub.post` returns `.approve`
immediately (no suspension). This matches the `NullMessageHub` / `NullDispatcher`
null-object convention established in ADR-0059 §2.2.

## 3. Consequences

- The 25 new Swift conformance IDs (`DIA-001..008`, `NOTIF-001..017`) are
  claimed in `langs/swift/conformance-subset.txt` and verified by
  `tools/check-conformance-coverage.py`.
- The Swift subset grows from 193 to **218 of 237** library IDs.
- The remaining 19 library IDs (`COMP-007/008/011/014..024/027`,
  `GRP-007..010`) and the `THEME-00x` flagship scenario IDs are deferred to
  subsequent increments.
- Future maintenance passes that see `DialogService` methods without `throws`
  must consult §2.1 — the non-throwing `async` signature is deliberate.
- Future maintenance passes that see `Notification` as a `final class` (not a
  struct) must consult §2.3 — the reference-type choice is load-bearing for
  identity-keyed waiters.
- Future maintenance passes that see `VirtualTimeScheduler` (a hand-rolled
  `Combine.Scheduler`) must consult §2.4 and ADR-0061 §2.7 before replacing it
  with a third-party scheduler.
- Future maintenance passes that see `schedule(at:)` (not `schedule(after:)`)
  must consult §2.4 — the `at:` label is deliberate (Combine extension
  collision avoidance).
- Future maintenance passes that see in-flight `post` callers resume with
  `.pending` on dispose (§2.5) must not change this to `.reject` — `.pending`
  is the specified safe default for callers that lose the race with `dispose`.

## 4. Rejected alternatives

1. **Declare `DialogService` methods as `async throws`.** Rejected: the spec
   (ADR-0056 / DIA-007) specifies that cancellation and safe-dismiss return the
   safe default without throwing. A throwing signature forces callers to
   `try await` every dialog call and handle a cancellation error that is not an
   error condition. The non-throwing `async` signature is correct per the spec.
1. **Return `URL?` from file-picker methods (Swift-idiomatic).** Rejected: the
   cross-flavor fixture contract represents file paths as strings. A `URL?`
   return would introduce a silent type mismatch between the Swift surface and
   the spec fixture shape. `String?` preserves fixture parity across all flavors.
1. **Ship notifications as a separate SwiftPM library target (matching C#'s
   `VMx.Notifications` companion assembly).** Rejected: SwiftPM does not support
   two targets sharing a module namespace without a module conflict. Python and
   TypeScript already establish the precedent that a `Notifications/` directory
   in the same distribution is conformance-equivalent. A companion target would
   require a separate `import VMxNotifications` in consumer code, breaking the
   single-`import VMx` surface.
1. **Make `Notification` a struct.** Rejected: struct instances are copied on
   every assignment, making `ObjectIdentifier`-based waiter keying impossible.
   `ObjectIdentifier` requires a class instance (or metatype). A value-type
   `Notification` cannot satisfy NOTIF-001/008's identity-distinct-waiter
   contract.
1. **Use a third-party virtual-time Combine scheduler.** Rejected: introducing
   an additional dependency for test infrastructure conflicts with the
   project-wide constraint of not introducing additional reactive libraries
   (CLAUDE.md). The hand-rolled `VirtualTimeScheduler` is a minimal
   `Combine.Scheduler` conformance that is validated by `swift build`
   (Scheduler conformance is checked at compile time) and whose behavior is
   covered by the NOTIF-011..016 test suite.
1. **Resume in-flight `post` waiters with `.reject` on dispose.** Rejected: the
   spec safe-default for a cancelled/interrupted wait is the pending state (not
   rejection). Resuming with `.pending` unblocks callers without asserting a
   deliberate rejection that the hub did not produce.
