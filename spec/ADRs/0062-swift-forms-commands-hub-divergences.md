# ADR 0062 — Swift Phase-3 Inc-4 forced divergences (forms / commands / hub: FORM / CMDD / CMD / HUB / HIER-014)

**Status:** Accepted (2026-06-29)
**Spec version:** 3.0.0 (subset — Phase 3, Increment 4)
**Relates-to:** [ADR-0006](0006-idiomatic-api-per-language.md) (idiomatic surface per
language), [ADR-0009](0009-cross-flavor-divergence-catalogue.md) (cross-flavor
divergence catalogue), [ADR-0012](0012-command-decorators.md) (command decorators),
[ADR-0030](0030-form-vm.md) (`FormVM<TM>` design),
[ADR-0037](0037-v2.5-maintenance-clarifications.md) (Swift subset origin),
[ADR-0048](0048-v3-form-vm-semantics.md) (v3 FormVM — injectable deep-equal,
approve error channel), [ADR-0049](0049-v3-command-semantics.md) (v3 commands —
confirmation-decorator `errors` channel),
[ADR-0052](0052-v3-public-surface-breaking-removals.md) (drop `RelayCommandOfT`
alias), [ADR-0053](0053-swift-converge-illegal-transition-and-non-child-current-to-throw.md)
(Swift throwing convergence), [ADR-0056](0056-v3-async-command-cancellation.md)
(v3 async command cancellation), [ADR-0059](0059-swift-leaf-area-divergences.md)
(Swift Phase-3 Inc-1 divergences), [ADR-0060](0060-swift-collections-divergences.md)
(Swift Phase-3 Inc-2 divergences), [ADR-0061](0061-swift-hierarchical-threading-divergences.md)
(Swift Phase-3 Inc-3 divergences)

## 1. Context

Phase 3, Increment 4 (`swift-parity-inc4`) ports the full command suite,
command decorators, message hub semantics, and `FormVM` to Swift, expanding
the Swift conformance subset from 153 to 193 IDs:

| Area | New IDs                   | Delta |
| ---- | ------------------------- | ----- |
| CMD  | `CMD-005`, `CMD-007..012` | +7    |
| CMDD | `CMDD-001..010`           | +10   |
| HIER | `HIER-014`                | +1    |
| HUB  | `HUB-001..007`            | +7    |
| FORM | `FORM-001..015`           | +15   |

All 40 new IDs have test markers in `langs/swift/Tests/VMxTests/` and entries
in `langs/swift/conformance-subset.txt`.

Swift's structured-concurrency model, ARC memory model, Combine's non-throwing
sink API, and value-type semantics require idiomatic adaptations across every
new area. These are **forced divergences**, not defects — each preserves the
observable behavior mandated by the spec while remaining idiomatic Swift. This
ADR records them per ADR-0009 §2 so they are not re-litigated as bugs in future
maintenance passes.

## 2. Decision

Accept the following idiomatic divergences; they are normatively equivalent to
the canonical TypeScript reference implementation unless stated otherwise.

### 2.1 CMD-012 two-runtime model — `CMD-012`

**Divergence:** The three full-parity flavors implement the cancellable async
command body using their language's idiomatic cancel channel: C# uses
`CancellationToken`, Python uses `asyncio.CancelledError`, TypeScript uses
`AbortSignal`. All three keep their reactive channels (`errors`,
`canExecuteChanged`) in the flavor's Rx library (System.Reactive / reactivex /
rxjs). Swift follows the same split, but with two distinct runtimes in the same
class:

| Responsibility      | Runtime                        | Detail                                                                       |
| ------------------- | ------------------------------ | ---------------------------------------------------------------------------- |
| Cancellable body    | Swift structured concurrency   | `Task { try await body?() }` checks `Task.isCancelled` / `checkCancellation` |
| `canExecuteChanged` | Combine (`PassthroughSubject`) | Fires on in-flight state transitions                                         |
| `errors`            | Combine (`PassthroughSubject`) | Fire-and-forget non-cancel faults                                            |

Swift has no Rx-family cancel-signal type that integrates with structured
concurrency; `AbortSignal` and `CancellationToken` are not native Swift
constructs. Using Swift's `Task` cooperative cancellation is the only idiomatic
analogue.

**Cancellation modes:**

- **Default (non-throwing):** A call to `cancel()` sets a `cancelRequested`
  flag before calling `bodyTask.cancel()`. When the body's `catch` block sees
  `cancelRequested == true && throwOnCancelFlag == false`, the `CancellationError`
  is swallowed and execution completes normally. This mirrors the DIA-007
  non-throwing default.
- **`throwOnCancel()` opt-in:** When `throwOnCancelFlag == true` and
  `cancelRequested == true`, the `CancellationError` is rethrown to the
  `executeAsync()` caller.
- **Fire-and-forget `execute()` with `throwOnCancel`:** When `execute()` is
  used (not `executeAsync()`) and `throwOnCancel=true`, a cancel produces a
  `CancellationError` that is caught by the `Task` wrapper and routed to the
  `errors` Combine channel. This mirrors the TS `execute()` fire-and-forget
  path and is consistent with ADR-0049 §2 (faults route to `errors`).

**In-flight guard:** `canExecute()` returns `false` while `isExecuting == true`,
blocking double-run. `isExecuting` flips in a `defer` block covering success,
cancel, and fault paths.

**Consequence:** `AsyncRelayCommand` exposes an `AsyncCommand` protocol (Swift's
analog to `IAsyncCommand`). Future maintenance passes that see "two runtimes in
`AsyncRelayCommand`" must consult this ADR before "unifying" them — the split is
deliberate and forced by Swift's type system.

### 2.2 Async confirm gate — `CMDD-007/010`, `FORM-010`

**Divergence:** `ConfirmationDecoratorCommand.confirm` is typed
`@escaping () async throws -> Bool` rather than the simpler `() async -> Bool`.
The `throws` width is required to cover CMDD-010 (a throwing confirm must route
its error to the `errors` channel) without a separate wrapper type.

`execute()` is fire-and-forget via an unstructured `Task`:

```swift
func execute() {
    Task {
        do { try await executeAsync() }
        catch { errorsSubject.send(error) }
    }
}
```

`executeAsync()` is the `async throws` sibling used in tests for deterministic
assertion (same `execute()` / `executeAsync()` split as the TS reference).
Failures — whether from a throwing confirm or, in principle, from a throwing
inner command — route to the sealed Combine `errors: AnyPublisher<Error, Never>`
channel (CMDD-010).

**`ModeledCrudCommands` confirm signatures:** The `confirmUpdate` and
`confirmDelete` optional delegates on `ModeledCrudCommands<VM: AnyObject>` are
widened to `(() async throws -> Bool)?` to be composable with
`ConfirmationDecoratorCommand` and to cover the FORM-010 confirm-guarded deny
scenario (a `ConfirmationDecoratorCommand` wrapping `FormVM.denyCommand` is the
canonical Inc-4 pattern).

**Consequence:** Tests for CMDD-010 and FORM-010 use `await fulfillment(of:timeout:)` (the standard async drain pattern for XCTestCase on
macOS 13+) to ensure the fire-and-forget `Task` has completed before asserting
on the `errors` recorder.

### 2.3 `FormVM` standalone class — `FORM-001..015`

**Divergence — not a `ComponentVMOf` subclass:** `FormVM<Model>` is a plain
`public final class` rather than a `ComponentVMOf<Model>` subclass. This matches
the spec (spec/20-form-vm.md §1.1) and ADR-0030: `FormVM` is not
lifecycle-aware — it has no `construct`/`destruct` transitions and its `dispose`
is terminal/idempotent without the full `ComponentVMBase` lifecycle contract.
Making it a subclass of `ComponentVMOf` would inherit 14 spec-mandated lifecycle
methods that have no meaning for a form.

**`isDirty` via injectable `equals` closure:** Swift has no
framework-provided structural deep-equals (no equivalent to JavaScript's
`JSON.stringify`-based deepEquals or C#'s `EqualityComparer.Default`). `isDirty`
is computed by comparing the live model to the snapshot via a caller-supplied
`equals: (Model, Model) -> Bool` closure. An `extension FormVM where Model: Equatable`
provides a convenience initializer that defaults `equals` to `==`, covering the
common case without requiring callers to supply a closure for Equatable models.

**`snapshotter` closure:** The snapshot taken on construction and after each
successful approve is produced by a `snapshotter: (Model) -> Model` closure
(default: `{ $0 }`). For Swift value-type models (structs), the identity closure
is correct — the assignment itself produces a copy. The closure is injectable for
callers whose model contains reference-type members that require deep copying.
This is equivalent in intent to the TypeScript `structuredClone`-based default
(ADR-0048), adapted for Swift's value-type ownership semantics.

**`approveAsync` model capture:** `approveAsync()` captures the current model
value before the `await persister(current)` call (`let current = _model`). If
the persister succeeds, `_snapshot = snapshotter(current)` advances the
snapshot and `_onApproved.send(current)` fires. If the persister throws, neither
`_model` nor `_snapshot` is mutated. This matches the spec contract: a failed
approve leaves the form in its pre-approve state.

**Sealed Combine channels:** `onApproved: AnyPublisher<Model, Never>` and
`approveErrors: AnyPublisher<Error, Never>` are type-erased subjects sealed on
`dispose()`. `approveCommand`'s task is fire-and-forget:

```swift
approveCommand = RelayCommand.builder()
    .task { [weak self] in
        // RelayCommand's task is synchronous, so the await is bridged into a
        // detached Task (the fire-and-forget boundary).
        Task {
            guard let self else { return }
            do { try await self.approveAsync() }
            catch { self._approveErrors.send(error) }
        }
    }
    ...
    .build()
```

This covers FORM-015 (approve failure surfaces on `approveErrors` without
crashing the fire-and-forget caller).

**Consequence:** `FormVM<Model>` is not a `ComponentVMOf` subclass and does not
participate in the lifecycle state machine. Future maintenance passes that see
`FormVM` without lifecycle methods must consult ADR-0030 and this ADR before
adding them.

### 2.4 `HUB-007` opt-in claim — `HUB-007`

**Divergence:** The spec's HUB-007 contract covers error isolation: an exception
thrown in one subscriber's handler must not prevent other subscribers from
receiving subsequent messages. In the full-parity flavors (rxjs / reactivex /
System.Reactive), this is achieved by the Rx error channel — the subscriber's
`error`-handler absorbs the thrown error while the subject remains live.

In Swift, Combine's `sink(receiveValue:)` takes a non-throwing closure. An
uncaught error thrown inside a Combine sink crashes the process rather than
being catchable. The `messages: AnyPublisher<Message, Never>` raw subscription
path therefore **cannot** satisfy HUB-007 on the Combine sink path.

**Resolution:** Swift claims HUB-007 exclusively via the opt-in `subscribe(_:)`
method, which wraps the caller-supplied throwing handler in a `do/catch` and
routes failures to a dedicated error reporter. The raw `messages` subscriber
path retains the documented limitation: handlers that throw will trap rather than
being isolated. HUB-001..006 hold on the raw `messages` path unchanged — those
IDs cover delivery semantics (ordering, no-replay, cancel-safety, fan-out) that
`PassthroughSubject` satisfies correctly without any error-isolation concern.

**Consequence:** Future maintenance passes that see "HUB-007 is claimed in the
subset but Combine sinks cannot catch" must consult this ADR. The claim is
narrow and intentional: HUB-007 is satisfied by `subscribe(_:)`, not by the raw
`messages` publisher.

### 2.5 `RelayCommandOf<T>` canonical name, `DecoratorCommand` `defer`, and bundled fixtures

**`RelayCommandOf<T>` canonical name (CMD-005):** The Swift parameterized relay
command is named `RelayCommandOf<T>`, not `RelayCommandOfT`. The `OfT` suffix
was a Python-specific alias dropped in v3 (ADR-0052 §2). Swift uses the same
canonical name as TypeScript (`RelayCommandOf<T>`). `RelayCommandOf<T>` does
**not** conform to the non-parameterized `Command` protocol, mirroring the
TypeScript design where `ICommandOf<T>` is a distinct interface from `ICommand`
with no non-parameterized `canExecute()`/`execute()` surface.

**`DecoratorCommand` `postExecute` in `defer` block:** `DecoratorCommand.execute()`
uses a Swift `defer` block to guarantee `postExecute` runs even if the inner
`execute()` throws or if an early return occurs due to the `canExecute` guard:

```swift
func execute() {
    guard canExecute() else { return }
    preExecute?()
    defer { postExecute?() }
    inner.execute()
}
```

This is idiomatic Swift and equivalent to TypeScript's `finally` block in the
same position (ADR-0012). Future maintenance passes that see `defer` in
`DecoratorCommand` must not flatten it into sequential calls — the guarantee is
load-bearing for CMDD-005.

**Two new bundled fixtures:** `command-truthtable.json` (CMD-007) and
`message-ordering.json` (HUB-006) are copied byte-for-byte from `spec/fixtures/`
into `langs/swift/Sources/VMx/Resources/` and bundled via the library target's
existing `.process("Resources")` rule in `Package.swift`. Tests load them via
`Bundle.module.url(forResource:withExtension:)` — no `resources:` entry is
added to the VMxTests target, consistent with the Inc-1/Inc-2 lifecycle and
derived-properties fixture pattern (ADR-0059 §2). The
`tools/check-swift-fixture-sync.py` drift guard is extended to check all four
fixture pairs (lifecycle-transitions, derived-properties, command-truthtable,
message-ordering).

## 3. Consequences

- The 40 new Swift conformance IDs (`CMD-005`, `CMD-007..012`, `CMDD-001..010`,
  `HIER-014`, `HUB-001..007`, `FORM-001..015`) are claimed in
  `langs/swift/conformance-subset.txt` and verified by
  `tools/check-conformance-coverage.py`.
- The Swift subset grows from 153 to **193 of 237** library IDs.
- The remaining 44 IDs (`NOTIF-*`, `DIA-*`, `COMP-007/008/011/014..024`,
  `GRP-007..010`) are deferred to subsequent increments.
- Future maintenance passes that see "two runtimes in `AsyncRelayCommand`"
  (Swift `Task` + Combine) must consult §2.1 before re-unifying them.
- Future maintenance passes that see `FormVM` without lifecycle methods must
  consult §2.3 and ADR-0030 before adding them.
- Future maintenance passes that see "HUB-007 claimed but Combine sinks cannot
  catch" must consult §2.4 — the claim is narrow to `subscribe(_:)`.
- `check-swift-fixture-sync.py` now validates all four fixture pairs; a fifth
  fixture copy (if added) must extend `_FIXTURE_PAIRS` in the same commit.

## 4. Rejected alternatives

1. **Use Combine for the `AsyncRelayCommand` body (avoid Swift `Task`).** Rejected:
   Combine has no cooperative cancellation primitive. `Future`/`Deferred` chains
   do not integrate with structured concurrency's `Task.isCancelled` semantics
   and cannot be cancelled cooperatively mid-body. The `Task`-based body is the
   only idiomatic cancellable async primitive in Swift.
1. **Type `confirm` as `() async -> Bool` (non-throwing).** Rejected: CMDD-010
   requires that a throwing confirm routes its error to the `errors` channel. A
   non-throwing signature forces callers to swallow or externalize errors before
   returning `Bool`, which is less composable and cannot cover the throwing case
   without a separate subtype.
1. **Make `FormVM<Model>` a `ComponentVMOf<Model>` subclass.** Rejected: ADR-0030
   establishes that `FormVM` is not lifecycle-aware. Inheriting 14 lifecycle
   methods from `ComponentVMBase` would diverge from the spec and force
   `construct`/`destruct` guards into every form operation for no observable
   benefit. The standalone `final class` pattern is the correct Swift analog of
   the other flavors' standalone `FormVM` class.
1. **Implement `HUB-007` on the raw `messages` path via a `catch`-wrapping
   operator.** Rejected: a Combine operator that catches errors inside subscriber
   closures would require a custom `Publisher` that cannot be expressed without
   breaking the `AnyPublisher<Message, Never>` failure-type contract. The
   `subscribe(_:)` opt-in path is a minimal, auditable addition that satisfies
   HUB-007 without changing the raw `messages` API surface.
1. **Add a `RelayCommandOfT` alias alongside `RelayCommandOf<T>`.** Rejected:
   ADR-0052 §2 explicitly dropped the `OfT`-suffix aliases in v3 across all
   flavors. Adding it back in Swift would contradict that decision and re-introduce
   cross-flavor naming drift.
