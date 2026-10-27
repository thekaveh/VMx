# 6.5. State & Reactive Helpers

## 6.5.1. When To Use It

Use these helpers when the VM shape is already correct, but you need reusable
reactive behavior layered onto it: search, expand/collapse state, derived
values, active-key coordination, edit/revert state, or one asynchronously
acquired presentation value.

## 6.5.2. Shape And Ownership

The main helpers in this area are:

- `SearchableState<TItem>` for debounced filtering/search
- `ExpandableState` for expand/collapse capability composition
- `DerivedProperty<TValue>` for N-source computed values
- `DiscriminatorVM<TKey>` for one active key with modal precedence
- `FormVM<TM>` for snapshot/revert/approve flows
- `AsyncResourceVM<T>` for cancellable Idle/Loading/Ready/Error acquisition

Most of these primitives are composed inside a larger VM. `AsyncResourceVM`
is itself a component VM and may be the outer binding boundary for one remote
or otherwise expensive value.

The table and examples below describe the canonical cross-flavor concepts.
Rust's `DerivedProperty` recomputes from one through five owned `ValueStream`
sources (`from_one` … `from_five`). It also accepts N same-typed sources
through `from_sources` and `from_sources_with_write_back`, which panic on an
empty list.

Rust's `ExpandableState` supports explicit initial state, the full capability
triple, and owned disposal. The
[Rust parity ledger](../../maintenance/2026-07-16-rust-capability-parity.md#1236-expandablestate-construction-and-disposal)
records the helper evidence.

## 6.5.3. Async Resource State

`AsyncResourceVM<T>` standardizes the state and commands around one async
loader without choosing a transport, cache, route, scheduler policy, or paging
model. Its immutable `state` / `State` snapshot has four statuses:

| Status    | Value                                       | Error   |
| --------- | ------------------------------------------- | ------- |
| `Idle`    | absent                                      | absent  |
| `Loading` | absent, or the retained last accepted value | absent  |
| `Ready`   | current accepted value                      | absent  |
| `Error`   | absent, or the retained last accepted value | present |

The `LoadCommand` is eligible only from Idle. `ReloadCommand` is eligible from
Loading, Ready, or Error, and `CancelCommand` only while Loading. Direct reload
may supersede active work: the latest admitted start wins, so a loader that
ignores cancellation cannot overwrite newer state. Loader faults become Error
state and do not also escape through the async command error channel.

Retention defaults to `DiscardPrevious`, which releases an accepted value
before the replacement load. `RetainPrevious` keeps that value visible while
loading and restores it on cancellation. An optional cleanup callback makes
ownership acquisition-based: discarded, replaced, stale, late-after-dispose,
and terminal accepted values are each cleaned exactly once.

Each successful loader return is a separate ownership unit, even when two
returns are reference-identical. Accepted ownership transfers into stable
resource state; a stale or late successful return retains only its own cleanup
obligation and cannot publish. See the [disposal contract](disposal-contract.md)
for the complete release rules.

In Rust, each load runs its loader on a worker thread while the `load_async`
thread or the command worker waits for it. The waiting thread blocks until the
loader reports or the load is cancelled, superseded, or disposed; it does not
poll. A loader that ignores its token keeps running on its own worker, but the
awaited load completes as soon as cancellation arrives, and the loader's late
value is cleaned once (ADR-0140).

In Python, every operation records the asyncio loop that created its task and
cancellation future. Cancellation and disposal invalidate resource state
synchronously, then perform native signals and late-result registration on that
operation loop. This is an asyncio ownership rule, not a UI-dispatch or general
VM thread-safety promise. See
[Python asyncio dispatcher ownership](services-messages-dispatching.md#669-python-asyncio-dispatcher-ownership)
for the supported synchronous-command sequence and shutdown order.

A loader can also end the current operation by cancelling itself. The flavors
handle this case differently:

- Python: a loader task that finishes with `asyncio.CancelledError` restores
  the saved stable state, exactly like `Cancel`. The error can be raised
  directly, come from cancelling the loader's own task, or come from a
  cancelled operation that the loader awaited.
- Swift: a loader that throws `CancellationError` restores the saved stable
  state in the same way.
- C# and TypeScript: cancellation that the VM did not request is an ordinary
  loader fault. Examples are an `OperationCanceledException` from another
  token, or a rejection while the operation's signal is not aborted.
- Rust: loaders report outcomes through `VmxResult`, so an error is a fault.

When Python or Swift restores the stable state, awaiters and commands
complete, and nothing enters Error or a command error channel. The
cancellation of a superseded loader never rolls back newer work. In every
flavor, the VM leaves Loading with a visible terminal state.

<!-- checked-snippet: langs/python/tests/unit/state/test_async_resource_cancellation_recipe.py#loader-cancellation -->

```python
async def load_profile() -> str:
    # Another owner may cancel the shared request. The CancelledError that
    # reaches this loader settles the VM like Cancel; it never stays Loading.
    return await profiles.shared_request()

profile = AsyncResourceVM(
    name="profile",
    loader=load_profile,
    hub=hub,
    dispatcher=dispatcher,
    retention=AsyncResourceRetention.RETAIN_PREVIOUS,
)
await profile.load()  # Ready("ada")
await profile.reload()  # the shared request is cancelled mid-flight

assert profile.state.status is AsyncResourceStatus.READY
assert profile.state.value == "ada"  # the retained value is restored
assert profile.reload_command.can_execute()  # the next reload is admitted
```

This recipe runs as
`langs/python/tests/unit/state/test_async_resource_cancellation_recipe.py`.

```typescript
const profile = new AsyncResourceVM({
  name: "profile",
  hub,
  dispatcher,
  loader: signal => api.loadProfile(userId, signal),
  retention: AsyncResourceRetention.RetainPrevious,
  cleanupValue: value => value.dispose(),
});

await profile.load();
if (profile.state.status === AsyncResourceStatus.Ready) {
  render(profile.state.value);
}
profile.dispose();
```

Use `PagedComposition` or `TokenPagedComposition` when the domain is a page or
cursor sequence; a failed token-page fetch is reported differently (see
[Token-Paged Fetch Failures](builders-collections-tree-utilities.md#6711-token-paged-fetch-failures)).
Keep product-specific client construction and caching outside this primitive
and inject them through the loader closure.

For a pushed connection state that reconnects over time, use the connection
state recipe in [Integration](../integration/index.md) instead.

### 6.5.3.1. Retry, Polling And Cancellation

A resource never starts loading at construct, and only disposal cancels its
load automatically (ADR-0100 §2.7, §4.6). The view-model below loads when it is
constructed, polls while it stays constructed, offers retry after a failure,
and cancels its load at destruct:

<!-- checked-snippet: langs/typescript/tests/unit/asyncResourceRecipes.test.ts#polling-panel -->

```typescript
class MetricsPanelVM extends ComponentVMBase {
  readonly resource: AsyncResourceVM<Metric[]>;
  readonly retryCommand: DecoratorCommand;
  #poll: Subscription | null = null;

  constructor(api: MetricsApi, hub: IMessageHub, dispatcher: IDispatcher) {
    super({ name: "metrics-panel", hub, dispatcher });
    this.resource = this.own(
      new AsyncResourceVM({
        name: "metrics",
        hub,
        dispatcher,
        loader: (signal) => api.fetch(signal),
        // A reload keeps the last value visible instead of blanking the view.
        retention: AsyncResourceRetention.RetainPrevious,
      }),
    );
    // Retry is a reload, offered only after a failure.
    this.retryCommand = this.own(
      wrapWith(
        this.resource.reloadCommand,
        () => this.resource.state.status === AsyncResourceStatus.Error,
      ),
    );
  }

  get type(): ViewModelType {
    return ViewModelType.Component;
  }

  // Poll while constructed: load at once, then reload every 30 s.
  protected override _onConstruct(): void {
    super._onConstruct();
    this.#poll = timer(0, 30_000, this._dispatcher.foreground).subscribe(() => {
      const { status } = this.resource.state;
      if (status === AsyncResourceStatus.Idle) void this.resource.load();
      // Skip a tick while a load runs; a reload would supersede it.
      else if (status !== AsyncResourceStatus.Loading) void this.resource.reload();
    });
  }

  protected override _onDestruct(): void {
    this.#poll?.unsubscribe();
    this.#poll = null;
    this.resource.cancel();
    super._onDestruct();
  }
}
```

- **Retry from Error.** `ReloadCommand` is the retry path (spec 23 §7). The
  wrapper hides retry while the data is current.
- **No rejection handling.** A reload also supersedes a load that
  `LoadCommand` started. A superseded or failed reload completes normally
  (spec 23 §6, §7), so `void this.resource.reload()` needs no rejection
  handler.
- **Tick rule.** A tick loads from Idle, reloads from Ready or Error, and skips
  Loading. Without the skip, an interval shorter than the load supersedes
  every load, and the view never reaches Ready. A polled view needs
  `RetainPrevious`; the default blanks the view at every reload.
- **Cancelling at destruct.** `cancel()` cancels the current operation,
  whichever call started it. To cancel only the loads that one construct
  started, pass the signal of a per-construct `AbortController` to
  `load(signal)` and abort it at destruct.

### 6.5.3.2. Poll Timers By Flavor

Start and stop the timer in the same construct and destruct hooks. The timer
needs a scheduler that supports a delay:

- C#: `Observable.Timer(TimeSpan.Zero, period, dispatcher.Foreground)` with a
  real UI scheduler. `NullDispatcher` and `RxDispatcher.Immediate()` use
  `ImmediateScheduler`, on which a periodic `Observable.Timer` does not return
  from `Subscribe`, so the construct hook hangs.
- Python: `RxDispatcher.asyncio(loop).foreground`, or an asyncio task on the
  loop that runs the resource's operations (see
  [Async Resource Operation Loops](services-messages-dispatching.md#6691-async-resource-operation-loops)).
  The `ImmediateScheduler` of `NullDispatcher` and `RxDispatcher.immediate()`
  raises `WouldBlockException` for a delayed action.
- Swift: dispatchers take work without a delay. Use a `Timer` or a `Task` that
  loops on `Task.sleep`.
- Rust: dispatchers take work without a delay. Drive the tick from the host
  event loop.

## 6.5.4. Reactive Search Sources

`SearchableState<TItem>` always keeps its existing lazy item supplier. Add the
optional source-change signal when the supplier can mutate while the search
term stays unchanged. Every signal immediately re-reads the supplier with the
current term; it does not wait for, cancel, or restart term debounce.

| Flavor     | Optional source input                          |
| ---------- | ---------------------------------------------- |
| C#         | `IObservable<Unit> sourceChanged`              |
| Python     | `Observable[object] source_changes`            |
| TypeScript | `Observable<unknown> sourceChanges`            |
| Swift      | `AnyPublisher<Void, Never> sourceChanges`      |
| Rust       | `new_with_changes` / `from_items_with_changes` |

The signal is transparent to batching: two pulses cause two refreshes, while
one upstream-coalesced pulse after many mutations causes one. A value-equal
result still emits because the pulse may represent meaningful external state.
Signal completion—and signal failure in the error-capable Rx flavors—stops only
automatic refresh; explicit search remains available.

For membership plus current-member changes, compose the aggregate stream rather
than installing item subscriptions inside search:

```typescript
import { map } from "rxjs";
import { AggregateChangeStream, SearchableState } from "@thekaveh/vmx";

const aggregate = AggregateChangeStream.forComponents(components);
const search = new SearchableState({
  items: () => components.snapshot(),
  predicate: (item, term) => item.title.includes(term),
  sourceChanges: aggregate.observe().pipe(map(() => undefined)),
});

// Search owns its pulse subscription; the consumer still owns the aggregate.
search.dispose();
aggregate.dispose();
```

Membership-only consumers can map their collection's structural event directly.
When no signal is supplied, call `search()` to refresh after a mutation.

## 6.5.5. Lifecycle And Messaging

The lifecycle rule is simple: if a helper owns subscriptions, dispose it with
its owner. That matters especially for `DerivedProperty`, `SearchableState`,
`DiscriminatorVM`, and `AsyncResourceVM`.

`DerivedProperty` is also the standard replacement for older ad hoc
initialization-token patterns: subscribe once, multicast value changes, and tear
down cleanly on disposal.

In C#, Python, Swift, and TypeScript, a `DerivedProperty` stores its first value
without a value-changed emission (DPROP-009). A binding that subscribes before
that value arrives must therefore also observe initialization, or it shows the
unseeded state until a later, different value. The TypeScript React adapter's
`useDerivedProperty` does this through an internal core seam. Rust constructs
derived properties with their initial value, so it has no unseeded state.

The [Disposal Contract](disposal-contract.md) inventories which helpers expose
disposal, which last values remain readable, and which streams complete.

### 6.5.5.1. Publishing A Derived Value

A `DerivedProperty` is self-contained and sends nothing on the hub (ADR-0011).
To publish a derived value as a view-model property, own the derived property
and forward its `valueChanged` to `_notifyPropertyChanged(name)`:

<!-- checked-snippet: langs/typescript/tests/unit/propertyMessageRecipes.test.ts#derived-total -->

```typescript
class CartVM extends ComponentVMBase {
  readonly #quantity$ = new BehaviorSubject(1);
  readonly #total: DerivedProperty<number>;

  constructor(prices: Observable<number>, hub: IMessageHub, dispatcher: IDispatcher) {
    super({ name: "cart", hub, dispatcher });
    // Seed every source, so `total` has a value at once (DPROP-001).
    this.#total = this.own(
      fromTwo(prices.pipe(startWith(0)), this.#quantity$, (price, quantity) => price * quantity),
    );
    // A DerivedProperty sends nothing on the hub. Forward each change.
    this.own(this.#total.valueChanged.subscribe(() => this._notifyPropertyChanged("total")));
  }

  get type(): ViewModelType {
    return ViewModelType.Component;
  }

  get total(): number {
    return this.#total.value;
  }

  get quantity(): number {
    return this.#quantity$.value;
  }

  // No compare-and-assign helper: compare, assign, then notify.
  set quantity(value: number) {
    if (this.#quantity$.value === value) return;
    this.#quantity$.next(value);
    this._notifyPropertyChanged("quantity");
  }
}
```

- **Seed every source.** `fromTwo` waits until each source emits once, and
  `.value` throws until then. A `BehaviorSubject` or `startWith` gives `total`
  a value at construction (DPROP-001).
- **The first value is silent** (DPROP-009, see above). Construction therefore
  publishes no `total` message. A binding reads the getter when it attaches.
- **Ownership.** `own()` disposes the derived property and the forwarding
  subscription with the view-model.

### 6.5.5.2. Comparing Before Notifying

VMx has no compare-and-assign helper, by design (spec 05 §2.3, ADR-0083 §4.4).
`_notifyPropertyChanged` does not compare or assign values. The setter keeps
the idiom: compare, assign, then notify. The `quantity` setter above shows it:
an assignment of the same value returns early and publishes nothing. See
[Authoring A Mutable Property](viewmodel-families/component-family.md#6229-authoring-a-mutable-property)
for the helper name in each flavor.

### 6.5.5.3. Expansion Commands

`ExpandableState` exposes `ExpandCommand`, `CollapseCommand`, and
`ToggleExpansionCommand` (Python `expand_command`, TypeScript and Swift
`expandCommand`, Rust `expand_command()`; ADR-0159). Each command's predicate
is the matching `can*` check, and its `CanExecuteChanged` fires on every
expansion change. The helper builds each command on its first read and owns
it: disposing the helper disposes the commands, which are then inert.

The helper publishes nothing to a message hub. The owning VM publishes
`isExpanded` with a one-line forwarder, and re-exports the commands it binds:

<!-- checked-snippet: langs/typescript/tests/unit/expandableStateRecipes.test.ts#expansion-forwarder -->

```typescript
class TreeNodeVM extends ComponentVMBase {
  readonly #expansion = this.own(new ExpandableState());
  // The helper owns its commands; the owner only re-exports them.
  readonly toggleCommand = this.#expansion.toggleExpansionCommand;

  constructor(name: string, hub: IMessageHub, dispatcher: IDispatcher) {
    super({ name, hub, dispatcher });
    // The one-line forwarder: the owner publishes isExpanded (spec 14 rule 6).
    this.own(
      this.#expansion.isExpandedChanged.subscribe(() => this._notifyPropertyChanged("isExpanded")),
    );
  }

  get type(): ViewModelType {
    return ViewModelType.Component;
  }

  get isExpanded(): boolean {
    return this.#expansion.isExpanded;
  }
}
```

In Rust, the helper reports changes through its `expanded_changed()` hub
instead of an observable, so the owner subscribes to that hub.

## 6.5.6. Cross-Language Surface

| Helper                    | Key surface                                       |
| ------------------------- | ------------------------------------------------- |
| `SearchableState<TItem>`  | search term, filtered view, force-search          |
| `ExpandableState`         | expanded flag, expand/collapse/toggle + commands  |
| `DerivedProperty<TValue>` | value, value-changed, optional write-back         |
| `DiscriminatorVM<TKey>`   | active key, modal depth, clear/open/close helpers |
| `FormVM<TM>`              | model, snapshot, dirty/valid state, approve/deny  |
| `AsyncResourceVM<T>`      | state snapshot, load/reload/cancel commands       |

## 6.5.7. Example

The Notes Workspace examples combine several helpers inside one editor and one
status surface:

- `NoteFormVM` composes `FormVM`, `DiscriminatorVM`, and `SearchableState`
- status and action bars compose `DerivedProperty`
- tree-like consumers can compose `ExpandableState` with hierarchical nodes

That composition style is the norm in VMx.

## 6.5.8. Common Pitfalls

- Re-implementing reactive glue with hand-managed subscriptions instead of
  composing a helper.
- Forgetting to dispose helper-owned subscriptions.
- Mutating a search supplier without either providing a source-change signal or
  calling `search()` explicitly.
- Creating a second per-item registry instead of mapping
  `AggregateChangeStream` when member-property changes matter.
- Using `DerivedProperty` as an imperative setter shortcut instead of letting it
  stay source-driven.
- Treating `AsyncResourceVM` as a cache, transport client, or paging owner.
- Forgetting cleanup when the loaded value owns a handle or subscription.

## 6.5.9. Related Primitives

- [Capability Families](capability-families.md)
- [FormVM](viewmodel-families/specialized/form-vm.md)
- [DiscriminatorVM](viewmodel-families/specialized/discriminator-vm.md)
