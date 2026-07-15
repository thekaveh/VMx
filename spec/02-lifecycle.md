# 02 — Lifecycle state machine

Every viewmodel has a `Status` of type `ConstructionStatus`. The state machine is
defined here normatively and encoded in `fixtures/lifecycle-transitions.json` so
every language's conformance tests can load the same table.

## 1. States

```
Disposed     ← terminal; once entered, cannot leave
Destructing  ← transient; during destruct()
Destructed   ← initial state of a freshly built VM
Constructing ← transient; during construct()
Constructed  ← ready-to-use state
```

`IsConstructed` is defined as `Status == Constructed`. This is normative.

## 2. Operations

A VM exposes four lifecycle operations (rendered per language as
`construct/destruct/reconstruct/dispose` or `Construct/Destruct/Reconstruct/Dispose`):

- `construct()` — moves `Destructed → Constructing → Constructed`.
- `destruct()` — moves `Constructed → Destructing → Destructed`.
- `reconstruct()` — equivalent to `destruct()` followed by `construct()`.
- `dispose()` — moves to `Disposed` from any state. Terminal.

Each operation MAY be invoked synchronously or asynchronously. When invoked
asynchronously, the operation completes when the final state is reached.
The async invocation form is C#-only (`ConstructAsync` / `DestructAsync` /
`ReconstructAsync` on `IComponentVM`) per ADR-0008; Python and TypeScript
expose only the synchronous form (catalogued as a row in the ADR-0009
divergence table). Swift likewise exposes only the synchronous form (the
async `ConstructAsync` shape is C#-only per ADR-0008); Swift covers the
`THR-*` threading IDs at full parity (ADR-0061), and the ADR-0009 async-form
row applies to all three non-C# flavors.

The C# async entry points report the operation outcome after its terminal
publication. A hook or deferred child-cascade failure first publishes the
transactional rollback from §2.5 and then faults the returned `Task` with the
original exception (ADR-0109). If terminal disposal wins the race, the waiter
completes at `Disposed` and the abandoned transition cannot replace that
outcome. This C#-specific TAP behavior adds no cross-flavor API requirement.
Subscribers to the message hub observe two `ConstructionStatusChangedMessage`
emissions per non-trivial transition: one for the intermediate state and one
for the final state.

### 2.1 `can_construct` / `can_destruct` / `can_reconstruct` predicates

Each operation has a paired predicate. Predicates are defined as:

- `can_construct()` returns `true` iff `Status ∈ {Destructed, Constructed}`. (Re-
  constructing while already `Constructed` is a no-op.)
- `can_destruct()` returns `true` iff `Status ∈ {Constructed, Destructed}`. (Re-
  destructing while already `Destructed` is a no-op.)
- `can_reconstruct()` returns `true` iff `Status == Constructed`.

Note that `can_construct()` returning `true` from `Constructed`, and `can_destruct()`
returning `true` from `Destructed`, are intentional: re-invoking those operations in
the matching state is a no-op (see `## Idempotency` below), not an error, and the
predicate signals "the operation is safe to call" rather than "the operation will
produce a state change".

Calling an operation when its predicate returns `false` MUST raise
`StatusTransitionError` (Python / TS / Swift) / `StatusTransitionException` (C#).
The exception's message MUST include the current state and the attempted
operation. As of v3 the Swift flavor **throws** a catchable
`StatusTransitionError` here — the same recoverable contract as the other
flavors — converging from its v2 trap (`preconditionFailure`) per ADR-0053,
which supersedes the documented divergence in ADR-0037 §2.5. The throwing
surface covers the three lifecycle operations (`construct` / `destruct` /
`reconstruct`) and the concurrent-re-invocation guard (`LIFE-008`); these are
`throws` in Swift, so legal call sites use `try`. Swift property setters that
cannot be `throws` — the `CompositeVM.current` slot and the
`ReadonlyComponentVMOf.model` read-only setter — retain a `preconditionFailure`
trap for misuse, and expose a catchable companion where a recoverable path
exists (`CompositeVM.setCurrent(_:)` / `canSetCurrent(_:)`, VMX-026). See
ADR-0053.

### 2.2 Subclass lifecycle hooks (`OnConstruct` / `OnDestruct` / `OnDispose`)

`ComponentVMBase` exposes three protected, overridable hooks so subclasses can
attach per-phase logic without reimplementing the status state machine. Names
follow the flavor idiom (`OnConstruct` C# / `_on_construct` Python /
`_onConstruct` TypeScript and Swift):

- `OnConstruct` — invoked during `construct()` (and the construct phase of
  `reconstruct()`), after the VM enters `Constructing` and before it reaches
  `Constructed`. Register **per-construct** subscriptions here.
- `OnDestruct` — invoked during `destruct()` (and the destruct phase of
  `reconstruct()`). Release the per-construct subscriptions acquired in
  `OnConstruct`.
- `OnDispose` — invoked once during `dispose()`. Perform subclass-specific
  terminal work. Long-lived resources SHOULD use the owned-resource helper in
  §2.3 when their cleanup fits an accepted resource shape.

The hooks preserve the per-construct vs. long-lived cleanup split without two
public bags (ADR-0041, refined by ADR-0090). The container VMs of §6 and §7 use
them to drive their child construct/destruct/dispose cascades.

### 2.3 Owned resources

`ComponentVMBase` exposes one flavor-idiomatic registration helper for resources
owned until terminal VM disposal: `Own` in C#, `_own` in Python, and `own` in
TypeScript, Swift, and Rust. C#, Python, and TypeScript keep the helper protected;
Swift and Rust expose the language-required public analogue because neither has
a protected member model that maps to the common subclass contract.

Accepted resource shapes are explicit:

| Flavor     | Accepted shape                                                  |
| ---------- | --------------------------------------------------------------- |
| C#         | `IDisposable` or `Action`                                       |
| Python     | zero-argument callable or object with `dispose()`               |
| TypeScript | zero-argument function, `{ dispose() }`, or `{ unsubscribe() }` |
| Swift      | throwing/non-throwing closure or Combine `Cancellable`          |
| Rust       | `FnOnce() + Send + 'static`                                     |

Registration returns the resource where the language benefits from inline
assignment (C#, Python, TypeScript); Swift and Rust return no value. Resources
are released exactly once in reverse registration (LIFO) order, after the
subclass `OnDispose` hook and before the base command/stream teardown. Each
cleanup failure is swallowed independently so later resources still run.
Registration that races with or follows disposal is serialized by the lifecycle
guard: it cleans the resource immediately exactly once instead of retaining or
rejecting it. `destruct()` and `reconstruct()` do not release owned resources.
Per-construct resources still belong in `OnConstruct` / `OnDestruct`.

The injected message hub is shared infrastructure, not an owned resource.
Disposing a VM MUST NOT dispose its hub.

### 2.4 Transition atomicity and the concurrency guard

Every status transition — the `Status` read-modify-write, the
`ConstructionStatusChangedMessage` publish, and the internal command-trigger
emission — executes **atomically with respect to other lifecycle operations on
the same VM**. Implementations MUST serialize these steps behind a per-VM
synchronization primitive: a per-VM lock/monitor in C# and Python; the
single-threaded event loop in TypeScript; an actor or lock in Swift (Phase 3 —
ADR-0037). This guarantees that a transition completing on the background
scheduler (§4 background construct/destruct, `11-threading.md §4`) cannot
interleave with `dispose()`: a background completion observes the terminal
`Disposed` state under the guard and aborts instead of resurrecting the VM,
publishing a post-dispose message, or emitting on a torn-down stream
(invariant 6).

The concurrent-re-invocation rule (invariant 5 / `LIFE-008`) is enforced by this
same primitive together with an in-flight guard: a second `construct()` /
`destruct()` / `reconstruct()` entered while one is in progress MUST raise rather
than rely on an unsynchronized `Status` read. The enforcement primitive is
named normatively so flavors do not detect re-entrancy with a racy status read.

### 2.5 Transactional hook failure (rollback)

If `OnConstruct` or `OnDestruct` raises, the transition is **transactional**: the
VM rolls `Status` back to the prior settled state before the exception
propagates, so the VM is left recoverable rather than wedged in a transient
`Constructing` / `Destructing` state (whose only legal exit would otherwise be
`dispose()`):

- A failed `construct()` (or the construct phase of `reconstruct()`) rolls back
  to `Destructed`. Subscribers observe `Constructing` then `Destructed`.
- A failed `destruct()` (or the destruct phase of `reconstruct()`) rolls back to
  `Constructed`. Subscribers observe `Destructing` then `Constructed`.

The rollback is itself a status change: it publishes its own
`ConstructionStatusChangedMessage` (invariant 4), runs under the §2.4 per-VM
guard, and clears the in-flight guard. In the synchronous form the original
exception is then re-raised to the caller. In the background form the rollback
emission is marshalled onto `IDispatcher.Foreground` (`11-threading.md §4`). C#
async callers receive the original exception through the returned `Task` after
rollback; a caller that used the synchronous fire-and-forget entry point has no
returned outcome surface. Non-C# flavors expose no async lifecycle waiter, and
Swift's non-throwing scheduler closure cannot redeliver a background hook error
to the already-returned caller (ADR-0053, ADR-0109). `OnDispose` is **not**
subject to rollback — `dispose()` is terminal and idempotent.

This behavior is verified by `LIFE-014`.

## 3. Invariants

These hold for every VM at every point in its lifetime:

1. `Status` is one of the five `ConstructionStatus` values.
1. `IsConstructed == (Status == Constructed)`.
1. Once `Status` reaches `Disposed`, it never changes again. All lifecycle
   operations from `Disposed` (except `dispose` itself, which is idempotent)
   raise. A **selection** change (`IsCurrent`) requested after `Disposed` is a
   silent no-op — it does not raise and emits no `PropertyChangedMessage` —
   distinguishing it from the lifecycle operations, which raise (VMX-006).
1. Every `Status` change publishes exactly one `ConstructionStatusChangedMessage`
   on the VM's message hub before the operation returns (synchronous) or before the
   awaiter resumes (asynchronous). A transactional rollback (§2.5) is itself a
   status change and so publishes its own message.
1. A VM in `Constructing` or `Destructing` MUST NOT have its operation re-invoked
   concurrently. Implementations MUST raise on the second invocation, detected via
   the per-VM guard of §2.4 (not an unsynchronized `Status` read).
1. Each status transition is atomic with respect to other lifecycle operations on
   the same VM (§2.4). A transition racing `dispose()` observes the terminal
   `Disposed` state under the guard and aborts — it never resurrects the VM nor
   publishes a post-dispose message.
1. If `OnConstruct` / `OnDestruct` raises, `Status` is rolled back to the prior
   settled state (`Destructed` for a failed construct, `Constructed` for a failed
   destruct) before the exception propagates (§2.5); the VM never remains in a
   transient state after a failed hook.

## 4. Idempotency

- `construct()` from `Constructed` is a no-op. `Status` remains `Constructed`. No
  `ConstructionStatusChangedMessage` is emitted.
- `destruct()` from `Destructed` is a no-op. Same emission behavior.
- `dispose()` from `Disposed` is a no-op. No emission.

## 5. Reconstruct

`reconstruct()` is defined as `destruct()` followed by `construct()`. The two are
executed in order, and the message hub observes the full transition sequence:
`ConstructionStatusChangedMessage(Destructing)`, `(Destructed)`, `(Constructing)`,
`(Constructed)`. Reconstruct is a first-class operation (rather than `destruct()` then
`construct()` composed by the caller) for two reasons: (1) it expresses "replace state"
as a single user-facing intent, naturally bound to a `ReconstructCommand`; (2) it
guarantees subscribers observe the full four-message transition sequence atomically with
respect to other lifecycle operations on the same VM.

## 6. Parent–child orchestration

`CompositeVM`, `GroupVM`, and `AggregateVM` compose their children's lifecycles:

- A composite/group/aggregate's `construct()` completes only when every child has
  reached `Constructed`.
- A composite/group/aggregate's `destruct()` completes only when every child has
  reached `Destructed`.
- The order in which children are constructed/destructed is unspecified.
  Implementations MAY drive them sequentially or concurrently; the reference
  implementations in the full-parity flavors drive
  them sequentially. The parent observes its children's
  `ConstructionStatusChangedMessage` emissions to know when to finalize its own
  state. Because the order is unspecified, subscribers MUST NOT rely on a
  particular child visitation order; no conformance ID constrains it (VMX-046).

Conformance IDs for this behavior are cataloged in `12-conformance.md` under the
`COMP-NNN`, `GRP-NNN`, and `AGG-NNN` prefixes; each VM file's `## Conformance` section
points at its applicable range.

Changing a component's owning container is not a lifecycle transition. An
atomic composite/group transfer preserves the child's settled or transient
status, subscriptions, and owned resources: the old parent stage-detaches the
child, the destination attaches it, and only destination
`AutoConstructOnAdd(true)` may construct an already-`Destructed` child under the
existing chapter 06/07 rule. Failure restores the pre-transfer lifecycle and
membership state. Transfer never calls `destruct()` or `dispose()`.

## 7. Disposal cascade

`dispose()` on a parent disposes every child (synchronously, depth-first). This
ensures no orphaned `IDisposable` resources are left behind.

Once disposal begins, a failure cannot abort the remaining terminal work.
Every child is attempted in deterministic order before the parent completes
its subclass hook, owned-resource cleanup, command teardown, and stream
completion. Flavors whose disposal surface can report failures preserve the
first failure in execution order, finish all mandatory teardown, and then
propagate that original failure. Later failures do not replace it. Repeated or
re-entrant disposal remains a no-op rather than a retry for skipped cleanup.

A disposed VM MAY still receive late-arriving subscriber events from the hub if
those events were already in flight. Subscribers MUST be tolerant of this.

A modeled assignment that begins after the target VM has entered `Disposed` is
a complete no-op. The terminal check is an admission boundary and occurs before
candidate equality, retained-state mutation, derived hint or snapshot work,
validation, command-state work, consumer callbacks, local notifications, or hub
messages. An assignment admitted before disposal retains its existing contract
and completes normally. Upstream cancellation remains responsible for stopping
application resources; this guard prevents only late VM state admission
(ADR-0091).

## 8. Reference table

See `fixtures/lifecycle-transitions.json` for the complete legal/illegal transition
matrix. Conformance tests (`LIFE-NNN` in `12-conformance.md`) load that fixture
directly.

## 9. Conformance

`LIFE-001` through `LIFE-014` in `12-conformance.md` cover:

- legal state transitions (construct / destruct / reconstruct / dispose)
- predicates raising `StatusTransitionError` / `StatusTransitionException` on illegal calls
- idempotency from `Constructed`/`Destructed`/`Disposed` states
- the `IsConstructed == Status == Constructed` invariant
- concurrent re-invocation during `Constructing` / `Destructing` raises (enforced by the
  §2.4 per-VM guard)
- the full transition matrix (table-driven from `fixtures/lifecycle-transitions.json`)
- dispose-from-Disposed emits no message
- dispose cascade (parent disposes children depth-first and completes all
  terminal cleanup before propagating the first failure)
- transactional rollback: a throwing `OnConstruct`/`OnDestruct` hook rolls `Status` back to
  the prior settled state and leaves the VM recoverable (`LIFE-014`, §2.5)

`DISP-001` adds the cross-cutting at-most-once assertion: invoking a parent
dispose path more than once produces one observable terminal transition and
one owned cleanup per node. See `01-concepts.md` §4 and ADR-0084.

`DISP-007` through `DISP-014` cover the owned-resource order, idempotency,
failure isolation, post-dispose registration, reconstruct lifetime, public hub
visibility, shared-hub non-ownership contract from §2.3, and inert modeled
assignment after terminal disposal (§7).
