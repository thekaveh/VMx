# 7.6. Rust

Rust is the fifth VMx source flavor. It lives under `langs/rust/` as the
`vmx-rs` Cargo package while exposing the crate namespace `vmx`.

## 7.6.1. Status

- Package: `vmx-rs`, imported as the crate `vmx`; it ships the repository's
  Apache-2.0 text
- Version: `vmx-rs` 0.36.0 implements spec 3.30.0; the MSRV is Rust 1.88
- Publication status: not published on crates.io
- Reactive primitive: VMx-owned hot-stream facade (ADR-0103)
- Naming: Rust type names such as `ComponentVm`, snake_case methods such as
  `construct()` and `dispose()`
- Conformance: behavioral Rust tests cover all 444 library IDs. Rust has no UI
  scenario suite for the five THEME IDs.
- Known gaps: the public surface and some behaviors are not fully aligned with
  the other flavors. The
  [Rust parity ledger](../../maintenance/2026-07-16-rust-capability-parity.md)
  lists the open items and recorded differences in §12.4.7 and §12.7–§12.12. Two COMP-026
  tests in `langs/rust/tests/conformance/composite_vm.rs` are `#[ignore]`d for
  a composite-selection gap.

For hub delivery and callback ordering, see
[Callback-Safe Transition Ordering](../architecture/lifecycle-messaging.md#541-callback-safe-transition-ordering).

## 7.6.2. Runtime Behavior

- Hub retention: a `MessageHub` keeps no delivered message.
  `record(capacity)` returns a bounded `MessageRecorder` for tests and
  diagnostics. The deprecated `history()` is always empty (ADR-0141).
- Property notifications: `notify_property_changed` publishes to the hub and
  then to the per-instance `property_changed` stream.
- Hint surfaces: `hint()` is immutable fixed metadata. `modeled_hint()` is
  recomputed from the model and publishes `modeled_hint` changes.
- Async commands: `AsyncRelayCommand::builder()` owns its task, predicate,
  additive triggers, cancellation mode, and fire-and-forget error stream.
- Completion handles: `AsyncValue<T>` is an executor-neutral `Future` with a
  blocking `wait()`. When a `map` or `and_then` callback panics, the returned
  handle settles as panicked. `wait()` and `.await` re-raise the panic, and
  `wait_result()` returns an `AsyncValuePanic`, so no waiter hangs (ADR-0138).
- Async resources: `AsyncResourceVm<T, D>` accepts the shared hub and
  dispatcher and implements the ordinary component and node contract. It keeps
  resource phase in `resource_status()` / `state().status()`, independently of
  lifecycle status.

## 7.6.3. Background Lifecycle And Threading

`Dispatcher` has paired foreground and background closure channels.
`NullDispatcher` and `ImmediateDispatcher` run both channels inline.
`DefaultDispatcher` supplies dedicated foreground and background workers. A host
dispatcher can target its foreground channel at the UI event loop.

Component and read-only component builders opt into background lifecycle work
with `.background(true)`:

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

Background mode applies only to standalone construct and destruct hooks. The
terminal state and its publication return to the foreground. Hook failures
arrive on the event-only hot `background_errors()` stream. `reconstruct()` and
its command complete their two-phase transition synchronously. Rejected
foreground or background scheduling restores lifecycle admission.

Containers stay Constructing or Destructing until their background children
settle. Thus a container `construct`, `destruct`, or `reconstruct` call can
return `Ok` while the container is still transient. A child failure rolls the
container back and arrives on the container's `background_errors()` stream.
Wrapper nodes should forward `VmNode::when_lifecycle_settled`. If a node does
not forward `when_lifecycle_settled`, the container accepts that node while it
is still in flight instead of failing.

An admitted `AsyncRelayCommand` execution runs on one worker thread, and a
rejected `execute()` starts none. A rejected `execute_async()` still returns a
`JoinHandle` that completes with `Ok(())` from a short-lived thread. An
`AsyncResourceVm` load runs its loader on its own worker. The thread that awaits
the load blocks, without polling, until the loader reports or the load is
cancelled (ADR-0140).

## 7.6.4. Fixed Aggregates

`AggregateVm1` through `AggregateVm6` expose immutable builders whose required
component factories run at construct time. Typed `component_1` through
`component_6` accessors return `None` before construction and the populated
component afterward:

```rust
let aggregate = AggregateVm2::<ComponentVm, ComponentVm>::builder()
    .name("workspace")
    .hint("Two fixed child surfaces")
    .services(MessageHub::new(), NullDispatcher::new())
    .component_1(|| ComponentVm::new("navigation"))
    .component_2(|| ComponentVm::new("content"))
    .build()?;

assert!(aggregate.component_1().is_none());
aggregate.construct()?;
assert!(aggregate.component_1().is_some());
```

Factories are all evaluated and ownership-validated before any previous slot
changes. Failed validation preserves the prior slots and parent links;
reconstruction invokes the factories again and disposes replaced children.

## 7.6.5. Serviced Collections

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

`remove` removes the first equal value and returns `false` when absent.
`remove_at` and `replace` return the removed or old item. `usize` indices make
negative positions unrepresentable, and out-of-range indexed operations fail
atomically with `VmxResult`. Same-index move, empty clear, and empty-to-empty
replacement are no-ops.

Rust messages carry the action, optional old and new positions, sender ID, and
property name. They carry no legacy `index` and no typed item payload. Use
`ObservableList<T>` for granular streams, batching, and `Count` notifications.

The caller owns the subscription and controls each stored VM's construct,
destruct, and dispose operations. Membership retains an item as an ordinary
Rust value but does not transfer lifecycle ownership.

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
Projector and duplicate-key failures are atomic `VmxResult` failures.

Captured keys do not follow mutable item properties. Indexed `replace` or
remove-then-push rekeys explicitly, and a same mutated instance can occupy two
memberships. Lookup and target discovery are expected O(1), push is amortized
O(1), and ordered middle shifts remain O(n). Local delivery precedes optional
hub publication; a hub transaction defers only external delivery. The keyed
type has no batch or VM lifecycle interface and never owns stored-item
lifecycle.

## 7.6.6. Imperative Engine Bridge

Rust expresses the fixed source as `hub + sender_id`. Every message variant
also carries the diagnostic `sender_name`; `Message::sender_name()` reads it
without a match on the concrete variant. `subscribe_value` returns
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
the initial value for both. The selector reevaluates after every property
message carrying this fixed sender ID rather than on every render frame. The
host adapter owns the subscription; VMx does not attach it to the observed VM's
lifetime.

### 7.6.6.1. Nested Command Execution

A command can be executed again from inside its own execution: from its
action, from a `can_execute_changed` handler, or from a hub subscriber it
triggers. As in the other flavors, the nested call evaluates `can_execute` when
it is made and, if admitted, runs before the outer `execute` returns; it never
deadlocks. Built-in commands, such as FormVM's approve and deny and the
component, CRUD, notification, and async-resource commands, run the nested
call inline.

A command built from a user `FnMut` action (`RelayCommand::new` or the
builder's `action`) cannot run that action while it is already running, so an
admitted nested call on the same thread is deferred: it runs after the current
action returns and before the outermost `execute` returns, in the order inline
recursion would give. A call from another thread waits for the running action.
A deferred call does not run once the command is disposed, and a panicking
action drops the calls deferred during it.

## 7.6.7. Local Use

Add the `vmx-rs` crate as [Installation](../installation.md) shows. This
program confirms that the crate builds and runs:

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

## 7.6.8. Development

```bash
cargo fmt --manifest-path langs/rust/Cargo.toml -- --check
cargo clippy --locked --manifest-path langs/rust/Cargo.toml --all-targets -- -D warnings
cargo test --locked --manifest-path langs/rust/Cargo.toml
cargo run --locked --manifest-path examples/rust/console/hello-vmx/Cargo.toml
cargo test --locked --manifest-path examples/rust/tui/notes-showcase/Cargo.toml
cargo run --locked --manifest-path examples/rust/tui/notes-showcase/Cargo.toml -- --smoke
```

CI also gates library coverage; see
[Coverage Floors](../contributing-releases.md#1133-coverage-floors).

## 7.6.9. Showcase

The Ratatui Notes Showcase is at `examples/rust/tui/notes-showcase/`. The host
is only a renderer and input adapter. VMx view models own notebook selection,
search and filtering, page state, form validation, save and revert operations,
global token search, notifications, and edit/preview mode.

See [Rust TUI Notes Showcase](../examples/rust-tui-notes-showcase.md) for the
VM-layer diagram and run commands.

Use [ADR-0080](../../../spec/ADRs/0080-rust-flavor-feasibility.md)
for the adoption decision and [ADR-0081](../../../spec/ADRs/0081-rust-full-parity-cutover.md)
for the full-conformance cutover.

## 7.6.10. Pointers

- Flavor README:
  [langs/rust/README.md](../../../langs/rust/README.md)
- Getting started guide:
  [Getting Started with VMx — Rust](../getting-started/rust.md)
- Example portfolio:
  [Examples overview](../examples/index.md)
- Rust TUI showcase:
  [Rust TUI Notes Showcase](../examples/rust-tui-notes-showcase.md)
- Host wiring routes:
  [Integration Recipes](../integration/index.md)
