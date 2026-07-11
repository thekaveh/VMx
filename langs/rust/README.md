# VMx Rust

Rust flavor of VMx, the language-neutral, lifecycle-aware MVVM viewmodel framework.

**v0.9.0** implements `spec-v3.9.0` at full source parity: all 332 library
conformance IDs are covered by behavioral Rust tests. The crate has not yet
been published to crates.io.

This crate implements the VMx spec with idiomatic Rust naming and error handling:

- recoverable failures return `VmxResult<T>`;
- viewmodels expose explicit lifecycle methods (`construct`, `destruct`, `dispose`);
- message and dispatcher primitives are UI-framework neutral;
- relay commands expose `raise_can_execute_changed` for precise binding
  invalidation without predicate polling;
- `FormVm::builder().reset_on_approved(...)` derives a pristine model after a
  successful persist without exposing a mutable form to the persister;
- `HierarchicalVm::attach_many(...)` resolves out-of-order tree windows with
  consumer keys, non-replacing dedupe, and park/reject orphan policy;
- `ObservableList::replace_all(...)` snapshots a full refresh and emits one
  reset with cardinality-correct `Count` notification;
- `VmCollection<T>` unifies groups and composites, while
  `SelectableVmCollection<T>` adds composite-only selection and `move_item`
  preserves child identity;
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
