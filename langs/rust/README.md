# VMx Rust

Rust flavor of VMx, the language-neutral, lifecycle-aware MVVM viewmodel framework.

**v0.29.0** implements `spec-v3.23.0` with complete catalog coverage: all 403
library conformance IDs are covered by behavioral Rust tests. The completed
[Rust parity ledger](../../docs/maintenance/2026-07-16-rust-capability-parity.md)
records the 0.27.0 capability, structural, command, reactive, and async
convergence retained by this line. [ADR-0130](../../spec/ADRs/0130-rust-paired-dispatch-and-background-lifecycle.md),
the 0.29.0 changelog, and current threading tests record the later paired-dispatch
work. The crate has not yet been published to crates.io.

This crate implements the VMx spec with idiomatic Rust naming and error handling:

- recoverable failures return `VmxResult<T>`;
- viewmodels expose explicit lifecycle methods (`construct`, `destruct`, `dispose`);
- component VMs expose their shared hub and accept LIFO disposal-lifetime
  cleanup through `hub()` and `own(...)`;
- modeled components expose `republish_model()` for an explicit retained-model
  notification without assignment or hint work;
- `hint()` is immutable fixed metadata while `modeled_hint()` is recomputed
  from the configured model hinter and publishes `modeled_hint` changes;
- message and dispatcher primitives are UI-framework neutral; `DefaultDispatcher`
  supplies dedicated foreground/background workers, custom dispatchers implement
  `dispatch_background`, and `ManualDispatcher` exposes independently drainable
  queues;
- component and read-only component builders opt into background lifecycle with
  `.background(true)`; terminal state/publication returns to foreground and hook
  failures arrive on the hot `background_errors()` stream;
- relay commands expose `raise_can_execute_changed` for precise binding
  invalidation without predicate polling;
- async relay commands provide an immutable builder, cooperative cancellation,
  additive triggers, an awaitable join handle, and fire-and-forget error routing;
- capability traits include predicate-based filtering, complete finite-page
  navigation, readable expansion state, and mutable search terms;
- `ExpandableState` supports explicit initial state and owned disposal, while
  disposed `SearchableState` reads as an empty term;
- every canonical component VM family exposes its `ViewModelType`, including
  group, composite wrappers, aggregate arities, hierarchy, form, and async
  resource VMs;
- `ValueStream<T>` provides typed replay and completion, message subscriptions
  can observe completion, notification pending state is replaying, and
  `DerivedProperty` automatically recomputes from one through five owned source
  subscriptions;
- `AsyncValue<T>` gives dialogs, notification waiters, modal completion, and
  confirmation gates an executor-neutral `Future` plus synchronous `wait()`,
  `map`, and `and_then`;
- confirmation-decorator `execute_async()` returns the thread-free
  `ConfirmationExecution` future; use `.await`, `.join()`, or
  `.is_finished()`. Rust 0.27.0 intentionally replaces the unpublished
  pre-release `JoinHandle<()>` return type, so explicitly typed callers must
  migrate and no `thread()` accessor exists. Blocking `.join()` preserves the
  original boxed panic payload for ordinary Rust downcasting;
- `FormVm::builder().reset_on_approved(...)` derives a pristine model after a
  successful persist without exposing a mutable form to the persister;
- `FormVm::set_model(...)` publishes one model hub message only after validation
  and approve-command state settle;
- `HierarchicalVm::attach_many(...)` resolves out-of-order tree windows with
  consumer keys, non-replacing dedupe, and park/reject orphan policy;
- `ObservableList::replace_all(...)` snapshots a full refresh and emits one
  reset with cardinality-correct `Count` notification;
- `ServicedObservableCollection<T>` provides the complete mutation surface,
  an always-present local stream, and optional local-before-external hub
  publication without batching or item ownership;
- `KeyedServicedObservableCollection<K, T>` adds captured-key lookup, upsert,
  and deletion without requiring `K: Clone` or changing ordered messages;
- `AggregateChangeStream<T>` follows dynamic membership and selected member
  streams with typed provenance and explicit coalescing;
- `SearchableState::from_items_with_changes(...)` maps a source hub pulse to
  one current-term filtered invalidation while owning only its subscription;
- `AsyncResourceVm<T, D>` is an ordinary component node with injected hub and
  dispatcher services, container ownership and selection, plus one cancellable
  latest-start-wins acquisition with retained/discarded presentation state and
  optional value cleanup;
- `VmCollection<T>` unifies groups and composites, while
  `SelectableVmCollection<T>` adds composite-only selection and `move_item`
  preserves child identity;
- `MessageHub::subscribe_value(...)` pushes selected fixed-source state into
  imperative hosts and returns a host-owned `Subscription`;
- UI integrations should live in examples or adapter crates, not in the core crate.

## 1. Commands

```bash
cargo test --locked --manifest-path langs/rust/Cargo.toml
cargo fmt --manifest-path langs/rust/Cargo.toml -- --check
cargo clippy --locked --manifest-path langs/rust/Cargo.toml --all-targets -- -D warnings
```

## 2. Minimal Example

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

### 2.1. Background Lifecycle

`NullDispatcher` and `ImmediateDispatcher` intentionally run both channels
inline. Use `DefaultDispatcher` for the built-in paired workers, or provide a
host dispatcher whose foreground channel targets the UI event loop:

```rust
use vmx::{ComponentVm, DefaultDispatcher, MessageHub, ValueSubscription, VmxResult};

fn start_in_background(
) -> VmxResult<(ComponentVm<(), DefaultDispatcher>, ValueSubscription)> {
    let vm = ComponentVm::builder()
        .name("loader")
        .model(())
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

The read-only family exposes the same option through
`ReadonlyComponentVm::builder().background(true)`.

### 2.2. Fixed Aggregates

`AggregateVm1` through `AggregateVm6` use immutable builders and populate their
typed slots from factories at construct time. Accessors return `None` before
construction and `Some(component)` afterward:

```rust
use vmx::{AggregateVm2, ComponentVm, MessageHub, NullDispatcher, VmxResult};

fn aggregate_example() -> VmxResult<()> {
    let hub = MessageHub::new();
    let aggregate = AggregateVm2::<ComponentVm, ComponentVm>::builder()
        .name("workspace")
        .hint("Two fixed child surfaces")
        .services(hub, NullDispatcher::new())
        .component_1(|| ComponentVm::new("navigation"))
        .component_2(|| ComponentVm::new("content"))
        .build()?;

    assert!(aggregate.component_1().is_none());
    aggregate.construct()?;
    assert!(aggregate.component_1().is_some());
    Ok(())
}
```

Every factory is evaluated and ownership-validated before slots change. A
failed candidate therefore leaves all previous slots and parent links intact.
Reconstruction invokes the factories again and disposes the replaced children.

## 3. Serviced Collections

Rust keeps `ServicedObservableCollection<T>` distinct from
`ObservableList<T>`: the serviced type owns an always-present local
`MessageHub` stream and can also publish to an external hub.

```rust
let notes = ServicedObservableCollection::with_hub(owner_id, hub.clone());
let local = notes.collection_changed();
let subscription = local.subscribe(|message| render(message));

notes.push(first);
notes.push(second);
let old = notes.replace(0, revised)?;
notes.move_item(0, notes.len() - 1)?; // one Move locally, then externally
notes.replace_all(server_snapshot);   // one Reset
```

`remove` deletes the first equal value and returns `false` when absent;
`remove_at` and `replace` return the removed / old item. `usize` indices make
negative positions unrepresentable, and out-of-range operations fail
atomically with `VmxResult`. Same-index move, empty clear, and empty-to-empty
replacement are no-ops. Messages carry action, optional old/new positions,
sender ID, and property name—never a legacy `index` or typed item payload. The
caller owns the subscription and stored items. Choose `ObservableList<T>` for
granular streams, batching, and `Count` notifications.

Use `KeyedServicedObservableCollection<K,T>` when the same ordered surface needs
one stable domain-key index:

```rust
let notes_by_id = KeyedServicedObservableCollection::with_hub(
    owner_id,
    hub.clone(),
    |note: &Note| Ok(note.id.clone()),
);
notes_by_id.push(first)?;
let note = notes_by_id.get_by_key(&first_id);
let added = notes_by_id.upsert(revised)?; // false: Replace at stable position
let removed = notes_by_id.remove_key(&first_id); // Option<Note>
```

Use `new(owner_id, key_of)` without an external hub. Positional `get(usize)` is
unchanged; keyed lookup is `get_by_key(&K)`, membership is `contains_key`, and
keys need `Eq + Hash + Send`, not `Clone`. Keys stay captured until indexed
replacement or remove-then-push. Failures are atomic; lookup/target discovery
are expected O(1), while ordered middle shifts remain O(n). The type never
batches or owns stored-item lifecycle.

## 4. Imperative Engine Bridge

Rust identifies the fixed source as `hub + sender_id`. Every message variant
also carries the diagnostic `sender_name`; use `Message::sender_name()` when
logging without matching the concrete variant. Use
`SubscribeValueOptions::default()` for `PartialEq` equality or
`SubscribeValueOptions::with_equality(...)` for a custom comparator:

```rust
use vmx::{SubscribeValueOptions, Subscription};

let selector_vm = camera_vm.clone();
let material_for_subscription = material.clone();
let exposure_subscription: Subscription = hub.subscribe_value(
    camera_vm.id(),
    move || selector_vm.model().exposure,
    move |exposure, _previous_exposure| {
        material_for_subscription.set_exposure(exposure);
    },
    SubscribeValueOptions::default().fire_immediately(true),
);

// When the host adapter is disposed:
exposure_subscription.dispose();
```

The callback receives `(current, previous)` by value; immediate delivery passes
the initial value for both. The selector runs after every property message for
this fixed sender ID. The host owns the returned `Subscription`; VMx does not
attach it to the observed VM's lifetime.
