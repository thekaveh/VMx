# ADR 0093 — Add explicit modeled-component republish

**Status:** Accepted (2026-07-11)
**Spec version:** introduced in 3.13.0
**Related:** ADR-0006, ADR-0040, ADR-0082, ADR-0083, ADR-0091, ADR-0092, issue #89

## 1. Context

Modeled-component assignment intentionally suppresses an equal candidate. That
guard prevents redundant work, but it also leaves no explicit way to announce
that observable state reachable through the retained model changed outside the
assignment path.

DayDreams stores a streamed height field outside its cell model and deliberately
uses the cell model notification to repaint renderer adapters. Its
`setHeightField` path creates a shallow model copy solely to defeat TypeScript
reference equality. The allocation represents publication intent as a fake
replacement and can silently stop working if equality semantics change.

The verified evidence is limited to that one site. `applyManifestDelta` creates
genuinely changed model content and remains an ordinary assignment. A proposed
`DerivedProperty` comparator is a separate concern and is not part of this
decision.

## 2. Decision

1. Add one dedicated modeled-component operation: `RepublishModel()` in C#,
   `republish_model()` in Python and Rust, and `republishModel()` in TypeScript
   and Swift.
1. Expose it on writable and read-only modeled leaf components. Forwarding
   modeled components delegate it to the wrapped component. Do not add it to
   non-modeled components, modeled composites, `FormVM`, or `DerivedProperty`.
1. One admitted call retains the exact model reference/value and cached modeled
   hint. It performs no equality check, assignment, hint recomputation, or
   `OnModelChanged` callback.
1. The operation invokes the chapter 05 dual-channel helper exactly once for
   the idiomatic model property name: `"Model"` in C# and `"model"` elsewhere.
   An ordinary top-level call therefore publishes one hub message before one
   local notification. A null/default hub keeps its null-object behavior while
   the local channel still emits once.
1. The existing helper owns lifecycle admission and re-entrant delivery. A call
   beginning after disposal is inert. A call admitted before re-entrant disposal
   completes its pair. A republish requested by a hub subscriber joins the
   lossless iterative queue and follows chapter 05 §2.3 ordering without a new
   recursive or global-order rule.
1. Read-only describes replacement authority, not deep immutability of a
   referenced object. Republish does not add a setter or recompute the stable
   modeled hint. Forwarding preserves the wrapped sender, hub, local stream, and
   disposal boundary.
1. Add `CVM-010` in all five full-parity flavors.

## 3. Consequences

- Consumers can state publication intent without allocating equality-defeating
  model copies.
- Ordinary equal assignment remains silent and ordinary unequal assignment
  retains its existing model/hint/callback behavior.
- The API is intentionally sharp: callers use it only when observable state
  reachable through the retained model changed outside ordinary replacement.
  It must not conceal a replacement or mutation that belongs in the assignment
  path.
- `FormVM` keeps its separate settled edit transaction from ADR-0092. A future
  form-specific republish would require evidence and explicit validation,
  dirty-state, command, deny, and reset semantics.
- The specification and stable packages advance to 3.13.0. Rust advances to
  0.13.0 while declaring minimum spec 3.13.0. The library catalog advances from
  341 to 342 IDs (347 total including five `THEME-00x` scenarios).

## 4. Rejected alternatives

- **Force option on assignment:** property setters cannot carry the option
  consistently, and a forced set obscures whether it installs the candidate,
  recomputes the hint, or invokes callbacks.
- **Generic `touch(property)`:** a public string escape hatch could claim
  changes for arbitrary or nonexistent properties and is broader than the sole
  verified model use case.
- **Continue allocating equal copies:** retains a silent, equality-dependent
  consumer idiom and represents notification as replacement.
- **Include FormVM now:** expands one renderer-driven component operation into a
  distinct validation and command transaction without supporting consumer
  evidence.
