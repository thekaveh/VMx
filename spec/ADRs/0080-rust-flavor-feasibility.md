# ADR 0080 — Adopt Rust as a planned fifth flavor

**Status:** Accepted (2026-07-09)
**Spec version:** introduced in 3.1.0

## 1. Context

VMx currently ships four full-parity flavors: C#, Python, TypeScript, and
Swift. Each implements the same language-neutral specification with idiomatic
surface syntax and full conformance coverage.

ADR 0002 makes Rx-style hot streams the reactive primitive for the VMx message
hub, command triggers, property-change streams, and scheduler-aware delivery.
It also says that languages without a comparable Rx port require an ADR
documenting the semantic mapping before they can join.

Rust has no single dominant MVVM framework equivalent to WPF/XAML or SwiftUI +
Combine, but VMx is explicitly UI-framework-agnostic. Current Rust UI
ecosystems are sufficient to host a VMx viewmodel layer:

- Slint supports reactive property bindings, data models, and backend-handled
  callbacks.
- Ribir exposes a non-intrusive reactive data/UI model.
- Dioxus has signal-based reactive state.
- Relm4 and iced use Elm/MVU loops that can own or delegate to VMx state.
- tgui and FUI demonstrate explicit Rust MVVM-style APIs.

Rust also has reactive/eventing candidates. `rxrust` is the closest conceptual
match for ADR 0002, while `futures`, `tokio`, and `async-stream` can support
async execution and adapter layers.

## 2. Decision

Rust is accepted as a planned fifth VMx flavor, subject to the same stability
bar as every other flavor: it is not a stable flavor until it reaches full
library conformance coverage.

The Rust flavor will:

1. Live under `langs/rust/`.
1. Publish as `vmx-rs` on crates.io if the name remains available; the Rust
   crate/module namespace should still be `vmx`.
1. Use idiomatic Rust naming (`ComponentVm`, `construct`, `dispose`,
   `property_changed`) while preserving VMx concepts.
1. Represent recoverable VMx errors with `Result<T, VmxError>`, not panics.
1. Use an internal VMx reactive facade over the subset of hot-stream semantics
   required by the spec, with `rxrust` as the initial backing candidate.
1. Keep runtime-specific async scheduling behind Cargo feature flags.
1. Treat `Drop` only as best-effort cleanup; explicit `dispose()` remains the
   normative lifecycle operation.
1. Stay UI-framework-neutral in core. Slint, Ribir, Dioxus, Relm4, iced, or
   tgui integrations may appear as examples/adapters, not mandatory core
   dependencies.

## 3. Consequences

- The Rust implementation must add a conformance scraper before it can claim
  parity. CI must report Rust coverage separately and eventually require
  281/281 library IDs before Rust is marked stable.
- `spec/12-conformance.md` does not gain new IDs merely because Rust is added;
  Rust must first implement the current catalog.
- Rust-specific divergences beyond naming/idiom require ADRs, just as Swift
  divergences did.
- A future release workflow should use `rust-v<X.Y.Z>` tags and publish
  `vmx-rs` to crates.io with package verification.
- The docs must describe Rust as planned/in-progress until full conformance is
  reached.

## 4. Rejected Alternatives

### 4.1 Reject Rust because it lacks one dominant MVVM UI framework

Rejected. VMx is a UI-framework-agnostic viewmodel library, not a UI binding
framework. The existence of multiple Rust UI architectures is enough if VMx
can expose viewmodel-owned state, property/collection notifications, commands,
and message streams that adapters can consume.

### 4.2 Bind VMx Rust directly to one UI framework

Rejected. A Slint-first or Ribir-first core would make the Rust flavor less
portable than the existing flavors and would violate VMx's UI-neutral boundary.
UI examples are welcome; core dependencies are not.

### 4.3 Use only `futures::Stream` and skip Rx-style semantics

Rejected for the core contract. `futures::Stream` is useful for adapters and
async integration, but VMx needs hot, subscription-oriented, scheduler-aware
event streams and command triggers. A VMx-owned facade backed initially by
`rxrust` better preserves ADR 0002 semantics while insulating the public API
from Rust reactive-library churn.

### 4.4 Start with partial public stability

Rejected. Rust may be developed incrementally, but it must be clearly marked
experimental until it reaches the same library conformance bar as the other
active flavors.
