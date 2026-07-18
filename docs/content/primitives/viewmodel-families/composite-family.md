# 6.2.5. Composite Family

## 6.2.5.1. When To Use It

Use `CompositeVM<VM>` when the parent owns an ordered homogeneous child list and
one child may be current. Tabs, note lists, result lists, and other "collection
plus selection" workflows belong here.

Use the modeled composite when children are projected from models during
construction instead of being provided directly.

<img src="../../../assets/diagrams/composite-family.svg" alt="Composite Family Deep Dive" class="vmx-diagram" />

<p>
  <a href="../../../assets/diagrams/composite-family.html">HTML</a>
  &middot;
  <a href="../../../assets/diagrams/composite-family.svg">SVG</a>
  &middot;
  <a href="../../../assets/diagrams/composite-family.png">PNG</a>
</p>

## 6.2.5.2. Shape And Ownership

`CompositeVM` adds one core concept on top of a collection container:

- `Current` may be one child or `null`

Everything else follows from that contract: guarded selection helpers,
foreground updates of `IsCurrent`, and optional builder hooks for initial
selection and current-changed callbacks.

Composite implements the selectable extension of the shared
[VM Collection Contract](../vm-collection-contract.md). Its atomic move keeps
the identical child, parent, lifecycle, subscriptions, and `Current` reference.

Every child has one authoritative owning parent. Adding or inserting a child
that belongs to another mutable composite or group atomically removes it from
the old parent first. Duplicate identity and ancestor cycles are rejected. If
the destination attach fails, old membership, index, and selection are restored
without publishing a partial transfer.

The destination and staged old parent stay isolated until commit or rollback.
Structural mutation attempted re-entrantly from an auto-construction or
population hook is rejected before it can invalidate rollback state. Selection
validation and assignment share the membership gate, and deferred selection
rechecks that the candidate is still a child. The transaction also rechecks
destination disposal after auto-construction before it commits membership. If
user lifecycle code fails during compensation, VMx surfaces that rollback
failure instead of claiming that lifecycle state was restored exactly
(ADR-0118).

Old-parent disposal requested by an attachment hook waits for commit or
rollback. A committed transfer publishes old removal and new addition before a
throwing/result-based flavor surfaces any deferred disposal failure. When
attachment already failed, that earlier error remains primary after rollback
and disposal complete. A lazy population that already committed stays
materialized rather than evaluating its factory again (ADR-0122).

## 6.2.5.3. Lifecycle And Messaging

The composite owns both child lifecycle and selection messaging:

- `construct()` waits for every child before the composite reports constructed
- `destruct()` clears `Current` before destructing children
- `Current` changes publish the parent `Current` property and the affected
  children's `IsCurrent`
- disposal requested by a current-changed callback is deferred until the
  selection notification finishes and does not deadlock the callback
- `AsyncSelection(true)` routes selection work through the foreground
  dispatcher
- a non-batched move emits one move event with both indices; a batched move is
  represented by the outer reset

## 6.2.5.4. Cross-Language Surface

| Concept               | C#                      | Python                 | TypeScript             | Swift                  | Rust                        |
| --------------------- | ----------------------- | ---------------------- | ---------------------- | ---------------------- | --------------------------- |
| Type                  | `CompositeVM<VM>`       | `CompositeVM[VM]`      | `CompositeVM<VM>`      | `CompositeVM<VM>`      | `CompositeVm<VM>`           |
| Modeled type          | `CompositeVMOfM<M, VM>` | `CompositeVMOf[M, VM]` | `CompositeVMOf<M, VM>` | `CompositeVMOf<M, VM>` | `ModeledCompositeVm<M, VM>` |
| Selection slot        | `Current`               | `current`              | `current`              | `current`              | `current()`                 |
| Initial selector hook | `Current(selector)`     | `current(selector)`    | `current(selector)`    | `current(selector)`    | `current(selector)`         |

## 6.2.5.5. Example

=== "C#"

    ```csharp
    var tabs = CompositeVM<ComponentVM<TabModel>>.Builder()
        .Name("tab-bar")
        .Services(hub, dispatcher)
        .Children(() => new[] { home, settings })
        .Build();
    ```

=== "Python"

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

=== "TypeScript"

    ```ts
    const tabs = CompositeVM.builder<ComponentVMOf<TabModel>>()
      .name("tab-bar")
      .services(hub, dispatcher)
      .children(() => [home, settings])
      .build();
    ```

=== "Swift"

    ```swift
    let tabs = try CompositeVM<ComponentVMOf<TabModel>>.builder()
        .name("tab-bar")
        .services(hub: hub, dispatcher: dispatcher)
        .children { [home, settings] }
        .build()
    ```

=== "Rust"

    ```rust
    let tabs = CompositeVm::<ComponentVm<TabModel>>::builder()
        .name("tab-bar")
        .services(hub, dispatcher)
        .children(|| vec![home.clone(), settings.clone()])
        .build()?;
    ```

Rust ships both `CompositeVm` and `ModeledCompositeVm`; consult the active Rust
[parity ledger](../../../maintenance/2026-07-16-rust-capability-parity.md) for
the remaining member/edge gaps.

## 6.2.5.6. Common Pitfalls

- Using a composite for recursive trees. `HierarchicalVM` carries the tree
  semantics directly.
- Forgetting that `Current` must always be a contained child or `null`.
- Treating one child identity as simultaneous membership in multiple
  containers. Mutable attachment transfers ownership; aggregate slots must be
  released by replacing or rebuilding the aggregate instead.
- Assuming add-after-construct auto-constructs by default. It does not unless
  `AutoConstructOnAdd(true)` is enabled.
- Updating selection predicates without wiring current-changed triggers into
  commands that depend on selection.

## 6.2.5.7. Related Primitives

- [Group Family](group-family.md)
- [Hierarchical Family](hierarchical-family.md)
- [Command Families](../command-families.md)
- [State & Reactive Helpers](../state-reactive-helpers.md)
- [VM Collection Contract](../vm-collection-contract.md)
