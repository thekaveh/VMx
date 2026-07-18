# 6.2.4. Group Family

## 6.2.4.1. When To Use It

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

## 6.2.4.2. Shape And Ownership

`GroupVM` mirrors the list-management surface of `CompositeVM` without the
selection slot:

- ordered children
- add, insert, remove, replace, clear, atomic move, batch update
- collection-changed notifications
- no `Current`
- no `select_component` / `deselect_component`

The group itself is still a component and may be selected by its own parent.
It implements the base [VM Collection Contract](../vm-collection-contract.md),
not its selectable extension.

Group membership uses the same exclusive ownership protocol as composites.
Attaching a child owned by another mutable container is one atomic transfer:
the old removal precedes the new add notification, and a failed destination
attach restores the old index and parent link. Duplicate identity and ancestor
cycles are rejected before mutation.

Destination and old-parent membership remain isolated through hooks and
commit/rollback. Re-entrant structural mutation is rejected, reverse-order bulk
transfers use deterministic reservation ordering, destination disposal is
rechecked after auto-construction, and lifecycle compensation failures are
surfaced rather than swallowed (ADR-0118).

## 6.2.4.3. Lifecycle And Messaging

Lifecycle orchestration matches `CompositeVM`:

- construct waits for all children to reach `Constructed`
- destruct waits for all children to reach `Destructed`
- `AutoConstructOnAdd(true)` can opt into post-construct child auto-construct
- `BatchUpdate()` suppresses per-mutation collection events and emits one reset

Group children are peers. Their inherited select command must stay disabled
while the group is their parent.

## 6.2.4.4. Cross-Language Surface

| Concept         | C#                      | Python                 | TypeScript              | Swift                   | Rust                       |
| --------------- | ----------------------- | ---------------------- | ----------------------- | ----------------------- | -------------------------- |
| Type            | `GroupVM<VM>`           | `GroupVM[VM]`          | `GroupVM<VM>`           | `GroupVM<VM>`           | `GroupVm<VM>`              |
| Builder entry   | `GroupVM<VM>.Builder()` | `GroupVMBuilder[VM]()` | `GroupVM.builder<VM>()` | `GroupVM<VM>.builder()` | `GroupVm::<VM>::builder()` |
| Children setter | `Children(...)`         | `children(...)`        | `children(...)`         | `children { ... }`      | `children(...)`            |

## 6.2.4.5. Example

Representative build shape:

- `C#`: `GroupVM<IComponentVM>.Builder().Name("actions").Services(hub, dispatcher).Children(() => new[] { save, delete }).Build()`
- `Python`: `GroupVMBuilder[ComponentVMProto]().name("actions").services(hub, dispatcher).children(lambda: [save, delete]).build()`
- `TypeScript`: `GroupVM.builder<ComponentVMBase>().name("actions").services(hub, dispatcher).children(() => [save, delete]).build()`
- `Swift`: `try GroupVM<ComponentVMBase>.builder().name("actions").services(hub: hub, dispatcher: dispatcher).children { [save, delete] }.build()`
- `Rust`: `GroupVm::<ComponentVm<_>>::builder().name("actions").services(hub, dispatcher).children(|| vec![save.clone(), delete.clone()]).build()?`

Rust ships the same peer-container and builder concepts; consult the active
[Rust parity ledger](../../../maintenance/2026-07-16-rust-capability-parity.md)
for the remaining member/edge gaps.

## 6.2.4.6. Common Pitfalls

- Reaching for `GroupVM` when the UI has one meaningful active child. That is
  `CompositeVM`.
- Assuming peer children become selectable because they inherit leaf commands.
  The group contract keeps those commands disabled.
- Expecting a child to remain in its former parent after adding it here. VMx
  transfers mutable ownership rather than permitting two parent lists.
- Forgetting that group batching affects collection events only, not any
  separate list or observable helper you compose beside it.

## 6.2.4.7. Related Primitives

- [Composite Family](composite-family.md)
- [Component Family](component-family.md)
- [Capability Families](../capability-families.md)
- [Builders, Collections & Tree Utilities](../builders-collections-tree-utilities.md)
- [VM Collection Contract](../vm-collection-contract.md)
