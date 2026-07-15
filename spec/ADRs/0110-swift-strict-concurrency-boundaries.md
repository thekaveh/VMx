# ADR 0110 — Enforce narrow Swift strict-concurrency boundaries

**Status:** Accepted (2026-07-15)
**Spec version:** clarified in 3.22.0

## 1. Context

The Swift flavor predates complete strict-concurrency checking. Its internally
spawned tasks and `DispatchQueue` closures intentionally transfer references to
VM objects whose mutable state is already serialized by the implementation,
but those private ownership facts were invisible to the compiler. Stateless
null services also lacked explicit `Sendable` declarations, and modal results
crossed checked continuations without a type-level sendability guarantee.

Broadly declaring mutable public VM types `@unchecked Sendable` would silence
the diagnostics while falsely promising unrestricted concurrent access. It
would also make future unsynchronized state easier to introduce unnoticed.

## 2. Decision

- CI compiles the Swift package with complete strict-concurrency warnings
  promoted to errors.
- Stateless singleton services conform to `Sendable`. Null hubs that retain
  immutable Combine publisher values use a narrowly justified
  `@unchecked Sendable` conformance.
- Internally created tasks and system-dispatch closures use private unchecked
  transfer boxes. The boxes assert only that the captured reference may cross
  that specific closure boundary; they do not make a public VM type Sendable.
- Existing retention semantics remain intact: command and form tasks retain an
  admitted owner, while async-resource work keeps its pre-existing weak-owner
  behavior.
- `ModalVM.Result` and `BasicModalVM.Result` conform to `Sendable`, because the
  same value is resumed through async continuations and may cross executors.
- The public `Dispatcher` closure signature remains source-compatible. Its
  system `DispatchQueue` bridge performs the private transfer internally.

No conformance ID or spec-version bump is required. This decision strengthens
the Swift implementation and its compiler gate without changing the
language-neutral behavioral contract.

## 3. Consequences

- New Swift concurrency diagnostics fail CI instead of accumulating silently.
- Mutable public VM objects are not advertised as generally safe to transfer
  between arbitrary tasks.
- Custom modal result types must be `Sendable`; ordinary value results already
  satisfy the constraint.
- Private unchecked boundaries require focused review, but remain small and
  searchable rather than spreading unchecked conformance across the API.

## 4. Rejected alternatives

- Mark every affected VM `@unchecked Sendable`: overstates thread-safety and
  suppresses useful diagnostics for all future stored state.
- Disable strict checking for legacy files: preserves the warning debt and
  creates enforcement gaps.
- Make every dispatcher closure `@Sendable`: imposes a broad source-breaking
  public signature change when only the system bridge needs the transfer.
- Leave modal results unconstrained: permits executor-crossing values whose
  safety cannot be expressed or checked.
