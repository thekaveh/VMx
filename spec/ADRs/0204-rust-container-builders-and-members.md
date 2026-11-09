# ADR 0204 — Rust containers populate on construct and own members

- **Status:** Accepted
- **Date:** 2026-11-09
- **Spec version:** 3.30.0 (removes the Rust gap notes in chapter 06 §1 and
  chapter 07 §3; no conformance ID changes)
- **Relates to:** [ADR-0161](0161-reverse-child-destruct-order.md),
  [ADR-0162](0162-supported-child-transition-helper.md),
  [ADR-0179](0179-foreign-dispose-publishes-disposed-first.md)

## 1. Context

Four Rust container gaps remained after the v3 convergence:

1. Rust `CompositeVmBuilder::build()` and `GroupVmBuilder::build()` called the
   `children` factory and attached its result (#1255). Chapter 06 §1 and
   chapter 07 §3 say that the factory runs on `construct()`, and C#, Python,
   TypeScript and Swift run it once, on the first construct. The two chapters
   recorded the Rust behavior as an open gap.
1. The Rust raw constructors of `CompositeVm` and `GroupVm` always used
   `ChildOrder::Insertion` (#1287). The constructor that takes an order was
   private. The TypeScript, Python and Swift raw constructors take the order
   as an optional argument.
1. Rust `CompositeVm`, `GroupVm` and `AggregateVm1` to `AggregateVm6` had no
   public `own_member` (#1289). Their disposal paths also never disposed
   registered members. The containers of the other flavors inherit the helper
   from the component base (ADR-0162 §2.2).
1. A stored `reconstruct_command()` of a Rust container stayed enabled after
   the last container handle dropped, but did nothing (#1483). The aggregate
   command also held the aggregate's parent registration strongly, so its
   children kept reporting the dropped aggregate as their parent.

## 2. Decision

Decided under the owner's 2026-11-07 delegation. Each rule takes the
cross-flavor behavior and the simplest Rust surface.

1. **Construct-time population.** A `CompositeVm` or `GroupVm` from the
   builder, or from `create(options)`, has no children after `build()`. Its
   first `construct()` calls the factory once and attaches the result
   atomically. The population runs inside the admitted construct transition,
   after the construct hook and before the construct walk, at the point where
   C# `OnConstruct` and TypeScript `_onConstruct` populate. So the construct
   hook of the first construct sees no children, and a construct that starts
   while the factory runs fails with `VmxError::InvalidLifecycleTransition`
   from `Constructing` (LIFE-008, ADR-0203). A population that is refused, for example
   `VmxError::DuplicateChild`, is a failed construct: the container publishes
   `Constructing` and rolls back to `Destructed`. It attaches nothing and keeps
   the factory for the next construct, as the C# `_populated` guard does. The
   factory leaves its slot only when the population commits, so a factory
   that panics also runs again on the next construct. A later `reconstruct()`
   or construct does not call the factory again. A disposed container never
   calls it. `ModeledCompositeVm` is unchanged.
1. **Raw destruct order.** `CompositeVm::with_destruct_order` and
   `GroupVm::with_destruct_order` become public. They take a name, a hub, a
   dispatcher and a `ChildOrder`. Rust has no optional arguments, so a named
   constructor is the idiomatic form (ADR-0006). `new` and `with_services`
   keep `ChildOrder::Insertion`.
1. **Container members.** `CompositeVm`, `ModeledCompositeVm`, `GroupVm` and
   `AggregateVm1` to `AggregateVm6` gain
   `own_member(&member) -> VmxResult<()>`, with the `ComponentVm::own_member`
   contract. The container itself is rejected with
   `VmxError::OwnershipCycle`. The disposal takes the registered members when
   it starts. It disposes the children and then the members at the
   admitted-hook boundary, so both orders of ADR-0179 hold. A member
   registered after the disposal started is disposed by its registration.
1. **Command liveness.** The stored reconstruct command of `CompositeVm`,
   `GroupVm` and `AggregateVm1` to `AggregateVm6` holds the command table and
   the parent registration weakly. Its predicate checks the same two handles
   before `can_reconstruct()`, so a command that outlives its container
   reports `can_execute()` false, as Swift does. Its action still does
   nothing. A dropped aggregate no longer stays registered as its children's
   parent.

## 3. Consequences

- Rust code that read the children of a built composite or group before
  `construct()` now reads an empty list. A duplicate child in the factory
  result fails the first `construct()`, not `build()`. The Rust 0.36.0
  CHANGELOG records this breaking change.
- The population of a built container publishes its collection messages
  after `Constructing`, as in C# and TypeScript.
- The leaf `ComponentVm` reconstruct command is unchanged. It holds its core
  strongly and still runs after a drop.
- Chapter 06 §1 and chapter 07 §3 no longer carry the Rust gap notes. No
  conformance ID changes. Rust tests cover the four rules.
