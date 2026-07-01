# ADR 0071 — Add declarative FormVM validation

**Status:** Accepted (2026-07-01)
**Spec version:** introduced in 3.1.0

## 1. Context

`FormVM<TM>` already owns the edit lifecycle that determines whether saving is
allowed, but consumers had to rebuild the same validation/error-map plumbing next
to every form. The aws-tui adoption feedback identified this as a recurring gap:
forms need field errors, model-level errors, an `IsValid` gate, and change
notifications without adopting a larger persistence or schema framework.

ADR-0051 intentionally deferred a first-class validation surface during the v3
reconciliation. The downstream usage is now concrete enough to add a small,
cross-flavor contract.

## 2. Decision

Add optional declarative validation to `FormVM<TM>` in every supported flavor:

- field validators keyed by idiomatic field/property name;
- one model-level validator returning a field-name keyed error map;
- `Errors`, `IsValid`, `ErrorsChanged`, and `FieldError(field)`;
- approve gating on `IsValid`, regardless of strict mode;
- `ApproveAsync` no-ops while invalid and does not invoke the persister;
- builder methods for registering validators immutably.

Validation runs at construction, after `SetModel`, and after `DenyCommand`
reverts the model. `ErrorsChanged` emits only when the effective error map
changes.

## 3. Consequences

The common field-error/save-gating pattern is now library-provided while still
remaining opt-in. Existing callers that do not pass validators continue to see an
empty error map and `IsValid == true`.

This does not replace richer UI state composition with `DerivedProperty<T>` or
consumer-owned validation services. It only standardizes the form lifecycle's
minimal validity contract.

## 4. Rejected alternatives

Adding a generic `IValidator<T>` service was rejected as heavier than the current
need and harder to keep idiomatic across all four flavors.

Keeping validation entirely outside `FormVM<TM>` was rejected because approval
gating and field-error notification are lifecycle behavior already owned by the
form.
