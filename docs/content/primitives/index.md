# 6.1. Framework Primitives

VMx is one language-neutral framework surface in five idiomatic source
flavors. These pages map that surface. Each page tells which primitive to use,
what it owns, and how it takes part in lifecycle and messaging. It also tells
where the Notes Workspace examples use the primitive.

## 6.1.1. Choose A Page

Choose the VM shape that owns the concern first. Then add behavior, helpers,
and services:

- [ViewModel Families](viewmodel-families/index.md): the VM shapes. These are
  the component, aggregate, group, composite, hierarchical, and
  forwarding-wrapper families, and the specialized workflow VMs such as
  `FormVM` and `ModalVM`.
- [Command Families](command-families.md): executable, bindable behavior and
  its decorators.
- [Capability Families](capability-families.md): opt-in behavior interfaces
  such as selection, expansion, and paging.
- [State & Reactive Helpers](state-reactive-helpers.md): async resources,
  delayed work, search, derived values, and expansion state.
- [Services, Messages & Dispatching](services-messages-dispatching.md): the
  message hub, hub transactions, dispatchers, and host wiring.
- [Builders, Collections & Tree Utilities](builders-collections-tree-utilities.md):
  construction, observable and serviced collections, paging compositions, and
  tree traversal.
- [Disposal Contract](disposal-contract.md): what disposal releases for each
  type, and the differences between flavors.
- [VM Collection Contract](vm-collection-contract.md): the ordered child
  collection that composites and groups share.

## 6.1.2. Cross-Language Surface

The concepts have the same meaning in every flavor. Only their spelling follows
the language idiom, as
[Cross-Language Naming](../flavors/cross-language-naming.md) shows. The
[Rust parity ledger](../../maintenance/2026-07-16-rust-capability-parity.md)
lists the open Rust items and the recorded differences.
