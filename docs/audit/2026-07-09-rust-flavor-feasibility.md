# VMx Rust Flavor Feasibility Report

> Historical audit record. This document captures a point-in-time review and may contain superseded paths, versions, findings, or conclusions. For current behavior, use the specification and current documentation.

> Issue: [#59](https://github.com/thekaveh/VMx/issues/59)\
> Date: 2026-07-09\
> Branch: `codex/rust-flavor-feasibility`\
> Verdict: **positive** — VMx should add Rust as the fifth full-parity flavor.

## 1. Executive Summary

Rust is a feasible and strategically useful fifth VMx flavor. The feasibility
case is positive for three reasons:

1. Rust has enough UI architectures that can consume a VMx-style viewmodel
   layer. Slint supplies declarative properties, bindings, callbacks, and data
   models; Ribir and Dioxus provide reactive state models; Relm4 and iced use
   Elm/MVU state-message-update loops that can treat VMx objects as application
   state; and tgui/FUI demonstrate explicit Rust MVVM-style APIs.
1. Rust has a credible reactive/eventing foundation. `rxrust` exists and is now
   the closest conceptual match to ADR-0002, while `futures`, `tokio`, and
   `async-stream` can cover async work, scheduling, and bridge adapters.
1. VMx is already UI-framework-agnostic. The spec explicitly keeps UI bindings
   out of core, so Rust does not need one dominant WPF-equivalent framework to
   join. It needs a stable VM layer, deterministic conformance tests, and small
   examples/adapters proving consumption by Rust UI ecosystems.

The recommended plan is to add `langs/rust/` as a first-party crate named
`vmx-rs` on crates.io, with the Rust module namespace `vmx`. The flavor should
start with the existing 281 library conformance IDs, then add a Rust flagship
example after core parity is measurable.

## 2. Current VMx Constraints

VMx is one language-neutral specification with idiomatic language surfaces. ADR
0006 allows per-language API shape as long as conceptual behavior is identical
and conformance IDs enforce parity. Rust should therefore use idiomatic
`snake_case`, `Result<T, VmxError>`, traits, builders, `Arc`/interior-mutability
where needed, and Cargo feature flags, not a literal C#/Swift surface.

ADR 0002 is the main gate. It standardizes on Rx-style hot streams for the
message hub, command triggers, and scheduler-aware delivery. It also states that
languages without an established Rx port require an ADR documenting the semantic
mapping before they join. ADR 0080 is that mapping.

The conformance catalog currently contains 281 library IDs, with C#, Python,
Swift, and TypeScript all at 281/281 coverage. Rust must not be marketed as a
stable flavor until it reaches the same conformance bar.

## 3. Rust UI Ecosystem Findings

The Rust UI ecosystem is not centered on one canonical MVVM framework. That is
not a blocker. VMx itself is UI-neutral, and the ecosystem shows several viable
ways for a Rust VM layer to be consumed.

### 3.1 Slint

Slint has a strong fit for VMx examples and adapters. Its language supports
reactive property bindings: the Slint docs state that bindings automatically
track dependencies and that properties can be `in`, `out`, or `in-out`
([Slint properties](https://docs.slint.dev/latest/docs/slint/guide/language/coding/properties/)).
Slint callbacks are explicitly designed to be handled by backend code, including
Rust
([Slint functions and callbacks](https://docs.slint.dev/latest/docs/slint/guide/language/coding/functions-and-callbacks/)).
Slint also has repeated elements over arrays/models
([Slint repetition and data models](https://docs.slint.dev/latest/docs/slint/guide/language/coding/repetition-and-data-models/)).

VMx Rust can expose adapters that translate VMx property-change and collection
messages into Slint `Model`/property updates without making Slint a core
dependency.

### 3.2 Ribir

Ribir is unusually aligned with VMx's separation goals. Its introduction says
the UI is a "re-description of data interaction" that responds to data
modifications, and it emphasizes no extra UI-specific state, notification
mechanisms, inheritance, or pre-constraints
([Ribir introduction](https://ribir.org/docs/introduction/)). The README
describes direct UI over data APIs and precise UI updates from mutations
([Ribir GitHub README](https://github.com/RibirX/Ribir)).

This makes Ribir a good candidate for an advanced example where a VMx viewmodel
is the application data API and Ribir observes/adapts it.

### 3.3 Dioxus

Dioxus is not MVVM, but it is reactive enough to host VMx. Dioxus 0.7 docs state
that UI is a function of current state and that signals are a single source of
mutable state with automatic dependency tracking
([Dioxus signals](https://dioxuslabs.com/learn/0.7/essentials/basics/signals/)).
The adapter direction is to bridge VMx property/collection/message streams into
Dioxus `Signal` updates.

### 3.4 Relm4 and iced

Relm4 and iced are better described as Elm/MVU than MVVM. Relm4 advertises the
Elm programming model, async background tasks, modular components, and GTK-backed
native apps ([Relm4](https://relm4.org/)). iced says it embraces The Elm
Architecture with state, messages, update logic, and view logic; its own docs
emphasize that state/update logic can be tested without GUI code
([iced first steps](https://book.iced.rs/first-steps.html)).

These ecosystems still support the VMx thesis: a VMx Rust object can be the
state/model that an Elm-style update loop owns or delegates to. VMx should not
pretend iced/Relm4 are MVVM frameworks, but they strengthen the case that Rust
apps can cleanly separate UI rendering from stateful application logic.

### 3.5 Explicit Rust MVVM Efforts

Two smaller crates are direct evidence that MVVM concepts are viable in Rust:

- `tgui` documents itself as a GPU-accelerated Rust GUI framework built around a
  small MVVM-style API with `ViewModelContext`, reactive `State`, derived
  `Signal`, and `Command` types
  ([tgui docs.rs](https://docs.rs/tgui/latest/tgui/)).
- `fui_core` is published as an MVVM Rust UI framework library
  ([fui_core crates.io](https://crates.io/crates/fui_core)).

These are not recommended as VMx dependencies; they are evidence that Rust's
type system and ownership model can represent viewmodel-like APIs.

## 4. Reactive Mapping

The positive mapping is:

- Core stream abstraction: `rxrust` for hot observable-like streams, subjects,
  subscriptions, and operator-style composition.
- Async execution: `tokio` or `async-executor` only behind optional feature
  flags; the core should avoid forcing one runtime until tests prove it is
  necessary.
- Future compatibility: expose a thin VMx-owned facade over the subset required
  by conformance tests so the flavor can migrate if Rust reactive libraries
  churn.
- Scheduling: start with deterministic immediate/current-thread and background
  dispatchers for tests; add runtime-backed dispatchers behind features.

The facade is important. Rust reactive crates are less settled than
System.Reactive, reactivex, rxjs, or Combine. VMx should depend conceptually on
hot stream semantics, not leak every `rxrust` type into public constructors.

## 5. Proposed Rust API Shape

The Rust flavor should be named:

- crate: `vmx-rs` (the `vmx` crate is already taken on crates.io)
- crate import/module: `vmx`
- source root: `langs/rust/`
- package version: independent SemVer, starting at the first released VMx Rust
  version
- minimum Rust version: propose MSRV 1.82+ initially, to be verified during
  scaffolding

Conceptual API mapping:

| VMx concept                | Rust shape                                                                           |
| -------------------------- | ------------------------------------------------------------------------------------ |
| `ComponentVM<TModel>`      | `ComponentVm<TModel>` struct                                                         |
| readonly modeled component | `ReadonlyComponentVm<TModel>`                                                        |
| lifecycle state            | `ConstructionStatus` enum                                                            |
| errors                     | `VmxError` enum + `type VmxResult<T> = Result<T, VmxError>`                          |
| message hub                | `MessageHub` with typed subscribe/filter helpers                                     |
| property changed           | `PropertyChangedMessage { property_name: &'static str / Cow<'static, str> }`         |
| commands                   | `RelayCommand`, `RelayCommand<T>`, async variants gated by async feature             |
| builders                   | owned immutable-ish builders using consuming `self` fluent methods                   |
| composite/group/aggregate  | structs using `Arc<dyn ViewModel>` or typed generic variants                         |
| disposal                   | explicit `dispose()` plus `Drop` as best-effort cleanup, never normative replacement |

Rust should prefer explicit results over panics. Panics are reserved for bugs or
impossible internal states. VMx lifecycle and builder validation errors should
return `Result`.

## 6. Implementation Roadmap

### Phase 0 — Feasibility and Decision

- Land this report and ADR 0080.
- Create follow-up implementation issues.
- Decide exact crate name and MSRV before publishing any crate.

### Phase 1 — Crate Scaffold and Tooling

- Add `langs/rust/Cargo.toml`, workspace configuration if needed, `src/lib.rs`,
  README, CHANGELOG, and RELEASING.
- Add GitHub Actions for `cargo fmt`, `cargo clippy`, `cargo test`, and docs.
- Add a Rust scraper to `tools/check-conformance-coverage.py` recognizing
  `// XXX-NNN` or `#[vmx_conformance("XXX-NNN")]` markers.
- Add crate version and spec-version exports.

### Phase 2 — Foundation Primitives

- Lifecycle, dispatcher, message hub, property-change helpers, null services.
- Conformance: LIFE, HUB, PROP, NULL, THR basics.

### Phase 3 — Commands and Components

- Relay commands, async commands, modeled/readonly components, builders.
- Conformance: CMD, CVM, BLD, CMDD as applicable.

### Phase 4 — Containers and Collections

- Composite, group, aggregate, forwarding, serviced collections,
  observable list/dictionary, pagination.
- Conformance: COMP, GRP, AGG, FWD, COL.

### Phase 5 — Specialized VMs

- DerivedProperty, capabilities, localization, hierarchical, dialogs, forms,
  notifications, DiscriminatorVM.
- Conformance: DPROP, CAP, LOC, HIER, DIA, FORM, NOTIF, DISC.

### Phase 6 — Examples and Release Channel

- Add a Rust example suite. Start with CLI/headless examples, then add one
  UI-backed example using Slint or Ribir.
- Add crates.io release workflow (`rust-v*` tags), package verification, and
  public docs.

## 7. Risks and Mitigations

| Risk                                  | Mitigation                                                                      |
| ------------------------------------- | ------------------------------------------------------------------------------- |
| Rust reactive crates churn            | Keep VMx-owned facade over required hot-stream semantics.                       |
| Lifetimes make tree ownership awkward | Use `Arc`, `Weak`, and explicit parent handles; avoid self-referential structs. |
| Async runtime fragmentation           | Keep runtime-backed scheduling behind features; test immediate scheduler first. |
| UI frameworks are not uniformly MVVM  | Keep core UI-neutral and provide adapters/examples, not hard dependencies.      |
| Crate name `vmx` unavailable          | Publish `vmx-rs`; keep Rust module namespace `vmx`.                             |
| Full parity is large                  | Gate public stability on conformance coverage; use ratcheted phases.            |

## 8. Acceptance Criteria Satisfaction

- **Written feasibility report:** this document.
- **Reactive strategy comparison:** §4 compares `rxrust` plus facade against
  runtime-native async primitives.
- **ADR:** ADR 0080 records the semantic mapping.
- **Public API conventions:** §5 defines naming, errors, ownership direction,
  builders, disposal, and crate naming.
- **Crate/package plan:** §5 and §6 define crate name, layout, MSRV proposal,
  CI, docs, and release direction.
- **Conformance strategy:** §6 phases conformance IDs and requires scraper
  support before stability.
- **Follow-up issues:** listed in §9 for creation after this decision lands.

## 9. Follow-up Issues Created

1. [#60 — Scaffold Rust VMx crate and CI](https://github.com/thekaveh/VMx/issues/60).
1. [#61 — Add Rust conformance coverage tooling](https://github.com/thekaveh/VMx/issues/61).
1. [#62 — Implement Rust lifecycle, dispatcher, and message foundations](https://github.com/thekaveh/VMx/issues/62).
1. [#63 — Implement Rust commands, components, and builders](https://github.com/thekaveh/VMx/issues/63).
1. [#64 — Implement Rust containers and collections](https://github.com/thekaveh/VMx/issues/64).
1. [#65 — Implement Rust specialized VMs and services](https://github.com/thekaveh/VMx/issues/65).
1. [#66 — Add Rust examples and UI adapter spike](https://github.com/thekaveh/VMx/issues/66).
1. [#67 — Add crates.io release channel for vmx-rs](https://github.com/thekaveh/VMx/issues/67).

## 10. Final Recommendation

Proceed. Rust should become VMx's fifth full-parity language flavor, with the
first public stability milestone defined as 281/281 library conformance coverage
and a working Rust example that demonstrates VMx as a UI-framework-neutral
viewmodel layer.
