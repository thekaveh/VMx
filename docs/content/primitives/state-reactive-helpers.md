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
Rust's `DerivedProperty` automatically recomputes from one through five owned
`ValueStream` sources, and `ExpandableState` supports explicit initial state,
the full capability triple, and owned disposal. The completed
[Rust parity ledger](../../maintenance/2026-07-16-rust-capability-parity.md#1236-expandablestate-construction-and-disposal)
records the focused helper evidence.

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

In Python, every operation records the asyncio loop that created its task and
cancellation future. Cancellation and disposal invalidate resource state
synchronously, then perform native signals and late-result registration on that
operation loop. This is an asyncio ownership rule, not a UI-dispatch or general
VM thread-safety promise. See
[Python asyncio dispatcher ownership](services-messages-dispatching.md#669-python-asyncio-dispatcher-ownership)
for the supported synchronous-command sequence and shutdown order.

A loader can also end the current operation by cancelling itself. In Python, a
loader task that finishes with `asyncio.CancelledError` (raised directly, from
cancelling its own task, or from a cancelled operation it awaited) restores the
saved stable state exactly like `Cancel`, as Swift does for a loader's
`CancellationError`: awaiters and commands complete, nothing enters Error or a
command error channel, and a superseded loader's cancellation never rolls back
newer work. C# and TypeScript treat cancellation they did not request (an
`OperationCanceledException` from another token, a rejection while the
operation's signal is not aborted) as an ordinary loader fault, and Rust loaders
report outcomes through `VmxResult`, so every flavor leaves Loading with a
visible terminal state.

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
cursor sequence. Keep product-specific client construction and caching outside
this primitive and inject them through the loader closure.

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
When no signal is supplied, mutation remains intentionally explicit: call
`search()` to refresh, preserving compatibility with earlier releases.

## 6.5.5. Lifecycle And Messaging

The lifecycle rule is simple: if a helper owns subscriptions, dispose it with
its owner. That matters especially for `DerivedProperty`, `SearchableState`, and
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

## 6.5.6. Cross-Language Surface

| Helper                    | Key surface                                       |
| ------------------------- | ------------------------------------------------- |
| `SearchableState<TItem>`  | search term, filtered view, force-search          |
| `ExpandableState`         | expanded flag, expand/collapse/toggle             |
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
