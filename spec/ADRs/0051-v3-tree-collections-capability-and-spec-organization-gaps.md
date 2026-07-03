# ADR 0051 — v3 spec reconciliation: tree/collections, capability, and spec-organization gaps; feature-port decisions

**Status:** Accepted (2026-06-28)
**Spec version:** 3.0.0

## 1. Context

The final spec-reconciliation pass of the v3 overhaul closes the remaining
pre-existing spec gaps surfaced by the framework-merged critique
(`docs/audit/2026-06-27-vmx-merged-critique.md`). Every gap here is a
**documentation / clarification defect — the shipped code is already correct**.
No runtime behaviour changes, no public surface changes, and (per §3) no new
conformance IDs are introduced. The findings reconciled, grouped by cluster:

- **Tree / collections** — VMX-112 (`walk_expanded` aggregate-slot descent left
  implicit in the pseudocode), VMX-109 (`ObservableList<T>` nested-batch
  ref-counting and empty-batch-no-event unspecified), VMX-113 (`CurrentPageIndex`
  clamp contradicting the empty-source case).
- **Capability / validation / persistence** — `IManagable<T>` undefined semantics
  (the undefined-semantics half of VMX-123), VMX-051 (no validation framework),
  VMX-125 (no persistence port, no undo/redo).
- **Spec organization / dangling references** — VMX-124 (`ICompositeVM<VM>`
  referenced but declared only inline; FormVM-vs-`ComponentVM<M>` overlap; ch.07
  paraphrase; scattered `*State` helpers; missing ADR pointer at 15 §8),
  VMX-050 (`proposals/` labelled "historical" yet normatively referenced),
  VMX-115 (implementation-defined / MAY behaviours carrying no conformance ID),
  VMX-116 (`IDialogService` cancellation opt-in makes `DIA-007` non-universal).

## 2. Decision

### 2.1 `walk_expanded` descends aggregate slots (VMX-112)

`13-tree-utilities.md` §5 previously wrote `if root has children`, which read as
composite/group descent only. All four full-parity implementations
already share **one** descent helper between `walk` and `walk_expanded`, so an
`AggregateVMN`'s non-null `Component1, Component2, …` slots are traversed by
`walk_expanded` exactly as by `walk`, gated only by the `IExpandable` check. The
§5 pseudocode now mirrors `walk`'s explicit `CompositeVM` / `GroupVM` /
`AggregateVMN` cases, and a new property bullet states the shared-descent-set
contract. **Documentation only** — `langs/{python,typescript,csharp}` `walk.py` /
`walk.ts` / `Tree.cs` already do this. No new conformance ID: the aggregate-slot
descent is the same container set `walk` covers under `UTIL-002`, and
`walk_expanded`'s expansion gate is covered by `EXP-005`; extending an aggregate
fixture to `walk_expanded` is recorded as optional test-strengthening, not a new
normative behaviour.

### 2.2 `ObservableList<T>` nested-batch and empty-batch semantics (VMX-109)

`21-collections.md` §3.5 now states normatively that an `ObservableList<T>` batch
(a) emits its single `Reset` **only if at least one mutation occurred** (empty
batch ⇒ no event), and (b) **ref-counts nested scopes** so only the outermost
completion emits the `Reset`. This mirrors the rules `CompositeVM.BatchUpdate()`
(06 §4.1) and `GroupVM.BatchUpdate()` (07 §5) already carry, and matches the
shipped implementations (e.g. Python `observable_list.py` `_batch_depth` /
`_mutated_in_batch`). **Documentation only.** Extending `COMP-013` / `GRP-006` /
`COL-009` to assert the nested-and-empty paths is recorded as accepted
test-strengthening future work (the behaviour is now normative; the present test
bodies exercise a single non-empty batch).

### 2.3 `CurrentPageIndex` clamp wording (VMX-113)

`14-capabilities.md` §2.10 and `21-collections.md` §5.1/§5.2 said the index is
"clamped to `[0, PageCount-1]`", which yields `[0, -1]` for an empty source
(`PageCount == 0`) and contradicts §5.4 / `COL-020`. Reworded to
`[0, max(0, PageCount-1)]` with an inline pointer to the empty-source rule.
Trivial wording fix; the implementations already clamp to `0`.

### 2.4 `IManagable<T>` semantics (undefined-semantics half of VMX-123)

`14-capabilities.md` §2.9 now defines `IManagable<T>` as the **generic
escape-hatch management capability**: `manage(item)` routes to the implementing
VM's item-scoped management surface, `can_manage(item)` reports availability, and
— unlike the §2.7 CRUD verbs — it prescribes no concrete effect by design. The
contract is **retained, not dropped**. The broader VMX-123 recommendation to
collapse the togglable triples and parameterize the CRUD cluster is **rejected**:
it is a breaking re-shaping of the capability surface (ADR-0010), out of scope for
a documentation reconciliation.

### 2.5 `ICompositeVM<VM>` declared canonically (VMX-124)

`ICompositeVM<VM>` was referenced as canonical in `09-forwarding.md` but declared
only inline there. It is now declared in `06-composite-vm.md` §2.1 (extends
`IComponentVM` + `IList<VM>` with `Current` and the `*_component` selection
methods), and chapter 09 references that declaration instead of re-stating it.

### 2.6 FormVM / validation / persistence positioning (VMX-124, VMX-051, VMX-125)

`20-form-vm.md` gains a §1.1 that:

- **Justifies `FormVM<TM>` as its own type** (VMX-124): it is not a
  `ComponentVM<M>` + `OnModelChanged` recipe — it adds the snapshot / dirty /
  revert / approve **edit lifecycle** the leaf model-VM has no notion of. ADR-0030
  is cited for the original rationale.
- **Documents that validation is composed via `DerivedProperty`** (VMX-051):
  `FormVM` ships no validation framework by design; a form's `IsValid` is a
  consumer-built `DerivedProperty<bool>` that strict mode gates alongside
  `IsDirty`. A first-class `IValidator<TM>` / `IsValid` surface is **accepted as
  future work** — additive opt-in, not introduced here.
- **Documents persistence as a consumer concern** (VMX-125): the
  consumer-supplied delegate / `IFormPersister<TM>` *is* the persistence seam;
  per `00-overview.md` §2, persistence/serialization/routing are out of framework
  scope, so a flagship owning its own `INoteRepository` is by design. A generalized
  `IRepository<T>` port and a command-level **undo/redo** stack are **deferred
  future work** — both new opt-in sub-packages, neither a clarification.

### 2.7 `proposals/` normative-reference caveat (VMX-050)

`spec/README.md` §1.10 no longer calls `proposals/` flatly "not part of the
published spec". It now caveats that where `12-conformance.md` cites a proposal's
**scenario contract**, that contract is normative — concretely the ThemeVM
`THEME-001..THEME-005` IDs (§28, ADR-0036 §2.C) — even though the surrounding
proposal prose remains historical. (Elevating the ThemeVM scenario to a full
numbered chapter was considered and rejected: it is an example-app contract built
from existing core primitives with no new core types, so a chapter would overstate
it; the caveat is the accurate, non-breaking fix.)

### 2.8 `IDialogService` cancellation normativity (VMX-116)

`19-dialogs.md` §6 now states that cancellation support is opt-in and the
non-throwing-completion rule is **conditionally normative**: universal *within*
the set of implementations that surface a cancellation channel, vacuous for those
(like `NullDialogService`) that do not. `DIA-007`'s own text already scopes itself
to "implementations that opt into a cancellation channel", so no test change is
needed. Making non-throwing completion unconditional for *every* implementation
was **rejected** — a host with no cancellation channel has nothing to make
non-throwing.

### 2.9 Implementation-defined behaviour register (VMX-115)

Several behaviours are explicitly `MAY` / implementation-defined and therefore
carry **no conformance ID by design** — pinning them to a universal assertion
would contradict the latitude the spec grants. They are catalogued here so future
audits stop re-flagging the absence of an ID as a gap:

| Behaviour                                                            | Spec locus       | Status                                                                                                                  |
| -------------------------------------------------------------------- | ---------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `DerivedProperty.SetValue` after `Dispose()` (no-op **or** raise)    | `15` §4          | Implementation-defined; spec forbids only further `ValueChanged` emission. No universal ID.                             |
| Re-`Post`ing the same pending `Notification` instance                | `16` §2.1        | Implementation-defined; SHOULD return the existing awaitable. A future minor MAY make it a normative no-op + add an ID. |
| Post-`Dispose` `IsCurrent` selection change                          | `02` invariant 3 | Already pinned: a normative **silent no-op** (ADR-0047 / VMX-006), distinct from the raising lifecycle ops.             |
| `AutoConstructOnAdd` child-construct vs `CollectionChanged` ordering | `06` §5.1        | Normatively ordered (construct completes **before** the event); the *visit order* across children is unspecified by §5. |

Where a row is genuinely impl-defined (rows 1–2) it stays id-free; rows 3–4 are
already covered or already ordered, recorded here only to close the finding.

### 2.10 Cross-reference and ADR-pointer hygiene (VMX-124, residual)

- `15-derived-properties.md` §8 now points the obsolete-`InitializationTokens`
  note at [ADR-0011](0011-derived-properties.md).
- **Reducing ch.07 to a delta** is treated as already-satisfied: `07-group-vm.md`
  is 78 lines and already frames itself as "identical to `CompositeVM<VM>` minus
  the `Current` slot", with only the genuinely different members spelled out. No
  edit; recorded as no-action.
- **Consolidating the scattered `*State` helpers** (SearchableState 06 §8 / 14
  §2.6; ExpandableState 13 §7 / 14 §2.2; DerivedProperty ch.15) is **rejected** as
  a churn-for-churn reorganization: each helper is documented at its point of use
  with capability cross-references already in place, and moving them would break
  stable section anchors for no normative gain.

## 3. New conformance IDs

**None.** Every change here is a clarification of already-tested or
explicitly-impl-defined behaviour. The catalog total stays at **241 (236 library +
5 THEME scenario IDs)**; chapter count stays at 22. The optional test-strengthening
noted in §2.1 / §2.2 (aggregate `walk_expanded`, nested/empty batch) extends
existing IDs and is left as future work.

## 4. Consequences

- The reference implementations are now fully described: `walk_expanded`'s
  aggregate descent, `ObservableList<T>` nesting, and the page-index clamp no
  longer read as ambiguous or self-contradictory.
- `ICompositeVM<VM>` has one canonical declaration; `09-forwarding.md` no longer
  carries a shadow inline definition.
- `IManagable<T>` has defined semantics, so it is no longer a bare two-method
  contract.
- The validation, persistence, and undo/redo recommendations have an explicit,
  recorded disposition (compose-via-`DerivedProperty` now; `IValidator`,
  `IRepository<T>`, and undo/redo as opt-in future sub-packages) rather than being
  silently open.
- `proposals/`'s normative-reference exception is documented, reconciling the
  "historical" label with `12-conformance.md` §28.
- The implementation-defined-behaviour register gives future audits a single place
  to confirm that an absent conformance ID is by design.

## 5. Alternatives considered

- **Adding conformance IDs for the impl-defined behaviours (VMX-115)** — rejected:
  the spec deliberately grants `MAY` latitude there; a universal assertion would
  contradict it. The register documents the intent instead.
- **Elevating the ThemeVM scenario to a numbered chapter (VMX-050)** — rejected:
  it is an example-app contract over existing primitives with no new core types; a
  chapter would overstate it. A caveat on the `proposals/` label is the accurate
  fix.
- **Collapsing the capability surface / parameterizing CRUD (VMX-123)** — rejected
  as a breaking re-shaping out of scope for a doc reconciliation; only the
  undefined-`IManagable` half is addressed.
- **Shipping `IValidator<TM>`, `IRepository<T>`, and an undo/redo stack now
  (VMX-051 / VMX-125)** — deferred: all three are additive opt-in features, not
  reconciliations; the v3 documentation pass records the seams (`DerivedProperty`
  for validity, `IFormPersister<TM>` for persistence) the framework already
  provides.
- **Consolidating the `*State` helpers and re-deltaing ch.07 (VMX-124)** —
  declined: ch.07 is already a delta, and moving the helper docs would break stable
  anchors for no normative benefit.
