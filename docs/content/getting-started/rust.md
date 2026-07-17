# 3.6. Getting Started with VMx — Rust

This tutorial walks you through building viewmodels with the VMx Rust crate.
You will build a `ComponentVm<Model>`, a `RelayCommand`, and a `CompositeVm<T>`
with child selection — all in a plain Cargo binary.

> The Rust flavor is a source-tree flavor at the v3.22.0 source line: it declares
> `MIN_SPEC_VERSION = "3.22.0"` and carries behavioral tests for all 395 library
> conformance IDs. The `vmx-rs` crate is not yet published to crates.io; consume
> it as a path or git dependency (below). See
> [`langs/rust/README.md`](../../../langs/rust/README.md) for the current status
> and [`docs/maintenance/2026-07-16-rust-capability-parity.md`](../../../docs/maintenance/2026-07-16-rust-capability-parity.md)
> for the tracked capability and behavioural parity gaps.
>
> For the normative contracts behind each type, see `spec/05-component-vm.md`,
> `spec/04-commands.md`, and `spec/06-composite-vm.md`.

______________________________________________________________________

## 3.6.1. Install

The crate is named `vmx-rs` and exposes the module namespace `vmx`. It requires
Rust edition 2021 and a `1.88` toolchain floor. Because it is not yet on
crates.io, depend on it by path from a checkout:

```toml
[dependencies]
vmx-rs = { path = "langs/rust" }
```

Or by git:

```toml
[dependencies]
vmx-rs = { git = "https://github.com/thekaveh/VMx.git" }
```

The crate declares only `serde` and `thiserror` as runtime dependencies; the
reactive primitives are VMx-owned hot-stream facades, so no third-party reactive
runtime is pulled in.

## 3.6.2. Wire up `MessageHub` and a `Dispatcher`

Every viewmodel needs two services: a hub that carries messages between
viewmodels and a dispatcher that routes scheduled work. `NullDispatcher` runs
foreground and background work inline on the calling thread — the right choice
for tests and synchronous programs. It is `Copy`, so it can be handed to several
viewmodels without cloning.

```rust
use vmx::{MessageHub, NullDispatcher};

let hub = MessageHub::new();
let dispatcher = NullDispatcher::new();
```

## 3.6.3. Build a `ComponentVm<Model>`

`ComponentVm<M>` is the primary leaf viewmodel. It holds a typed model, publishes
a property message on the hub when the model changes, and participates in the
lifecycle state machine. `with_model` constructs one directly; the model type
must be `Clone + PartialEq`.

```rust
use vmx::{ComponentVm, MessageHub, NullDispatcher};

#[derive(Clone, PartialEq)]
struct UserModel {
    name: String,
    email: String,
}

let hub = MessageHub::new();
let dispatcher = NullDispatcher::new();

let user = ComponentVm::with_model(
    "user-card",
    UserModel { name: "Alice".into(), email: "alice@example.com".into() },
    hub.clone(),
    dispatcher,
)
.with_model_hint(|model| Some(model.name.clone()));

user.construct()?;
assert!(user.is_constructed());

user.set_model(UserModel { name: "Alice Smith".into(), email: "asmith@example.com".into() });
assert_eq!(user.model().name, "Alice Smith");
assert_eq!(user.modeled_hint(), Some("Alice Smith".to_string()));
```

> See `spec/05-component-vm.md` for the full component contract.

## 3.6.4. Build a `RelayCommand`

`RelayCommand` wraps an action closure, an optional `can_execute` predicate, and
zero or more trigger hubs that announce when eligibility may have changed. Use
`RelayCommand::new` for the action-only form, or the builder to add a predicate.

```rust
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use vmx::{Command, RelayCommand};

let is_dirty = Arc::new(AtomicBool::new(false));
let dirty_for_predicate = is_dirty.clone();

let save = RelayCommand::builder()
    .action(|| println!("Saving..."))
    .can_execute(move || dirty_for_predicate.load(Ordering::Acquire))
    .build();

assert!(!save.can_execute());
is_dirty.store(true, Ordering::Release);
assert!(save.can_execute());
save.execute(); // prints "Saving..."

save.dispose();
```

> See `spec/04-commands.md` for the full command contract. `Command` is the
> object-safe trait exposing `can_execute()` and `execute()`.

## 3.6.5. Build a `CompositeVm<T>` with selection

`CompositeVm<T>` owns an ordered child collection and a `current` selection slot.
Children come from a factory evaluated on the first `construct()`; an optional
`current` selector seeds the initial selection.

```rust
use vmx::{ComponentVm, CompositeVm, MessageHub, NullDispatcher, VmxResult};

fn build_tabs() -> VmxResult<()> {
    let hub = MessageHub::new();
    let dispatcher = NullDispatcher::new();

    let home = ComponentVm::with_model("home-tab", "Home", hub.clone(), dispatcher);
    let settings = ComponentVm::with_model("settings-tab", "Settings", hub.clone(), dispatcher);

    let tabs = CompositeVm::builder()
        .name("tab-bar")
        .services(hub, dispatcher)
        .children({
            let children = vec![home.clone(), settings.clone()];
            move || children.clone()
        })
        .current(|items| items.first().cloned())
        .build()?;

    tabs.construct()?;
    assert_eq!(tabs.len(), 2);
    assert_eq!(tabs.current().map(|c| c.name()), Some("home-tab".to_string()));

    tabs.select_component(&settings)?;
    assert_eq!(tabs.current().map(|c| c.name()), Some("settings-tab".to_string()));

    tabs.dispose()
}
```

Project a live filtered view over a composite with `FilteredCompositeVm`:

```rust
use vmx::FilteredCompositeVm;

let matches = FilteredCompositeVm::new(tabs.clone(), |tab| tab.model().contains("Home"));
assert_eq!(matches.visible_count(), 1);
```

> See `spec/06-composite-vm.md` for the full `CompositeVm` contract.

## 3.6.6. Lifecycle and cleanup

Every viewmodel follows a five-state lifecycle —
`Destructed -> Constructing -> Constructed -> Destructing -> Destructed` — plus
the terminal `Disposed`. The mutating transitions return `VmxResult<()>`: an
illegal transition (for example constructing a disposed viewmodel) is a
**catchable** `Err`, not a panic, under the v3 lifecycle convergence (ADR-0053).

```rust
use vmx::ConstructionStatus;

assert_eq!(user.status(), ConstructionStatus::Constructed);

user.reconstruct()?; // destruct + construct in one call; round-trips to Constructed
assert_eq!(user.status(), ConstructionStatus::Constructed);

user.destruct()?;
assert_eq!(user.status(), ConstructionStatus::Destructed);

user.dispose()?; // idempotent and terminal
assert_eq!(user.status(), ConstructionStatus::Disposed);
```

Selecting a non-child returns `Err(VmxError::NonChild)` rather than trapping, so
callers can branch on the result. Builders return `Err` from `build()` when a
required field is missing.

> See `spec/02-lifecycle.md` for the full transition table (LIFE-001..014).

## 3.6.7. Where to go next

| Resource                      | Path                            |
| ----------------------------- | ------------------------------- |
| Spec overview                 | `spec/00-overview.md`           |
| Lifecycle contract            | `spec/02-lifecycle.md`          |
| Commands                      | `spec/04-commands.md`           |
| ComponentVM contract          | `spec/05-component-vm.md`       |
| CompositeVM contract          | `spec/06-composite-vm.md`       |
| Architecture decision records | `spec/ADRs/`                    |
| Rust flavor README            | `langs/rust/README.md`          |
| Rust examples                 | `examples/rust/README.md`       |
| Rust conformance suite        | `langs/rust/tests/conformance/` |
