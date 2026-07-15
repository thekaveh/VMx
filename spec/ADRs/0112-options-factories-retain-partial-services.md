# ADR 0112 — Options factories retain partial service input for builder validation

**Status:** Accepted (2026-07-15)
**Spec version:** clarified in 3.22.0
**Clarifies:** [ADR-0055](0055-v3-positional-options-construction.md) and
[ADR-0079](0079-swift-phase-3-parity-completion.md)

## 1. Context

The common VM options factories accept the message hub and dispatcher as two
independent fields, then delegate construction and required-field validation to
the corresponding immutable builder. C#, Python, TypeScript, and Swift only
called the builder's paired `Services` / `services` setter when both option
fields were present. When exactly one field was supplied, the factory silently
discarded it.

That broke ADR-0055's structural guarantee that options input reaches the same
builder validation state. The defect was observable in C# and Python: supplying
only a hub incorrectly reported the hub, rather than the dispatcher, as missing.
TypeScript and Swift report the combined `services` field, so their error text
did not expose the loss, but the delegation defect was the same.

## 2. Decision

- A common VM options factory MUST retain each supplied service field
  independently until the builder performs its normal validation.
- The public fluent builder surface remains unchanged: callers still configure
  services as a pair.
- Implementations use package-internal immutable builder withers for options
  delegation. These withers are not part of the public fluent API.
- Validation order remains the builder's existing order. C# and Python identify
  the missing `Hub`/`hub` or `Dispatcher`/`dispatcher`; TypeScript and Swift
  retain their existing combined `services` error.
- Rust requires both concrete service fields in its options value, so a partial
  service tuple is not representable and needs no implementation change.

This repairs the existing BLD-006 equivalence contract. It adds no conformance
ID and does not change package or specification versions.

## 3. Consequences

- A lone service option can no longer be erased before validation.
- Missing-field diagnostics in C# and Python now identify the actual absent
  counterpart.
- Name, model, service, and children validation precedence remains unchanged.
- Complete options and fluent-builder construction produce the same VMs as
  before.

## 4. Rejected alternatives

- Add public one-service builder setters: this would expand the fluent API for
  an options-delegation implementation detail and contradict ADR-0055's promise
  that the builder surface remains unchanged.
- Pre-validate the pair in the factory: this duplicates builder validation and
  can report services before an earlier missing name or model.
- Keep discarding partial input in TypeScript and Swift because their error is
  combined: invisible data loss still violates the cross-flavor delegation
  contract and invites future drift.
