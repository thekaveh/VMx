# VMx Rust

Rust flavor of VMx, the language-neutral, lifecycle-aware MVVM viewmodel framework.

## 1. Status

**v0.36.0** implements spec 3.30.0. Behavioral Rust tests cover every
library conformance ID. Rust has no UI scenario suite for the THEME IDs.

The public surface and some behaviors are not fully aligned with the other
flavors. See the
[Rust parity ledger](https://github.com/thekaveh/VMx/blob/main/docs/maintenance/2026-07-16-rust-capability-parity.md)
(original scope closed; recorded difference in §12.7 and open item in §12.13).

## 2. Install

- Package: `vmx-rs`; code imports the crate as `vmx` (`use vmx::…`).
- Minimum supported Rust version: 1.88.
- Cargo features: `notifications`, on by default, builds the notification
  sub-package of spec/16 (`NotificationHub`, `NullNotificationHub`,
  `NotificationHubApi`, `make_confirm`, `NotificationVm`, `ConfirmationVm`).
  Set `default-features = false` to build the core without it (ADR-0211).
- Add the crate from crates.io. A git or path dependency also works.

```toml
[dependencies]
vmx-rs = "0.36.0"

# Or, from the repository:
# vmx-rs = { git = "https://github.com/thekaveh/VMx.git" }

# Or, with VMx cloned beside your project:
# vmx-rs = { path = "../VMx/langs/rust" }
```

## 3. Minimal Example

```rust
use vmx::{ComponentVm, MessageHub, NullDispatcher, VmxResult};

fn main() -> VmxResult<()> {
    let hub = MessageHub::new();
    let dispatcher = NullDispatcher::new();
    let note = ComponentVm::with_services("hello", hub, dispatcher);

    note.construct()?;
    assert!(note.is_constructed());
    note.dispose()?;
    Ok(())
}
```

### 3.1. Background Lifecycle

`NullDispatcher` and `ImmediateDispatcher` run both channels inline. Use
`DefaultDispatcher` for the built-in paired workers, or provide a host
dispatcher whose foreground channel targets the UI event loop:

```rust
use vmx::{ComponentVm, DefaultDispatcher, MessageHub, ValueSubscription, VmxResult};

fn start_in_background(
) -> VmxResult<(ComponentVm<(), DefaultDispatcher>, ValueSubscription)> {
    let vm = ComponentVm::builder()
        .name("loader")
        .background(true)
        .services(MessageHub::new(), DefaultDispatcher::new())
        .build()?;

    let errors = vm.background_errors().subscribe(|error| {
        eprintln!("background lifecycle failed: {error}");
    });
    vm.construct()?; // admits Constructing; completion is fire-and-forget
    Ok((vm, errors)) // host retains both for the active lifetime
}
```

Component and read-only component builders opt in with `.background(true)`
and keep reusable `on_construct` and `on_destruct` callbacks. Background mode
applies only to standalone construct and destruct hooks. The terminal state and
its publication return to the foreground. Hook failures arrive on the
event-only hot `background_errors()` stream. `reconstruct()` and its command
complete their two-phase transition synchronously.

Containers stay Constructing or Destructing until their background children
settle, so a container call can return `Ok` while the container is transient.
A child failure rolls the container back and arrives on its
`background_errors()` stream. Wrapper nodes should forward
`VmNode::when_lifecycle_settled`.

Without background children, reconstruct remains a synchronous
destruct/construct operation. A rejected background or foreground scheduling
restores lifecycle admission (ADR-0130).

## 4. Surface Summary

The crate uses idiomatic Rust naming and error handling:

- Recoverable failures return `VmxResult<T>`.
- Message and dispatcher primitives are UI-framework neutral. Custom
  dispatchers implement `dispatch_background`, and `ManualDispatcher` exposes
  independently drainable queues.
- Viewmodels expose explicit `construct`, `destruct`, and `dispose` methods.
  Component VMs expose `hub()` and accept LIFO disposal cleanup through
  `own(...)`.
- Modeled components expose `republish_model()` for an explicit retained-model
  notification. `hint()` is fixed metadata; `modeled_hint()` is recomputed from
  the model hinter.
- Relay commands expose `raise_can_execute_changed`. Async relay commands have
  an immutable builder, cooperative cancellation, additive triggers, an
  awaitable join handle, and fire-and-forget error routing.
- Confirmation-decorator `execute_async()` returns a thread-free
  `ConfirmationExecution` future. Use `.await`, `.join()`, or `.is_finished()`.
  Blocking `.join()` preserves the original boxed panic payload.
- Every canonical component VM family exposes its `ViewModelType`.
- Capability traits include predicate filtering, finite-page navigation,
  readable expansion state, and mutable search terms. `ExpandableState`
  supports an explicit initial state, owned disposal, and owned expand,
  collapse, and toggle commands. A disposed `SearchableState` reads as an
  empty term.
- `ValueStream<T>` provides typed replay and completion. Message subscriptions
  can observe completion, and notification pending state replays.
- `DerivedProperty` recomputes from one through five owned source
  subscriptions. `AsyncValue<T>` is an executor-neutral `Future` with
  synchronous `wait()`, `map`, and `and_then`.
- `FormVm::builder().reset_on_approved(...)` derives a pristine model after a
  successful persist. `FormVm::set_model(...)` publishes one model message
  after validation and approve-command state settle.
- `HierarchicalVm::attach_many(...)` resolves out-of-order tree windows with
  consumer keys, non-replacing dedupe, and a park/reject orphan policy.
- `HierarchicalVm<M, N>` keeps consumer per-node state in a node-data type
  `N`, which `node_data()` returns (ADR-0202).
- `TreeSelection<M, N = ()>` keeps one current node for the tree under a root
  `HierarchicalVm` and clears it when the node leaves that tree.
- `ObservableList::replace_all(...)` emits one reset with a
  cardinality-correct `Count` notification. `ObservableList::new(owner_id)`
  has no hub and sends typed `item_added`, `item_removed`, `item_replaced` and
  `reset` events; `with_hub(owner_id, hub)` also publishes to a hub.
- `ObservableMultiDictionary` has a local `collection_changed()` event, live
  read-only `keys1()` and `keys2()` views, and a hash index. Containers expose
  their children's local stream as `collection_changed()`.
- `PagedComposition` publishes its paging properties on its hub and can follow
  a `CompositeVm` through `from_composite`.
- `VmCollection<T>` unifies groups and composites. `SelectableVmCollection<T>`
  adds composite-only selection, and `move_item` preserves child identity.
- `AggregateChangeStream<T>` follows dynamic membership with typed provenance.
  `SearchableState::from_items_with_changes(...)` maps a source hub pulse to
  one filtered invalidation.
- `AsyncResourceVm<T, D>` is an ordinary component node with one cancellable
  latest-start-wins acquisition and optional value cleanup.
- UI integrations belong in examples or adapter crates, not in the core crate.

See the
[Rust flavor guide](https://github.com/thekaveh/VMx/blob/main/docs/content/flavors/rust.md)
for runtime behavior, threading, and nested command execution.

## 5. Fixed Aggregates

`AggregateVm1` through `AggregateVm6` use immutable builders and populate typed
slots from factories at construct time. Accessors return `None` before
construction. A failed candidate leaves previous slots intact. See
[Rust fixed aggregates](https://github.com/thekaveh/VMx/blob/main/docs/content/flavors/rust.md#764-fixed-aggregates).

## 6. Serviced Collections

`ServicedObservableCollection<T>` is distinct from `ObservableList<T>`: it owns
an always-present local stream and can also publish to an external hub.
`KeyedServicedObservableCollection<K, T>` adds captured-key lookup
(`get_by_key`), upsert, and deletion; keys need `Eq + Hash + Send`, not
`Clone`. Neither type batches or owns stored-item lifecycle. See
[Rust serviced collections](https://github.com/thekaveh/VMx/blob/main/docs/content/flavors/rust.md#765-serviced-collections).

## 7. Imperative Engine Bridge

`MessageHub::subscribe_value(...)` pushes a selected value for a fixed
`sender_id` into an imperative host as `(current, previous)`. It returns a
host-owned `Subscription`; VMx does not attach it to the observed VM's
lifetime. See
[Rust imperative engine bridge](https://github.com/thekaveh/VMx/blob/main/docs/content/flavors/rust.md#766-imperative-engine-bridge).

## 8. Development

See the Rust section of
[`CONTRIBUTING.md`](https://github.com/thekaveh/VMx/blob/main/CONTRIBUTING.md)
for build and test commands, and
[`RELEASING.md`](https://github.com/thekaveh/VMx/blob/main/langs/rust/RELEASING.md)
for the release runbook.
