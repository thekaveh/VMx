# ADR 0061 — Swift Phase-3 Inc-3 forced divergences (hierarchical / threading: HIER / THR / EXP / COMP-006/009/010)

**Status:** Accepted (2026-06-29)
**Spec version:** 3.0.0 (subset — Phase 3, Increment 3)
**Relates-to:** [ADR-0006](0006-idiomatic-api-per-language.md) (idiomatic surface per
language), [ADR-0009](0009-cross-flavor-divergence-catalogue.md) (cross-flavor
divergence catalogue), [ADR-0028](0028-hierarchical-vm.md) (`HierarchicalVM` design),
[ADR-0037](0037-v2.5-maintenance-clarifications.md) (Swift subset origin),
[ADR-0053](0053-swift-converge-illegal-transition-and-non-child-current-to-throw.md)
(Swift throwing convergence), [ADR-0059](0059-swift-leaf-area-divergences.md)
(Swift Phase-3 Inc-1 divergences), [ADR-0060](0060-swift-collections-divergences.md)
(Swift Phase-3 Inc-2 divergences)

## 1. Context

Phase 3, Increment 3 (`swift-parity-inc3`) ports hierarchical VMs, threading
contracts, expand/collapse, and the remaining composite-threading IDs to Swift,
expanding the Swift conformance subset from 124 to 153 IDs:

| Area | New IDs                                                     | Delta |
| ---- | ----------------------------------------------------------- | ----- |
| EXP  | `EXP-001..005`                                              | +5    |
| HIER | `HIER-001..013`, `HIER-015..018` (HIER-014 deferred — §2.8) | +17   |
| THR  | `THR-001..004`                                              | +4    |
| COMP | `COMP-006`, `COMP-009`, `COMP-010`                          | +3    |

All 29 new IDs have test markers in
`langs/swift/Tests/VMxTests/` and entries in
`langs/swift/conformance-subset.txt`.

Swift's type system, ARC memory model, Combine scheduler API surface, and the
absence of a framework-provided virtual-time test scheduler require idiomatic
adaptations across every new area. These are **forced divergences**, not defects —
each preserves the observable behavior mandated by the spec while remaining
idiomatic Swift. This ADR records them per ADR-0009 §2 so they are not
re-litigated as bugs in future maintenance passes.

## 2. Decision

Accept the following idiomatic divergences; they are normatively equivalent
to the canonical TypeScript reference implementation unless stated otherwise.

### 2.1 CRTP relaxation — `HIER-001..013`, `HIER-015..018`

**Divergence:** C# and TypeScript allow a self-referential generic constraint:

```csharp
// C#
public abstract class HierarchicalVM<TModel, TVM>
    where TVM : HierarchicalVM<TModel, TVM>
```

```typescript
// TypeScript
abstract class HierarchicalVM<TModel, TVM extends HierarchicalVM<TModel, TVM>>
```

Swift rejects the equivalent declaration outright:

```
error: generic class 'HierarchicalVM' has self-referential generic requirements
open class HierarchicalVM<TModel, TVM: HierarchicalVM<TModel, TVM>>
```

This is a hard Swift compiler limitation — not a typo or configuration issue.

**Resolution:** Bind `TVM: AnyObject` (every concrete node is a class) and uphold
the recursive relationship at runtime through two isolated, always-safe downcasts
that are the sole points of contact with the constraint:

```swift
open class HierarchicalVM<TModel, TVM: AnyObject>: ComponentVMBase {

    // View of `self` as the concrete TVM type.
    // Sound because every concrete TVM IS-A HierarchicalVM<TModel, TVM>.
    private var selfNode: TVM { self as! TVM }

    // Recovers the base view of a neighbour TVM so its tree members
    // (parent, children, depth) can be accessed.
    private func node(_ vm: TVM) -> HierarchicalVM<TModel, TVM> {
        vm as! HierarchicalVM<TModel, TVM>
    }
}
```

The canonical concrete shape compiles and runs without issues:

```swift
final class MyNode: HierarchicalVM<MyModel, MyNode> { … }
```

**Runtime vs compile-time enforcement:** In C#/TS the compiler rejects
`class Bad: HierarchicalVM<M, Other>` at definition time. In Swift, `Bad` would
pass the `AnyObject` bound at definition time and trap at the first downcast at
runtime. This is a documented constraint; misuse is detectable in tests and
development but not at compile time. All tree members (`depth`, `isFirst`,
`isLast`, `materializeChildren`, `buildPath`) are routed through
`selfNode`/`node(_:)` to keep ad-hoc casts out of the general surface.

**Consequence:** `HierarchicalVM` has signature
`open class HierarchicalVM<TModel, TVM: AnyObject>` in Swift. Future maintenance
passes that see `TVM: AnyObject` instead of the recursive bound must consult this
ADR before "fixing" it — the recursive bound is not expressible in Swift.

### 2.2 `vmFactory` required in `HierarchicalVMBuilder` — `HIER-015..017`

**Divergence:** `HierarchicalVMBuilder<TModel, TVM: AnyObject>` cannot construct
`TVM` directly because `AnyObject` exposes no `init` surface. The builder
therefore requires a caller-supplied `vmFactory` closure (confirmed by the first
build attempt: removing it produces a "cannot call init on a value of type
'TVM.Type'" compile error).

This is the **same pattern as TypeScript** — TS erases generic-type identity at
runtime and cannot call `TVM.init(...)` from the builder — but the cause is
different: TypeScript erases generics; Swift relaxes the bound to `AnyObject`.
Both flavors reach the same `vmFactory`-required surface for the same conceptual
reason (the builder cannot construct `TVM` from the constraint alone).

**Consequence:** The Swift builder validates four required fields in order:
`model`, `childrenFactory`, `services` (hub + dispatcher), and `vmFactory`. The
`HIER-015` test covers all four missing-field cases including `vmFactory`. A
possible future ergonomic improvement (a `HierarchicalVMConstructionArgs` context
struct mirroring TS's `HierarchicalVMConstructionContext`) is deferred — it would
add a new public type without spec coverage.

### 2.3 Weak parent back-reference — `HIER-002` and all structural HIER IDs

**Divergence:** `HierarchicalVM` maintains a parent back-reference
(`public private(set) weak var parent: TVM?`). The back-reference is declared
`weak` to avoid ARC retain cycles: parent nodes hold their children strongly
(the `_children: [TVM]?` cache) while the upward link is weak. Without `weak`,
a subtree would form a reference cycle and leak.

**Consequence:** `parent` is an `Optional<TVM>`, which is consistent with the
spec's "null for root" contract. The `weak` qualifier is invisible to callers.
C#/Python/TypeScript handle this implicitly via their own GC/ownership semantics;
Swift's ARC requires the explicit annotation.

### 2.4 Synchronous-only child loading — `HIER-007`, `HIER-008`, `HIER-009`

**Divergence:** The spec describes a lazy child-loading strategy but does not
mandate async. The C#/Python/TypeScript reference implementations use synchronous
factories. Swift's implementation is also synchronous (no `async`/`Task`/`await`
anywhere in the lazy or eager paths).

The eager construction cascade (`_onConstruct()` override) calls
`try node(child).construct()` synchronously for each child, producing the
depth-first ordering required by HIER-009 without any concurrency primitives.
The throwing cascade (`try`) propagates errors up through `_onConstruct()` into
`ComponentVMBase.construct()`, which rolls the parent back to its prior status on
failure (LIFE-014 contract).

**Consequence:** No `async` or concurrency annotations appear in
`HierarchicalVM`. This matches all three full-parity flavors and the spec's
synchronous ordering requirement.

### 2.5 Throwing reparent guard and builder validation — `HIER-018`, `HIER-015`

**Divergence:** Following the v3 Swift convergence in ADR-0053 (`StatusTransitionError`,
`CompositeMembershipError`), `HierarchicalVM.reparentChild` and
`HierarchicalVMBuilder.build()` use the same throwing pattern rather than
`preconditionFailure`:

- `reparentChild(_:)` throws `HierarchyError.invalidReparent` when the child is
  `self` or an ancestor (detected by `path.contains(where: { $0 === child })`);
  no mutation and no hub publish occur on a thrown guard.
- `HierarchicalVMBuilder.build()` throws `BuilderValidationError` for each
  missing required field.

Both are catchable errors at the call site. This is consistent with the v3
throwing direction (ADR-0053) and diverges from the pre-v3 `preconditionFailure`
pattern (ADR-0037).

**Consequence:** Tests for `HIER-018` / `HIER-015` use `XCTAssertThrowsError`
(consistent with `LIFE-005` / `LIFE-006` / `LIFE-008` test patterns). Callers
expecting silent traps must be updated to catch-or-`try?`.

### 2.6 `name` default from `TVM.self` — `HIER-017`

**Divergence:** When the builder does not set an explicit `name`, `HierarchicalVM`
defaults to `String(describing: TVM.self)`. For a concrete final class
`MyNode: HierarchicalVM<M, MyNode>`, this yields `"MyNode"` — the expected
human-readable type name. For an intermediate open subclass, `TVM.self` resolves
to the type-parameter identity, which may not match the concrete runtime type
name.

`TVM.self` is used rather than `type(of: self)` because `self` is unavailable
before `super.init` in a Swift designated initializer. Under the canonical CRTP
pattern (`final class MyNode`) the two resolve to the same string; the difference
is only observable if a caller subclasses `MyNode` further without resetting
`name` in the subclass's builder.

**Consequence:** The HIER-017 test verifies the default-name behavior using a
concrete `final class TestNode` where `String(describing: TVM.self) == "TestNode"`.
Edge cases with intermediate subclasses are documented, not tested.

### 2.7 Hand-rolled `ManualScheduler` substituting for framework TestScheduler — `THR-001..004`

**Divergence:** The rxjs / System.Reactive / reactivex flavors each ship (or can
use) a framework-provided virtual-time `TestScheduler` that controls simulated
time, buffers scheduled work, and runs it on demand. **Combine provides no such
construct** — its `Scheduler` protocol is sufficient for custom implementations,
but no `TestScheduler` is included in the framework.

**Resolution:** Swift ships a hand-rolled `ManualScheduler: Combine.Scheduler` in
the production library (`Sources/VMx/Services/ManualScheduler.swift`). It
implements the full `Scheduler` conformance — including the three required
`schedule` overloads and the two associated types — and buffers all scheduled
work into a FIFO queue drained only when `flush()` is called. A companion
`ManualDispatcher: Dispatcher` provides per-channel buffers (`flushForeground()`
/ `flushBackground()`) for the `scheduleBackground`-driven construct deferral
tested by THR-002. The `Dispatcher` protocol itself was **not** modified — no
`foreground`/`background` scheduler-typed properties were added — preserving the
existing `DefaultDispatcher`, `ImmediateDispatcher`, and `NullDispatcher`
implementations unchanged.

Key implementation details:

- `ManualScheduler.SchedulerTimeType` and `.Stride` are nested `struct` types
  satisfying all required associated-type protocols (`Strideable`,
  `SchedulerTimeIntervalConvertible`, `SignedNumeric`, `Comparable`). Virtual
  time is fixed at `0`; the scheduler makes no wall-clock calls.
- All three `schedule` overloads buffer into a `[() -> Void]` under
  `NSRecursiveLock`; `flush()` drains FIFO under the same lock so re-entrant
  scheduling (chained `.receive(on:)`) is picked up on the next `flush()` call
  without corrupting the in-flight iteration.
- `.receive(on: manualScheduler)` drives only the immediate `schedule(options:_:)`
  overload; subscription/demand passes through synchronously, so the subject has
  demand before the first value is sent — the "0 before flush, 1 after" pattern
  holds for a hot `PassthroughSubject`.

**Consequence:** Tests for THR-001..004 use `ManualScheduler` and `ManualDispatcher`
where the other flavors use their framework's `TestScheduler`. The deterministic
virtual-time contract (buffer until explicit flush) is identical. Future
maintenance passes that see "no TestScheduler in Swift" must consult this ADR
before adding a third-party dependency — `ManualScheduler` is the intentional
substitute.

### 2.8 `asyncSelection` opt-in flag and foreground-marshaled deferred selection — `COMP-006`, `COMP-010`

**Divergence:** `COMP-006` requires the previous child's `isCurrent = false` flip
to be dispatched through the foreground execution target rather than emitted
synchronously inline. `COMP-010` requires an opt-in `asyncSelection` mode that
defers the entire current-change (including the new child's `isCurrent = true`)
through the foreground target.

The TypeScript reference uses `observeOn(dispatcher.Foreground)` at the subscriber
side. Swift achieves the equivalent by calling `dispatcher.scheduleForeground { … }`
at the **call site** in `_applyCurrentChange` and `_setCurrent` — the same
observable contract with Combine's `PassthroughSubject` and the `ManualDispatcher`
test double.

The `_applyCurrentChange` path includes a TOCTOU guard: if a child is removed
before `flushForeground()` runs, the stale deferred selection is dropped silently
(`if let value, !children.contains(where: { $0 === value }) { return }`).

**Known narrow edge case (COMP-010 / Inc-4 follow-up):** A deferred selection
flushed after `_onDestruct()` has run may transiently re-point `current` at a
torn-down child before `_onDestruct`'s `_applyCurrentChange(nil)` clears it
again. The consequences are status-gated and silenced by the TOCTOU guard in
`_onDestruct`'s direct (non-deferred) path. This is a documented limitation
rather than a silent bug; a more robust teardown ordering is deferred to
Increment 4.

**Consequence:** `asyncSelection` is an opt-in builder flag (default `false`);
all existing tests that use `ImmediateDispatcher`/`NullDispatcher` are
unaffected. Tests for `COMP-006`/`COMP-010` use `ManualDispatcher.flushForeground()`
to verify the deferred-vs-immediate contract.

### 2.9 `HIER-014` deferred to Increment 4

`HIER-014` ("Composition with `ModeledCrudCommands` mutates the tree") requires
`ModeledCrudCommands` from the `CMDD` area, which is not yet implemented in
Swift. `CMDD` (including `CompositeCommand`, `DecoratorCommand`,
`ConfirmationDecoratorCommand`, and `ModeledCrudCommands`) is scheduled for
Phase 3, Increment 4.

`HIER-014` is explicitly absent from `langs/swift/conformance-subset.txt`; the
subset count reflects this (153 of 237, not 154). It will be added in the same
increment that ships the CMDD area.

## 3. Consequences

- The 29 new Swift conformance IDs (`EXP-001..005`, `HIER-001..013`,
  `HIER-015..018`, `THR-001..004`, `COMP-006`, `COMP-009`, `COMP-010`) are
  claimed in `langs/swift/conformance-subset.txt` and verified by
  `tools/check-conformance-coverage.py`.
- The Swift subset grows from 124 to **153 of 237** library IDs.
- The remaining 84 IDs (`HUB-*`, `CMDD-*`, `NOTIF-*`, `DIA-*`, `FORM-*`,
  `HIER-014`, `CMD-005/007`, `COMP-007/008/011`, `COMP-014..024`,
  `GRP-007..010`) are deferred to subsequent increments.
- Future maintenance passes that see "`HierarchicalVM` has `TVM: AnyObject`
  instead of a recursive bound" or "`HierarchicalVMBuilder` requires `vmFactory`"
  must consult this ADR before filing a bug — both are documented, deliberate
  choices forced by Swift's type system.
- Future maintenance passes that see "no framework TestScheduler in Swift" must
  consult §2.7 before adding a Combine-extension dependency — `ManualScheduler`
  is the intentional, self-contained substitute.
- The `COMP-010` deferred-selection teardown edge case (§2.8) is tracked for
  Increment 4.

## 4. Rejected alternatives

1. **Use a third-party `CombineSchedulers` library for TestScheduler.** Rejected:
   introduces a test-infrastructure dependency not present in any other flavor,
   complicates Package.swift without spec justification, and the hand-rolled
   `ManualScheduler` is simpler, dependency-free, and fully sufficient for the
   four THR IDs.
1. **Add `Scheduler`-typed `foreground`/`background` properties to the
   `Dispatcher` protocol.** Rejected: it couples `Dispatcher` to Combine's
   `Scheduler` existential (which requires `AnySchedulerOf`-style type erasure
   that Combine does not ship natively), forces changes to `DefaultDispatcher`,
   `ImmediateDispatcher`, and `NullDispatcher`, and adds API surface with no spec
   mandate. Buffering via `scheduleForeground`/`scheduleBackground` closures is
   the correct substitution.
1. **Use `async`/`Task` for the lazy child-loading path.** Rejected: the spec
   mandates synchronous ordering (HIER-009 depth-first); `async` would require
   callers to `await` every `children` access and diverge from all three
   full-parity flavors. The synchronous factory pattern is correct and simpler.
1. **Use `fatalError`/`preconditionFailure` for the reparent guard (matching the
   pre-v3 Swift pattern).** Rejected: ADR-0053 established the v3 direction —
   illegal operations throw catchable errors in Swift. `preconditionFailure` is
   now reserved for programming errors that cannot be caught (e.g., setter
   constraints); the reparent guard is a recoverable validation failure.
1. **Defer `COMP-006`/`COMP-010` to Increment 4.** Rejected: the `ManualDispatcher`
   shipped for THR-002 already provides the exact test infrastructure needed; the
   foreground-dispatch and async-selection IDs are a natural fit for this
   increment and share no CMDD dependencies.
