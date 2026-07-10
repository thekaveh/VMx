# Rust Full-Parity Flavor Design

## 1. Goal

Promote Rust from a source-tree preview flavor to a fifth full-parity VMx flavor.
Rust must expose the same VMx component families, services, helpers, examples,
documentation, and conformance guarantees as C#, Python, TypeScript, and Swift,
while keeping Rust surface idioms from ADR-0080.

## 2. Success Criteria

- `langs/rust/` is a real Rust crate named `vmx-rs` with crate namespace `vmx`.
- Rust implements all 281 library conformance IDs in `spec/12-conformance.md`
  with behavioral tests, not marker-only tests.
- The conformance workflow requires Rust alongside C#, Python, TypeScript, and
  Swift.
- The public Rust API contains the same conceptual component families as the
  stable flavors: lifecycle, messages, services, commands, components,
  composites, groups, aggregates, forwarding wrappers, builders, capabilities,
  collections, derived properties, notifications, localization, dialogs, forms,
  hierarchical VMs, discriminator VMs, and tree utilities.
- The Rust flavor remains idiomatic: Rust-style type names (`ComponentVm`),
  snake_case methods (`construct`, `dispose`), `VmxResult<T>`, and explicit
  disposal.
- All docs surfaces describe Rust as full parity only after the Rust
  conformance suite is required by CI.
- Diagrams are regenerated from dark-themed architecture-diagram HTML masters,
  with SVG and high-resolution PNG outputs kept in the existing diagram asset
  locations.

## 3. Architecture

Rust will keep one public crate, `vmx`, but the implementation will be split
into modules that mirror the other flavor layouts:

- `lifecycle`, `messages`, `services`
- `commands`, `components`, `composites`, `groups`, `aggregates`
- `collections`, `capabilities`, `properties`, `notifications`
- `localization`, `dialogs`, `forms`, `hierarchical`, `forwarding`, `state`,
  `tree`, `builders`

The crate root will re-export the stable public surface. Internal shared state
will use cloneable handles backed by `Arc<Mutex<_>>`, because Rust has no class
inheritance. VMx hierarchy semantics will be expressed through traits and
explicit parent/child handles.

## 4. Test Strategy

Rust conformance tests will be organized by the same catalog families used by
the other languages, for example `lifecycle.rs`, `message_hub.rs`,
`commands.rs`, `component_vm.rs`, `composite_vm.rs`, `collections.rs`,
`hierarchical_vm.rs`, and `forms.rs`.

Each library conformance ID must attach to a real Rust test through the current
doc-comment marker convention:

```rust
/// LIFE-001 — construct from Destructed transitions through Constructing to Constructed
#[test]
fn construct_from_destructed_transitions_to_constructed() {
    // behavioral assertion here
}
```

The generated `catalog_markers.rs` file will be deleted once every ID has a
real behavioral home. The coverage tool will then require Rust in CI.

## 5. Documentation And Diagrams

Documentation updates must cover all current surfaces:

- root README and compatibility matrix
- `docs/site/**` MkDocs source
- `docs/wiki/**` wiki source
- generated wiki build output where the repo keeps it
- flavor READMEs and examples READMEs

Diagrams under `docs/assets/diagrams/` will be regenerated with the
architecture-diagram skill. Required outputs for each diagram are `.html`,
`.svg`, and high-resolution `.png`. Updated diagrams must use a dark background,
landscape layout, and non-overlapping labels and component boxes.

## 6. Release Boundary

This work does not publish `vmx-rs` to crates.io. It makes Rust eligible for a
future release channel by proving parity in source and CI. The crates.io release
channel remains tracked by issue #67.
