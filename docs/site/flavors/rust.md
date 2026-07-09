# Rust

Rust is the in-progress fifth VMx flavor. It lives under `langs/rust/` as the
`vmx-rs` Cargo package while exposing the crate namespace `vmx`.

## Status

- Source tree: `langs/rust/`
- Package: `vmx-rs`
- Publication status: crates.io release channel not published yet
- Reactive primitive: VMx-owned facade over `rxrust`
- Naming: Rust type names such as `ComponentVm`, snake_case methods such as
  `construct()` and `dispose()`
- Conformance: 281 catalog markers are present; behavioral assertions are still
  being expanded before Rust is marked stable full parity

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
```

Use [ADR-0080](https://github.com/thekaveh/VMx/blob/main/spec/ADRs/0080-rust-flavor-feasibility.md)
for the adoption decision and the Rust-specific constraints.
