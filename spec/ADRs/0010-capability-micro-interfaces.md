# ADR 0010 — Capability micro-interfaces (additive)

**Status:** Accepted (2026-05-25)
**Spec version:** introduced in 2.0.0

## 1. Context

The 2012 C# VMx predecessor encoded almost every user-visible behavior as a
small marker / behavior interface — `ISelectable`, `IDeselectable`,
`IExpandable`, `ICollapsible`, `IExpansionTogglable`, `IConstructable`,
`IDestructable`, `IReconstructable`, `IClosable`, `ISearchable`,
`IApprovable`, `ICancelable`, `ISavable<T>`, `IManagable<T>`,
`INewCreatable`, `IDeletable<T>`, `IUpdatable<T>`, `ICurrentDeletable`,
`ICurrentUpdatable` (`Contract/Receivers.cs`). Consumers wrote
capability-based code (`if (vm is ISelectable) …`) instead of branching on
concrete VM type.

The current VMx replaces that style with fewer, broader VM types
(`ComponentVM` / `CompositeVM` / `GroupVM` / `AggregateVM`). Consumers branch
on those types. The two styles are not equivalent: capability-based code is
strictly more flexible (a single VM can opt into any subset of capabilities;
new capabilities can be added without modifying existing VM types).

The VMx.old absorption goal asks us to bring this discipline forward, but
without restructuring the existing VM hierarchy around it.

## 2. Options considered

1. **Restructure existing VMs around capability interfaces.** Make
   `ComponentVM` implement `IClosable` + `IReconstructable`, `CompositeVM`
   implement `ISelectable` + `ICurrentDeletable`, etc. Aggressive — breaks
   v1.x consumers that don't expect the new interfaces, and forces consumers
   to import capability types they don't need.
1. **Additive — define capability interfaces as opt-in contracts, with no
   change to existing VMs.** Existing VMs neither know nor care about the
   capability interfaces. New code can implement any combination; old code is
   unaffected.
1. **Skip capability interfaces entirely.** Lose the philosophy gain.
   Consumer code continues to branch on concrete VM types only.

## 3. Decision

Option 2. All 20 capability interfaces are defined in a new chapter
(`14-capabilities.md`) and exposed in the public surface of all three
flavors. Existing VM types do NOT implement them by default; consumers opt
in by subclassing or wrapping. The only exception is that the three
lifecycle capabilities (`IConstructable`, `IDestructable`, `IReconstructable`)
are trivially satisfied by every VM and SHOULD be declared on the base VM
interface; per-language declarations follow the flavor's idiomatic interface
inheritance rules.

## 4. Consequences

- A new chapter `14-capabilities.md` lists every capability and its
  members.
- Twenty conformance IDs `CAP-001..CAP-020` cover the per-interface contract
  plus opt-in (no implicit implementation) and composition (a VM may
  implement multiple).
- Each flavor adds a `capabilities/` directory (`Capabilities/` in C#,
  `capabilities/` in Python and TypeScript) containing the interface
  declarations only — no implementations.
- Consumers can begin writing capability-based code without waiting for any
  other absorption cycle.
- Subsequent cycles (Item 6 expand/collapse, Item 7 modeled CRUD) extend
  existing VM types to additively implement specific capabilities. Each such
  extension is itself a non-breaking change.
- This ADR does not introduce new event channels. Property-change messages
  for capability-defined state (e.g., `ISearchable.SearchTerm`) flow through
  the existing `IMessageHub` per ADR-0002 and the rules in chapter 03.
