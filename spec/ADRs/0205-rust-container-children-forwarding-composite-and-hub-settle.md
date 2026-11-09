# ADR 0205 — Rust container children: forwarding composite node and hub-observed settle

- **Status:** Accepted
- **Date:** 2026-11-09
- **Spec version:** 3.30.0 (amends chapter 02 §2.2, chapter 09 §2 and chapter
  11 §4; `FWD-004`, `LIFE-014`)

## 1. Context

Two Rust container gaps were recorded as open.

**Forwarding composite as a child (#1271).** Chapter 09 §2 says that a
forwarding composite used as a child follows the §1 ownership rules. C#,
Python and Swift meet the rule. Rust `CompositeVm`, `GroupVm` and every
`AggregateVm` type require `VmNode` children. Rust `ForwardingCompositeVm`
did not implement `VmNode`, so a container of decorated composites did not
compile. The decorator also did not forward the selection members, the
commands, expansion, `on_current_changed`, `background_errors` or the
configuration setters. ADR-0203 added the lifecycle hook methods.

**Nodes that do not forward the settle hook (#1274).** A Rust container waits
for a background child through `VmNode::when_lifecycle_settled`. The default
returns `false`. A container then accepted the child while it was still
Constructing or Destructing. If the child then failed, the container stayed
Constructed and the child ended Destructed. That breaks chapter 02 §6 and
`LIFE-014`. Chapter 11 §4 documented the acceptance as Rust behavior. The
parity ledger recorded that Rust has no node-level hub accessor. A container
that waits on a hub where the child never publishes would wait without limit.

## 2. Decision

Decided under the owner's 2026-11-07 delegation, with the simplest option that
keeps the cross-flavor rules.

### 2.1. Forwarding composite node

- `ForwardingCompositeVm<T, D>` implements `VmNode`, `PartialEq` and `Eq`.
  Each `VmNode` method forwards to the wrapped composite. This includes
  `set_parent_handle`, `parent_handle`, `commit_current_flag`,
  `publish_current_flag`, `is_current`, `when_lifecycle_settled` and
  `lifecycle_publication_pending`. The decorator and the wrapped composite
  therefore have one ownership identity, one current flag and one lifecycle.
- Equality compares the wrapped identity, as `ForwardingComponentVm` does.
- The decorator forwards the rest of the `CompositeVm` surface:
  `can_select`, `select`, `can_deselect`, `deselect`, `is_current`, the five
  commands, the expansion members, `on_current_changed`,
  `background_errors`, `set_current_selector`, `set_auto_construct_on_add`
  and `set_async_selection`. The lifecycle hook methods come from ADR-0203.
- The decorator still has no override hooks (chapter 09 §2).

### 2.2. Hub-observed settle for a node that does not forward the hook

- Before a container starts a child, it subscribes to its own message hub for
  the child's `ConstructionStatusChanged` messages.
- When the child does not forward `when_lifecycle_settled`, the container
  waits only if, by the time the start call returned, the hub delivered the
  child's transient status or holds it in its queue. The hub queues instead
  of delivering inside a batch, inside a borrowed scope, and in the drain of
  the starting thread (for example when a container starts its next child
  from the delivery of the previous child's status). Either way, the child
  publishes on the container's hub, so its next status arrives there too.
- The container then waits on that hub for a status of the child that arrives
  while the child is no longer at the transient status. It checks the child's
  status as for a forwarded settle.
- The hub can still hold statuses of the child's earlier transitions, queued
  before the start call (in a batch, a borrowed scope or another thread's
  drain). A message does not name its transition. So when a non-transient
  status arrives while the child is still at the transient status, the
  container treats it as an earlier transition's status and keeps waiting. A child that settled
  at another status rolls the container back, and the failure reaches the
  container's `background_errors()` stream.
- Hub completion ends the wait, and the container checks the child's status.
- In every other case, the container accepts the child while it is still in
  flight, as before. These cases are: the child publishes on another hub, and
  the container joined a child that was already in flight.
- The subscription ends when the check runs, or when the container drops the
  wait (disposal, a newer transition, or drop). It never holds the container.

### 2.3. Related Rust fixes in the same change

These fixes follow existing rules and change no spec text:

- `AggregateVm1` to `AggregateVm6` construct their slot children through the
  joining child step, as the composite and group walks do. A slot child that
  is already Constructing is joined, not constructed again (#1273).
- `CompositeVm::clear()` no longer writes the flag of each removed child after
  it releases the membership gate. The detach clear commits the previous
  current child's flag under the gate, as in C# and Python (chapter 06 §4.3
  rules 1 and 2, #1285).

## 3. Consequences

- Chapter 09 §2 no longer lists the Rust `VmNode` gap. Chapter 02 §2.2 no
  longer lists `ForwardingCompositeVm` among the Rust types without hook
  methods.
- Chapter 11 §4, the Rust flavor guide and the `when_lifecycle_settled`
  rustdoc describe the hub fallback.
- A wrapper node that publishes on the container's hub no longer needs to
  forward the settle hook for rollback. Forwarding the hook is still the
  recommended form, because it also covers joins and other hubs.
- The container continuation after a hub-observed settle runs inside the
  hub's delivery of the child's status. The container's own status message is
  queued behind it, so the child's terminal status is delivered first.
- The parity ledger closes §12.8 and records §12.7 as a documented
  difference: the container `background_errors()` stream (chapter 11 §2,
  ADR-0149).

## 4. Alternatives Considered

- **Add a `VmNode` hub accessor.** A third-party node that does not forward
  the settle hook would likely not forward a new method either.
- **Wait on the container's hub for every in-flight child.** A child that
  publishes on another hub would hold the container without limit.
- **Poll the child's status through the dispatcher.** Polling would keep a
  dispatcher busy without limit and has no portable interval.
