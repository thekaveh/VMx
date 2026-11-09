# ADR 0206 — Rust public-surface parity for hints, builders, expansion and localization

- **Status:** Accepted
- **Date:** 2026-11-09
- **Spec version:** 3.30.0 (removes the Rust gap notes in chapter 01 §1.3,
  chapter 05 §3.1, §3.2 and §8, chapter 10 §4 and chapter 17 §2)

## 1. Context

The spec recorded six Rust public-surface differences as open gaps. C#,
Python, TypeScript and Swift already follow the spec for each one.

1. `Hint` and `ModeledHint` are strings with an empty-string default (chapter
   01 §1.3, chapter 05 §3.1, chapter 10 §4). Rust typed every `hint()` and
   `modeled_hint()` accessor as `Option<String>`. The direct constructors left
   `hint()` as `None`, and the default hinter returned `None` (#1251).
1. The builder accepts an `OnModelChanged` callback that runs after an accepted
   model change (chapter 05 §3.2). The Rust `ComponentVmBuilder` and
   `ComponentVmOptions` had no such callback (#1252).
1. `ModeledCompositeVmBuilder` had no `hint` setter, and `ModeledCompositeVm`
   had no inherent `name()`, `hint()` or `id()`. An unmodeled
   `ComponentVm<()>` builder required `.model(())`, although chapter 10 §3
   requires only `Name` and `Services` (#1253).
1. `ExpandableState.IsExpandedChanged` is an `Observable<bool>` (chapter 05
   §8). Rust had only the `expanded_changed()` hub, whose `Message::Custom`
   carries the new value as the message name `"true"` or `"false"` (#1254).
1. `ILocalizer` has an optional `Localize(key, args)` form (chapter 17 §1).
   The Rust `Localizer` trait had only `localize(key)` (#1266).
1. Chapter 10 §3 lists `Services(IMessageHub, IDispatcher)` for the hierarchy
   builder. Rust `HierarchicalVmBuilder::services` accepted only
   `NullDispatcher` and discarded it. The other Rust builders accept any
   `Dispatcher` (#1268).

Rust 0.36.0 is unreleased, so breaking Rust signature changes are allowed with
a CHANGELOG note.

## 2. Decision

Decided under the owner's 2026-11-07 delegation: Rust takes the spec shape for
each item. Where Rust needs a different name, it takes the simplest name that
matches an existing Rust precedent.

1. **String hints.** Every public `hint()` and `modeled_hint()` accessor
   returns `String`. A new component core starts with an empty hint, so every
   direct constructor reports `""`. The default hinter returns `""`.
   `with_model_hint` and both builder `model_hint` setters take
   `Fn(&M) -> String`. `ForwardingComponentVm::with_hint_override` takes
   `Fn() -> String`. Optional `hint` inputs on builders and options structs stay
   `Option<String>`, because they mean "not set".
1. **`on_model_changed`.** `ComponentVmBuilder::on_model_changed(Fn(&M))` and
   the optional `ComponentVmOptions::on_model_changed` field (type
   `ModelChangedCallback<M>`, an `Arc<dyn Fn(&M) + Send + Sync>`) install the
   callback. `set_model` calls it last with the accepted model, after the
   `model` notification and any `modeled_hint` notification. An equal
   assignment, an assignment after disposal and `republish_model()` do not
   call it. The read-only builder has no setter, because a read-only component
   does not replace its model.
1. **Modeled composite and unmodeled builder.** `ModeledCompositeVmBuilder`
   gains `hint(...)`, with the `CompositeVmBuilder` default `""`.
   `ModeledCompositeVm` gains inherent `id()`, `name()` and `hint()`, which
   delegate to the inner composite. `ComponentVmBuilder::build()` supplies the
   model `()` when `M` is `()` and no model was set, so an unmodeled builder
   needs only `name` and `services`. A missing hub then reports
   `hub is required`. `ReadonlyComponentVmBuilder` wraps
   `ComponentVmBuilder`, so the same fallback applies to a
   `ReadonlyComponentVm<()>` builder.
1. **Typed expansion stream.** `ExpandableState::expansion_changes()` returns a
   hot `ValueStream<bool>`. It sends the new value once per effective change,
   before the hub message, and does not replay the current value to a new
   subscriber. When a newer change commits before an older one publishes, the
   older value is skipped, as in `DiscriminatorVm::active_key_changes()`.
   `dispose()` completes it. The `expanded_changed()` hub stays, because the
   expansion commands use it as their trigger (ADR-0159). The name follows the
   `active_key_changes()` precedent; `is_expanded_changed` would sit beside
   `expanded_changed()` and be easy to confuse with it.
1. **Localizer args form.** The `Localizer` trait gains
   `localize_with_args(&self, key: &str, args: &[&dyn Display]) -> String`.
   Rust has no overloading, so the args form needs its own name. A slice of
   `&dyn Display` keeps the trait object-safe and accepts any positional
   value that can be formatted. The default implementation ignores `args` and
   returns `localize(key)`, so existing implementors compile unchanged and
   `NullLocalizer` returns the key for both forms.
1. **Hierarchy dispatcher.** `HierarchicalVmBuilder::services` accepts any
   `D: Dispatcher`. The built hierarchy keeps only the hub and drops the
   dispatcher, because it runs no dispatched work and has no background option.
   Every node keeps using `NullDispatcher`. ADR-0009 records this difference
   from C#, whose `HierarchicalVM` passes the dispatcher to its base class.

## 3. Consequences

- The Rust gap notes in chapter 01 §1.3, chapter 05 §3.1 and §3.2, chapter 10
  §4 and chapter 17 §2 are removed. Chapter 05 §8 names the Rust typed stream,
  and chapter 17 §1 names the Rust args method.
- Rust callers that compared hints with `Some(...)` or returned `Option<String>`
  from a hinter must use `String`. Callers that build `ComponentVmOptions` with
  a struct literal must set `on_model_changed`. Both are breaking changes in the
  Rust 0.36.0 CHANGELOG.
- Existing `HierarchicalVmBuilder::services(hub, NullDispatcher::new())` and
  `.model(())` calls compile unchanged.
- No conformance ID is added. Focused Rust tests cover each item, and the Rust
  `CVM-003`, `CVM-004`, `CVM-010`, `EXP-002` and `EXP-003` tests assert the new
  shapes.

## 4. Rejected alternatives

- **Keep `Option<String>` and default to `Some("")`.** It keeps a `None` state
  that the spec does not have, and every caller still unwraps.
- **A dispatcher type parameter on `HierarchicalVm`.** It changes every
  hierarchy type for a value that the hierarchy never uses.
- **A `Default` bound for the unmodeled builder.** It would also default other
  `Default` models silently, while chapter 10 §3 requires a model source for
  modeled components.
- **Carry the boolean on the hub message.** `Message::Custom` has no payload
  field; #673 tracks application message payloads.
