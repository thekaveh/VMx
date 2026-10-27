# ADR 0158 — The `Current(selector)` hook runs on every construct

- **Status:** Accepted
- **Date:** 2026-10-27
- **Spec version:** 3.30.0 (clarification)

## 1. Context

Chapter 06 §3.2 said that the composite invokes `Current(selector)` "once during
the composite's construct phase". `COMP-025` tested one construct only.

All five flavors call the selector from the construct path, after the children
settle. A later construct calls it again, and so does the construct phase of
`reconstruct()`. Destruct sets `Current` to `null` first (§5, `COMP-005`), so
the selector chooses `Current` again on each construct.

A consumer cannot rely on behavior that the spec does not state. The Heimdall
plan (#649) records a consumer that accepts a null current page after every
reconstruct for this reason (#654).

## 2. Decision

- §3.2 says that the selector runs during every construct phase, including the
  construct phase of `reconstruct()`. It runs after all children reach
  `Constructed` and before the composite reaches `Constructed`.
- §3.2 says that destruct reports `null` to `OnCurrentChanged`. A selector that
  returns the last non-null value that `OnCurrentChanged` received restores
  that child after a destruct, if the composite still contains it.
- `COMP-025` adds two checks. After a select, `destruct()` and `construct()`,
  the selector has run twice and has selected again. After `reconstruct()`, it
  has run three times and has selected again.

## 3. Consequences

- The text matches the behavior of every flavor. No behavior changes.
- No conformance ID is added. The `COMP-025` tests of all five flavors check the
  two new clauses.
- The restore-the-last-child recipe is documented through #659.
