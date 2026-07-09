# Rust Full-Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote Rust from preview marker coverage to a fifth full-parity VMx flavor.

**Architecture:** Split the Rust crate into spec-aligned modules and drive each module with real conformance tests. Rust stays idiomatic while matching the conceptual behavior of C#, Python, TypeScript, and Swift.

**Tech Stack:** Rust 2021, Cargo, `rxrust`, `serde`, `serde_json`, `thiserror`, repository Python tooling, MkDocs Material, architecture-diagram HTML/SVG/PNG assets.

## Global Constraints

- The Rust package name is `vmx-rs`; the crate namespace is `vmx`.
- The Rust crate declares `MIN_SPEC_VERSION = "3.1.0"`.
- Rust must expose Rust-style type names and snake_case methods.
- Rust behavioral conformance must cover all 281 library IDs from `spec/12-conformance.md`.
- The 5 `THEME` IDs remain example scenario IDs and are not part of the Rust library conformance gate.
- CI must require Rust only after marker-only tests are replaced by behavioral tests.
- Documentation must be updated on repo markdown, MkDocs `.io` source, and wiki source.
- Diagrams must be generated with the architecture-diagram skill and kept as `.html`, `.svg`, and high-resolution `.png`.

---

## Task 1: Rust Foundations

**Files:**
- Modify: `langs/rust/src/lib.rs`
- Create: `langs/rust/tests/conformance/lifecycle.rs`
- Create: `langs/rust/tests/conformance/message_hub.rs`
- Create: `langs/rust/tests/conformance/property_change.rs`
- Modify: `langs/rust/tests/conformance.rs`
- Delete once IDs move: `langs/rust/tests/conformance/catalog_markers.rs`

**Interfaces:**
- Produces: `ConstructionStatus`, `LifecycleOperation`, `VmxError`, `VmxResult<T>`, `MessageHub`, `Subscription`, `Message`, `PropertyChangedMessage`, `ConstructionStatusChangedMessage`, `ComponentVm`, `VmNode`, `Dispatcher`, `NullDispatcher`, `ImmediateDispatcher`, `ManualDispatcher`.

- [ ] Write behavioral tests for `LIFE-001..014`, `HUB-001..007`, and `PROP-001..004`.
- [ ] Run targeted Rust tests and verify they fail for missing or incorrect behavior:

```bash
cargo test --manifest-path langs/rust/Cargo.toml lifecycle message_hub property_change
```

- [ ] Implement lifecycle, hub, dispatcher, and property-change behavior until the tests pass.
- [ ] Run:

```bash
cargo fmt --manifest-path langs/rust/Cargo.toml -- --check
cargo clippy --manifest-path langs/rust/Cargo.toml --all-targets -- -D warnings
cargo test --manifest-path langs/rust/Cargo.toml
python3 tools/check-conformance-coverage.py
```

- [ ] Commit:

```bash
git add langs/rust
git commit -m "feat(rust): implement foundation conformance"
```

## Task 2: Commands, Capabilities, And Null Services

**Files:**
- Modify: `langs/rust/src/lib.rs`
- Create: `langs/rust/tests/conformance/commands.rs`
- Create: `langs/rust/tests/conformance/command_decorators.rs`
- Create: `langs/rust/tests/conformance/capabilities.rs`
- Create: `langs/rust/tests/conformance/null_services.rs`

**Interfaces:**
- Produces: `Command`, `CommandOf<T>`, `AsyncRelayCommand`, `RelayCommand`, `RelayCommandOf<T>`, `CompositeCommand`, `DecoratorCommand`, `ConfirmationDecoratorCommand`, fluent command helpers, capability traits, `NullMessageHub`, `NullDispatcher`.

- [ ] Write behavioral tests for `CMD-001..013`, `CMDD-001..010`, `CAP-001..022`, and `NULL-001..003`.
- [ ] Verify red with targeted Rust tests.
- [ ] Implement command and capability behavior.
- [ ] Run Rust fmt, clippy, full Rust tests, and conformance coverage.
- [ ] Commit `feat(rust): implement command and capability conformance`.

## Task 3: Component, Composite, Group, Aggregate, Forwarding, Builders

**Files:**
- Modify: `langs/rust/src/lib.rs`
- Create: `langs/rust/tests/conformance/component_vm.rs`
- Create: `langs/rust/tests/conformance/composite_vm.rs`
- Create: `langs/rust/tests/conformance/group_vm.rs`
- Create: `langs/rust/tests/conformance/aggregate_vm.rs`
- Create: `langs/rust/tests/conformance/forwarding.rs`
- Create: `langs/rust/tests/conformance/builders.rs`

**Interfaces:**
- Produces: `ReadonlyComponentVm`, `CompositeVm`, `CompositeVmOf<M, VM>`, `GroupVm`, `AggregateVm1..6`, `ForwardingComponentVm`, `ForwardingCompositeVm`, Rust builders for common VM families.

- [ ] Write behavioral tests for `CVM-001..006`, `COMP-001..027`, `GRP-001..011`, `AGG-001..006`, `FWD-001..003`, and `BLD-001..006`.
- [ ] Verify red with targeted Rust tests.
- [ ] Implement the VM family behavior and immutable builder semantics.
- [ ] Run Rust fmt, clippy, full Rust tests, and conformance coverage.
- [ ] Commit `feat(rust): implement viewmodel family conformance`.

## Task 4: Collections, Search, Derived Properties, Tree, Threading

**Files:**
- Modify: `langs/rust/src/lib.rs`
- Create: `langs/rust/tests/conformance/collections.rs`
- Create: `langs/rust/tests/conformance/search_filter.rs`
- Create: `langs/rust/tests/conformance/derived_properties.rs`
- Create: `langs/rust/tests/conformance/tree_utilities.rs`
- Create: `langs/rust/tests/conformance/threading.rs`

**Interfaces:**
- Produces: `ObservableList<T>`, `ObservableDictionary<K,V>`, `ServicedObservableCollection<T>`, `PagedComposition<T>`, `TokenPagedComposition<T, Token>`, `SearchableState<T>`, `ExpandableState`, `DerivedProperty<T>`, `walk`, `walk_expanded`, `find`.

- [ ] Write behavioral tests for `COL-001..031`, `COMP-028..037`, `DPROP-001..012`, `EXP-001..005`, `UTIL-001..003`, and `THR-001..004`.
- [ ] Verify red with targeted Rust tests.
- [ ] Implement collection/state/tree/threading behavior.
- [ ] Run Rust fmt, clippy, full Rust tests, and conformance coverage.
- [ ] Commit `feat(rust): implement collection and reactive conformance`.

## Task 5: Specialized VMs And Services

**Files:**
- Modify: `langs/rust/src/lib.rs`
- Create: `langs/rust/tests/conformance/localization.rs`
- Create: `langs/rust/tests/conformance/notifications.rs`
- Create: `langs/rust/tests/conformance/dialogs.rs`
- Create: `langs/rust/tests/conformance/forms.rs`
- Create: `langs/rust/tests/conformance/hierarchical_vm.rs`
- Create: `langs/rust/tests/conformance/discriminator_vm.rs`

**Interfaces:**
- Produces: `Localizer`, `NullLocalizer`, `NotificationHub`, `NullNotificationHub`, `NotificationVm`, `ConfirmationVm`, `DialogService`, `NullDialogService`, `ModalVm`, `FormVm`, `HierarchicalVm`, `HierarchicalVmBuilder`, `DiscriminatorVm`.

- [ ] Write behavioral tests for `LOC-001..003`, `NOTIF-001..017`, `DIA-001..013`, `FORM-001..023`, `HIER-001..022`, and `DISC-001..006`.
- [ ] Verify red with targeted Rust tests.
- [ ] Implement specialized VM and service behavior.
- [ ] Run Rust fmt, clippy, full Rust tests, and conformance coverage.
- [ ] Commit `feat(rust): implement specialized vm conformance`.

## Task 6: Promote Rust To Required Parity

**Files:**
- Modify: `tools/check-conformance-coverage.py`
- Modify: `.github/workflows/conformance.yml`
- Modify: `.github/workflows/rust.yml`
- Modify: `compatibility-matrix.md`
- Modify: `README.md`
- Modify: `spec/README.md`

**Interfaces:**
- Produces: Rust required in CI conformance coverage.

- [ ] Remove the generated marker-only Rust test file if any marker remains.
- [ ] Run coverage with Rust required:

```bash
uv --project langs/python run python tools/check-conformance-coverage.py \
  --require csharp --require python --require typescript --require swift --require rust
```

- [ ] Update status language from preview to full parity only after coverage passes.
- [ ] Run version/tooling tests.
- [ ] Commit `chore(rust): require rust conformance parity`.

## Task 7: Rust Examples

**Files:**
- Modify: `examples/rust/README.md`
- Modify/Create: `examples/rust/**`
- Modify: `docs/site/examples/**`
- Modify: `docs/wiki/Examples/**`

**Interfaces:**
- Produces: Rust examples that showcase the same best-fit VMx components used by other language examples.

- [ ] Expand Rust examples beyond `hello-vmx` to cover search, paging, forms, discriminator, notifications, and hierarchical composition.
- [ ] Add commands to the Rust workflow for example validation.
- [ ] Run example commands locally.
- [ ] Commit `docs(examples): add full-parity rust examples`.

## Task 8: Docs And Diagrams Across Three Surfaces

**Files:**
- Modify: `docs/site/**`
- Modify: `docs/wiki/**`
- Modify: `docs/assets/diagrams/**`
- Modify: `README.md`
- Modify: `mkdocs.yml`

**Interfaces:**
- Produces: synchronized Rust full-parity documentation and regenerated diagrams.

- [ ] Regenerate all architecture diagrams using the architecture-diagram skill.
- [ ] Ensure each diagram has `.html`, `.svg`, and high-resolution `.png`.
- [ ] Add or update Rust language tabs wherever language snippets are shown.
- [ ] Update wiki pages to include Rust in the language flavor hierarchy.
- [ ] Run:

```bash
uv --project langs/python run pytest tools/tests/test_docs_code_tabs.py tools/tests/test_docs_diagrams.py tools/tests/test_docs_wiki.py
python3 -m mkdocs build --strict
```

- [ ] Commit `docs: document rust full parity`.

## Task 9: Final Verification

**Files:**
- Verify only.

- [ ] Run Rust:

```bash
cargo fmt --manifest-path langs/rust/Cargo.toml -- --check
cargo clippy --manifest-path langs/rust/Cargo.toml --all-targets -- -D warnings
cargo test --manifest-path langs/rust/Cargo.toml
```

- [ ] Run repo tools:

```bash
uv --project langs/python run python tools/check-conformance-coverage.py \
  --require csharp --require python --require typescript --require swift --require rust
python3 tools/check-version-consistency.py
uv --project langs/python run pytest tools/tests/
python3 -m mkdocs build --strict
```

- [ ] Commit any final fixes.
- [ ] Push branch.
