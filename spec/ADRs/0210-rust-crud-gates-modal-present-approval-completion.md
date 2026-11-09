# ADR 0210 — Rust CRUD confirmation gates, modal presentation and approval completion

- **Status:** Accepted
- **Date:** 2026-11-09
- **Spec version:** 3.30.0 (amends the Rust notes in chapter 06 §7 and chapter
  19 §2.1; chapter 20 §10 is unchanged)

## 1. Context

Three Rust surfaces lacked a signal or a gate that the other four flavors
have.

- **Modeled CRUD gates (#1258).** Chapter 06 §7 gives `ModeledCrudCommands`
  optional `confirm_update` and `confirm_delete` async delegates. A supplied
  delegate wraps the command in a `ConfirmationDecoratorCommand`. Rust had no
  Update gate. Its `with_confirm_delete` constructor took a synchronous
  `Fn() -> bool` inside a plain `RelayCommand` and accepted no
  `current_changed` trigger. `with_current_changed` took the trigger but no
  gate. The Update and Delete accessors returned `RelayCommand`.
- **Modal presentation (#1267).** Chapter 19 §2.1 defines `Present` as the
  fifth dialog-service method. Python and Swift put it on the service with a
  default that dismisses the modal with its cancellation result. C# and
  TypeScript add the `IModalDialogService` extension interface. In Rust, only
  `NullDialogService` had `present`, as an inherent method. Code that is
  generic over `DialogService` could not call it.
- **Approval completion (#1270).** Chapter 20 §10 requires `Dispose()` to
  complete `OnApproved`. Rust `FormVm::subscribe_approved` (ADR-0139) takes
  only an approval callback, so a subscriber got no signal when the form was
  disposed. `errors_changed()` and `approve_errors()` already complete through
  `MessageHub::subscribe_with_completion`.

## 2. Decision

Decided under the owner's 2026-11-07 delegation. Each choice is the simplest
one that matches the other flavors.

### 2.1. `ModeledCrudCommands`

- A new constructor, `ModeledCrudCommands::with_options`, takes the four
  actions, an optional `confirm_update` gate, an optional `confirm_delete`
  gate, and an optional `current_changed` trigger. Each gate is a
  `Fn() -> AsyncValue<bool>`, the gate type of `ConfirmationDecoratorCommand`.
  This matches the one C# constructor and the one Swift initializer. The
  `NO_CONFIRM` constant names an absent gate without a type annotation, as
  `NO_HOOK` does for `wrap_with`.
- A supplied gate wraps that command in a
  `ConfirmationDecoratorCommand<RelayCommand>`. The trigger sends on the inner
  relay's `can_execute_changed` hub. The decorator returns that hub, so a
  trigger message also reaches the subscribers of a gated command.
- `update_current_command()` and `delete_current_command()` return
  `Arc<dyn Command>`, the Rust form of the `ICommand` that the other flavors
  return. A gated command is awaitable through `Command::as_async`. An ungated
  command is the plain relay, so its `execute()` stays synchronous.
  `create_new_command()` still returns `RelayCommand`.
- `new` and `with_current_changed` stay and call `with_options` with no gates.
  `with_confirm_delete` is removed: its synchronous gate is the divergence
  that this ADR closes. Code that used it passes
  `Some(move || AsyncValue::ready(confirm()))` as `confirm_delete`.

### 2.2. `DialogService::present`

- `DialogService` gains a provided method
  `fn present<T: Clone + Send + 'static>(&self, modal: &ModalVm<T>) -> AsyncValue<T> where Self: Sized`.
  This follows the Python and Swift model. The default dismisses the modal
  with its cancellation result and returns its completion, so an
  already-dismissed modal keeps its first result. A host adapter overrides it
  to show the modal and dismiss it with the user's choice.
- Effect on trait objects: the `where Self: Sized` bound keeps
  `DialogService` dyn-compatible. `Box<dyn DialogService>` and
  `Arc<dyn DialogService>` keep working for the other four methods, and every
  existing implementation compiles without a `present` of its own. `present`
  cannot be called through `dyn DialogService`, because a generic method
  cannot be dispatched dynamically. Code that presents modals holds a
  concrete or generic service type. An extension trait, the C# and
  TypeScript model, would have the same restriction and one more name.
- `NullDialogService::present` stays as an inherent method that calls the
  trait default, so a call without the trait in scope still compiles.

### 2.3. `FormVm::subscribe_approved_with_completion`

- A new additive method, `subscribe_approved_with_completion(on_approved, on_completed)`, returns an `ApprovalSubscription`. `subscribe_approved`
  keeps its signature, and the deprecated `on_approved` gets no completion.
- The completion rules follow `MessageHub::subscribe_with_completion`.
  Disposal calls `on_completed` once, in registration order, after the form
  disposes its `errors_changed()` and `approve_errors()` hubs, with no form
  lock held. A repeated `dispose()` calls nothing. A subscription made on a
  disposed form calls `on_completed` at once, never calls `on_approved`, and
  returns an inactive handle. A handle detached before disposal releases both
  callbacks, and `on_completed` never runs.
- A panic in `on_completed` is contained, as a hub completion panic is, so
  disposal still completes the other subscribers. ADR-0139 still holds: a
  panic in `on_approved` propagates out of `approve`.
- The registry is closed before any completion runs. A completion that
  subscribes again on the same form therefore gets an inactive handle, and
  its own completion runs at once.

## 3. Consequences

- Breaking for Rust: the Update and Delete accessors of `ModeledCrudCommands`
  return `Arc<dyn Command>` instead of `RelayCommand`, and
  `with_confirm_delete` is removed. The Rust CHANGELOG records the migration.
- Additive for Rust: `ModeledCrudCommands::with_options`, `NO_CONFIRM`,
  `DialogService::present`, and `FormVm::subscribe_approved_with_completion`.
- Chapter 06 §7 names `with_options` and drops its "Open Rust gap" paragraph.
  Chapter 19 §2.1 replaces its "Open Rust gap" paragraph with the Rust
  contract. The Rust capability parity ledger closes its §12.4.7 CRUD item
  and §12.9. The FormVM docs page and the disposal contract describe the Rust
  approval completion.
- The Rust `COMP-024`, `DIA-009` and `DIA-010` tests await a gate or present
  through the trait. No conformance ID is added.
- C#, Python, TypeScript and Swift do not change.
