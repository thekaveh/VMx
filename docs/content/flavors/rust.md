# 7.6. Rust

Rust is the fifth VMx source flavor. It lives under `langs/rust/` as the
`vmx-rs` Cargo package while exposing the crate namespace `vmx`.

## Status

- Source tree: `langs/rust/`
- Package: `vmx-rs`
- Publication status: crates.io release channel not published yet
- Reactive primitive: VMx-owned facade over `rxrust`
- Naming: Rust type names such as `ComponentVm`, snake_case methods such as
  `construct()` and `dispose()`
- Conformance: all 354 library IDs are covered by behavioral Rust tests
- Property notifications: `notify_property_changed` publishes to the hub and
  then the per-instance `property_changed` stream

## Imperative Engine Bridge

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

## Local Use

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

## Development

```bash
cargo fmt --manifest-path langs/rust/Cargo.toml -- --check
cargo clippy --manifest-path langs/rust/Cargo.toml --all-targets -- -D warnings
cargo test --manifest-path langs/rust/Cargo.toml
cargo run --manifest-path examples/rust/console/hello-vmx/Cargo.toml
cargo test --manifest-path examples/rust/tui/notes-showcase/Cargo.toml
cargo run --manifest-path examples/rust/tui/notes-showcase/Cargo.toml -- --smoke
```

## Showcase

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
