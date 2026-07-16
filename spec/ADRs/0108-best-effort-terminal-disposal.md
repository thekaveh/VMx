# ADR 0108 — Complete terminal disposal before propagating errors

**Status:** Accepted (2026-07-14)
**Spec version:** introduced in 3.22.0

## 1. Context

The lifecycle contract requires a parent to dispose every child depth-first,
but some TypeScript and Rust container loops returned or threw as soon as one
child failed. TypeScript also let a throwing subclass disposal hook skip base
command and stream teardown. The VM was already terminal, so retrying could not
reliably reach the skipped work.

C# and Python already preserve the first failure while finishing the cascade,
and Swift's non-throwing public disposal surface completes every child. The
language-neutral contract needs to make that terminal behavior explicit.

## 2. Decision

Once a VM claims disposal, teardown is best-effort and non-abortable. A parent
disposes every child in deterministic depth-first order and then performs its
own subclass hook, owned-resource cleanup, command teardown, and stream
completion even when an earlier step fails.

Throwing/result-based flavors preserve the first failure in execution order,
finish all remaining mandatory teardown, and then propagate that original
failure. Later failures do not replace it. Existing owned-resource cleanup
remains independently swallowed as specified in chapter 02 §2.3. Non-throwing
flavors keep their non-throwing surface while still completing the cascade.

Repeated or re-entrant disposal remains a no-op after the first terminal claim;
it is not a retry mechanism for skipped teardown.

## 3. Consequences

- One faulty child cannot strand its siblings or parent resources.
- A faulty subclass hook cannot leave base commands or streams active.
- Callers still receive the earliest actionable failure where the flavor can
  report one.
- Disposal order remains depth-first: descendants, children, then parent.

## 4. Rejected alternatives

- Stop at the first failure: leaves terminal objects partially live and makes
  the idempotent retry a no-op.
- Swallow every failure: hides actionable teardown defects in flavors whose
  disposal APIs already report errors.
- Aggregate all failures into a new wrapper: loses the original error identity
  and changes established public error surfaces.
