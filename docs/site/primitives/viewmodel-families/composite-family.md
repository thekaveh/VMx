# Composite Family

## When To Use It

Use `CompositeVM<VM>` when the parent owns an ordered homogeneous child list and
one child may be current. Tabs, note lists, result lists, and other "collection
plus selection" workflows belong here.

Use the modeled composite when children are projected from models during
construction instead of being provided directly.

<img src="../../assets/diagrams/composite-family.svg" alt="Composite Family Deep Dive" class="vmx-diagram" />

<p>
  <a href="../../assets/diagrams/composite-family.html">HTML</a>
  &middot;
  <a href="../../assets/diagrams/composite-family.svg">SVG</a>
  &middot;
  <a href="../../assets/diagrams/composite-family.png">PNG</a>
</p>

## Shape And Ownership

`CompositeVM` adds one core concept on top of a collection container:

- `Current` may be one child or `null`

Everything else follows from that contract: guarded selection helpers,
foreground updates of `IsCurrent`, and optional builder hooks for initial
selection and current-changed callbacks.

## Lifecycle And Messaging

The composite owns both child lifecycle and selection messaging:

- `construct()` waits for every child before the composite reports constructed
- `destruct()` clears `Current` before destructing children
- `Current` changes publish the parent `Current` property and the affected
  children's `IsCurrent`
- `AsyncSelection(true)` routes selection work through the foreground
  dispatcher

## Cross-Language Surface

| Concept               | C#                   | Python                 | TypeScript             | Swift                  |
| --------------------- | -------------------- | ---------------------- | ---------------------- | ---------------------- |
| Type                  | `CompositeVM<VM>`    | `CompositeVM[VM]`      | `CompositeVM<VM>`      | `CompositeVM<VM>`      |
| Modeled type          | `CompositeVM<M, VM>` | `CompositeVMOf[M, VM]` | `CompositeVMOf<M, VM>` | `CompositeVMOf<M, VM>` |
| Selection slot        | `Current`            | `current`              | `current`              | `current`              |
| Initial selector hook | `Current(selector)`  | `current(selector)`    | `current(selector)`    | `current(selector)`    |

## Example

=== "C#"

````
```csharp
var tabs = CompositeVM<ComponentVM<TabModel>>.Builder()
    .Name("tab-bar")
    .Services(hub, dispatcher)
    .Children(() => new[] { home, settings })
    .Build();
```
````

=== "Python"

````
```python
tabs = (
    CompositeVM[ComponentVMOf[TabModel]]
    .builder()
    .name("tab-bar")
    .services(hub, dispatcher)
    .children(lambda: [home, settings])
    .build()
)
```
````

=== "TypeScript"

````
```ts
const tabs = CompositeVM.builder<ComponentVMOf<TabModel>>()
  .name("tab-bar")
  .services(hub, dispatcher)
  .children(() => [home, settings])
  .build();
```
````

=== "Swift"

````
```swift
let tabs = try CompositeVM<ComponentVMOf<TabModel>>.builder()
    .name("tab-bar")
    .services(hub: hub, dispatcher: dispatcher)
    .children { [home, settings] }
    .build()
```
````

## Common Pitfalls

- Using a composite for recursive trees. `HierarchicalVM` carries the tree
  semantics directly.
- Forgetting that `Current` must always be a contained child or `null`.
- Assuming add-after-construct auto-constructs by default. It does not unless
  `AutoConstructOnAdd(true)` is enabled.
- Updating selection predicates without wiring current-changed triggers into
  commands that depend on selection.

## Related Primitives

- [Group Family](group-family.md)
- [Hierarchical Family](hierarchical-family.md)
- [Command Families](../command-families.md)
- [State & Reactive Helpers](../state-reactive-helpers.md)
