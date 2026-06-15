# ADR 0040 — `IProperty<T>` reactive backing-field abstraction not adopted

**Status:** Accepted (2026-06-13)
**Spec version:** 2.6.0 (teaching ADR; no code change)
**Related:** ADR-0018, ADR-0039, `spec/proposals/2026-06-13-vmx-absorption-audit-followup.md` §6 L2

## 1. Context

The 2012 predecessors (`My.Architecture.New/Core/Property.cs`, `GuideArch.Older/VMx/Property/{ValueProperty,ReferenceProperty,TransformationProperty}.cs`) wrapped every property in an `IProperty<T>` abstraction:

- `Value`, `HasValue`, `OnValueChanging`, `OnValueChanged` hooks per property.
- Implicit `operator TValue(Property<T> p) => p.Value` so `IProperty<int>` was silently usable wherever `int` was expected.
- `Dummy<T>` null-object sentinel returned by `Property<T>.GetDummyProperty()`.
- `TransformationProperty<S1..S5, V>` derived computation built on top of `IProperty<T>`.

`Object<T>.RegisterProperty(propertyExpression, IProperty<T>)` wired each property's value-channel notifications back to the host VM's INPC and the hub.

The `dotnet-tag/VMx` ancestor already dropped this abstraction. Current VMx uses plain fields plus `[CallerMemberName]` (C#), descriptors (Python), auto-accessors (TypeScript), `@Published` (Swift).

## 2. Decision

VMx does not adopt `IProperty<T>` as a first-class reactive backing-field type. Plain fields plus the host language's INPC convention remain the property idiom.

## 3. Rationale

- **Modern language features cover the use case.** Each flavor has a one-line idiom for "field with INPC notification":
  - C#: `private string _name; public string Name { get => _name; set { if (_name != value) { _name = value; RaisePropertyChanged(); } } }`
  - Python: setter that calls `_raise_property_changed("Name")` after assigning the backing field.
  - TypeScript: setter that calls `this.raisePropertyChanged("name")` after assigning the backing field.
  - Swift: setter that calls `_raisePropertyChanged("name")` after assigning the backing field.
    Wrapping these in `IProperty<T>` adds indirection without expressive gain.
- **`DerivedProperty` covers the multi-source case without `IProperty<T>`.** `Properties/DerivedProperty.cs` provides `From<T1..T5>` + `FromMany` with `CombineLatest` semantics, two-way `setAction` support, and `HasValue` gating via `canTransformFunction`. The predecessors' `TransformationProperty<...>` was load-bearing because `IProperty<T>` was the building block; current `DerivedProperty` is standalone.
- **Implicit conversion is exactly the magic ADR-0018 cited as a clarity regression.** `IProperty<int> x` silently flowing into an `int` parameter hides the property identity and breaks reasoning about lifetime and subscription.
- **Two-class-of-property forces a per-site choice.** Adopting `IProperty<T>` would mean every consumer chooses between "plain field" and "IProperty wrapper" with no clear win for either.

## 4. Consequences

- Components, composites, groups, and aggregates use the host language's idiomatic INPC pattern, not a wrapped property type.
- `DerivedProperty` remains the only first-class property type, scoped to derived/computed values where the multi-source dependency wiring earns its weight.
- This ADR may be reconsidered if a future consumer use case structurally requires "transactional changing→changed observation per property" — at which point ADR-0039 must be reopened in the same change.
