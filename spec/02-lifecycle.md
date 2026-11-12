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
row applies to all four non-C# flavors.

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

`can_construct()` returns `true` from `Constructed`, and `can_destruct()`
returns `true` from `Destructed`, on purpose. A repeated call of those
operations in the matching state is a no-op (§4), not an error. The predicate
signals "the operation is safe to call", not "the operation will produce a
state change".

Calling an operation when its predicate returns `false` MUST raise
`StatusTransitionError` (Python / TS / Swift) / `StatusTransitionException` (C#).
Rust returns an `Err`: every illegal call returns
`VmxError::InvalidLifecycleTransition`, whose `from` and `operation` fields
name the state and the operation, also from `Disposed` and during another
transition (ADR-0203).
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
`_onConstruct` TypeScript and Swift). Rust has no subclassing: its component,
forwarding, composite, group, aggregate, and async-resource VM types expose
public `on_construct`, `on_destruct`, and `on_dispose` methods that replace the
hook with a closure returning `VmxResult<()>`. `HierarchicalVm`,
`ModeledCompositeVm`, and `ForwardingCompositeVm` have the same three methods
(ADR-0203):

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
them to drive their child construct/destruct/dispose cascades. A leaf
view-model drives its member view-models with the child-transition helper of
§6.1 and disposes them with the member-disposal helper of §7.1.

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

Every status transition atomically validates and writes `Status`, applies the
terminal guard, and reserves its place in a per-VM FIFO publication sequence.
Implementations MUST serialize this admission behind a per-VM synchronization
primitive: a per-VM lock/monitor and FIFO publication queue in C#, Python, Swift,
and Rust (Rust's `ComponentCore` is mutex-backed); and the single-threaded event
loop in TypeScript. This guarantees
that a transition completing on the background scheduler (§4 background
construct/destruct, `11-threading.md §4`) cannot interleave with `dispose()`:
the completion observes `Disposed`, or an inline dispose cascade in progress
(§7.2), under the guard and aborts instead of resurrecting the VM or reserving
a post-terminal publication (invariant 6).

A container's construct commit step (chapter 06 §5.1, ADR-0186) is one such
transition write. Under the guard, it writes `Constructed` and reserves the
publication.
The publication follows when the transition completes, and only `Disposed`
can replace it (§7.2). Until then, `Status` reads `Constructed` and the
transition stays in flight (invariant 5).

Consumer callbacks MUST NOT run while that state guard is held. The admitted
`ConstructionStatusChangedMessage`, local property notifications, command
triggers, and lifecycle waiter completions are delivered by the per-VM
serializer after releasing the guard. A normal top-level call remains
synchronous through its publication. A foreign call MAY enqueue and return only
when waiting for the target drainer would close an actual thread wait cycle;
unrelated foreign calls wait synchronously. The target drainer preserves FIFO
order and completes terminal stream teardown only after the `Disposed`
publication (ADR-0117).

The concurrent-re-invocation rule (invariant 5 / `LIFE-008`) is enforced by this
same primitive together with an in-flight guard: a second `construct()` /
`destruct()` / `reconstruct()` entered while one is in progress MUST raise rather
than rely on an unsynchronized `Status` read. The enforcement primitive is
named normatively so flavors do not detect re-entrancy with a racy status read.

Hook admission is part of the same atomic transition decision. Once a
construct/destruct hook is admitted, foreign `dispose()` publishes the terminal
status but waits for that hook and its container action before running terminal
cleanup. The hook rechecks terminal supersession before any post-hook container
action, so disposed parents cannot begin new child work. Factory population is
such an action. A container whose construct hook a foreign `dispose()`
superseded does not call its children factory and attaches nothing. Its
`construct()` returns without an error, as §7.2 says for a superseded call
(ADR-0218, `LIFE-015`). An `add()` during disposal still fails.

If two active hooks
cross-dispose their peers, the flavor's wait-for graph breaks the cycle by
deferring one VM's terminal cleanup to its admitted hook's completion; both
hooks and both teardown paths still run exactly once. TypeScript's
single-threaded event loop cannot form this foreign-thread wait. Swift keeps its
documented nonthrowing disposal surface.

Throwing/result-based flavors preserve
the earliest already-propagating failure when deferred cleanup also fails;
later cleanup failures never replace it (ADR-0126). When the call that runs the
deferred cleanup has no earlier failure, it reports the cleanup's first failure
(ADR-0200).

That call is the admitted hook's `construct()`, `destruct()`, or
`reconstruct()`, which `Disposed` has superseded. Its background form reports
the failure through the flavor's background-failure path. A C# async method
reports it as it reports a hook failure. The cycle-broken `dispose()` returns
normally.

In C#, Python, Swift, and Rust, lifecycle publication waits and hook-lease
waits are recorded in the flavor's single wait-for graph, with its hub,
container membership, and ownership waits (chapter 03 §4.1, ADR-0172). Each
edge is keyed by the one delivery or hook lease that the caller waits for,
never by the VM. A Rust status publication is a hub send, so it records a hub
edge. A cycle that crosses these
waits is therefore refused like any other: the wait that would close it takes
the escape above. `dispose()` does not return before another thread's admitted
hook, or another thread's delivery of the VM's `Disposed` publication,
finishes, unless that wait would close a live cycle. A cycle is live only when
every owner on it still holds its resource. The thread that finishes a hook or
delivers a publication removes the edges that name it as that resource's
owner before it wakes the waiters, so an ended wait never causes an early
return or a deferred cleanup.

When no hook is admitted on another thread, `dispose()` closes hook admission
under the same guard before it disposes the first child or member. From then
on, no construct or destruct hook of the VM is admitted, a lifecycle call that
starts fails, and a transition that started earlier commits no further status:
the VM's next and last status is `Disposed` (§7.2, ADR-0175).

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

This behavior is verified by `LIFE-014`. Coordination between an admitted hook
and terminal disposal is verified by `LIFE-015`. A transition during the inline
dispose cascade is verified by `LIFE-021` (§7.2).

## 3. Invariants

These hold for every VM at every point in its lifetime:

1. `Status` is one of the five `ConstructionStatus` values.

1. `IsConstructed == (Status == Constructed)`.

1. Once `Status` reaches `Disposed`, it never changes again. All lifecycle
   operations from `Disposed` (except `dispose` itself, which is idempotent)
   raise. They also raise once an inline dispose cascade has started, before
   `Status` reads `Disposed` (§7.2).

   A `select()` or `deselect()` call on the VM itself after `Disposed` is a
   silent no-op. It does not raise and emits no `PropertyChangedMessage`,
   unlike the lifecycle operations, which raise (VMX-006). The composite's
   `Current` setter is a different path: it raises the non-member error for a
   `Disposed` child (chapter 06 §4.3 rule 2).

   One change still applies: when its composite stops making it `Current`, a
   `Disposed` VM's `IsCurrent` becomes `false`. The VM publishes no
   `PropertyChangedMessage` for that change (chapter 06 §4.3, ADR-0189).

1. Every `Status` change publishes exactly one `ConstructionStatusChangedMessage`
   on the VM's message hub before the operation returns (synchronous) or before the
   awaiter resumes (asynchronous). A transactional rollback (§2.5) is itself a
   status change and so publishes its own message.

1. A VM in `Constructing` or `Destructing` MUST NOT have its operation re-invoked
   concurrently. Implementations MUST raise on the second invocation, detected via
   the per-VM guard of §2.4 (not an unsynchronized `Status` read).

1. Each status transition is atomic with respect to other lifecycle operations on
   the same VM (§2.4). A transition racing `dispose()` observes the terminal
   `Disposed` state, or an inline dispose cascade in progress (§7.2), under the
   guard and aborts — it never resurrects the VM nor publishes a post-dispose
   message or a status other than `Disposed` once the cascade has started.

1. If `OnConstruct` / `OnDestruct` raises, `Status` is rolled back to the prior
   settled state (`Destructed` for a failed construct, `Constructed` for a failed
   destruct) before the exception propagates (§2.5); the VM never remains in a
   transient state after a failed hook.

## 4. Idempotency

- `construct()` from `Constructed` is a no-op. `Status` remains `Constructed`. No
  `ConstructionStatusChangedMessage` is emitted.
- `destruct()` from `Destructed` is a no-op. Same emission behavior.
- `dispose()` from `Disposed` is a no-op. No emission.

The first two no-ops do not apply once an inline dispose cascade has started:
`construct()` and `destruct()` then fail (§7.2).

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
  reached `Constructed`. For a composite or group, every child means every
  member when the construct walk checks it. A child that a removal takes out
  during the walk does not count. A child added after the walk's commit step
  follows the add-after-`Constructed` rule (chapter 06 §5.1, ADR-0186).
- A composite/group/aggregate's `destruct()` completes only when every child has
  reached `Destructed`.
- A child that is `Disposed` does not count for either rule (ADR-0189). The
  walk skips a child that is `Disposed` when the walk reaches it. It also
  stops waiting for a child that reaches `Disposed` while the walk waits for
  it. Neither case fails the walk, and the walk calls no lifecycle operation on
  a `Disposed` child (invariant 3). A composite or group keeps the `Disposed`
  child as a member until a consumer removes it. An `AggregateVM` that holds a
  `Disposed` slot leaves `Constructed` through `destruct()` or `reconstruct()`.
  Its next construct replaces the slot from the slot factory (chapter 08 §2).
  A child in its inline dispose cascade (§7.2) is not `Disposed` yet. A walk
  call on that child fails with the `Disposed` error (`LIFE-021`), and the
  container rolls back. `LIFE-022` covers this rule.
- A walk starts a child only when no transition of the child is in flight. It
  checks this together with its start call (ADR-0218). A walk that finds a
  transition of the child in flight in the walk's own direction joins it: a
  construct for a construct walk, a destruct for a destruct walk. This
  includes one that another thread started after the walk read the status
  (ADR-0227). A child whose `reconstruct()` is in its destruct phase settles
  at `Constructed`, so a container `destruct()` that joins it rolls back to
  `Constructed`. The call raises the child's failure when the walk learns of it
  before the call returns. A join still in flight when the walk registers it
  lets the call return `Ok`, and the container rolls back when the child fails
  (ADR-0227 §3, §5).
- A walk that waited, for a child to settle or for an add's start attempt,
  and did not continue at once, continues on the walking VM's own foreground
  dispatcher. This covers the rest of the walk, its `after` step, its commit
  step and the terminal publication. A walk whose waits all end at once runs
  on the calling thread to its end (chapter 11 §4, ADR-0218). The rule also
  covers the child-transition helper of §6.1.
- The order in which children are constructed/destructed is unspecified,
  except as the next item says. Implementations MAY drive them sequentially or
  concurrently. The reference implementations drive aggregates and the Rust
  composites and groups sequentially. The C#, Python, TypeScript, and Swift
  composites and groups start factory-populated children during population,
  so background children in those containers can run concurrently. The parent
  observes its children's `ConstructionStatusChangedMessage` emissions to know
  when to finalize its own state. Because the default order is unspecified,
  subscribers MUST NOT rely on a particular child visitation order (VMX-046).
- A `GroupVM` or `CompositeVM` built with the `Reverse` destruct order
  (chapter 06 §5, chapter 07 §2, ADR-0161) MUST destruct and dispose its
  children in reverse child order, last child first. This covers the destruct
  phase of `reconstruct()`, and the walk waits for each background child
  before it starts the next one. Construct order does not change. The default
  order, `Insertion`, stays unspecified; every reference implementation walks
  the children first child first. `GRP-014` and `COMP-046` constrain the
  `Reverse` order.

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

### 6.1 Child-transition helper for leaf view-models

A leaf view-model (a subclass of `ComponentVMBase`) that keeps member
view-models in fields uses the child-transition helper to construct and
destruct them inside its own transition (ADR-0162). The helper takes an
ordered list of children, a direction, and an optional `after` callback:

- It walks the list in the given order. It starts a child only after the
  previous child settled.
- It skips a child that is already at the target status (`Constructed` for
  construct, `Destructed` for destruct), and a child that is `Disposed` (§6).
  It joins a child that is already in the transient status (`Constructing` or
  `Destructing`) and does not start it again (`LIFE-020`).
- It waits for a background child. The parent stays in its transient status
  until the child settles, and only then starts the next child (`LIFE-016`).
- A child that settles at any status other than the target or `Disposed`
  fails the walk.
  The parent rolls back to its prior settled status, as in §2.5, and the
  failure surfaces from the call or through the flavor's background-failure
  path (`LIFE-017`). The helper does not undo a sibling that already reached
  the target. Whether a walk should undo it is an open question.
- It runs `after` exactly once, after every child settled at the target and
  before the parent publishes its terminal status. A failing `after` rolls the
  parent back like a failing child.
- Only the parent's own construct and destruct hooks may call it, including
  the two phases of `reconstruct()`. A call from anywhere else raises the
  flavor's usage error and starts no child.

**Several failures in one flush.** A shared scheduler can run the lifecycle
work of several calls in one synchronous flush. Each failure in that flush is
reported exactly once (ADR-0200). The first failure to leave the flush is
thrown to the flush's caller, and no later failure replaces it. Every other
failure of the flush goes to the flavor's unhandled-error route after the flush
returns. This includes a failure of work that VMx runs again after a flush
error dropped it. A scheduler that cancels its queued work on purpose marks
itself first, so VMx runs none of the lifecycle work that it unsubscribes. Only
TypeScript has such a flush: `RxDispatcher.immediate()` and `NullDispatcher`
run both channels on rxjs `queueScheduler`. Its unhandled-error route is rxjs
`config.onUnhandledError`, and its mark is `markSchedulerCancelled`. TypeScript
also uses that route for a failure throw that any foreground scheduler
unsubscribes before it runs, including a separate or cancelled scheduler.

The helper has no child-order option: the caller passes the children in the
order it wants. A leaf that destructs its members in reverse passes the
reversed list (`LIFE-019`).

| Flavor     | Helper                                                                                           | Usage error                 |
| ---------- | ------------------------------------------------------------------------------------------------ | --------------------------- |
| C#         | `CompleteLifecycleHookAfter(TransitionChildrenAsync(children, construct, after))`                | `InvalidOperationException` |
| Python     | `self._complete_lifecycle_hook_after(self._transition_children(children, construct=…, after=…))` | `RuntimeError`              |
| TypeScript | `this._transitionChildren(children, construct, after)`                                           | `Error`                     |
| Swift      | `try _transitionChildren(children, construct: …, after: …)` (`public`)                           | `ChildTransitionError`      |
| Rust       | `on_construct_children` / `on_destruct_children`, or a one-call `*_with_children` walk           | none (compile time)         |

C#, Python and TypeScript keep the helper protected. Swift makes it `public`
so that a subclass in another module can call it. Rust has no subclassing: a
consumer view-model type composes a `ComponentVm` and gives it a walk closure,
which the component runs after its hook and passes a `ChildTransitions`
handle. The handle adds child steps (`transition`) and the `after` step
(`then`). It borrows the transition, so it cannot be used outside the closure.
`on_construct_children` and `on_destruct_children` store a walk, so every
`construct()`, `destruct()`, `reconstruct()` and reconstruct command runs it,
as the hooks of the other flavors call the helper.
`construct_with_children`, `destruct_with_children` and
`reconstruct_with_children` run a walk for one call in place of the stored
one. A walk runs where the hook runs, so a component built with
`background(true)` runs it on the background dispatcher (chapter 11 §4,
ADR-0203).

## 7. Disposal cascade

`dispose()` on a parent disposes every child (synchronously, depth-first). This
ensures no orphaned `IDisposable` resources are left behind. A `GroupVM` or
`CompositeVM` built with the `Reverse` destruct order disposes its children
last child first (§6, ADR-0161).

The order of the parent's `Disposed` publication depends on the hooks that run
when `dispose()` starts (ADR-0179). A *foreign dispose* is a `dispose()` call
while a construct or destruct hook of the parent is admitted on another thread
(§2.4).

- **Not foreign.** The parent disposes its children inline, under the rules of
  §7.2. Every child reaches `Disposed` before the parent publishes `Disposed`
  (`LIFE-013`). A dispose from the hook's own thread is not foreign.
- **Foreign.** The parent publishes `Disposed` first. It then waits for the
  hook, or defers its terminal cleanup to the hook's completion when the wait
  would close a cycle (§2.4). After that, it disposes its children, before its
  subclass dispose hook runs (`LIFE-015`).

TypeScript runs its hooks on one thread, so a foreign dispose cannot occur
there.

Once disposal begins, a failure cannot abort the remaining terminal work.
Every child is attempted in deterministic order before the parent completes
its subclass hook, owned-resource cleanup, stream completion, and command
teardown. Flavors whose disposal surface can report failures preserve the
first failure in execution order, finish all mandatory teardown, and then
propagate that original failure. Later failures do not replace it. Repeated or
re-entrant disposal remains a no-op rather than a retry for skipped cleanup.

The call that runs the terminal cleanup reports its failure. A deferred cleanup
(§2.4) reports it from the admitted hook's lifecycle call, not from the
`dispose()` call that deferred it (ADR-0200). Rust also defers a `dispose()`
made on the hook's own thread, and the same rule applies: that `dispose()`
returns `Ok(())`, and the hook's call returns the failure. C# and Python run
that disposal inline, so their `dispose()` raises it. Swift disposal does not
throw and reports nothing.

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

### 7.1 Depth-first member disposal

A leaf view-model registers each member view-model with the member-disposal
helper: `OwnMember` in C#, `_own_member` in Python, `ownMember` in TypeScript
and Swift, and `own_member` in Rust (ADR-0162). Registration returns the member
in C#, Python, TypeScript and Swift; Rust returns a `VmxResult<()>`.

The member-disposal rules are:

1. **Order.** `dispose()` stops waiting for a pending child walk, then
   disposes the registered members in registration order. Each member disposes
   its own children first, so the cascade stays depth-first (`LIFE-018`). A
   container disposes its children before its members. The members follow the
   two orders of §7 (ADR-0179).
1. **Publication.** For a dispose that is not foreign, every member reaches
   `Disposed` before the parent publishes `Disposed`. For a foreign dispose,
   the parent publishes `Disposed` first, waits for the hook (§2.4,
   `LIFE-015`), and then disposes the members before its subclass dispose
   hook.
1. **Failures.** Member disposal is best-effort, as in §7. Every member is
   attempted, and the first failure is reported after the parent's mandatory
   teardown. Swift disposal does not throw, so Swift attempts every member and
   reports nothing.
1. **Late registration.** A member registered once the parent's disposal has
   started, or after it reached `Disposed`, is disposed at once.
1. **Repeated dispose.** While the member cascade runs, any further
   `dispose()` of the parent returns at once without waiting and does nothing.
   This holds for a re-entrant call on the same thread and for a call from
   another thread. The first call finishes the cascade. For a dispose that is
   not foreign, the first call publishes `Disposed` only after the members. A
   caller that returns early can therefore observe the parent before it is
   `Disposed`.
1. **Self-registration.** Registering the view-model itself is a usage error:
   `InvalidOperationException` in C#, `RuntimeError` in Python, `Error` in
   TypeScript, a trap in Swift (ADR-0009), and `VmxError::OwnershipCycle` in
   Rust.
1. **Lifecycle calls.** Member disposal follows the cascade rule of §7.2. A
   member dispose hook can call `construct()` or `destruct()` on its leaf.
   That call gets the lifecycle error, and the leaf commits no status other
   than `Disposed` (`LIFE-021`).

A member is not a container child. It has no parent link and no selection
state, and registration does not construct it. A leaf that wants reverse
teardown registers its members in reverse order. Resources registered with
`own` (§2.3) are still released after the parent publishes `Disposed`.

### 7.2 Lifecycle calls during the inline cascade

The *inline cascade* of a VM is the part of its first `dispose()` call that
disposes its children (§7) and its registered members (§7.1) while no
construct or destruct hook of the VM is admitted on another thread. It starts
when that call closes hook admission under the §2.4 guard, and it ends when the
VM publishes `Disposed`. A VM with no children and no members has no inline
cascade. When a hook is admitted on another thread, disposal publishes
`Disposed` first (§2.4), and invariant 3 applies (ADR-0175).

A `construct()`, `destruct()`, or `reconstruct()` call that starts during the
inline cascade fails with the error that the same call raises on a `Disposed`
VM. The call can come from a child or member dispose hook, a subscriber, or
another thread. The error names `Disposed` and the attempted operation, as in
§2.1: `StatusTransitionException` in C#, `StatusTransitionError` in Python,
TypeScript, and Swift, and `VmxError::InvalidLifecycleTransition` from
`Disposed` in Rust (ADR-0203). The background form
and the C# async methods deliver it the way they deliver it for a call from
`Disposed`. The call publishes no status, admits no hook, starts no child work,
and calls no slot factory. This check runs before the idempotent no-ops of §4,
the legality check of §2.1, and the concurrent-operation check (`LIFE-008`), so
`construct()` from `Constructed` fails in the same way. The §2.1 predicates do
not change: they read `Status`, which does not read `Disposed` yet.

Once the inline cascade has started, the VM admits no construct or destruct
hook and commits no status other than `Disposed`. A transition that started
before the cascade therefore publishes nothing more. This covers its settled
commit, its rollback after a failed hook, child step, or `after` callback
(§2.5, §6.1), the restore after a failed transient publication, a commit that a
background transition queued on the foreground, and the construct phase of
`reconstruct()`. Such a call returns as a call that `Disposed` superseded
returns (invariant 6): the supersession raises nothing, a failure that was
already propagating still propagates, and the in-flight guard is cleared. Until
the cascade publishes `Disposed`, `Status` can still read the transient or
prior status after the call returns.

A container's child cascade and a leaf's member cascade (§7.1) follow these
rules in the same way (`LIFE-021`).

## 8. Reference table

See `fixtures/lifecycle-transitions.json` for the complete legal/illegal transition
matrix. Conformance tests (`LIFE-NNN` in `12-conformance.md`) load that fixture
directly.

## 9. Conformance

Chapter 12 §3 holds the `LIFE` IDs, and §30 holds the `DISP` IDs. The table
maps each ID to the rules of this chapter, and chapter 12 states the behavior
of each ID.

| IDs                                            | Rules                                                      |
| ---------------------------------------------- | ---------------------------------------------------------- |
| `LIFE-001`, `LIFE-002`, `LIFE-004`             | §2 operations                                              |
| `LIFE-003`                                     | §5 reconstruct                                             |
| `LIFE-005`..`LIFE-007`                         | §3 invariants                                              |
| `LIFE-008`                                     | §2.4 concurrency guard                                     |
| `LIFE-009`, `LIFE-010`, `LIFE-012`             | §4 idempotency                                             |
| `LIFE-011`                                     | §8 reference table (`fixtures/lifecycle-transitions.json`) |
| `LIFE-013`                                     | §7 disposal cascade                                        |
| `LIFE-014`                                     | §2.5 transactional hook failure                            |
| `LIFE-015`                                     | §2.4 disposal during an admitted hook                      |
| `LIFE-016`, `LIFE-017`, `LIFE-019`, `LIFE-020` | §6.1 child-transition helper                               |
| `LIFE-018`                                     | §7.1 depth-first member disposal                           |
| `LIFE-021`                                     | §7.2 lifecycle calls during the inline cascade             |
| `LIFE-022`                                     | §6 container walks and a `Disposed` child                  |
| `DISP-001`                                     | §7 repeated parent disposal (chapter 01 §4, ADR-0084)      |
| `DISP-007`..`DISP-011`                         | §2.3 owned resources                                       |
| `DISP-012`, `DISP-013`                         | §2.3 shared hub; chapter 05 §2.2 hub exposure              |
| `DISP-014`                                     | §7 modeled assignment after disposal                       |
