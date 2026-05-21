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
`(Constructed)`. See ADR-0002 for the rationale of why this is a first-class
operation rather than letting users compose it themselves.

## Parent–child orchestration

`CompositeVM`, `GroupVM`, and `AggregateVM` compose their children's lifecycles:

- A composite/group/aggregate's `construct()` completes only when every child has
  reached `Constructed`.
- A composite/group/aggregate's `destruct()` completes only when every child has
  reached `Destructed`.
- The children are constructed/destructed in parallel. The parent observes its
  children's `ConstructionStatusChangedMessage` emissions to know when to finalize
  its own state.

Specific conformance IDs for this behavior live in `06-composite-vm.md`,
`07-group-vm.md`, and `08-aggregate-vm.md`.

## Disposal cascade

`dispose()` on a parent disposes every child (synchronously, depth-first). This
ensures no orphaned `IDisposable` resources are left behind.

A disposed VM MAY still receive late-arriving subscriber events from the hub if
those events were already in flight. Subscribers MUST be tolerant of this.

## Reference table

See `fixtures/lifecycle-transitions.json` for the complete legal/illegal transition
matrix. Conformance tests (`LIFE-NNN` in `12-conformance.md`) load that fixture
directly.
