# ADR 0114 — Reject invalid TypeScript paging numbers atomically

**Status:** Accepted (2026-07-15)
**Spec version:** clarified in 3.22.0
**Clarifies:** [ADR-0023](0023-paging-capability-and-paged-composition.md)

## 1. Context

The paging contract defines `PageSize` and `CurrentPageIndex` as integers.
TypeScript represents both with the wider JavaScript `number` type. Its
`PagedComposition` applied `Math.max` and range clamping without first enforcing
the integer contract, so `NaN`, infinities, and fractional values could enter
state. They then produced `NaN`/fractional page counts or invalid slice bounds.

The other flavor surfaces use integer types. This is a TypeScript admission gap,
not a new cross-flavor paging mode.

## 2. Decision

- The TypeScript `PagedComposition` constructor requires `pageSize` to be a
  finite integer.
- Its `pageSize` and `currentPageIndex` setters validate the candidate before
  mutation, re-clamping, or property notification.
- A non-finite or fractional candidate raises `RangeError`; retained paging
  state and observers remain unchanged.
- Negative finite integers preserve the established behavior: page size and
  current index clamp to zero.

This repairs the existing chapter 21 integer and COL-016 clamping contracts. It
adds no conformance ID and does not change package or specification versions.

## 3. Consequences

- Page count and slice calculations cannot inherit `NaN`, infinity, or a
  fractional offset from public paging state.
- Invalid setter calls are atomic and silent to `propertyChanged` subscribers.
- Existing callers that use integral numbers, including negative values relying
  on zero clamping, remain source- and behavior-compatible.

## 4. Rejected alternatives

- Round or truncate fractions: silently changes caller intent and makes typo-like
  input look valid.
- Clamp every non-finite value to zero: `Infinity` and `NaN` are not meaningful
  requests to disable paging or select the first page.
- Let array slicing coerce invalid state: page count and command bounds are
  already corrupted before slicing occurs.
