# 14 — Capability micro-interfaces

Capability interfaces are small, opt-in contracts that describe **what a VM can
do**, not what it is. They never alter the shape of an existing VM type; a
`ComponentVM`, `CompositeVM`, `GroupVM`, or `AggregateVM` is unchanged unless it
chooses (or its consumer chooses, via a wrapper) to additionally implement one
or more capabilities.

This chapter lists the 22 capability interfaces, their members, and the rules
that govern how they compose with the existing VM hierarchy.

## 1. Why capability interfaces

The legacy 2012 VMx encoded most user-visible behavior as small marker /
behavior interfaces (e.g., `ISelectable`, `IExpandable`, `INewCreatable`). The
current VMx replaces that with fewer, broader VM types. The two styles are not
mutually exclusive: capability interfaces give consumers a way to write
**capability-based code** ("show a Close button if and only if the VM is
`IClosable`") without changing the shape of the base VM types.

See ADR-0010 for the rationale and the decision to absorb these interfaces
additively rather than restructuring the existing VM hierarchy around them.

## 2. The 22 capabilities

Capabilities are grouped by intent. Every capability is independently
implementable; a VM may implement any subset.

### 2.1 Selection capabilities

```
ISelectable:
    can_select() : bool
    select() : void

IDeselectable:
    can_deselect() : bool
    deselect() : void

ISelectionTogglable:
    can_toggle_selection() : bool
    toggle_selection() : void
```

### 2.2 Expansion capabilities

```
IExpandable:
    IsExpanded : bool        # read-only on this contract; setter (if any) is
                             # provided by the concrete VM
    can_expand() : bool
    expand() : void

ICollapsible:
    can_collapse() : bool
    collapse() : void

IExpansionTogglable:
    can_toggle_expansion() : bool
    toggle_expansion() : void
```

### 2.3 Lifecycle capabilities

```
IConstructable:
    can_construct() : bool
    construct() : void / async

IDestructable:
    can_destruct() : bool
    destruct() : void / async

IReconstructable:
    can_reconstruct() : bool
    reconstruct() : void / async
```

The three lifecycle capabilities mirror the operations already defined in
`02-lifecycle.md`. A VM that implements the full lifecycle (every VM in the
core library) implements all three by virtue of its base type. The interfaces
exist so that **consumers** can express dependencies on partial lifecycles —
for example, a button binding that only requires `IReconstructable`.

### 2.4 Dialog / form capabilities

```
IClosable:
    can_close() : bool
    close() : void

IApprovable:
    can_approve() : bool
    approve() : void

ICancelable:
    can_cancel() : bool
    cancel() : void
```

### 2.5 Search capability

```
ISearchable:
    SearchTerm : string      # read/write; emits PropertyChangedMessage on
                             # change
    can_search() : bool
    search() : void          # apply current SearchTerm
```

### 2.6 Filter capability

```
IFilterable<TItem>:
    Filter : Predicate<TItem>?  # null means no filter; setter triggers re-filter
    can_filter() : bool         # whether filtering is currently allowed
```

The capability says nothing about _how_ the filtered view is exposed (an
observable, a paged slice, a snapshot) — that is the concrete collection's
responsibility. `SearchableState<TItem>` (per ADR-0014) provides a
string-debounced predicate builder over this capability.

See ADR-0022.

### 2.7 CRUD capabilities

```
INewCreatable:
    can_create_new() : bool
    create_new() : void

IDeletable<T>:
    can_delete(item: T) : bool
    delete(item: T) : void

IUpdatable<T>:
    can_update(item: T) : bool
    update(item: T) : void

ISavable<T>:
    can_save(item: T) : bool
    save(item: T) : void
```

### 2.8 Container-current capabilities

```
ICurrentDeletable:
    can_delete_current() : bool
    delete_current() : void

ICurrentUpdatable:
    can_update_current() : bool
    update_current() : void
```

### 2.9 Generic management capability

```
IManagable<T>:
    can_manage(item: T) : bool
    manage(item: T) : void
```

`IManagable<T>` is the **generic escape-hatch management capability**: `manage(item)`
routes the consumer to whatever item-scoped management surface the implementing VM
defines (open an editor/detail view for `item`, invoke a context action, etc.), and
`can_manage(item)` reports whether that action is currently available for `item`.
Unlike the specific CRUD verbs (§2.7) it prescribes **no** concrete effect — it
exists so a consumer can advertise a single "Manage…" affordance for VMs whose
management action does not map onto create/update/delete/save. As with every verb
capability (§3 Rule 4), `manage(item)` must not be called when `can_manage(item)`
is `false`; doing so is implementation-defined. `IManagable<T>` is intentionally
retained as a thin, behaviour-agnostic contract; ADR-0051 records the decision to
define its semantics in place rather than drop it, and to leave the broader
capability-surface consolidation (collapsing the togglable triples / parameterizing
the CRUD cluster) as a rejected breaking change.

### 2.10 Paging capability

```
IPageable:
    PageSize         : int   # mutable; 0 means "all items in one page"
    CurrentPageIndex : int   # mutable; clamped to [0, max(0, PageCount-1)]
                             # (an empty source has PageCount == 0 and clamps to 0 — see 21 §5.4)
    PageCount        : int   # derived: ceil(itemCount / PageSize), or 1 when PageSize == 0
    IsPagingEnabled  : bool  # derived: PageSize > 0
    move_to_first_page()     # no-op when CurrentPageIndex == 0
    move_to_previous_page()  # no-op at lower bound
    move_to_next_page()      # no-op at upper bound
    move_to_last_page()      # no-op when at last page
```

The capability describes the _navigation surface_ of a paged view; the
underlying composition is not mutated. `PagedComposition<TVM>` (see
chapter 21) is the canonical helper that decorates any composition with
this capability.

See ADR-0023.

## 3. Rules

1. **Additive only.** Adding a capability interface to a VM type is a
   non-breaking change. Removing one is a breaking change.
1. **No implicit implementation.** The core VM types (`ComponentVM`,
   `CompositeVM`, `GroupVM`, `AggregateVM`) do NOT automatically implement
   capability interfaces beyond the trivially-satisfied lifecycle three
   (`IConstructable`, `IDestructable`, `IReconstructable`). Consumers wanting
   capability-based dispatch must either (a) subclass and implement, or (b)
   use a wrapper that adds the capability.
1. **Capability composition.** A single VM may implement any number of
   capabilities. There is no exclusivity constraint.
1. **`can_*` precedes the verb.** Every capability whose verb can be invalid
   also exposes a `can_*` predicate, and the verb must not be called when
   `can_*` returns false — calling regardless is implementation-defined
   behavior (typically a raised exception or a no-op, decided per
   implementation). Verb families defined as bound-safe need no predicate:
   `IPageable`'s `move_to_*` methods (§2.10) clamp at the page bounds by
   contract, so every call is legal. (Scoped in v2.5.0 via ADR-0038.)
1. **Per-language idiom.** Capability interfaces follow the per-language
   identifier convention from ADR-0006 (PascalCase in C#, snake_case in
   Python, camelCase in TypeScript). The conceptual surface is identical.
1. **Capabilities do not subscribe to the hub on their own.** Capability
   interfaces define member contracts only. Any change-notification side
   effects (e.g., `PropertyChangedMessage` when `SearchTerm` mutates) come
   from the implementing class, not from the capability interface.

## 4. Capability-aware consumers

A consumer that wants to render a context menu of available actions for a VM
might write (pseudo-code):

```
actions = []
if vm is ISelectable:           actions.append("Select")
if vm is IExpandable:           actions.append("Expand")
if vm is IClosable:             actions.append("Close")
if vm is INewCreatable:         actions.append("New")
if vm is ICurrentDeletable:     actions.append("Delete current")
```

Each branch is independent. The consumer needs no knowledge of the VM's
concrete type.

## 5. Conformance

`CAP-001` through `CAP-022` in `12-conformance.md` cover the 22 capability
interfaces. Each test verifies that:

- the interface exists in the flavor's public surface
- the documented members are present with the documented signatures
- a fixture class implementing the capability satisfies the per-interface
  semantic contract (where one applies)

The opt-in rule (Rule 2) is covered by `CAP-020`: a default-built
`ComponentVM` must NOT satisfy `ISelectable` / `IExpandable` / `IClosable`
etc.

The composition rule (Rule 3) is covered by `CAP-019`: a fixture class can
satisfy any combination of capability interfaces simultaneously.
