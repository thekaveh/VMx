# ADR 0129 — Clarify terminal stream and command teardown order

- **Status:** Accepted
- **Date:** 2026-08-02
- **Spec version:** 3.23.0

## 1. Context

The lifecycle chapter described parent disposal as finishing the parent hook,
owned resources, command teardown, and stream completion in that order. All
five catalog-complete flavors instead complete the component's terminal streams
before disposing its cached commands. Existing conformance tests protect the
terminal effects, but no contract requires commands to be torn down before the
streams complete.

The sentence was therefore an inaccurate editorial ordering claim rather than
an implementation disparity.

## 2. Decision

The lifecycle chapter describes the established order as parent hook,
owned-resource cleanup, terminal stream completion, and command teardown.
Children still finish first, every teardown step is attempted, and the first
reportable failure remains authoritative.

This clarification adds no behavior, public member, fixture transition, or
conformance ID. The spec and flavor versions therefore remain unchanged.

## 3. Consequences

The normative prose now agrees with all five implementations and their existing
disposal tests. Future changes to the relative stream/command order require a
new observable contract and cross-flavor evidence rather than relying on the
former accidental wording.

## 4. Rejected alternatives

- **Reorder all five implementations:** this would introduce a new observable
  behavior solely to match an unsupported sentence.
- **Leave the mismatch documented elsewhere:** a maintenance note cannot
  override the language-neutral specification.
