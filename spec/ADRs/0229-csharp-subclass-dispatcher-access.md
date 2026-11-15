# ADR 0229 — C# subclasses read the injected dispatcher through a protected `Dispatcher` property

- **Status:** Accepted
- **Date:** 2026-11-15
- **Spec version:** 3.30.0 (C# only; no spec chapter or conformance ID changes)
- **Related:** [ADR-0006](0006-idiomatic-api-per-language.md) (idiomatic names per
  language), [ADR-0066](0066-swift-componentvm-cross-module-subclassing.md) (the Swift
  precedent for cross-module subclass access), #1597.

## 1. Context

`ComponentVMBase` stores the dispatcher it is constructed with in
`private protected readonly IDispatcher _dispatcher`. `private protected` limits the
field to subclasses in the same assembly. A subclass in another assembly, such as an
application's view-model project, cannot read it. Its `_dispatcher` reference fails
with CS0122, and a `Dispatcher` reference fails with CS0103 because no such member
exists. Such a subclass must keep its own copy of the dispatcher, which the
same-assembly container subclasses avoid.

The other flavors already give subclasses this access. TypeScript has
`protected get _dispatcher()`, Python sets `self._dispatcher` in
`components/base.py`, and Swift has a public read-only `dispatcher` (ADR-0066). C# was
the only flavor whose subclasses could not reach the dispatcher the base was built
with.

## 2. Decision

`ComponentVMBase` gains a protected, read-only property over the existing field:

```csharp
protected IDispatcher Dispatcher => _dispatcher;
```

The field does not change. The property returns the same object the base was
constructed with. The name follows the C# convention for a property, which ADR-0006
asks for. The decision chose the simplest option that matches the other flavors.

| Flavor        | Subclass access to the injected dispatcher                                 |
| ------------- | -------------------------------------------------------------------------- |
| C# (this ADR) | `protected IDispatcher Dispatcher` (read-only property over `_dispatcher`) |
| TypeScript    | `protected get _dispatcher(): IDispatcher`                                 |
| Python        | `self._dispatcher` (set in `components/base.py`)                           |
| Swift         | `public let dispatcher: Dispatcher` (ADR-0066)                             |

Each flavor spells the name in its own idiom (ADR-0006). The access level and the
read-only shape match across flavors.

## 3. Consequences

- A subclass in any assembly can schedule on the dispatcher its base was built with.
  It no longer needs to store a copy of its own.
- The public API of `ComponentVMBase` gains one member,
  `VMx.Components.ComponentVMBase.Dispatcher.get -> VMx.Services.IDispatcher!`. It is
  recorded in `langs/csharp/src/VMx/PublicAPI.Unshipped.txt`, and it moves to
  `PublicAPI.Shipped.txt` in the next C# release. The change is additive. This ADR
  does not bump a version.
- A subclass that declares its own member named `Dispatcher` now hides the inherited
  property. The compiler reports warning CS0108 for it. A project that sets
  `TreatWarningsAsErrors` fails to build until the member is renamed or marked `new`.
  The name is the choice to revisit if this causes trouble.
- Name lookup finds an inherited member before a member of an enclosing type. So a
  subclass that names a `Dispatcher` identifier from an enclosing scope now binds to
  the inherited property. In a base initializer, where no instance exists, the
  compiler reports CS0120. In an instance member body, the reference compiles and
  binds to the inherited property without a diagnostic. The VMx test projects had
  three nested subclasses whose base initializers named an enclosing static
  `Dispatcher` (`DestructOrderBuilderTests`,
  `COMP_048_GRP_016_CrossThreadMembership_Tests`, and
  `HIER_041_DisposedNodeStructuralCallsTests`). Those tests now qualify the outer name
  with its enclosing type.

## 4. Alternatives considered

- **Widen the field to `protected`.** Rejected. Widening the field would expose the
  storage name `_dispatcher`. A read-only property gives the same access without
  exposing storage, which is the idiomatic C# shape (ADR-0006).
- **Another name, such as `Scheduler` or `Dispatchers`.** Rejected. The type is
  `IDispatcher`, and the other flavors name the value `dispatcher`.
