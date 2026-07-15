# ADR 0053 — Swift converges illegal-transition and non-child-`current` handling from trap to throw

**Status:** Accepted (2026-06-28)
**Spec version:** 3.0.0

## 1. Context

Through v2.6 the Swift flavor surfaced illegal lifecycle operations and a
non-child `current` assignment as **uncatchable `preconditionFailure` traps**,
rather than the catchable thrown error the C#/Python/TypeScript flavors raise.
This was a deliberate, documented divergence (ADR-0037 §2.5): traps are the
Swift-stdlib convention for API misuse, and making the lifecycle throwing would
force `try` onto every legal call site. The merged framework critique
(`docs/audit/2026-06-27-vmx-merged-critique.md`) flagged the divergence as a
recoverability/safety gap to close in the v3 full-parity phase:

- **VMX-028** — illegal lifecycle transitions (`construct` / `destruct` /
  `reconstruct` from an illegal state) and the in-flight reentrancy guard
  (`LIFE-008`) were uncatchable `preconditionFailure` traps
  (`ComponentVMBase.swift`), so a host could not recover from a mis-sequenced
  lifecycle call — it crashed the process.
- **VMX-026** — `CompositeVM.current`'s setter trapped on a non-child via
  `preconditionFailure` with no gating predicate (`CompositeVM.swift`), an
  additional undocumented uncatchable trap versus the C# `InvalidOperationException`
  / Python/TS thrown error on a non-child `Current` assignment (spec/06 §3.1,
  `COMP-009`).

v3 is a breaking major, so this is the cycle to converge Swift onto the throwing
contract.

## 2. Decision

### 2.1 Lifecycle operations throw (`VMX-028`, supersedes ADR-0037 §2.5)

`ComponentVMBase.construct()`, `destruct()`, and `reconstruct()` are now `throws`.
On an illegal transition (the operation's predicate is `false`) and on a
concurrent re-invocation while a transition is in flight (`LIFE-008`), they
throw a catchable `StatusTransitionError` — the existing error type, previously
used only to carry the trap's description — instead of calling
`preconditionFailure`. The legal idempotent no-ops (`construct` from
`Constructed`, `destruct` from `Destructed`) still return without throwing.

Because the operations are `throws`, the cascade hooks `_onConstruct()` and
`_onDestruct()` are also `throws` so a child's throwing `construct()` propagates
up to the originating call — parity with the implicit exception propagation of
the C#/Python/TypeScript cascades. Container overrides (`CompositeVM`,
`GroupVM`, `AggregateVM1..6`) use `try` on their child transitions. Legal call
sites (the common path) now use `try`.

The **background** lifecycle path has no completion/error future in this flavor:
a throwing hook/child transition on the background queue cannot be redelivered
to the already-returned caller, so it is caught at the background callback and
the in-flight guard is still cleared. Transactional hook-failure rollback was
subsequently completed for Swift (`LIFE-014`, ADR-0047); ADR-0109 retains the
no-awaiter limitation while requiring the C#-specific async surface to preserve
the original failure.

### 2.2 `CompositeVM.current` gains a throwing companion (`VMX-026`)

Swift property setters cannot be `throws`, so the `current` **property setter is
retained** (not deprecated) and still traps on a non-child — assigning a known
member or `nil` is the common case and never traps, and the non-deprecated
setter keeps ergonomic SwiftUI-style binding. Alongside it, two recoverable,
catchable members are added:

- `func canSetCurrent(_ value: Child?) -> Bool` — the pre-flight predicate
  (`true` iff `value` is `nil` or a member).
- `func setCurrent(_ value: Child?) throws` — validates membership and throws
  `CompositeMembershipError` (a new public error) on a non-child, otherwise
  assigns exactly as the property setter does.

`CompositeMembershipError` is the Swift convergence of the C#
`InvalidOperationException` / Python/TS thrown error for a non-child `Current`
assignment.

### 2.3 Property-setter traps that cannot throw remain documented

Where Swift's type system genuinely cannot express a throwing surface, the trap
stays — now explicitly documented rather than divergent:

- The `CompositeVM.current` **property setter** keeps its `preconditionFailure`
  (the recoverable path is `setCurrent(_:)` / `canSetCurrent(_:)`).
- The `ReadonlyComponentVMOf.model` read-only setter keeps its
  `preconditionFailure`. Unlike `current` and the lifecycle ops, there is **no**
  recoverable external use case — the read-only contract means an external
  `vm.model = …` is always a programmer error; the legitimate update path is the
  module-internal `_setModel(_:)`. So no throwing companion is added (it would
  imply external writes are sometimes valid, contradicting the contract).

## 3. Consequences

- `02-lifecycle.md` §2.1 now states Swift throws `StatusTransitionError` on
  illegal lifecycle ops and the `LIFE-008` guard, converging from the v2 trap,
  and notes the residual property-setter traps. ADR-0037's body is unchanged;
  its §2.5 divergence is superseded by this ADR.
- **Breaking (v3):** every Swift lifecycle call site — including host code and
  container overrides — now needs `try`; `_onConstruct`/`_onDestruct` overrides
  in external subclasses become `throws`. `CompositeMembershipError` is a new
  public type.
- The Swift conformance subset gains **`LIFE-008`** (concurrent re-invocation
  raises), now genuinely testable as a catchable throw — `LifecycleRaceTests`
  parks the VM mid-`.constructing` via the deferred dispatcher and asserts the
  second `construct()` throws. `LIFE-005`/`LIFE-006` move from "assert the gating
  predicate" to "assert the catchable throw". The subset manifest
  (`langs/swift/conformance-subset.txt`) grows **41 → 42 IDs**; the Swift README
  count and the §5 in/deferred breakdown are reconciled accordingly. No catalog
  ID is added (the `LIFE-005/006/008` headings already describe a raise), so no
  new cross-flavor stubs are required.
- Tests are **CI-verified only**: `swift test` needs full Xcode (XCTest) and runs
  on `swift.yml` (macos-latest); the development host here is CommandLineTools-only,
  so changes were verified via `swift build` (library) and `swiftc -frontend -parse`
  (test files).
- The coordinated `spec/VERSION` bump to 3.0.0 and the per-flavor package version
  bumps are handled by the v3 release task, not here; this ADR's "Spec version:
  3.0.0" records the line the change belongs to.

## 4. Rejected alternatives

- **Keep the lifecycle traps (status quo, ADR-0037 §2.5)** — rejected for v3:
  the recoverability gap is exactly what the full-parity phase exists to close,
  and a major version is the right place to add the `try` requirement.
- **Make `current` a throwing setter** — impossible: Swift property setters
  cannot be `throws`. Hence the `setCurrent(_:)` / `canSetCurrent(_:)` companion.
- **Add a throwing `setModel(_:)` companion to `ReadonlyComponentVMOf`** —
  rejected (§2.3): there is no recoverable external write on a read-only model;
  a throwing external setter would contradict the read-only contract. The trap
  stays, documented.
- **Introduce a dedicated `LifecycleError` enum instead of reusing
  `StatusTransitionError`** — rejected: `StatusTransitionError` already models
  exactly `(currentStatus, attemptedOperation)` and was already the trap's
  payload; reusing it keeps the Swift surface aligned with the cross-flavor
  `StatusTransitionError` / `StatusTransitionException` naming.
