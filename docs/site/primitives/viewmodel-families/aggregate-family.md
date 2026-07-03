# Aggregate Family

## When To Use It

Use `AggregateVM1` through `AggregateVM6` when the parent owns a fixed set of
heterogeneous children and each slot has a stable semantic role: workspace
shells, multi-pane roots, dashboards, or status bundles.

This is the right primitive when "component 1" and "component 2" mean different
things and variable-length child lists would weaken the contract.

<img src="../../../assets/diagrams/aggregate-family.svg" alt="Aggregate Family Map" class="vmx-diagram" />

<p>
  <a href="../../../assets/diagrams/aggregate-family.html">HTML</a>
  &middot;
  <a href="../../../assets/diagrams/aggregate-family.svg">SVG</a>
  &middot;
  <a href="../../../assets/diagrams/aggregate-family.png">PNG</a>
</p>

## Shape And Ownership

An aggregate is a component-shaped parent with named child slots:

- `Component1` is always present on every arity.
- Higher arities add `Component2` through `Component6`.
- Each slot is populated lazily through a factory during `construct()`.

The explicit arity surface is deliberate. VMx keeps `AggregateVM1` through
`AggregateVM6` rather than a variadic abstraction so every flavor preserves the
same compile-time slot contract.

## Lifecycle And Messaging

Construction and destruction cascade through the slot children:

1. slot factories run during `construct()`
1. each populated child is constructed
1. the aggregate reaches `Constructed` only after every child does

Each successful slot population publishes a property-changed message for that
slot (`Component1`, `component_1`, `component1`, and so on).

## Cross-Language Surface

| Concept              | C#                  | Python              | TypeScript          | Swift               |
| -------------------- | ------------------- | ------------------- | ------------------- | ------------------- |
| Arity-6 type         | `AggregateVM6<...>` | `AggregateVM6[...]` | `AggregateVM6<...>` | `AggregateVM6<...>` |
| Slot builder setters | `Component1(...)`   | `component_1(...)`  | `component1(...)`   | `component1(...)`   |
| Slot property        | `Component1`        | `component_1`       | `component1`        | `component1`        |

## Example

- `C#`: `AggregateVM6<...>.Builder().Name("workspace").Services(hub, dispatcher).Component1(() => notebooks).Component2(() => notes).Build()`
- `Python`: `AggregateVM6Builder[...]().name("workspace").services(hub, dispatcher).component_1(lambda: notebooks).component_2(lambda: notes).build()`
- `TypeScript`: `AggregateVM6.builder<...>().name("workspace").services(hub, dispatcher).component1(() => notebooks).component2(() => notes).build()`
- `Swift`: `try AggregateVM6<...>.builder().name("workspace").services(hub: hub, dispatcher: dispatcher).component1 { notebooks }.component2 { notes }.build()`

The Notes Workspace shell uses this pattern as its six-pane root in the C#,
Python, TypeScript, and Swift examples.

## Common Pitfalls

- Using an aggregate when the child set is variable or homogeneous. Prefer
  `CompositeVM` or `GroupVM`.
- Expecting slot factories to run at build time. They run at construct time.
- Flattening semantic slots into a list and losing explicit ownership names.
- Treating slot children as selectable peers. Aggregates own structure, not a
  `Current` selection slot.

## Related Primitives

- [Component Family](component-family.md)
- [Composite Family](composite-family.md)
- [Hierarchical Family](hierarchical-family.md)
- [Builders, Collections & Tree Utilities](../builders-collections-tree-utilities.md)
