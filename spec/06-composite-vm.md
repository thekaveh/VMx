# 06 — CompositeVM

`CompositeVM<VM>` is a container with selection: it holds an ordered list of child
viewmodels and exposes a `Current` slot that designates at most one child as the
selected one.

## 1. Variants

| Variant                         | Children source                                      | `Current` |
| ------------------------------- | ---------------------------------------------------- | --------- |
| `CompositeVM<VM>` (non-modeled) | builder factory `() -> Iterable<VM>`                 | yes       |
| `CompositeVM<M, VM>` (modeled)  | model factory `() -> Iterable<M>` + mapper `M -> VM` | yes       |

The non-modeled builder factory is evaluated once, on the first `construct()`,
as for `GroupVM` (chapter 07 §3). A built composite has no children before
then (ADR-0204).

For domains that are natively recursive (trees), use `HierarchicalVM<TModel, TVM>` (chapter 18) instead of
recursively nesting `CompositeVM<M, VM>`. `HierarchicalVM` provides built-in parent / depth / path semantics
plus depth-first construction order.

## 2. Members

```
CompositeVM<VM> : ISelectableVmCollection<VM>:
    # IComponentVM members (see 01-concepts.md and 05-component-vm.md):
    Name, Hint, Type=Composite, IsCurrent, IsConstructed, Status,
    SelectCommand, DeselectCommand, SelectNextCommand, SelectPreviousCommand,
    ReconstructCommand, can_construct/construct/..., can_select/select/...

    # CompositeVM-specific:
    Current : VM?                        # may be null; one child or none

    # IList<VM>:
    Add(vm: VM) : void
    Remove(vm: VM) : bool
    Insert(index: int, vm: VM) : void
    RemoveAt(index: int) : void
    Replace(index: int, vm: VM) : void
    Clear() : void
    Move(fromIndex: int, toIndex: int) : void
    Count : int
    indexer [i] : VM
    iterator

    # Selection:
    select_component(vm: VM) : void
    deselect_component(vm: VM) : void
    can_select_component(vm: VM) : bool
```

### 2.1 The `ICompositeVM<VM>` contract

`ICompositeVM<VM>` is the compatibility name every `CompositeVM<VM>` realizes.
It extends the shared selectable VM collection capability (chapter 01 §1.4,
ADR-0085), which combines the non-selecting collection surface with
the members above describe:

```
ICompositeVM<VM> : ISelectableVmCollection<VM>:
    Current : VM?                         # selection slot (§3)
    select_component(vm: VM) : void       # guarded selection (§3.1)
    deselect_component(vm: VM) : void
    can_select_component(vm: VM) : bool
```

The shared collection surface contributes `Add` / `Remove` / `Insert` /
`RemoveAt` / replacement / `Clear` / `Move` / `BatchUpdate` / `Count` / the
indexer / iteration / collection-change observation; `Current` and the three
`*_component` methods are the composite-specific additions over the base
`IComponentVM`. This is the interface `ForwardingCompositeVM<VM>`
(`09-forwarding.md`) wraps and delegates; chapter 09 references this declaration
as canonical rather than re-declaring it inline. `ICompositeVM<VM>` is the
language-neutral contract name; each flavor realizes it per the ADR-0006 idiom:
C# ships the literal `ICompositeVM<VM>` interface, Python the structural
`CompositeVMProto` (the `…Proto` convention catalogued in ADR-0009), and
TypeScript the structural `CompositeVMBase<VM>` shape the forwarding decorator
wraps. Swift realizes it as the `open class CompositeVM<Child>`, which
`ForwardingCompositeVM` subclasses and wraps. Rust has no separate interface: the
concrete `CompositeVm<T, D>` struct is the surface that `ForwardingCompositeVm`
holds and delegates to.

## 3. `Current` contract

- `Current` MAY be `null` (no child selected).
- If `Current` is non-null, it MUST be a member of the children collection.
- Setting `Current` to a value not in the children collection MUST raise. A
  child that an `Add`, `Insert`, index replacement or population has attached
  but not yet admitted is not in the collection for this rule (§4.3).
- Setting `Current = null` is always legal (no-op if already null), also while
  disposal of the composite is pending. The only refusal is a call inside the
  caller's own uncommitted membership transaction (§4.3).
- While disposal of the composite is requested or deferred, setting a non-null
  `Current` MUST raise. After `Disposed`, the composite keeps its documented
  post-dispose behavior (chapter 01 §4). When the value is also not a member,
  the disposal refusal applies, not the non-member refusal (§4.3, ADR-0217).
- Another thread's membership transaction never makes a selection fail or wait
  (§4.3, ADR-0173).
- A `Disposed` child is not selectable. Setting `Current` to it raises the
  non-member error (§4.3 rule 2, ADR-0189).
- When the child that is `Current` publishes `Disposed` from its own
  `dispose()`, the composite clears `Current` (§4.3 rule 9, ADR-0189).
- While the composite is `Destructing`, a non-null selection changes nothing
  and raises nothing (§4.3 rule 8, ADR-0188).
- A change to `Current` fires `PropertyChangedMessage("Current")` and updates the
  affected children's `IsCurrent` (raising their `PropertyChangedMessage("IsCurrent")`).
- If the builder enabled `AsyncSelection(true)`, the setter dispatches the work via
  `IDispatcher.Foreground` and returns immediately. The new `Current` is observable
  only after the dispatcher delivers. The call validates as the synchronous
  setter does, and the delivery validates again; a delivery that is no longer
  valid is a silent no-op (§4.3). If `AsyncSelection(false)` (the default), the
  setter is synchronous.

### 3.1 `select_component(vm)` / `deselect_component(vm)`

- `select_component(vm)` sets `Current = vm` after verifying `can_select_component(vm)`.
  If the predicate is false, the call raises. The one exception is a call
  that only §4.3 rule 8 refuses: it changes nothing and raises nothing.
- `deselect_component(vm)` sets `Current = null` after verifying `Current == vm`.
  If `Current != vm`, the call raises. This is a guarded convenience; the raw
  `Current = null` setter (§3) checks nothing else. Like every selection call,
  both calls are refused inside the caller's own uncommitted membership
  transaction (§4.3).
- `can_select_component(vm)` returns `true` iff `vm ∈ children` and `vm.Status == Constructed`,
  and `select_component(vm)` would not be refused now: `vm` is admitted, no
  disposal of the composite is pending, the composite is not `Destructing`,
  and the caller is not inside its own uncommitted membership transaction
  (§3, §4.3, ADR-0173, ADR-0188).
- The child `select()` and `deselect()` paths run the same checks. A refusal
  there changes nothing and raises nothing, in every flavor (chapter 05 §6,
  ADR-0188).

### 3.2 Initial `Current` selection and change callback (spec v2.6.0)

`CompositeVMBuilder<VM>` and `CompositeVMOfMBuilder<M, VM>` accept two optional declarative hooks for `Current`:

- `Current(selector)` — `selector: Iterable<VM> -> VM | None`. Invoked during every construct phase of the composite, including the construct phase of `reconstruct()`, **after** all children have transitioned to `Constructed` and **before** the composite reaches `Constructed`. The selector receives the composite's membership when it runs, so it sees a late child (§5.1). Its pick goes through the assignment below, so a pick that is not an admitted member is a no-op (ADR-0218, `COMP-053`). Destruct first sets `Current` to `null` (§5), which reports `null` to `OnCurrentChanged`, so each construct selects again. To restore the previous selection, record only the non-null values that `OnCurrentChanged` receives and return the last one from the selector; if that child is no longer contained, the assignment is the no-op described below (ADR-0158). The composite assigns `Current` to the selector's return value through an internal **non-raising validated assignment** — NOT the guarded `select_component` path, which raises on a non-child (§3.1, `COMP-009`). If the selector returns a contained child, the normal `Current` transition fires (`PropertyChangedMessage("Current")` plus the `IsCurrent` updates of §3). If the selector returns `null` or a value not contained in the composite, the assignment is a **silent no-op**: `Current` stays at its prior value (initially `null`) and no notification fires. (ADR-0042 §5.1 phrased this as "the `SelectComponent` path"; ADR-0050 corrects the wording to the non-raising assignment that the reference implementations and `COMP-025` actually exercise, reconciling it with §5.4's no-op rule.)
- `OnCurrentChanged(callback)` — `callback: (VM | None) -> void`. Invoked synchronously after every `Current` transition, **after** the state is updated and the hub publishes `PropertyChangedMessage("Current")`. Receives the new `Current` value (which may be `null`). Re-entrant disposal from this callback is deferred through the current-publication lease and completes after publication without deadlocking selection (§4.3). The shared cross-composite coordinator protects validation and the committed state update only; hub publication and consumer callbacks execute after it is released.

The construct walk's assignment uses committed membership and never waits
(ADR-0165, ADR-0173). Every flavor follows these rules:

- It opens no membership transaction. Another thread's open transaction
  neither fails it nor makes it wait. The composite reaches `Constructed` with
  the selected child current, also when that thread waits for the walk.
- A child that an `Add`, `Insert`, index replacement or population has
  attached but not yet admitted is not contained yet. Its rollback could still
  remove it.
- While disposal of the composite is requested or deferred, the assignment is a
  silent no-op. It is also a silent no-op on a thread that owns an uncommitted
  membership transaction of the composite (§4.3).
- A disposal requested from the assignment's own `OnCurrentChanged` or
  current-flag callbacks returns at once. The disposal starts after the
  publication and any open membership transaction end. The request does not
  wait for another thread's transaction.
- A transaction that detached the current child clears `Current` only while
  that child is still current. It never clears a selection made after the
  detach.
- The assignment is synchronous, also with `AsyncSelection(true)`: the
  composite reaches `Constructed` with the selected child already current.

The other selection paths commit in the same way (§4.3).

Both hooks are optional; absent calls yield v2.5.0 behavior. The hooks compose: if both are present, each selector assignment that changes `Current` triggers the callback exactly once.

Conformance: `COMP-025` (selector runs on every construct), `COMP-026` (`OnCurrentChanged` callback fires on `Current` change).

## 4. Collection change notification

The collection raises `INotifyCollectionChanged.CollectionChanged` events:

- `Add(vm)` → `CollectionChanged(action=Add, newItems=[vm], newIndex=Count-1)`.
- `Remove(vm)` → `CollectionChanged(action=Remove, oldItems=[vm], oldIndex=where vm was)`.
- `Insert(i, vm)` → `CollectionChanged(action=Add, newItems=[vm], newIndex=i)`.
- `RemoveAt(i)` → `CollectionChanged(action=Remove, oldItems=[old], oldIndex=i)`.
- `Move(from, to)` → one `CollectionChanged(action=Move, oldItems=[vm], newItems=[vm], oldIndex=from, newIndex=to)`.
- `Clear()` → `CollectionChanged(action=Reset)`.

Move follows chapter 01 §1.4 exactly: indices are validated before mutation,
same-index moves emit nothing, and a successful move preserves child identity,
parent, lifecycle, subscriptions, and `Current`.

After each local event, the composite publishes the equivalent
`CollectionChangedMessage` to its hub, sending it as itself (chapter 01 §1.4,
ADR-0142, `COMP-042`). Once its disposal is requested or deferred, it publishes
nothing, also for a change whose local event it has delivered (chapter 01 §1.4,
ADR-0190, `COMP-049`).

Rust `CompositeVm`, `GroupVm`, and `ModeledCompositeVm` expose the local
stream as `collection_changed()`, the name that `ServicedObservableCollection`
uses. It returns a `MessageHub` that receives each `CollectionChangedMessage`
before the container's hub. A hub batch never defers it (ADR-0208).

### 4.1 Batch updates (spec v1.1)

A composite MUST expose an idiomatic scoped batch API: a returned disposable /
context-manager handle, or a callback-taking method whose scope is the callback
invocation. While at least one batch scope is active, mutations (`Add`, `Insert`,
`Remove`, `RemoveAt`, `Clear`, indexer set) MUST NOT raise individual
`CollectionChanged` events. Move participates as one mutation. When the
outermost scope completes normally:

- If any mutations occurred during the batch, a single
  `CollectionChanged(action=Reset)` MUST be raised, followed by one hub
  `CollectionChangedMessage(action=Reset)`.
- If no mutations occurred, no event is raised and nothing is published.

Nested batches are ref-counted: only the outermost completion fires the `Reset`.
No hub message is published while a batch scope is active (`COMP-043`).

### 4.2 Atomic child ownership transfer (spec v3.21)

Child identity is exclusive. `Add`, `Insert`, index replacement, and builder
population MUST validate destination indices, same-container duplicate
identity, and self/ancestor cycles before changing either container.

When the child belongs to a different mutable composite or group, the
destination performs one transaction:

1. Capture the old parent, child index, selection/current flags, and deferred
   removal notification.
1. Remove the child from the old membership without destructing, disposing, or
   publishing.
1. Attach it to the destination and perform any required auto-construction.
1. Commit the old `Remove` notification before the new `Add` notification.
   Each container's hub message follows its own local event, so the hub also
   receives the old `Remove` before the new `Add` (`COMP-044`). An old parent
   whose disposal is requested sends no hub message (`COMP-049`).

The destination and any staged old parent remain under an exclusive membership
transaction through hooks and commit or rollback. Re-entrant structural
mutation of either protected container MUST fail before mutation; coherent
snapshot reads remain legal. Child reservations use a deterministic acquisition
strategy so two reverse-order bulk populations cannot deadlock. Selection
validation and assignment are one membership-gated operation that opens no
membership transaction, and deferred selection revalidates membership when it
executes (§4.3). Concurrent flavors use a shared re-entrant coordination lane
for cross-composite validation and state commit, including the affected child
current flags, then release it before hub publication and consumer callbacks.
A flavor MAY retain a logical structural transaction without its mutex during
publication. Consumer code holds neither the shared lane nor a non-reentrant
membership mutex, so opposing callback graphs cannot retain one while acquiring
another container. A callback observes the selected child still constructed;
any deferred disposal cascade begins only after the callback returns.

A membership change never waits for another thread's membership transaction
(spec v3.30, ADR-0187). The membership changes are `Add`, `Insert`, index
replacement, population, the detach of a child that moves out of the
container, `Remove`, `RemoveAt` and `Clear`. While any thread holds the
container's transaction, each of them MUST fail before mutation, on the owner
thread and on any other thread. Membership, parent links, `Current` and the
event stream stay unchanged. When the old parent refuses a detach, the add
that moves the child fails and rolls back like any failed transfer. A refusal
uses the "membership transaction in progress" error of a re-entrant change:
C# `InvalidOperationException`, Python `RuntimeError`, TypeScript `Error`,
Swift `ContainerOwnershipError.attachmentFailed`, and Rust
`VmxError::OwnershipTransactionInProgress`. Swift `remove(_:)` returns
`false`. Swift `add(_:)` cannot throw: a refused call fails a debug
assertion, and a release build returns with no change. Swift `insert(_:at:)`,
`replace(at:with:)`, `removeAt(_:)` and `clear()` cannot throw, so a refused
call returns with no change. A Swift caller that must see the refusal uses
`addResult`, `insertResult` or `replaceResult`. Rust `clear()` returns
`VmxResult<()>` and reports the refusal. Only disposal waits for another thread's transaction, as the
disposal paragraph below says. Selection follows §4.3, and a wait for a
child's ownership gate follows chapter 03 §4.1 (`COMP-048`).

If any step after preflight fails, both memberships, `Parent`, `Current`, child
current flags, lazy/builder population state, and the event stream MUST equal
their pre-call values. Bulk population rolls earlier transfers back in reverse
order if a later child fails. Lifecycle compensation is attempted. If a
consumer lifecycle hook makes compensation fail, that failure MUST be surfaced
and MUST NOT be swallowed; exact lifecycle restoration is then not claimed.
The reported failure MUST give access to the original operation failure and
to the first compensation failure (spec v3.30, ADR-0218):

- C# throws an `AggregateException`. `InnerExceptions[0]` is the original
  failure, and the compensation failures follow in order.
- Python raises the first compensation failure `from` the original failure.
- TypeScript throws `ContainerRollbackError`, with the original failure as
  `cause` and the compensation failure as `rollbackError`.
- Swift returns `ContainerOwnershipError.attachmentFailed` with a
  `ContainerRollbackError` payload, which has `originalError` and
  `compensationError`.
- Rust returns `VmxError::ContainerRollback { original, compensation }`.

In particular, when this attempt auto-constructed a previously destructed child
before admission failed, compensation destructs it back to its original state.
When that child's construct is still in flight at the rollback (a background
child), compensation does not wait. When the child's construct settles at
`Constructed` and the child has no parent, VMx calls the child's
`destruct()`. Neither the failed operation nor the container reports a
failure of that call. The failure goes where a failed fire-and-forget
background hook of that child goes (chapter 02 §2.5). In Rust that is the
child's `background_errors()` stream. A child that settles anywhere else, or
that has a parent by then, is left alone (ADR-0218, `COMP-054`). The rollback
clears the child's parent before it compensates the child.
Add, insert, replacement, and factory or bulk population MUST recheck destination
viability after successful construction hooks; destination disposal at that
point rejects admission and performs the same exact rollback. Replacement
rollback identifies the candidate by identity, restores the displaced child
before deferred disposal can take a terminal snapshot, and MUST NOT mutate an
unrelated member merely because the original index changed (ADR-0118).
The selection rules of §4.3 keep `Current` out of the rollback: the owner
thread cannot select before the commit, and no thread can select a staged
child. A selection that another thread commits on an admitted child during the
step is independent of it and stays, as does the clear of the composite's own
`destruct()` (§5).

Disposal MUST observe a stable membership boundary. If the transaction-owning
thread requests disposal of a protected old parent from an attachment or
construction hook, that terminal request is deferred until commit or rollback;
a request from another thread waits for the same boundary. When that wait would
close a wait-for cycle, because the transaction owner already waits, directly or
through other threads, for the requesting thread, the request MUST NOT wait: it
is recorded as deferred terminal intent, and the owner disposes the container
when its transaction ends (ADR-0153, ADR-0166, ADR-0167). A
successful transfer commits removal before the old parent takes its disposal snapshot. A failed
transfer restores the child, parent metadata, selection, and lifecycle before
old-parent disposal snapshots and cascades through the restored child. Once the
request is pending, the protected container rejects any new structural admission
as disposal in progress. Destination disposal requested by its own hook still
causes attachment to fail and roll back (ADR-0122).

If deferred old-parent disposal fails after a successful transfer, both
committed local membership events still publish in old-remove/new-add order
before a throwing or result-based flavor propagates that disposal failure. Only
the new parent sends its hub message, because the old parent's disposal is
requested (chapter 01 §1.4). If
attachment has already failed, that earlier attachment failure remains the
reported first failure; deferred disposal still completes but cannot replace
it. Non-throwing flavors complete the same state and notification sequence
without adding an error surface. Lazy and bulk population that reached this
commit boundary stays materialized and MUST NOT reevaluate its factory because
the later disposal step failed.

Adding an identity already present in the destination or creating a parent
cycle fails without mutation. `Move` remains the only operation that reorders
an existing child within one container.

A forwarding component decorator is a valid child. The collection retains the
decorator instance supplied by the caller, while parent ownership, lifecycle,
current flags, and the built-in selection commands behave transparently through
the wrapped component (ADR-0123).

### 4.3 Selection during membership transactions (spec v3.30)

The selection paths are the `Current` setter, `select_component`,
`deselect_component`, the child `Select` and `Deselect` paths, the
`AsyncSelection(true)` setter and its delivery, the construct walk's
assignment (§3.2), the destruct clear (§5), the clear that a detach commits
and the clear that a child's dispose commits (rule 9). The selection calls
are the setter, synchronous or asynchronous, `select_component`,
`deselect_component` and the child `Select` and `Deselect` paths. Every flavor follows these rules (ADR-0165, ADR-0173, ADR-0188,
ADR-0189):

1. **No transaction.** No selection path opens, joins or waits for a membership
   transaction, on any thread. It validates and commits `Current` and the
   affected `IsCurrent` flags under the coordination lane and the membership
   gate, and publishes after it releases both. Another thread's open
   transaction neither fails nor delays it. Publications from two threads can
   interleave.
1. **Committed membership.** A child that an `Add`, `Insert`, index
   replacement or population has attached but not yet admitted is not a
   member for selection, on any thread. The setter raises the non-member
   error, and `can_select_component` returns `false`. The child becomes
   selectable when its add admits it, before `CollectionChanged` publishes.
   When the add moves the child from another parent, it admits the child
   after that parent's detach commit, so the old parent's detach clear never
   resets the `IsCurrent` flag of a selection in the new parent (`COMP-006`).
   A `Disposed` child is not a member for selection either. The setter
   raises the non-member error, the walk's assignment and an asynchronous
   delivery are silent no-ops, and `can_select_component` returns `false`.
1. **Disposal.** While disposal of the composite is requested or deferred, a
   non-null selection is refused. A null clear is never refused because of
   disposal. For a non-null selection, this rule applies before rule 2: a
   value that is not a member gets the disposal refusal (ADR-0217).
1. **The caller's own uncommitted transaction.** A membership transaction is
   uncommitted while its rollback could still undo a staged change: a child
   attached but not admitted, a staged population, or a child detached for a
   transfer whose commit has not run. On the thread that owns such a
   transaction of the composite, every selection call on that composite fails
   before it changes anything, also a null clear, with the "membership
   transaction in progress" error. The walk's assignment there is a silent
   no-op. From the commit on, including the transaction's `CollectionChanged`
   publication, the owner thread's selection commits under rule 1.
1. **Publication lease.** A selection path that changes `Current` holds the
   current-publication lease while it publishes `Current` and `IsCurrent` and
   runs `OnCurrentChanged`. Leases nest, so a selection from those callbacks
   commits under rule 1. A disposal requested on a thread that holds a lease
   returns at once and is deferred. A disposal requested on another thread
   first follows §4.2 for a foreign membership transaction; if a lease is still
   active after that, the disposal is deferred. A deferred disposal starts when
   the last lease ends and no membership transaction is open. The deferral
   stays set until the disposal starts, so no transaction and no non-null
   selection is admitted in between. The composite sends no collection hub
   message in between either (chapter 01 §1.4).
1. **Detach clear.** A transaction that detached the current child clears
   `Current` only while that child is still current.
1. **Asynchronous selection.** With `AsyncSelection(true)`, the setter
   validates at call time under rules 2, 3 and 4 and raises as the synchronous
   setter does. It then schedules the change and returns. The delivery commits
   under rules 1 and 5 and validates membership and rules 2, 3 and 4 again; a
   delivery that is no longer valid is a silent no-op. The walk's assignment
   and the destruct clear stay synchronous.
1. **Destructing.** While the composite is `Destructing`, a non-null selection
   that rules 2, 3 and 4 admit changes nothing and raises nothing, on every
   path. This covers the setter, `select_component`, the child `select` path,
   and the asynchronous call and its delivery. `can_select_component` returns
   `false`. A null clear commits as usual. The rule also applies in the
   destruct phase of `reconstruct()`.
1. **Dispose clear.** When a child publishes `Disposed` from its own
   `dispose()` while it is `Current`, the composite clears `Current` before
   that `dispose()` returns. The clear runs after the child publishes
   `Disposed`, in both disposal orders of chapter 02 §7. Like the detach clear,
   it clears `Current` only while that child is still current, and it commits
   under rules 1 and 5. It is not a selection call, so rules 3, 4 and 8 never
   refuse it. It publishes `PropertyChangedMessage("Current")` once and runs
   `OnCurrentChanged(null)` once. The child's `IsCurrent` becomes `false`, and
   the child publishes no message for it (chapter 02 §3 invariant 3). The
   composite's own dispose cascade does not clear `Current`. The clear does
   not run while disposal of the composite is requested or deferred, or after
   `Disposed`.

Each surface reports a refusal through the channel it already uses for that
case. The Swift `current` property setter cannot throw, so it traps
(ADR-0009); `setCurrent(_:)` is its catchable form. Two refusals are silent in
every flavor: a refused child `select()` or `deselect()` (chapter 05 §6), and a
selection that only rule 8 refuses (ADR-0188).

## 5. Children construction orchestration

The non-modeled `CompositeVM<VM>` may be built with the fluent builder or the
additive positional-options form (`Create`/`create` — see `10-builders.md §7`);
both validate the same required fields (`name`, services, `children`) and produce
an identical VM.

`CompositeVM` overrides the base `construct()` and `destruct()` to coordinate
children:

- `construct()` proceeds through `Destructed → Constructing`. It calls `construct()`
  on every child; each call returns once that child has reached `Constructed`
  (per the synchronous lifecycle contract — ADR-0008). Once every child is
  `Constructed`, the composite transitions to `Constructed` and emits its own
  status message. An asynchronous flavor MAY instead observe the children's
  `ConstructionStatusChangedMessage(Constructed)` on the hub; the synchronous
  default is a strict subset of that behavior.
- `destruct()` proceeds through `Constructed → Destructing`. If `Current != null`,
  the composite first sets `Current = null`. It then calls `destruct()` on every
  child; each call returns once that child reaches `Destructed`. Once every
  child is `Destructed`, the composite transitions to `Destructed`.
- Both walks skip a child that is `Disposed` (chapter 02 §6, ADR-0189).
- The destruct clear, also in the destruct phase of `reconstruct()`, commits
  under §4.3 rules 1 and 5. It is not a selection call, so §4.3 rules 3 and 4
  never refuse it. It never raises, waits or is skipped: it also clears while
  another thread holds a membership transaction, inside the composite's own
  transaction and while disposal is deferred (`COMP-005`, ADR-0173). A disposal
  from `OnCurrentChanged(null)` is deferred through its lease. A rollback does
  not restore a `Current` that the destruct cleared. A consumer selection made
  while the composite is `Destructing` changes nothing and raises nothing
  (§4.3 rule 8, ADR-0188). This covers a selection from
  `OnCurrentChanged(null)`, from a child's destruct hook and from another
  thread. `COMP-005` therefore holds when `destruct()` returns (`COMP-051`).

The order in which children are visited is unspecified by default. Chapter 02
§6 says which reference implementations drive container children sequentially
and which start factory-populated children during population.

Both composite builders, and the options form of the non-modeled composite,
accept an optional `DestructOrder(ChildOrder)` (spec v3.30, ADR-0161):

- `Insertion` is the default. The composite keeps the current behavior, and
  every reference implementation walks the children first child first.
- `Reverse` makes `destruct()`, including the destruct phase of
  `reconstruct()`, and the `dispose()` cascade walk the children in reverse
  child order, last child first. The composite still sets `Current = null`
  before it destructs a child. The walk waits for each background child before
  it starts the next one. For a dispose that is not foreign, every child is
  disposed before the composite publishes `Disposed` (`LIFE-013`). A foreign
  dispose publishes `Disposed` first (chapter 02 §7).

The option does not change `construct()`. The rollback of a failed
population or a failed `Add`, `Insert` or `Replace` keeps its own order, newest
attachment first. The order is fixed when the composite is built.

### 5.1 Add after Constructed

A child added via `Add` AFTER the composite has reached `Constructed` does NOT
automatically `construct()` by default — the host MUST invoke it.

A composite built with `AutoConstructOnAdd(true)` (added in spec v1.1) MUST
automatically call `construct()` on any child added via `Add` / `Insert` after
the composite reaches `Constructed`, completing the child's transition to
`Constructed` BEFORE the `CollectionChanged` event fires. Builds default to
`false` for backwards compatibility.

With `AutoConstructOnAdd(true)`, a child added while the composite is still
`Constructing` is also started, and the composite reaches `Constructed` only
after that child does (chapter 02 §6). If its construction fails during the
add, the add fails and is undone. A child added before the construct walk
takes its membership snapshot (for example by the construct hook) is walked
like any other member. A child added after the snapshot is a late child: the
walk joins it and never restarts it, and if it fails while it is still a
member, the composite rolls back.

A child added before the snapshot has two possible starters: the add and the
walk. Each starts the child only when no construct of the child is in flight,
and checks this together with its start call (spec v3.30, ADR-0218). When the
walk finds the construct in flight, it joins it. When the add finds it in
flight, it does not start it again and does not wait for it. So neither the
add nor the composite fails because the other side started the child.

An add marks its start attempt done only after it ends its membership
transaction: after its commit, its local event and its hub message, or after
its rollback. A walk that waits on the attempt resumes only then, so the
composite publishes `Constructed` outside that transaction. A resumed walk
continues on the composite's foreground dispatcher (chapter 02 §6).

The construct walk counts members only (spec v3.30, ADR-0186). A member is a
child in the composite's membership when the walk checks it. These rules hold
for snapshot children and late children, with and without
`AutoConstructOnAdd(true)`:

1. Before the walk starts or joins a child, it checks under the membership
   gate that the child is a member, and skips a child that is not. It checks
   a late child after that child's add finished its start attempt.
1. After a child settles, the walk checks again. When the child is no longer
   a member, its result does not change the composite: a failure does not
   roll the composite back, and the walk goes on to the next child. A removal
   does not stop the wait; the walk goes on when the removed child settles.
1. A removal does not cancel, destruct or dispose the child. A child that the
   walk started before the removal finishes its own transition and can reach
   `Constructed`.

So a snapshot child removed before the walk reaches it is not constructed. A
snapshot background child or a late child removed while the walk waits on it
does not roll the composite back, whatever its result. A late child removed
before the walk reaches it is skipped. A failed add undoes its own attach, so
its child is removed too: the add fails, and the composite does not roll
back. The composite reaches `Constructed` when every remaining member has
(`COMP-047`).

With `AutoConstructOnAdd(true)`, the walk ends with a commit step under the
membership gate. The step joins a late child that an add started after the
walk's last scan. With none left, it writes `Status = Constructed` and
reserves the `Constructed` publication in the same gated section (chapter 02
§2.4). The publication follows when the transition completes. Until then,
`Status` reads `Constructed`, but the transition is still in flight:
`construct()`, `destruct()` and `reconstruct()` raise as for an in-flight
transition (`LIFE-008`), and the `can_*` predicates return `false`. An add in
this window follows the add-after-`Constructed` rule above, and the walk does
not join its child. A background child added in the window can therefore
still be `Constructing` when the composite publishes `Constructed`. A walk
that disposal stopped, or that its construct hook abandoned by raising after
it started the walk, commits nothing. The commit step checks this under the
same lock as the status write. TypeScript writes and publishes the status
with no consumer code in between, so it has no window.

## 6. Modeled variant `CompositeVM<M, VM>`

Identical to `CompositeVM<VM>` except the children come from a model factory:

- Builder accepts:
  - `ChildrenModels : () -> Iterable<M>`
  - `ChildModelToChildViewModel : (M) -> VM`
- On `construct()`, the composite first evaluates `ChildrenModels()`, then maps
  each `M` to a `VM`, then orchestrates children construction as above.
- When the projector throws, the composite disposes the children it already
  projected for that population and keeps no children. It applies the
  candidate-cleanup rule of chapter 08 §2 (ADR-0224): it skips a child that has
  a parent, that another ownership transaction holds, or that is an owner on
  the composite's ancestor chain, and it disposes each canonical ownership
  identity once. The projector's failure propagates. Swift and Rust projectors
  return plain values and cannot fail.

The model values themselves are NOT exposed on the composite; the composite is a
container of VMs, not models. Each child VM is responsible for holding its own
model.

## 7. Modeled CRUD commands (spec v2.0)

A modeled composite (`CompositeVM<M, VM>`) MAY opt into a CRUD command set via
the `ModeledCrudCommands<M, VM>` helper (designed in ADR-0016):

```
ModeledCrudCommands<M, VM>:
    CreateNewCommand    : ICommand    # invokes the create-new action
    UpdateCurrentCommand: ICommand    # invokes update(current_vm) when current != null
    DeleteCurrentCommand: ICommand    # invokes delete(current_vm) when current != null
```

The helper takes:

- A `current` provider (a function returning the current VM or `null`).
- A `create_new` action (a parameterless callable).
- An `update_current` action (a callable taking the current VM).
- A `delete_current` action (a callable taking the current VM).
- Optional `confirm_update` / `confirm_delete` async delegates that gate
  execution via `ConfirmationDecoratorCommand` (see chapter 04 §Decorators).
- An optional `current_changed` trigger (`Observable<Unit>`) — typically the
  owning composite's current-child-changed stream — that raises the
  Update/Delete `CanExecuteChanged` when the selection changes, so consumers
  re-read `CanExecute` (spec v3, ADR-0049).

Behavior:

- `CreateNewCommand.CanExecute` returns `true` whenever the helper exists.
- `UpdateCurrentCommand.CanExecute` returns `true` iff `current != null`.
- `DeleteCurrentCommand.CanExecute` returns `true` iff `current != null`.
- When a confirm delegate is supplied, the command is wrapped in a
  `ConfirmationDecoratorCommand` and `Execute` resolves the confirm gate
  before invoking the action.
- The `CanExecute` predicate **values** above (`true` iff `current != null`) are
  verified by `COMP-021` / `COMP-023`. Their **reactivity** is separate: because
  the predicates read the mutable `current` provider, `CanExecuteChanged` cannot
  fire on its own (chapter 04 §4), so a bound button's enabled state would go
  stale on every selection change. When a `current_changed` trigger is supplied,
  the helper wires it as a `Triggers` source on the Update and Delete commands so
  `CanExecuteChanged` fires the moment the selection changes and consumers
  re-read `CanExecute` (chapter 04 §4.2, ADR-0049). Supplying the trigger is
  RECOMMENDED whenever the commands are bound to UI; omitting it leaves
  `CanExecute` correct on demand but non-reactive. Exposing the optional
  `current_changed` parameter is, per ADR-0049, a clarification first realized in
  C# (VMX-011). All five flavors accept the trigger: C# (`currentChanged`),
  Python (`current_changed`), TypeScript (the `currentChanged` option field),
  Swift (`currentChanged`), and Rust (`ModeledCrudCommands::with_options`, which
  also takes the confirm gates, and `ModeledCrudCommands::with_current_changed`).
  The trigger also reaches the Update and Delete commands that a confirm gate
  wraps, and `dispose()` releases the trigger subscriptions.

Rust takes the two gates as `Fn() -> AsyncValue<bool>` closures in
`ModeledCrudCommands::with_options`, with the `current_changed` trigger. Its
Update and Delete accessors return `Arc<dyn Command>`; a gated command is a
`ConfirmationDecoratorCommand` and is awaited through `Command::as_async`.
`update_confirmation()` and `delete_confirmation()` return the gated command
with its concrete type, for its error stream, and `dispose()` disposes every
command the helper built (ADR-0210).

The helper is opt-in; the base `CompositeVM<M, VM>` retains its current shape.

## 8. Search / filter (spec v2.0, source reactivity v3.19)

A composite (or group) MAY opt into search/filter via the `SearchableState`
helper, which implements `ISearchable` from chapter 14 (designed in ADR-0014):

```
SearchableState<TItem>:
    SearchTerm : string                          # read/write; debounced
                                                 # (default 1s, configurable)
    Predicate : (TItem, string) -> bool           # user-supplied
    Items : Iterable<TItem>                       # current source set
    SourceChanged : Observable<void>?             # optional invalidation signal
    Filtered : Observable<list<TItem>>            # filtered set, recomputed on
                                                 # debounced SearchTerm change,
                                                 # SourceChanged, or search()
    can_search() : bool
    search() : void                              # force immediate recompute
```

Behavior:

- Setting `SearchTerm` to a new value starts an internal debounce. The default
  debounce is **1 second**; consumers may override via builder/constructor. No
  flavor exposes the debounced term as a public stream; consumers observe
  `Filtered`.
- Construction starts no debounce, whatever the debounce length. The initial
  empty term is not a new value. After construction, `Filtered` emits only
  for a term change after its debounce, a `search()` call, or a source signal
  (ADR-0198). A replay of the current value to a new subscriber is not a new
  emission.
- After the debounce, the helper recomputes `Filtered` by applying
  `Predicate(item, search_term)` to each item in `Items` and emitting the
  list of matches.
- `Predicate` is user-supplied; common defaults (case-insensitive substring
  match) are NOT mandated by the spec.
- `search()` forces an immediate recompute, bypassing the debounce.
- `can_search()` returns `true` when at least one item is present (helpers
  MAY relax this).
- When an optional `SourceChanged` signal is supplied, every signal immediately
  re-reads `Items`, applies the current `SearchTerm`, and emits one filtered
  snapshot. The signal payload is ignored.

The debounce runs on an injected scheduler (chapter 11 §6). Rust maps the
pushed output to one `Custom("filtered")` message on the `filtered_changed()`
hub, and consumers pull the projection with `filtered()`. Rust sets the
debounce with `with_debounce(Duration)` and the scheduler with
`with_scheduler(scheduler)`; the defaults are 1 second and `SystemScheduler`.
A zero debounce sends the message before `set_search_term` returns, as the C#,
Python and TypeScript helpers skip the debounce for zero. A `search()` call
sends its message at once and does not cancel a pending term delivery
(ADR-0219).

### 8.1 Source-change timing and batching (spec v3.19)

The source-change signal is independent of the search-term debounce. A signal
uses the current term immediately and MUST NOT cancel, restart, or otherwise
consume a pending debounced term delivery. That pending delivery still occurs
after its original quiet window. Each source signal produces one recompute even
when the resulting sequence is value-equal to the preceding snapshot.

`SearchableState` adds no source-change debounce or batch scope. It is
transparent to the supplied signal: N signals produce N recomputes. A source
collection, hub, or `AggregateChangeStream` that coalesces a mutation batch into
one signal therefore produces one recompute. Consumers needing both membership
and current-member changes SHOULD map the `AggregateChangeStream` from chapter
21 §9 to this signal; `SearchableState` MUST NOT create a second member registry.

The item supplier remains authoritative and MAY return a different collection
instance. The next source signal or explicit `search()` reads that replacement.
The signal subscription itself is fixed for the helper's lifetime.

### 8.2 Setup, termination, and ownership (spec v3.19)

When `SourceChanged` is present, construction MUST install its subscription and
then reconcile from `Items` again before returning. This closes the ordinary
initial-snapshot/attach gap without exposing constructor-only intermediate
snapshots. The supplier and source retain their own threading requirements;
`SearchableState` does not make concurrent mutation of an unsafe source safe.

Source completion stops automatic source-triggered recomputation only. A source
error, in flavors whose signal type can fail, has the same isolated effect: it
is not forwarded to `Filtered`. Term changes and explicit `search()` remain
operational until helper disposal. Swift encodes the signal with
`Failure == Never`; Rust's message-hub signal likewise has no error channel.

**Failing predicate or subscriber (spec v3.30, ADR-0191).** A predicate or
item supplier that fails during a recompute stops that recompute. `Filtered`
keeps its last snapshot and emits nothing. The failure is stream-fed under
chapter 03 §3.6, even for a zero debounce or a `search()` call, so it never
reaches the caller. The recompute subscription stays attached, and the next
term change, source signal or `search()` recomputes as usual. A failing
`Filtered` subscriber also follows chapter 03 §3.6. A failure in the
constructor's first filter still reaches the constructor's caller. Swift
predicates cannot fail. Rust evaluates the predicate when the caller pulls
`filtered()` or calls `search()`, so a panic reaches that caller, and a later
pull with a valid term returns the filtered items.

The helper owns only the subscription it creates. It MUST NOT dispose the source
signal, item collection, supplied items, predicate, or an upstream aggregate.
Disposal cancels the owned subscription exactly once, completes the
helper-owned filtered output according to the existing flavor contract, and
makes later source signals inert. Omitting `SourceChanged` preserves the
supplier-only compatibility path: source mutation alone emits nothing and an
explicit `search()` refreshes the view.

Consumers wire `SearchableState` to a composite by passing
`composite as Iterable<TItem>` as `Items`. The helper is opt-in; the base
`CompositeVM<VM>` retains its current shape unchanged.

## 9. Filtered composite views (spec v3.1)

`FilteredCompositeVM<VM>` provides a cursor-owning visible projection over a
source `CompositeVM<VM>`.

```
FilteredCompositeVM<VM>:
    source       : CompositeVM<VM>
    predicate    : (VM) -> bool
    Visible      : IReadOnlyList<VM>
    VisibleCount : int
    Current      : VM?
    Changed      : Observable/Event

    SetPredicate(predicate)
    SetCurrent(vm?)
    MoveToNextVisible()
    MoveToPreviousVisible()
    Dispose()
```

`SetCurrent` raises for a non-null item that is not visible and changes
nothing. Swift `setCurrent(_:)` and the `current` setter cannot throw without
a source break, so they trap; `setCurrentResult(_:)` returns the refusal as a
failure (ADR-0217).

The source composite remains the owner of child membership and lifecycle. The
filtered view owns the visible projection and its own current slot in the visible
domain. When the source mutates or the predicate changes, the projection is
recomputed and current is reconciled according to a cursor policy:

- `SnapToFirst`: if current is filtered out, select the first visible item.
- `Clear`: if current is filtered out, clear current.
- `PreserveIfVisible`: keep current only if it remains visible, otherwise clear.

The policy is a construction argument, `SnapToFirst` by default. It also sets
the start state: a `SnapToFirst` view starts on the first visible item, and a
`Clear` or `PreserveIfVisible` view starts with no current item.

`Changed` fires once after each projection recompute (a source mutation, a
predicate change, or a refresh), and once when `SetCurrent` or a visible move
changes `Current`. A handler reads the new `Visible` and `Current`. `Dispose()`
completes the stream where the flavor's stream completes, and later calls fire
nothing (ADR-0207).

`ScoredFilteredCompositeVM<VM>` filters out null/absent scores and orders visible
items by descending score with source-order stable tie breaks. `RefreshScores()`
forces a recompute when external score state changes.

A view whose first recompute throws, from its predicate or its scorer, detaches
from its source before the failure propagates (ADR-0224). A later source change
runs neither the predicate nor the scorer of the unreachable view. A C#
`ScoredFilteredCompositeVM` with a null scorer detaches the same way. Swift and
Rust predicates and scorers return plain values and cannot fail.

## 10. Conformance

`COMP-001` through `COMP-013`, `COMP-014` through `COMP-018`, (the
modeled-CRUD additions documented later) `COMP-019` through `COMP-024`, and
the builder hooks `COMP-025` and `COMP-026` (see below), plus filtered/scored
view IDs `COMP-028` through `COMP-037`, plus source-reactivity IDs `SRCH-001`
through `SRCH-008` and the failure ID `SRCH-009`, in
`12-conformance.md` cover:

- collection-change events on add/remove
- `Current` setter behavior (legal/illegal values)
- async selection dispatch (`AsyncSelection(true)` via `IDispatcher.Foreground`)
- `select_component` / `deselect_component` / `can_select_component` predicates
- construction wait-for-all-children
- destruction unsets `Current` before destructing children
- modeled variant maps model factory output to children
- `can_select_component` returns false for non-children
- `Current` setter raises on non-child assignment
- `IsCurrent` change on the previously-Current child dispatches on the foreground scheduler
- `deselect_component` raises when the argument is not `Current`
- (v1.1) `AutoConstructOnAdd(true)` auto-constructs children added after the composite is `Constructed`
- (v1.1) `BatchUpdate()` suppresses per-mutation events and emits a single `Reset` at completion
- filtered visible projections and visible-domain current
- scored filtering with stable score ordering
- optional source-change refresh, independent debounce timing, termination,
  batching transparency, and subscription-only ownership
- no term debounce and no filtered emission from construction (`SRCH-008`,
  ADR-0198)

Hub publication of collection changes (chapter 01 §1.4, ADR-0142) is covered by:

- `COMP-042` — each effective local event is followed by one hub
  `CollectionChangedMessage` sent by the composite, with the same action and
  positions.
- `COMP-043` — a batch publishes nothing inside its scope and one `Reset` on
  outermost completion; an empty batch publishes nothing.
- `COMP-044` — a transfer publishes the old `Remove` before the new `Add`;
  failed preflight, rollback, and same-index moves publish nothing.
- `COMP-045` — hub transactions defer the messages in order, a disposed
  composite publishes nothing, and a forwarding wrapper adds no publication.
- `COMP-049` — a composite or group whose disposal a local subscriber or an
  `OnCurrentChanged` callback requests sends no hub message for that change,
  whether the disposal runs at once or is deferred (ADR-0190).

The `Disposed`-child, `Destructing` and child-`select()` rules of §3, §3.1,
§4.3 and §5 are covered by:

- `COMP-050` — disposing the current child clears `Current` once. The
  child's `IsCurrent` becomes false with no child message, and the child is
  not selectable. The composite's own dispose cascade does not clear.
- `COMP-051` — a non-null selection while the composite is `Destructing`
  changes nothing and raises nothing; a null clear commits.
- `COMP-052` — a refused child `select()` or `deselect()` changes nothing and
  raises nothing.

The `DestructOrder` option introduced in §5 is covered by:

- `COMP-046` — `Reverse` destructs and disposes the children last child first,
  and construct is the same with and without the option.

The construct-walk membership rules of §5.1 are covered by:

- `COMP-047` — a child removed before the walk reaches it, or while the walk
  waits on it, does not roll the composite back, whether it is a snapshot or a
  late child, and the walk does not construct a snapshot child removed before
  it.

The cross-thread membership rule of §4.2 is covered by:

- `COMP-048` — while another thread holds the composite's membership
  transaction, an add, a population and a removal fail at once and change
  nothing.

The builder hooks introduced in §3.2 are covered by:

- `COMP-025` — `Current(selector)` builder hook drives selection during every construct.
- `COMP-026` — `OnCurrentChanged(callback)` fires synchronously after each `Current` change.
- `COMP-053` — the selector receives the live membership, so it can pick a
  late child.

The `Parent` back-reference wiring (declared in `01-concepts.md` §1.3 and
`05-component-vm.md` §6.1) is covered by:

- `COMP-027` — `Add` sets a child's `Parent` (the child becomes selectable and
  `select()` delegates through it); `Remove` clears it (the child is no longer
  selectable and `select()` becomes a no-op).
- `COMP-038` — adding to a new mutable parent removes the same identity from its
  previous parent without changing child lifecycle state.
- `COMP-039` — duplicate and self/ancestor-cycle attempts fail before mutation.
- `COMP-040` — failed attachment or auto-construction isolates and restores both
  containers, the parent link, index, and selection state; failed lifecycle
  compensation is surfaced rather than hidden, and the reported failure gives
  access to the original failure and to the first compensation failure.
- `COMP-054` — a failed add, insert or replacement that started a background
  child returns it to `Destructed` with no parent once its construct settles.
- `COMP-041` — successful transfer publishes old removal before new addition;
  failed transfer publishes neither.

Cross-cutting `DISP-001` covers repeated parent cascades, and `DISP-006`
covers idempotent batch/projection disposal without changing this chapter's
ownership rules.
