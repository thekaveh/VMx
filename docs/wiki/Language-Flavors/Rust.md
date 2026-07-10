# Rust

Rust is VMx's fifth source flavor. It lives under `langs/rust/` as the
`vmx-rs` Cargo package and exposes the crate namespace `vmx`.

## Status

- Source tree: `langs/rust/`
- Package name: `vmx-rs`
- Public registry: crates.io release channel not published yet
- Reactive primitive: VMx-owned facade over `rxrust`
- Conformance: behavioral tests for all 281 library IDs

## Minimal Shape

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

## Related Pages

- [[Cross-Language Naming|Language-Flavors/Cross-Language-Naming]]
- [[Conformance Workflow|Specification-and-Conformance/Conformance-Workflow]]
- [[Smaller Examples|Examples/Smaller-Examples]]
- [[Rust TUI Notes Showcase|Examples/Rust-TUI-Notes-Showcase]]
