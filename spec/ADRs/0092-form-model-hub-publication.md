# ADR 0092 — Publish settled FormVM model assignments on the hub

**Status:** Accepted (2026-07-11)
**Spec version:** introduced in 3.12.0
**Related:** ADR-0006, ADR-0030, ADR-0048, ADR-0087, ADR-0091, issues #89 and #128

## 1. Context

`FormVM.SetModel` is the edit path behind controlled form fields. C#, Python,
TypeScript, and Swift replaced the live model and reran validation without
publishing a model property message on the injected hub. A UI store subscribed to
that hub therefore could not observe an ordinary edit. Tableau had to wrap each
genesis edit in an application command that called both `SetModel` and a shell
refresh.

Rust was observably different rather than silent. Its `FormVm` delegates model
storage to an embedded `ComponentVm`, which published before form validation and
command state settled. That delegation also made deny publish an early `"model"`
message plus a legacy `"Model"` message, and made `reset_on_approved` publish a
model message that chapter 20 did not specify.

The portable contract therefore needs exact equality, ordering, count, deny,
reset, disposal, and re-entrancy rules rather than four additional send calls.

## 2. Decision

1. An accepted unequal `SetModel` / `set_model` call publishes exactly one model
   `PropertyChangedMessage` on the configured hub. The property name is `"Model"`
   in C# and `"model"` in Python, TypeScript, Swift, and Rust per ADR-0006.
1. The synchronous operation order is: disposal admission; null rejection where
   applicable; live-model equality; capture prior dirty/valid state; install the
   candidate; validation/error publication; approve-command invalidation; model
   hub publication. A hub observer therefore sees settled form state.
1. Equality uses the same configured or idiomatic mechanism as dirty tracking:
   `object.Equals`, `__eq__`, TypeScript/Swift `equals`, or Rust `PartialEq`. An
   equal candidate is a complete no-op and the current model instance/value is
   retained.
1. A synchronous model-message subscriber may re-enter assignment. Each accepted
   unequal call completes all state work before publishing once, and performs no
   additional state work after its send returns.
1. Deny retains its explicit pair: exactly one `FormRevertedMessage` followed by
   exactly one idiomatic model property message. Approval reset retains its
   existing outcome channels and publishes no model property message.
1. Rust adds a private silent model-replacement helper to `ComponentVm`. Public
   component assignment keeps its existing behavior; `FormVm` uses the helper to
   own notification timing for direct edits, deny, and approval reset.
1. The #141 disposal admission rule remains first. Null/default hubs retain their
   null-object behavior. Add `FORM-030` in every full-parity flavor.

## 3. Consequences

- Hub-backed view adapters observe ordinary FormVM edits without consumer-owned
  refresh wrappers, and synchronous observers see model, validation, dirty, and
  command state already consistent.
- Equal replacement objects are no longer installed or validated in the four
  standalone forms. Callers that intentionally need an equal-value republish use
  the explicit API selected by future issue #89; this ADR does not add one.
- Rust no longer leaks an early component notification from deny or approval
  reset, and its deny property name follows the Rust idiom.
- Validator exceptions keep their existing behavior. This decision does not add
  transactional rollback or a new concurrency primitive.
- The specification and stable packages advance to 3.12.0. Rust advances to
  0.12.0 while declaring minimum spec 3.12.0. The library catalog advances from
  340 to 341 IDs (346 total including five `THEME-00x` scenarios).

## 4. Rejected alternatives

- **Append a send to the four silent setters:** leaves Rust's early publication,
  deny duplication, approval-reset leak, and cross-flavor ordering divergence.
- **Refactor every FormVM onto ComponentVM inheritance/composition:** changes the
  intentional standalone edit-lifecycle architecture in four flavors and is much
  broader than the notification defect.
- **Publish before validation:** a synchronous observer can see stale errors and
  command state, and re-entrant assignment lets the outer call resume state work
  against the nested model.
