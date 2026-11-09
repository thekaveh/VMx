# ADR 0213 — The TypeScript forwarding composite joins containers and exposes `wrappedBase`

- **Status:** Accepted
- **Date:** 2026-11-09
- **Spec version:** 3.30.0 (removes the TypeScript gap note in chapter 09 §2;
  no conformance ID changes)
- **Supersedes:** [ADR-0151](0151-forwarding-decorators-own-resources-on-the-wrapped-component.md)
  Decision rule 3
- **Relates to:** [ADR-0124](0124-canonicalize-forwarding-ownership-and-callback-boundaries.md)

## 1. Context

Two TypeScript gaps remained for forwarding decorators:

1. The TypeScript `ForwardingCompositeVM` did not extend `ComponentVMBase`
   (#1272). TypeScript containers take children of type
   `VM extends ComponentVMBase`. That class has ECMAScript private fields, so
   the compiler compares it nominally and rejected the decorator in `add`.
   The decorator also had no `own()` helper. Chapter 09 §2 listed the gap,
   and ADR-0151 Decision rule 3 excluded the class from the owned-resource
   rule. C#, Python and Swift support both.
1. The `@thekaveh/vmx-react` hook `useVm` re-renders only for hub messages
   whose sender is the bound object (#1350). A decorator delegates its hub and
   its setters to the wrapped VM, and the wrapped VM sends each message with
   itself as the sender. A component bound to a decorator never re-rendered.
   `wrappedBase` on the component decorator was public but undocumented, and
   the composite decorator had no accessor for the wrapped VM.

## 2. Decision

Decided under the owner's 2026-11-07 delegation, with the simplest option
that matches the other flavors.

1. **Container child.** The TypeScript `ForwardingCompositeVM` extends
   `ComponentVMBase`, as `ForwardingComponentVM` does. It shares the
   canonical ownership identity of the wrapped composite and the same
   parent-link forwarding, so chapter 09 §1 and §2 apply unchanged: adding
   the decorator removes the wrapped composite from its previous container,
   and selection and current flags reach the wrapped composite. The
   selection command getters now return `RelayCommand`, the type that the
   base class declares.
1. **Owned resources.** The inherited `own()` and `ownMember()` forward to
   the ownership identity, as ADR-0151 defines. This replaces ADR-0151
   Decision rule 3: the owned-resource rule now covers the composite
   decorator in all five flavors.
1. **`wrappedBase`.** Both TypeScript decorators expose the wrapped VM as the
   documented read-only `wrappedBase` getter. The component decorator throws a
   `TypeError` when it wraps an object that is not a `ComponentVMBase`. The
   getter is TypeScript surface (ADR-0006). The other flavors have no view
   adapter that needs it, so they add nothing.
1. **`useVm`.** `useVm` re-renders for a message whose sender is the bound
   object or a VM that the `wrappedBase` chain of the bound object reaches. It
   reads no `_`-prefixed member. A message from any other VM on the same hub
   still causes no re-render.

Rejected: a `useVm` that re-renders for every hub message when the bound
object is a decorator. It cannot tell the wrapped VM from other VMs on a
shared hub, so a decorator would re-render for unrelated changes.

## 3. Consequences

- `GroupVM.add` and `CompositeVM.add` accept a TypeScript
  `ForwardingCompositeVM`. `FWD-004` and `FWD-005` cover it in TypeScript.
- Code that typed the decorator's selection commands as `ICommand` still
  compiles, because `RelayCommand` implements `ICommand`.
- `useVm` supports a `ForwardingCompositeVM` only with an `@thekaveh/vmx`
  release that contains this change. A component decorator works with every
  release in the adapter's peer range, because `wrappedBase` already existed.
- Chapter 09 §2 keeps one open gap: the Rust `ForwardingCompositeVm` does not
  implement `VmNode`.
