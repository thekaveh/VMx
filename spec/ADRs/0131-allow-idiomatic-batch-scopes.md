# ADR 0131 — Allow idiomatic batch scopes

**Status:** Accepted (2026-08-02)
**Spec version:** introduced in 3.23.0

## 1. Context

The composite and group chapters described batching exclusively as a returned
disposable or context-manager handle. That accurately described C#, Python,
TypeScript, and Swift, but not Rust's established callback-scoped
`batch_update` API. Rust already satisfied the observable conformance contract:
nested mutations are suppressed, the outermost scope emits at most one reset,
and panic unwinding restores batch state before resuming the panic.

The overly concrete wording made an accepted idiomatic API look
non-conforming even though no observable behavior differed.

## 2. Decision

The normative batch contract permits either:

1. a returned disposable or context-manager handle; or
1. a callback-taking API whose callback invocation defines the batch scope.

Both forms MUST preserve nested suppression, emit at most one reset when the
outermost dirty scope exits, emit nothing for a clean scope, restore batch
state during exception or panic unwinding, and then propagate the original
failure according to the language's normal error model.

`COMP-013` and `GRP-006` remain the stable conformance IDs. Their wording now
describes both scope shapes; no catalog behavior or implementation changes.

## 3. Consequences

- Rust's callback API is explicitly conforming without introducing an
  ownership-hostile borrowed disposable.
- Handle-based flavors retain their existing public APIs and behavior.
- Cross-flavor audits compare observable scope semantics rather than requiring
  one resource-management syntax in every language.

## 4. Rejected alternatives

Requiring Rust to return a disposable handle was rejected because it would add
lifetime and misuse hazards without strengthening the observable contract.
