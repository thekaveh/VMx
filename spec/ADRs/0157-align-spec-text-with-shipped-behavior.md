# ADR 0157 — Align spec text with shipped behavior and CI

- **Status:** Accepted
- **Date:** 2026-10-26
- **Spec version:** 3.30.0 (clarification)

## 1. Context

#556, #614 and #636 changed rules but left older text in place (#787).

- Chapters 05 and 06 said that a trigger makes a command re-evaluate its
  predicate. Chapter 04 §4 says that a trigger raises `CanExecuteChanged` and
  that consumers re-read `CanExecute`. The command does not evaluate its
  predicate itself.
- Chapter 19 said that null `Present` always resolves with the modal's
  cancellation result. Every flavor dismisses the modal with that result, and
  the first result wins. So a modal that is already dismissed keeps its earlier
  result, and null `Present` returns that result.

The catalog, three ADRs, the ADR registry and the modal page had the same kind
of drift.

## 2. Decision

- Chapters 05 and 06 say that a trigger raises `CanExecuteChanged` and that
  consumers re-read `CanExecute`, as chapter 04 §4 says.
- Chapter 19 §3, the §4 table and the DIA-010 line give the null `Present`
  rule: an undismissed modal resolves with `cancellationResult`, and an
  already-dismissed modal keeps its result. Catalog DIA-010 and the modal page
  say the same.
- The catalog §20 and §21 headings cover `COMP-014..045` and `GRP-007..013`.
  The §18 intro records `CMDD-014..CMDD-017` (spec v3.29, ADR-0145).
- FORM-013 lists only Rust as a flavor that exposes the form's hub.
- ADR-0134 §2 item 7 lists Swift with the wrappers that hold their own
  subscriptions and release them at disposal.
- ADR-0069 and ADR-0024 record their amendments by ADR-0136 and ADR-0142, in
  the status line, an Amendments entry and the registry row.
- The ADR registry lists `spec/HISTORY.md` with the other exempt paths, as
  `spec-discipline.yml` does.

## 3. Consequences

- The text matches the behavior of every flavor and CI. No behavior changes.
- No conformance ID is added or removed. C#, Python, TypeScript and Swift
  already test the already-dismissed case, under DIA-012. Rust gets a DIA-010
  test for it.
