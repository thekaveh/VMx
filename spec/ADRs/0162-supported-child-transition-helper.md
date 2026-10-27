# ADR 0162 — Supported child-transition helper and depth-first member disposal

- **Status:** Accepted
- **Date:** 2026-10-27
- **Spec version:** 3.30.0 (additive)

## 1. Context

A leaf view-model often keeps child view-models in fields. For example, a panel
keeps a chart and a table. The leaf must construct, destruct and dispose those
members itself. Hand-written loops in the construct and destruct hooks get
three things wrong (#661):

- They do not wait for a background child (chapter 02 §6). The parent publishes
  `Constructed` while the child is still `Constructing`.
- They do not roll the parent back when a child fails on a background
  scheduler.
- A member registered with `own` is disposed after the parent publishes
  `Disposed`. Containers do the opposite: they dispose their children
  depth-first, before the parent (`LIFE-013`).

The containers already have the machinery. TypeScript has a protected
`_transitionChildren`, C# has a protected `TransitionChildrenAsync`, and Python
has a protected `_transition_children`. The spec does not describe them. The
Swift helper is internal and the Rust helper is `pub(crate)`, so consumers of
those flavors cannot use them.

`AggregateVM` is not a substitute. Its factories run on every construct,
reconstruct replaces its slots (`AGG-007`), and its arity stops at six
(ADR-0058).

## 2. Decision

### 2.1 The child-transition helper

The component base exposes the child-transition helper as supported API for
subclasses. Chapter 02 §6.1 specifies it. The helper takes an ordered list of
children, a direction (construct or destruct), and an optional `after`
callback. It has these rules:

- It walks the list in the given order. It starts a child only after the
  previous child settled.
- It skips a child that is already at the target status. It joins a child that
  is already in the transient status and does not start it again.
- It waits for a background child. The parent stays `Constructing` or
  `Destructing` until the child settles.
- A child that settles at any status other than the target fails the walk. The
  parent rolls back to its prior settled status and the failure surfaces.
- It runs `after` once, after every child settled at the target and before the
  parent publishes its terminal status. A failing `after` rolls the parent
  back like a failing child.
- Only the parent's own construct and destruct hooks may call it, including the
  two phases of `reconstruct()`. Elsewhere it raises the flavor's usage error
  and starts no child.

The helper does not undo siblings that already reached the target when a later
child fails. This matches the containers (ADR-0047 §2.4, ADR-0161 §2). Whether
any walk should undo them stays an open question in the cross-flavor decisions
ledger (`docs/maintenance/2026-10-18-open-cross-flavor-decisions.md` §1.3).

The helper has no child-order option. The caller passes the children in the
order it wants. For reverse-order destruct it passes the reversed list. The
`ChildOrder` option of ADR-0161 configures a container, which owns its child
list. A leaf owns its list, so a second ordering mechanism adds nothing.

The container-only parameters (factory-population joins and late-child seals)
are unsupported and not part of the API. They live in separate container
variants: a `private protected` overload in C#, an internal method in Swift
and Rust, a `protected` method marked
`@internal` and documented as unsupported in TypeScript, and an underscore
method documented as unsupported in Python.

The surface follows ADR-0006:

| Flavor     | Helper                                                                                           |
| ---------- | ------------------------------------------------------------------------------------------------ |
| C#         | `CompleteLifecycleHookAfter(TransitionChildrenAsync(children, construct, after))`, protected     |
| Python     | `self._complete_lifecycle_hook_after(self._transition_children(children, construct=…, after=…))` |
| TypeScript | `this._transitionChildren(children, construct, after?)`, protected                               |
| Swift      | `try _transitionChildren(children, construct:, after:)`, `public`                                |
| Rust       | `ComponentVm::construct_with_children` / `destruct_with_children` / `reconstruct_with_children`  |

C# and Python keep their two-call form. The walk returns a task or future, and
the hook hands it to the base, which defers the terminal status until the walk
settles. The usage error is `InvalidOperationException` in C#, `RuntimeError`
in Python, `Error` in TypeScript and `ChildTransitionError` in Swift, which
becomes public so that a consumer can catch it by type.

In Python, C# and Swift the hook guard is scoped to the thread of the running
hook, not to the view-model. In C# and Python the walk checks only that some
construct or destruct hook runs on the calling thread; the deferral call then
checks that the hook belongs to this view-model. TypeScript is single-threaded
and checks this view-model's own hook.

Swift makes the helper `public` and not `open`. A subclass in another module
must call it, and `public` is enough for that (ADR-0066). `open` would also let
a subclass replace it, and the containers call it internally, so an override
could break their walks. #661 asked for `open`, so this choice needs owner
sign-off.

Rust has no subclassing. A consumer view-model type composes a `ComponentVm`
and drives its members the way the crate's containers do. The walk methods run
the component's own transition on the calling thread and pass a
`ChildTransitions` handle to a closure. `reconstruct()` and the reconstruct
command still run only the hooks, so a consumer type routes its own reconstruct
through `reconstruct_with_children`. Because the walk runs on the calling
thread, `construct_with_children` and `destruct_with_children` reject a
component built with `background(true)` (`VmxError::InvalidArgument`, chapter
11 §4). Running the walk on the background dispatcher would need a `'static`
walk closure, which is an API change; it is left for later. `ChildTransitions::transition(&child)`
adds the next child step, and `ChildTransitions::then(after)` adds the `after`
step. The handle borrows the
transition, so it cannot leave the closure. The type system enforces the
"hooks only" rule, and Rust needs no runtime usage error.

### 2.2 Depth-first member disposal

The component base gets a member registration helper: `OwnMember` in C#,
`_own_member` in Python, `ownMember` in TypeScript and Swift, and `own_member`
in Rust. Chapter 02 §7.1 specifies it.

- `dispose()` first stops waiting for a pending child walk. It then disposes
  the registered members in registration order, before the parent publishes
  `Disposed`. A container still disposes its own children first.
- Member disposal is best-effort (ADR-0108). Every member is attempted. A
  flavor with a throwing or result-based disposal surface keeps the first
  failure, finishes the parent's teardown, and then reports that failure.
  Swift disposal does not throw, so it attempts every member and reports
  nothing.
- A member registered once the parent's disposal has started is disposed at
  once.
- While the member cascade runs, any further `dispose()` of the parent returns
  at once without waiting and does nothing, whether it comes from the same
  thread or another thread. The first call finishes the cascade and publishes
  `Disposed` after the members. Waiting would let two opposing disposals block
  each other, which §2.4 of chapter 02 forbids.
- Registering the view-model itself is a usage error. Swift traps, because
  registration does not throw (ADR-0009). Rust returns
  `VmxError::OwnershipCycle`, as the aggregates do for the same mistake.
- A member is not a container child. It has no parent link and no selection,
  and registration does not construct it. The helper of §2.1 transitions it.
- Member disposal follows the same admitted-hook rule as the container cascade
  (`LIFE-015`).

Registration order is the containers' default order (`LIFE-013`). A leaf that
wants reverse teardown registers its members in reverse order.

### 2.3 Conformance

Five conformance IDs cover the helper and member disposal:

- `LIFE-016`: the helper waits for a background child and runs `after` once.
- `LIFE-017`: a child failure rolls the parent back and keeps earlier siblings.
- `LIFE-018`: members are disposed depth-first before the parent publishes
  `Disposed`.
- `LIFE-019`: the helper destructs children in the order the caller passes.
- `LIFE-020`: the helper joins a child that is already in transit.

The usage error is checked by per-flavor API tests. Rust enforces it at compile
time.

## 3. Consequences

- Chapter 02 gets §6.1 (the helper) and §7.1 (member disposal), and its
  conformance list covers `LIFE-016` through `LIFE-020`. Chapter 11 §4 states
  where the helper runs for a background-enabled parent and the Rust limit.
- In Swift, `AggregateVM1` to `AggregateVM6` now ignore a re-entrant or
  concurrent `dispose()` during their component cascade, like the other
  containers, so a member registered during the cascade is disposed at once.
- The change is additive. Existing containers keep their behavior.
- The component-family guide shows the helper in place of hand-written loops.
- `own` keeps its order. A member registered with `own` is still disposed after
  the parent publishes `Disposed`.

## 4. Rejected alternatives

- **A dispose-members hook.** An overridable hook that disposes members before
  `Disposed` makes each subclass write its own best-effort loop and keep the
  first failure itself. Registration puts that logic in the base once.
- **A `ChildOrder` argument on the helper.** The caller already controls the
  order of its own list.
- **Dispose members in reverse registration order, like `own`.** The members
  are view-models with a lifecycle, so they follow the container default
  instead.
- **Undo constructed siblings on a later failure.** No container does this
  today, and the owner has not decided it. It stays in the ledger.
- **`open` in Swift.** A subclass needs to call the helper, not replace it.
