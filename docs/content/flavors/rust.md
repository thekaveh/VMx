# 7.6. Rust

Rust is the fifth VMx source flavor. It lives under `langs/rust/` as the
`vmx-rs` Cargo package while exposing the crate namespace `vmx`.

## 7.6.1. Status

- Source tree: `langs/rust/`
- Package: `vmx-rs`
- Current source line: `vmx-rs` 0.24.0 implementing spec 3.22.0
- Publication status: crates.io release channel not published yet
- Reactive primitive: VMx-owned hot-stream facade
- Naming: Rust type names such as `ComponentVm`, snake_case methods such as
  `construct()` and `dispose()`
- Conformance: all 395 library IDs are covered by behavioral Rust tests
- Property notifications: `notify_property_changed` publishes to the hub and
  then the per-instance `property_changed` stream
- Async commands: `AsyncRelayCommand::builder()` owns its task, predicate,
  additive triggers, cancellation mode, and fire-and-forget error stream

## 7.6.2. Serviced Collections

Rust's `ServicedObservableCollection<T>` is distinct from `ObservableList<T>`.
It owns an always-present local `MessageHub` stream and may also forward to an
external hub:

```rust
let notes = ServicedObservableCollection::with_hub(owner_id, hub.clone());
let local = notes.collection_changed();
let subscription = local.subscribe(|message| render(message));

notes.push(first);
notes.push(second);
let old = notes.replace(0, revised)?;
notes.move_item(0, notes.len() - 1)?;     // one Move locally, then externally
notes.replace_all(server_snapshot);       // one Reset
```

`remove` removes the first equal value and returns `false` when absent;
`remove_at` and `replace` return the removed or old item. Indices are `usize`,
and out-of-range indexed operations fail atomically with `VmxResult`. Empty
clear and same-index move are no-ops. Rust messages carry action plus optional
old/new positions, sender ID, and property name; they intentionally carry no
legacy `index` or item payload. The caller owns the subscription and stored
items.

`KeyedServicedObservableCollection<K,T>` adds captured-key access while
preserving that ordered surface. Rust keeps positional `get(usize)` and names
the keyed operation `get_by_key(&K)` because methods cannot be overloaded:

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

Without an external hub, construct it with `new(owner_id, key_of)`.
`contains_key` tests membership. Keys require `Eq + Hash + Send`, not `Clone`.
Projector and duplicate-key failures are atomic `VmxResult` failures. Captured
keys do not follow mutable item properties; indexed `replace` or
remove-then-push rekeys explicitly, and a same mutated instance can occupy two
memberships. Lookup and target discovery are expected O(1), push is amortized
O(1), and ordered middle shifts remain O(n). Local delivery precedes optional
hub publication; a hub transaction defers only external delivery. The keyed
type has no batch or VM lifecycle interface and never owns stored-item
lifecycle.

## 7.6.3. Imperative Engine Bridge

Rust expresses the fixed source as `hub + sender_id`. `subscribe_value` returns
VMx's `Subscription`; `SubscribeValueOptions::default()` uses `PartialEq`, while
`SubscribeValueOptions::with_equality(...)` accepts custom equality without
that bound:

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

// Host adapter disposal:
exposure_subscription.dispose();
```

The callback receives `(current, previous)` by value; immediate delivery uses
the initial value for both. The host adapter owns the subscription, and the
selector reevaluates after every property message carrying this fixed sender
ID rather than on every render frame.

## 7.6.4. Local Use

=== "Cargo.toml"

    ```toml
    [dependencies]
    vmx-rs = { path = "langs/rust" }
    ```

=== "Rust"

    ```rust
    use vmx::{Command, ComponentVm, MessageHub, NullDispatcher, RelayCommand, VmxResult};

    fn main() -> VmxResult<()> {
        let hub = MessageHub::new();
        let dispatcher = NullDispatcher::new();
        let vm = ComponentVm::with_services("hello-rust", hub, dispatcher);

        vm.construct()?;
        RelayCommand::new(|| println!("Hello from VMx Rust")).execute();
        vm.dispose()
    }
    ```

## 7.6.5. Development

```bash
cargo fmt --manifest-path langs/rust/Cargo.toml -- --check
cargo clippy --locked --manifest-path langs/rust/Cargo.toml --all-targets -- -D warnings
cargo test --locked --manifest-path langs/rust/Cargo.toml
cargo run --locked --manifest-path examples/rust/console/hello-vmx/Cargo.toml
cargo test --locked --manifest-path examples/rust/tui/notes-showcase/Cargo.toml
cargo run --locked --manifest-path examples/rust/tui/notes-showcase/Cargo.toml -- --smoke
```

## 7.6.6. Showcase

Rust now ships a Ratatui Notes Showcase at
`examples/rust/tui/notes-showcase/`. The host is intentionally a renderer and
input adapter only: VMx view models own notebook selection, search/filtering,
page state, form validation, save/revert commands, global token search,
notifications, and edit/preview mode.

See [Rust TUI Notes Showcase](../examples/rust-tui-notes-showcase.md) for the
VM-layer diagram and run commands.

Use [ADR-0080](../../../spec/ADRs/0080-rust-flavor-feasibility.md)
for the adoption decision and [ADR-0081](../../../spec/ADRs/0081-rust-full-parity-cutover.md)
for the full-conformance cutover.
