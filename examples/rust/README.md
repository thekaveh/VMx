# VMx Rust Examples

Demos for the [VMx Rust crate](../../langs/rust/).
Generated architecture diagrams for all examples live in
[`../DIAGRAMS.md`](../DIAGRAMS.md).

## 1. Example 1 — `console/hello-vmx`

Minimal Cargo console demo. Demonstrates:

1. Constructing modeled `ComponentVm` rows with explicit VMx services.
1. Owning those rows in a `CompositeVm` with an initial `current(...)` selector.
1. Projecting a live search result through `FilteredCompositeVm`.
1. Executing a `RelayCommand`.
1. Running the lifecycle through `construct()` and `dispose()`.

Run from the repository root:

Diagram:
[`rust-console-hello-vmx.svg`](../../docs/assets/diagrams/rust-console-hello-vmx.svg)
([HTML](../../docs/assets/diagrams/rust-console-hello-vmx.html),
[PNG](../../docs/assets/diagrams/rust-console-hello-vmx.png)).

```bash
cargo run --locked --manifest-path examples/rust/console/hello-vmx/Cargo.toml
```

Expected output:

```text
Hello from VMx Rust
notes constructed with 3 notes
current: rust-roadmap
rust search matches: 1
```

## 2. Example 2 — `tui/notes-showcase`

Cross-platform Ratatui showcase app. The terminal host is intentionally thin:
VMx view models own notebook selection, note filtering, page state, editor
mode, form validation, save/revert commands, global token search, and
notifications.

### 2.1. Parity Role

This is a **reduced companion** to the four canonical Notes Workspace
flagships, not a fifth column in the 19-feature parity matrix. It intentionally
does not implement `THEME-001..005`, `IDialogService` export, the capability
action bar, the async dispatcher scenario, or tag autocomplete. The narrower
scope keeps the example focused on Rust-native terminal composition while the
four UI-backed hosts remain the executable cross-flavor scenario contract.

VM-layer diagram:
[`docs/assets/diagrams/rust-tui-notes-showcase.svg`](../../docs/assets/diagrams/rust-tui-notes-showcase.svg)
([HTML](../../docs/assets/diagrams/rust-tui-notes-showcase.html),
[PNG](../../docs/assets/diagrams/rust-tui-notes-showcase.png)).

Run the non-interactive smoke path from the repository root:

```bash
cargo run --locked --manifest-path examples/rust/tui/notes-showcase/Cargo.toml -- --smoke
```

Run the VM-layer tests:

```bash
cargo test --locked --manifest-path examples/rust/tui/notes-showcase/Cargo.toml
```

Run the interactive TUI:

```bash
cargo run --locked --manifest-path examples/rust/tui/notes-showcase/Cargo.toml
```

Key bindings:

- `q`: quit
- `/`: apply the sample `vmx` note search
- `x`: clear note search
- `n` / `p`: next or previous notes page
- `m`: toggle edit/preview mode
- `d`: request delete confirmation
- `y` / `r`: approve or reject pending delete

## 3. Project Layout

```text
examples/rust/
├── README.md
├── console/
│   └── hello-vmx/
│       ├── Cargo.toml
│       └── src/main.rs
└── tui/
    └── notes-showcase/
        ├── Cargo.toml
        ├── src/
        │   ├── app.rs
        │   ├── lib.rs
        │   ├── main.rs
        │   ├── models.rs
        │   ├── viewmodels.rs
        │   └── views.rs
        └── tests/viewmodels.rs
```
