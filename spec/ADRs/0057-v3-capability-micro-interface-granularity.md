# ADR 0057 — v3 capability micro-interface granularity: keep the families, clarify the chapter

**Status:** Accepted (2026-06-28)
**Spec version:** 3.0.0

## 1. Context

The framework-merged critique (`docs/audit/2026-06-27-vmx-merged-critique.md`,
**VMX-123**, Minor) raised two concerns about `14-capabilities.md`'s 22
capability micro-interfaces:

1. **`IManagable<T>` had no defined semantics.** — Already addressed in
   **ADR-0051 §2.4**, which defined `IManagable<T>` as the generic escape-hatch
   management capability and retained it. That half is closed and is **not**
   revisited here.
1. **Over-fragmentation.** — The selection and expansion families are each a
   three-member *triple* (`ISelectable` / `IDeselectable` /
   `ISelectionTogglable`; `IExpandable` / `ICollapsible` / `IExpansionTogglable`)
   in which the `…Togglable` member "mirrors" the two singular verbs, and the
   CRUD/container-current surface spans seven interfaces (`INewCreatable`,
   `IDeletable<T>`, `IUpdatable<T>`, `ISavable<T>`, `ICurrentDeletable`,
   `ICurrentUpdatable`, plus the generic `IManagable<T>`). The audit's
   recommendation was to *collapse the togglable triples into one toggle
   interface* and *parameterize the CRUD cluster into fewer contracts*.

ADR-0051 §2.4 already rejected the collapse in passing, as "out of scope for a
documentation reconciliation." This ADR is the **dedicated, per-cluster record**
of that engineering decision and the chapter-clarity changes that make the
granularity read as deliberate. It must be read against **ADR-0010**, which
established the additive, opt-in capability micro-interface philosophy — a VM
advertises *exactly* the verbs it supports, and a consumer depends on *exactly*
the verb it needs, rather than branching on concrete VM type.

## 2. Decision

**Keep all 22 capability interfaces; merge or remove none.** The "fragmentation"
is the intended granularity of ADR-0010. The chapter is reorganized for clarity
so the deliberateness is explicit. **No interface, member, conformance ID
(`CAP-001..CAP-022`), or catalog count changes.** This is a documentation /
clarification change only; the four flavors' `capabilities/` surfaces are
untouched.

### 2.1 Selection / expansion triples — KEEP (with documented composition)

The `…Togglable` member of each triple is **not** redundant with the two
singular verbs, so the triple is **not** a tautology that consolidating into a
single toggle interface would simplify without loss:

- A VM may implement the two singular verbs (`select()` / `deselect()`) **without**
  a single toggle affordance, or implement `ISelectionTogglable` **alone** (a
  checkbox-style row whose only action is "flip my selection"). The same holds
  for `IExpandable` / `ICollapsible` vs `IExpansionTogglable`.
- When all three are present, `toggle_selection()` / `toggle_expansion()` is
  expected to delegate to the singular verbs, **but** the toggle predicate
  (`can_toggle_selection()` / `can_toggle_expansion()`) is an independent
  capability that need not equal `can_select() || can_deselect()`.

Collapsing the triple into one interface would force every selectable VM to also
advertise a toggle (and vice versa), erasing exactly the opt-in discrimination
ADR-0010 exists to provide. **Decision: keep all six interfaces.** The
composition relationship is now stated explicitly in `14-capabilities.md` §2.1
and §2.2.

### 2.2 CRUD cluster — KEEP (with documented parameterization)

The CRUD verbs are **four independent capabilities each parameterized by the
item type they act on** (`<T>`), not one monolithic `ICrud<T>`:

- `INewCreatable` is unparameterized (creation takes no existing item).
- `IDeletable<T>` / `IUpdatable<T>` / `ISavable<T>` each take `item: T`.
- `ICurrentDeletable` / `ICurrentUpdatable` (§2.8) are the **item-argument-free**
  variants of delete/update that act on the implementing container's own
  `Current` selection.

A single parameterized `ICrud<T>` would force every implementer to advertise
(and no-op-or-throw) verbs it does not offer — a read-and-create-only surface
would have to expose `delete` / `update` / `save` it cannot honour, defeating
the capability-as-discrimination contract. **Decision: keep the cluster
granular.** The parameterization and the singular-vs-current relationship are
now stated explicitly in `14-capabilities.md` §2.7.

### 2.3 Chapter organization — clarify

`14-capabilities.md` §2 gains an explicit **family-taxonomy table** (the ten
families and their members) and a paragraph stating that the per-verb
granularity is deliberate (cross-referencing ADR-0010 and this ADR). The §2.1 /
§2.2 / §2.7 composition notes above are added. The §2.9 `IManagable<T>` closing
paragraph (from ADR-0051) now also forward-references this ADR.

## 3. New conformance IDs

**None.** No interface is added, removed, merged, or re-signatured, so the
catalog total and chapter count are unchanged: the capability set stays at **22
interfaces / `CAP-001..CAP-022`**. The merged-critique recommendation to collapse
the togglable triples and parameterize the CRUD cluster is **rejected** as a
breaking re-shaping of the capability surface (it would change every
implementing VM's advertised contract set) for a Minor, documentation-grade
benefit.

## 4. Consequences

- The "22 interfaces" no longer read as accidental fragmentation: the family
  taxonomy is enumerated up front, and the singular-vs-togglable and
  CRUD-parameterization relationships are documented at their point of use.
- VMX-123 is fully closed: the `IManagable<T>`-semantics half by ADR-0051, the
  over-fragmentation half by this keep-with-rationale decision.
- The capability surface (`CAP-001..CAP-022`, all four flavors' `capabilities/`
  directories) is unchanged; no conformance, coverage-tool, or version impact.

## 5. Rejected alternatives

- **Collapse the selection/expansion triples into one toggle interface** —
  rejected: the toggle predicate is an independent capability, and forcing every
  selectable/expandable VM to advertise a toggle (and vice versa) erases the
  opt-in discrimination of ADR-0010; it is also a breaking change to
  `CAP-003` / `CAP-006` and the four flavors' public surfaces.
- **Parameterize the CRUD cluster into one `ICrud<T>`** — rejected: it forces
  implementers to advertise verbs they do not support, defeating
  capability-as-discrimination; breaking to `CAP-013..CAP-017`.
- **Drop `IManagable<T>`** — already rejected and resolved in ADR-0051 §2.4 (its
  semantics are now defined); not reopened here.
