# VMx Rust Examples

Preview demos for the [VMx Rust crate](../../langs/rust/).

## 1. Example 1 — `console/hello-vmx`

Minimal Cargo console demo. Demonstrates:

1. Constructing a `ComponentVm` with explicit VMx services.
1. Executing a `RelayCommand`.
1. Running the lifecycle through `construct()` and `dispose()`.

Run from the repository root:

```bash
cargo run --manifest-path examples/rust/console/hello-vmx/Cargo.toml
```

Expected output:

```text
Hello from VMx Rust
hello-rust constructed: true
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
