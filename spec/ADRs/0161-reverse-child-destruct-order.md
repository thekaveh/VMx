# ADR 0161 — Opt-in reverse child order for container destruct and dispose

- **Status:** Accepted
- **Date:** 2026-10-27
- **Spec version:** 3.30.0 (additive)
- **Amends:** ADR-0047 §2.5

## 1. Context

`GroupVM` and `CompositeVM` construct, destruct and dispose their children in
child order in all five flavors. Chapter 02 §6 and ADR-0047 §2.5 leave that
order unspecified, and no conformance ID constrains it.

A container whose later children depend on earlier ones needs the reverse
order for teardown. For example, a chart child reads from a query child, and
the query child reads from a connection child. Heimdall kept a hand-written
reverse loop instead of a `GroupVM` for this reason (#662).

ADR-0090 drains owned resources in LIFO order, because FIFO "conflicts with
stack-like acquisition and dependency order". Containers had no way to ask for
the same order.

## 2. Decision

`GroupVM<VM>`, `CompositeVM<VM>` and the modeled `CompositeVM<M, VM>` accept an
optional child order for destruct and dispose. The order has two values.

- `Insertion` is the default. The container keeps the current behavior. The
  spec still does not require a particular order for this value, and every
  flavor walks the children in child order, first child first.
- `Reverse` makes destruct and dispose walk the children in reverse child
  order, last child first. Child order is the order in which the container
  holds its children, which is insertion order unless `Insert` or `Move`
  changed it.

The order applies to every walk that tears down all of the children:

- `destruct()`, including the destruct phase of `reconstruct()`. A composite
  still clears `Current` before it destructs a child.
- The disposal cascade. Disposal stays depth-first: every child is disposed
  before the container publishes `Disposed` (`LIFE-013`). A flavor that
  reports disposal failures still attempts every child and keeps the first
  failure in execution order, which is now the reverse order.
- Background children. The walk starts one child at a time and waits for it
  to settle before it starts the next, so the waits follow the same order.

The order does not apply to these paths:

- `construct()`, and the construct phase of `reconstruct()`, are the same with
  and without the option. Chapter 02 §6 still leaves their order unspecified.
  Late children that `AutoConstructOnAdd(true)` starts during the walk are
  joined in the order they were added.
- The rollback of a failed factory population or of a failed `Add`, `Insert`
  or `Replace` keeps its current order. That rollback undoes a membership
  change, and every flavor already undoes the newest attachment first.
- A failed construct walk rolls back the container status only (ADR-0047
  §2.4). It does not destruct the children that already reached
  `Constructed`, so it has no child order.

The surface follows ADR-0006 in each flavor:

| Flavor     | Builder setter                         | `create(options)` field                          |
| ---------- | -------------------------------------- | ------------------------------------------------ |
| C#         | `.DestructOrder(ChildOrder.Reverse)`   | `DestructOrder = ChildOrder.Reverse`             |
| Python     | `.destruct_order(ChildOrder.REVERSE)`  | `create(..., destruct_order=ChildOrder.REVERSE)` |
| TypeScript | `.destructOrder("reverse")`            | `{ destructOrder: "reverse" }`                   |
| Swift      | `.destructOrder(.reverse)`             | `destructOrder: .reverse`                        |
| Rust       | `.destruct_order(ChildOrder::Reverse)` | `destruct_order: ChildOrder::Reverse`            |

The modeled composite has no options form (chapter 10 §7), so it gets only the
builder setter. The order is fixed when the builder builds the container, and
no member changes it later.

Two conformance IDs cover the option. `GRP-014` checks the group, and
`COMP-046` checks the composite. Each one checks that `Reverse` makes destruct,
the destruct phase of `reconstruct()` and dispose walk the children last child
first, and that construct is the same with and without the option. The
default order stays unspecified, so no ID checks it.

## 3. Consequences

- Chapter 02 §6, chapter 06 §5, chapter 07 §2 and §3, and chapter 10 §4 and §7
  describe the option. Chapter 02 §6 no longer says that no conformance ID
  constrains child order.
- ADR-0047 §2.5 is amended. Child visitation order stays unspecified for the
  default value, and subscribers still must not rely on it. A container built
  with `Reverse` guarantees the reverse order for destruct and dispose.
- The change is additive. A container that does not set the option behaves as
  before.

## 4. Rejected alternatives

- **Make reverse order the default.** It matches ADR-0090, but it changes the
  teardown order of every existing container. The owner chose an opt-in option
  on 2026-10-24 (#662).
- **A separate order for dispose.** A container that destructs its children in
  one order and disposes them in the other gives no useful guarantee. One
  option controls both walks.
- **Reverse the construct walk too.** Construct order is what the children
  depend on, so it stays in child order.
- **Make population rollback follow the option.** That rollback undoes
  attachments, and it already undoes the newest attachment first.
