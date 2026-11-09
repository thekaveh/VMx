# 06 — CompositeVM

`CompositeVM<VM>` is a container with selection: it holds an ordered list of child
viewmodels and exposes a `Current` slot that designates at most one child as the
selected one.

## 1. Variants

| Variant                         | Children source                                      | `Current` |
| ------------------------------- | ---------------------------------------------------- | --------- |
| `CompositeVM<VM>` (non-modeled) | builder factory `() -> Iterable<VM>`                 | yes       |
| `CompositeVM<M, VM>` (modeled)  | model factory `() -> Iterable<M>` + mapper `M -> VM` | yes       |

The non-modeled builder factory is evaluated on `construct()`, as for `GroupVM`
(chapter 07 §3). Open Rust gap: Rust's `CompositeVmBuilder::build()` evaluates
the factory and attaches the initial population at build time.

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
  post-dispose behavior (chapter 01 §4).
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

- `Current(selector)` — `selector: Iterable<VM> -> VM | None`. Invoked during every construct phase of the composite, including the construct phase of `reconstruct()`, **after** all children have transitioned to `Constructed` and **before** the composite reaches `Constructed`. Destruct first sets `Current` to `null` (§5), which reports `null` to `OnCurrentChanged`, so each construct selects again. To restore the previous selection, record only the non-null values that `OnCurrentChanged` receives and return the last one from the selector; if that child is no longer contained, the assignment is the no-op described below (ADR-0158). The composite assigns `Current` to the selector's return value through an internal **non-raising validated assignment** — NOT the guarded `select_component` path, which raises on a non-child (§3.1, `COMP-009`). If the selector returns a contained child, the normal `Current` transition fires (`PropertyChangedMessage("Current")` plus the `IsCurrent` updates of §3). If the selector returns `null` or a value not contained in the composite, the assignment is a **silent no-op**: `Current` stays at its prior value (initially `null`) and no notification fires. (ADR-0042 §5.1 phrased this as "the `SelectComponent` path"; ADR-0050 corrects the wording to the non-raising assignment that the reference implementations and `COMP-025` actually exercise, reconciling it with §5.4's no-op rule.)
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
ADR-0142, `COMP-042`).

Open Rust gap: Rust `CompositeVm` and `GroupVm` have no public local
collection-change stream; consumers observe membership through the hub
`CollectionChanged` messages. The local-recorder clauses of `COMP-041` and
`COMP-042` apply to Rust through the hub messages only.

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
   receives the old `Remove` before the new `Add` (`COMP-044`).

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

If any step after preflight fails, both memberships, `Parent`, `Current`, child
current flags, lazy/builder population state, and the event stream MUST equal
their pre-call values. Bulk population rolls earlier transfers back in reverse
order if a later child fails. Lifecycle compensation is attempted. If a
consumer lifecycle hook makes compensation fail, that failure MUST be surfaced
and MUST NOT be swallowed; exact lifecycle restoration is then not claimed.
In particular, when this attempt auto-constructed a previously destructed child
before admission failed, compensation destructs it back to its original state.
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
committed membership notifications still publish in old-remove/new-add order
before a throwing or result-based flavor propagates that disposal failure. If
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
   disposal.
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
   selection is admitted in between.
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
walk joins it and never restarts it, and if it fails while the walk waits on
it, the composite rolls back.

## 6. Modeled variant `CompositeVM<M, VM>`

Identical to `CompositeVM<VM>` except the children come from a model factory:

- Builder accepts:
  - `ChildrenModels : () -> Iterable<M>`
  - `ChildModelToChildViewModel : (M) -> VM`
- On `construct()`, the composite first evaluates `ChildrenModels()`, then maps
  each `M` to a `VM`, then orchestrates children construction as above.

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
  C# (VMX-011). C# (`currentChanged`), Swift (`currentChanged`), and Rust
  (`ModeledCrudCommands::with_current_changed`) accept the trigger. The Python and
  TypeScript helpers accept no trigger input, so their Update and Delete commands
  stay correct on demand but non-reactive. To get reactive commands in these two
  flavors, build the commands directly with the base `Triggers` mechanism
  (chapter 04 §4.2).

Open Rust gap: Rust has no `confirm_update` delegate. Its
`ModeledCrudCommands::with_confirm_delete` takes a synchronous `Fn() -> bool`
inside a plain `RelayCommand`, not an async delegate wrapped in a
`ConfirmationDecoratorCommand`. The `with_confirm_delete` constructor also
takes no `current_changed` trigger, so that Delete command is not reactive; the
`with_current_changed` constructor accepts the trigger but has no confirmation.

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

Open Rust gap: Rust's `SearchableState` has no debounce. `set_search_term` and each explicit `search()` send one synchronous
`Custom("filtered")` notification on the `filtered_changed()` hub, and consumers
pull the result with `filtered()`. ADR-0099 §2.7 records this facade mapping.

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

Open Rust gap: Rust's `FilteredCompositeVm` has no `Changed` stream, so a view
reads `visible()` and `current()` on demand.

The source composite remains the owner of child membership and lifecycle. The
filtered view owns the visible projection and its own current slot in the visible
domain. When the source mutates or the predicate changes, the projection is
recomputed and current is reconciled according to a cursor policy:

- `SnapToFirst`: if current is filtered out, select the first visible item.
- `Clear`: if current is filtered out, clear current.
- `PreserveIfVisible`: keep current only if it remains visible, otherwise clear.

`ScoredFilteredCompositeVM<VM>` filters out null/absent scores and orders visible
items by descending score with source-order stable tie breaks. `RefreshScores()`
forces a recompute when external score state changes.

## 10. Conformance

`COMP-001` through `COMP-013`, `COMP-014` through `COMP-018`, (the
modeled-CRUD additions documented later) `COMP-019` through `COMP-024`, and
the builder hooks `COMP-025` and `COMP-026` (see below), plus filtered/scored
view IDs `COMP-028` through `COMP-037`, plus source-reactivity IDs `SRCH-001`
through `SRCH-007`, in
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

The builder hooks introduced in §3.2 are covered by:

- `COMP-025` — `Current(selector)` builder hook drives selection during every construct.
- `COMP-026` — `OnCurrentChanged(callback)` fires synchronously after each `Current` change.

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
  compensation is surfaced rather than hidden.
- `COMP-041` — successful transfer publishes old removal before new addition;
  failed transfer publishes neither.

Cross-cutting `DISP-001` covers repeated parent cascades, and `DISP-006`
covers idempotent batch/projection disposal without changing this chapter's
ownership rules.
