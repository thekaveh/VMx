# ADR 0069 — Add token-paged composition

**Status:** Accepted (2026-07-01)
**Spec version:** introduced in 3.1.0

## 1. Context

`PagedComposition<TVM>` models finite, index-based paging over a source whose
total count can be known or derived. It is a poor fit for forward-only APIs that
return an opaque next token and do not expose a total count. AWS-style `list_*`
operations are the canonical example: consumers accumulate loaded rows and issue
"load more" requests until the service returns no next token.

The adoption feedback also found a composition mismatch in Python and
TypeScript: finite `PagedComposition` observed `ObservableList` split streams
but not composite-style collection change streams.

## 2. Decision

Add `TokenPagedComposition<TVM,TToken>` alongside the existing finite
`PagedComposition<TVM>`.

The new primitive owns an accumulator, an opaque current token, `HasMore`,
`LoadMoreCommand`, `RefreshCommand`, property-change notification, and a coarse
reset collection-change stream. `LoadMoreCommand` fetches with the current token
and appends returned items. `RefreshCommand` fetches with the initial terminal
token and replaces the accumulator unless the refreshed first page matches the
current accumulator head according to the flavor's equality hook.

Also require finite `PagedComposition<TVM>` to observe composite-style collection
change streams in addition to observable-list split streams.

## 3. Consequences

Consumers no longer need to hand-roll a VM wrapper for next-token pagination.
Finite paging remains unchanged and remains the correct primitive for known-size
sources, page numbers, and random-access slices.

The new conformance IDs are `COL-024..COL-031`. Every supported flavor ships the
same conceptual surface with idiomatic casing and its existing async command
primitive.

## 4. Rejected alternatives

Retrofitting token semantics into `PagedComposition<TVM>` was rejected because it
would mix two incompatible models: page-index navigation over a finite source and
append-only forward pagination over an unknown total.

Adding only an adapter from `CompositeVM` to `ObservableList` was rejected as too
narrow; direct observation of composite change streams is simpler and avoids a
new adapter surface.
