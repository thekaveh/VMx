# 6.4. Capability Families

## 6.4.1. When To Use It

Use capability interfaces when consumers should depend on what a VM can do
rather than what concrete type it is. Capabilities are the additive behavior
surface of VMx.

## 6.4.2. Shape And Ownership

The 22 capabilities are grouped by intent:

- selection and expansion verbs
- lifecycle verbs
- dialog and form verbs
- search, filter, and paging
- CRUD and current-item CRUD
- generic management

Capabilities never reshape the core hierarchy. A VM advertises only the verbs it
actually supports.

## 6.4.3. Lifecycle And Messaging

Capabilities define contracts, not subscriptions. Any property-changed or
message-hub side effects come from the implementing VM or helper, not from the
interface itself.

The important rule is uniform across families: if a capability has a `can_*`
predicate, callers should respect it before invoking the verb.

## 6.4.4. Cross-Language Surface

Representative families:

| Family    | Examples                                                         |
| --------- | ---------------------------------------------------------------- |
| Selection | `ISelectable`, `IDeselectable`, `ISelectionTogglable`            |
| Expansion | `IExpandable`, `ICollapsible`, `IExpansionTogglable`             |
| CRUD      | `INewCreatable`, `IDeletable<T>`, `IUpdatable<T>`, `ISavable<T>` |
| Paging    | `IPageable`                                                      |

C#, Python, TypeScript, and Swift expose this conceptual set member-for-member,
with identifier casing adapted to each language. Rust is catalog-complete but
its capability-member convergence remains tracked in the
[Rust parity ledger](../../maintenance/2026-07-16-rust-capability-parity.md).

## 6.4.5. Example

Capability-aware consumers usually read like this in any flavor:

- show Select only when the VM is selectable
- show Expand only when the VM is expandable
- show Delete current only when the container exposes current-item delete

The Notes Workspace capability action bar is the concrete reference for this
style of consumer.

## 6.4.6. Common Pitfalls

- Treating capabilities as inheritance roots instead of additive contracts.
- Collapsing granular verbs into a coarser abstraction and losing intent.
- Forgetting that core VM types do not implicitly implement every capability.

## 6.4.7. Related Primitives

- [State & Reactive Helpers](state-reactive-helpers.md)
- [Command Families](command-families.md)
- [ViewModel Families](viewmodel-families/index.md)
