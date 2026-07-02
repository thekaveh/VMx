# Component Family

## When To Use It

Use `ComponentVM` for any addressable leaf VM that is not itself a container.
This is the default choice for note rows, notebook rows, status panels,
capability bars, and other single-node surfaces.

Reach for the modeled variant when the VM owns a domain payload, and the
readonly variant when the payload should be fixed after construction.

<img src="../../../assets/diagrams/component-family.svg" alt="Component Family Map" class="vmx-diagram" />

<p>
  <a href="../../../assets/diagrams/component-family.html">HTML</a>
  &middot;
  <a href="../../../assets/diagrams/component-family.svg">SVG</a>
  &middot;
  <a href="../../../assets/diagrams/component-family.png">PNG</a>
</p>

## Shape And Ownership

The component family has three shipped variants:

| Variant                                               | Owns model | Model mutable | Typical use                  |
| ----------------------------------------------------- | ---------- | ------------- | ---------------------------- |
| `ComponentVM`                                         | No         | n/a           | simple leaf state            |
| `ComponentVM<M>` / `ComponentVMOf<M>`                 | Yes        | Yes           | editable or refreshable leaf |
| `ReadonlyComponentVM<M>` / `ReadonlyComponentVMOf<M>` | Yes        | No            | immutable projection         |

All variants share the same lifecycle base, built-in selection commands, and
per-instance property-changed surface. They also carry the internal `Parent`
back-reference used by selection predicates, but they never own children.

## Lifecycle And Messaging

Construction is leaf-local: there is no child orchestration. The family still
publishes the same status transitions and property-changed messages as every
other VM.

Important behavior from the spec:

- `Model` changes publish only on real value change.
- `ModeledHint` recomputes only when the model actually changes.
- `SelectNextCommand` and `SelectPreviousCommand` exist for uniform surface,
  but the base leaf implementation is inert.
- `can_select()` depends on `Parent`, current-selection state, and the leaf
  being constructed.

## Cross-Language Surface

| Concept          | C#                       | Python                     | TypeScript                 | Swift                      |
| ---------------- | ------------------------ | -------------------------- | -------------------------- | -------------------------- |
| Unmodeled leaf   | `ComponentVM`            | `ComponentVM`              | `ComponentVM`              | `ComponentVM`              |
| Modeled leaf     | `ComponentVM<M>`         | `ComponentVMOf[M]`         | `ComponentVMOf<M>`         | `ComponentVMOf<M>`         |
| Readonly leaf    | `ReadonlyComponentVM<M>` | `ReadonlyComponentVMOf[M]` | `ReadonlyComponentVMOf<M>` | `ReadonlyComponentVMOf<M>` |
| Builder entry    | `Builder()`              | `builder()`                | `builder()`                | `builder()`                |
| Property channel | `INotifyPropertyChanged` | `property_changed`         | `propertyChanged`          | `propertyChanged`          |

## Example

Representative modeled leaf shape across the four flavors:

- `C#`: `ComponentVM<TabModel>.Builder().Name("home-tab").Model(model).Services(hub, dispatcher).Build()`
- `Python`: `ComponentVMOf.builder().name("home-tab").model(model).services(hub, dispatcher).build()`
- `TypeScript`: `ComponentVMOf.builder<TabModel>().name("home-tab").model(model).services(hub, dispatcher).build()`
- `Swift`: `try ComponentVMOf<TabModel>.builder().name("home-tab").model(model).services(hub: hub, dispatcher: dispatcher).build()`

The Quickstart page uses exactly this pattern before composing those leaves into
a `CompositeVM`.

## Common Pitfalls

- Using a component when the VM really owns a collection. Move up to
  `CompositeVM`, `GroupVM`, or `AggregateVM`.
- Expecting the built-in next/previous commands on a leaf to walk siblings.
  Container-driven navigation is the intended model.
- Subclassing to add domain behavior instead of composing around the sealed VM.
- Forgetting that a detached leaf has no `Parent`, so selection predicates stay
  false until a container owns it.

## Related Primitives

- [Composite Family](composite-family.md)
- [Group Family](group-family.md)
- [Aggregate Family](aggregate-family.md)
- [FormVM](specialized/form-vm.md)
- [State & Reactive Helpers](../state-reactive-helpers.md)
