# Group Family

## When To Use It

Use `GroupVM<VM>` for an ordered collection of peer children when the parent
owns the children but does not own a selected child. Toolbars, capability rows,
stacked panels, and other peer lists usually belong here.

<img src="../../../assets/diagrams/group-family.svg" alt="Group Family Map" class="vmx-diagram" />

<p>
  <a href="../../../assets/diagrams/group-family.html">HTML</a>
  &middot;
  <a href="../../../assets/diagrams/group-family.svg">SVG</a>
  &middot;
  <a href="../../../assets/diagrams/group-family.png">PNG</a>
</p>

## Shape And Ownership

`GroupVM` mirrors the list-management surface of `CompositeVM` without the
selection slot:

- ordered children
- add, insert, remove, clear, batch update
- collection-changed notifications
- no `Current`
- no `select_component` / `deselect_component`

The group itself is still a component and may be selected by its own parent.

## Lifecycle And Messaging

Lifecycle orchestration matches `CompositeVM`:

- construct waits for all children to reach `Constructed`
- destruct waits for all children to reach `Destructed`
- `AutoConstructOnAdd(true)` can opt into post-construct child auto-construct
- `BatchUpdate()` suppresses per-mutation collection events and emits one reset

Group children are peers. Their inherited select command must stay disabled
while the group is their parent.

## Cross-Language Surface

| Concept         | C#                      | Python                 | TypeScript              | Swift                   |
| --------------- | ----------------------- | ---------------------- | ----------------------- | ----------------------- |
| Type            | `GroupVM<VM>`           | `GroupVM[VM]`          | `GroupVM<VM>`           | `GroupVM<VM>`           |
| Builder entry   | `GroupVM<VM>.Builder()` | `GroupVMBuilder[VM]()` | `GroupVM.builder<VM>()` | `GroupVM<VM>.builder()` |
| Children setter | `Children(...)`         | `children(...)`        | `children(...)`         | `children { ... }`      |

## Example

Representative build shape:

- `C#`: `GroupVM<IComponentVM>.Builder().Name("actions").Services(hub, dispatcher).Children(() => new[] { save, delete }).Build()`
- `Python`: `GroupVMBuilder[ComponentVMProto]().name("actions").services(hub, dispatcher).children(lambda: [save, delete]).build()`
- `TypeScript`: `GroupVM.builder<ComponentVMBase>().name("actions").services(hub, dispatcher).children(() => [save, delete]).build()`
- `Swift`: `try GroupVM<ComponentVMBase>.builder().name("actions").services(hub: hub, dispatcher: dispatcher).children { [save, delete] }.build()`

## Common Pitfalls

- Reaching for `GroupVM` when the UI has one meaningful active child. That is
  `CompositeVM`.
- Assuming peer children become selectable because they inherit leaf commands.
  The group contract keeps those commands disabled.
- Forgetting that group batching affects collection events only, not any
  separate list or observable helper you compose beside it.

## Related Primitives

- [Composite Family](composite-family.md)
- [Component Family](component-family.md)
- [Capability Families](../capability-families.md)
- [Builders, Collections & Tree Utilities](../builders-collections-tree-utilities.md)
