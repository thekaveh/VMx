# VMx Rust Examples

Demos for the [VMx Rust crate](../../langs/rust/).

## 1. Example 1 — `console/hello-vmx`

Minimal Cargo console demo. Demonstrates:

1. Constructing modeled `ComponentVm` rows with explicit VMx services.
1. Owning those rows in a `CompositeVm` with an initial `current(...)` selector.
1. Projecting a live search result through `FilteredCompositeVm`.
1. Executing a `RelayCommand`.
1. Running the lifecycle through `construct()` and `dispose()`.

Run from the repository root:

```bash
cargo run --manifest-path examples/rust/console/hello-vmx/Cargo.toml
```

Expected output:

```text
Hello from VMx Rust
notes constructed with 3 notes
current: rust-roadmap
rust search matches: 1
```

## 2. Project Layout

```text
examples/rust/
├── README.md
└── console/
    └── hello-vmx/
        ├── Cargo.toml
        └── src/main.rs
```
