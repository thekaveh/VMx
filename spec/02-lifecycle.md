# 02 — Lifecycle state machine

Every viewmodel has a `Status` of type `ConstructionStatus`. The state machine is
defined here normatively and encoded in `fixtures/lifecycle-transitions.json` so
every language's conformance tests can load the same table.

## States

```
Disposed     ← terminal; once entered, cannot leave
Destructing  ← transient; during destruct()
Destructed   ← initial state of a freshly built VM
Constructing ← transient; during construct()
Constructed  ← ready-to-use state
```

`IsConstructed` is defined as `Status == Constructed`. This is normative.

## Operations

A VM exposes four lifecycle operations (rendered per language as
`construct/destruct/reconstruct/dispose` or `Construct/Destruct/Reconstruct/Dispose`):

- `construct()` — moves `Destructed → Constructing → Constructed`.
- `destruct()` — moves `Constructed → Destructing → Destructed`.
- `reconstruct()` — equivalent to `destruct()` followed by `construct()`.
- `dispose()` — moves to `Disposed` from any state. Terminal.

Each operation MAY be invoked synchronously or asynchronously. When invoked
asynchronously, the operation completes when the final state is reached. Subscribers
to the message hub observe two `ConstructionStatusChangedMessage` emissions per
non-trivial transition: one for the intermediate state and one for the final state.

### `can_construct` / `can_destruct` / `can_reconstruct` predicates

Each operation has a paired predicate. Predicates are defined as:

- `can_construct()` returns `true` iff `Status ∈ {Destructed, Constructed}`. (Re-
  constructing while already `Constructed` is a no-op.)
- `can_destruct()` returns `true` iff `Status ∈ {Constructed, Destructed}`. (Re-
  destructing while already `Destructed` is a no-op.)
- `can_reconstruct()` returns `true` iff `Status == Constructed`.

Note that `can_construct()` returning `true` from `Constructed`, and `can_destruct()`
returning `true` from `Destructed`, are intentional: re-invoking those operations in
the matching state is a no-op (see `## Idempotency` below), not an error, and the
predicate signals "the operation is safe to call" rather than "the operation will
produce a state change".

Calling an operation when its predicate returns `false` MUST raise
`StatusTransitionError` (Python) / `StatusTransitionException` (C#). The exception's
message MUST include the current state and the attempted operation.

## Invariants

These hold for every VM at every point in its lifetime:

1. `Status` is one of the five `ConstructionStatus` values.
1. `IsConstructed == (Status == Constructed)`.
1. Once `Status` reaches `Disposed`, it never changes again. All operations from
   `Disposed` (except `dispose` itself, which is idempotent) raise.
1. Every `Status` change publishes exactly one `ConstructionStatusChangedMessage`
   on the VM's message hub before the operation returns (synchronous) or before the
   awaiter resumes (asynchronous).
1. A VM in `Constructing` or `Destructing` MUST NOT have its operation re-invoked
   concurrently. Implementations MUST raise on the second invocation.

## Idempotency

- `construct()` from `Constructed` is a no-op. `Status` remains `Constructed`. No
  `ConstructionStatusChangedMessage` is emitted.
- `destruct()` from `Destructed` is a no-op. Same emission behavior.
- `dispose()` from `Disposed` is a no-op. No emission.

## Reconstruct

`reconstruct()` is defined as `destruct()` followed by `construct()`. The two are
executed in order, and the message hub observes the full transition sequence:
`ConstructionStatusChangedMessage(Destructing)`, `(Destructed)`, `(Constructing)`,
`(Constructed)`. Reconstruct is a first-class operation (rather than `destruct()` then
`construct()` composed by the caller) for two reasons: (1) it expresses "replace state"
as a single user-facing intent, naturally bound to a `ReconstructCommand`; (2) it
guarantees subscribers observe the full four-message transition sequence atomically with
respect to other lifecycle operations on the same VM.

## Parent–child orchestration

`CompositeVM`, `GroupVM`, and `AggregateVM` compose their children's lifecycles:

- A composite/group/aggregate's `construct()` completes only when every child has
  reached `Constructed`.
- A composite/group/aggregate's `destruct()` completes only when every child has
  reached `Destructed`.
- The order in which children are constructed/destructed is unspecified.
  Implementations MAY drive them sequentially or concurrently; the reference
  implementations in all three flavors drive them sequentially. The parent observes its children's
  `ConstructionStatusChangedMessage` emissions to know when to finalize its own
  state.

Conformance IDs for this behavior are cataloged in `12-conformance.md` under the
`COMP-NNN`, `GRP-NNN`, and `AGG-NNN` prefixes; each VM file's `## Conformance` section
points at its applicable range.

## Disposal cascade

`dispose()` on a parent disposes every child (synchronously, depth-first). This
ensures no orphaned `IDisposable` resources are left behind.

A disposed VM MAY still receive late-arriving subscriber events from the hub if
those events were already in flight. Subscribers MUST be tolerant of this.

## Reference table

See `fixtures/lifecycle-transitions.json` for the complete legal/illegal transition
matrix. Conformance tests (`LIFE-NNN` in `12-conformance.md`) load that fixture
directly.

## Conformance

`LIFE-001` through `LIFE-013` in `12-conformance.md` cover:

- legal state transitions (construct / destruct / reconstruct / dispose)
- predicates raising `StatusTransitionError` / `StatusTransitionException` on illegal calls
- idempotency from `Constructed`/`Destructed`/`Disposed` states
- the `IsConstructed == Status == Constructed` invariant
- concurrent re-invocation during `Constructing` / `Destructing` raises
- the full transition matrix (table-driven from `fixtures/lifecycle-transitions.json`)
- dispose-from-Disposed emits no message
- dispose cascade (parent disposes children depth-first)
