# VMx Rust

Rust flavor of VMx, the language-neutral, lifecycle-aware MVVM viewmodel framework.

**v0.18.0** implements `spec-v3.18.0` at full source parity: all 373 library
conformance IDs are covered by behavioral Rust tests. The crate has not yet
been published to crates.io.

This crate implements the VMx spec with idiomatic Rust naming and error handling:

- recoverable failures return `VmxResult<T>`;
- viewmodels expose explicit lifecycle methods (`construct`, `destruct`, `dispose`);
- component VMs expose their shared hub and accept LIFO disposal-lifetime
  cleanup through `hub()` and `own(...)`;
- modeled components expose `republish_model()` for an explicit retained-model
  notification without assignment or hint work;
- message and dispatcher primitives are UI-framework neutral;
- relay commands expose `raise_can_execute_changed` for precise binding
  invalidation without predicate polling;
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
- `VmCollection<T>` unifies groups and composites, while
  `SelectableVmCollection<T>` adds composite-only selection and `move_item`
  preserves child identity;
- `MessageHub::subscribe_value(...)` pushes selected fixed-source state into
  imperative hosts and returns a host-owned `Subscription`;
- UI integrations should live in examples or adapter crates, not in the core crate.

## Commands

```bash
cargo test --manifest-path langs/rust/Cargo.toml
cargo fmt --manifest-path langs/rust/Cargo.toml -- --check
cargo clippy --manifest-path langs/rust/Cargo.toml --all-targets -- -D warnings
```

## Minimal Example

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

## Serviced Collections

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

## Imperative Engine Bridge

Rust identifies the fixed source as `hub + sender_id`. Use
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
