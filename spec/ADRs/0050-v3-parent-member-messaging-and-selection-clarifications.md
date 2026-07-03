# ADR 0050 — v3 spec reconciliation: `Parent` member, `whenPropertyChanged`, and selection clarifications

**Status:** Accepted (2026-06-28)
**Spec version:** 3.0.0

## 1. Context

The v3 framework overhaul reconciles the spec with the framework-merged critique
(`docs/audit/2026-06-27-vmx-merged-critique.md`). This ADR closes four
documentation gaps where the implemented behaviour was correct but the prose was
missing, ambiguous, or self-contradictory. None of these change runtime behaviour;
the helper and the wiring already shipped (`whenPropertyChanged` landed in commit
`261056c`, the `Parent` back-reference predates v3). The findings reconciled here:

- **VMX-017** — cross-VM hub subscriptions were hand-wired `OfType/instanceof + ReferenceEquals/===` filters copy-pasted across all three flagships. A typed
  `whenPropertyChanged(hub, sender, prop)` helper now exists in every full-parity
  flavor but was undocumented in the spec.
- **VMX-040** — `Parent` is read by every selection predicate in `05` §6
  (`Parent`, `Parent.Current`) and by `IsCurrent`, yet it was never declared as a
  member: no type, nullability, set/clear timing, or observability.
- **VMX-039** — `SelectNextCommand` / `SelectPreviousCommand` were described in
  `05` §5 with sibling-navigation semantics, but the reference implementations leave
  their predicate permanently `false` and their task a no-op. The intended-vs-actual
  gap was undocumented (only `GRP-002` hinted at it for the group case).
- **VMX-045** — `06` §3.2 said the initial-current selector assigns "via the existing
  `SelectComponent` path", which raises on a non-child (§3.1, `COMP-009`), directly
  contradicting the same paragraph's (and ADR-0042 §5.4's) silent-no-op rule for an
  out-of-set selector return.

## 2. Decision

### 2.1 Document `whenPropertyChanged` (VMX-017)

`03-messages.md` §7 is restructured into §7.1 (`PropertyValueChangedMessagesFor`,
the value-projecting helper, unchanged) and a new §7.2 documenting
`whenPropertyChanged` as the **canonical typed primitive for a cross-VM
subscription**. It filters `Messages` to `PropertyChangedMessage` events whose
runtime sender is reference-equal to a given `sender` and whose `PropertyName`
matches exactly (idiomatic-cased per ADR-0006), and emits the matching **message**
(versus §7.1, which emits the projected value). The C# extension matches across the
covariant `IPropertyChangedMessage<TSender>`; null arguments raise.

Like `PropertyValueChangedMessagesFor` (ADR-0032), the helper is **informative** —
it carries **no conformance ID**, because the underlying `Messages` stream is the
conformance-tested contract. Each full-parity flavor already covers it with a unit
test (`WhenPropertyChangedTests` / `test_when_property_changed` /
`whenPropertyChanged.test.ts`). Adding a `HUB-NNN` would duplicate the `Messages`
contract for an ergonomic wrapper, so we deliberately keep it id-free, matching the
sibling helper's precedent.

Per-flavor entry points: `IMessageHub.WhenPropertyChanged` (C#),
`vmx.messages.when_property_changed` (Python), `whenPropertyChanged` from
`src/messages` (TypeScript), and `MessageHubProtocol.whenPropertyChanged` (Swift).

### 2.2 Declare the `Parent` member (VMX-040)

`01-concepts.md` §1.3 and `05-component-vm.md` (§2 note, new §6.1) now declare
`Parent` as an **internal back-reference**, documenting exactly what the reference
implementations do rather than inventing a new public member:

- **Type** — the owning container (`CompositeVM` or `GroupVM`), or `null`. Reference
  implementations type it as a minimal internal parent interface exposing only the
  selection-delegation members the child needs (`IParentCompositeVM` in C#,
  `_ParentCompositeVM` in Python, `IParentVM` in TypeScript), not the full container.
- **Nullability** — `null` whenever the VM is not a member of any container.
- **Set/clear timing** — the container sets it to itself when the child is added
  (`Add` / `Insert`, or wired as a child at build time) and clears it to `null` when
  the child is removed (`Remove` / `RemoveAt` / `Clear`) or re-parented.
- **Observability** — **none**. `Parent` is not consumer-settable and a change to it
  does NOT publish a `PropertyChangedMessage`. Its effect is observed only indirectly,
  through the selection predicates and `select()`/`deselect()` delegation.

This is the most faithful reconciliation: declaring `Parent` as a public, observable
`ICompositeVM?` (as the audit's suggested fix sketched) would have over-stated the
implementation, which keeps the reference deliberately internal so the public
`IComponentVM` surface carries no mutator. We instead declare the contract the code
actually honours.

### 2.3 Clarify `SelectNext` / `SelectPrevious` (VMX-039)

`05-component-vm.md` §5 now states normatively that these two baseline commands have
a predicate that **always returns `false`** and a **no-op** task in the reference
implementations of all four flavors — a leaf VM does not enumerate its parent's
children. The table's sibling-navigation rows describe the *intended* semantics a
container MAY implement, not behaviour the base leaf performs. The inert base
behaviour is already asserted for the group case by `GRP-002`; no new conformance ID
is added, because there is no new testable behaviour (an always-false predicate is
covered by existing presence/always-false assertions).

### 2.4 Reconcile the initial-current selector (VMX-045)

`06-composite-vm.md` §3.2 now states the `Current(selector)` return is applied
through an internal **non-raising validated assignment**, explicitly NOT the guarded
`select_component` path (which raises on a non-child per §3.1 / `COMP-009`). A
contained child triggers the normal `Current` transition; a `null` or out-of-set
return is a **silent no-op** (`Current` unchanged, no notification), matching
ADR-0042 §5.4 and the behaviour `COMP-025` already asserts. ADR-0042 §5.1's
"`SelectComponent` path" phrasing is superseded by this clarification.

## 3. New conformance ID

- **`COMP-027`** — Adding a child to a `Constructed` `CompositeVM` sets the child's
  `Parent` (the child becomes selectable and `select()` delegates through it);
  removing it clears the `Parent` (the child is no longer selectable and `select()`
  becomes a no-op). Real passing tests ship in C# / Python / TypeScript per
  `spec-discipline.yml`. Swift is unaffected: `COMP-027` is not added to
  `langs/swift/conformance-subset.txt`, so the subset stays at 41 IDs.

`12-conformance.md` catalog total goes from 240 to 241 (236 library + 5 THEME
scenario IDs). Chapter count stays at 22.

## 4. Consequences

- The cross-VM subscription pattern now has a single documented, typed primitive;
  flagships can drop the repeated hand-wired filters.
- `Parent` is no longer an undeclared dependency of the normative selection
  predicates — implementers know its exact lifecycle and that it is not observable.
- The `SelectNext`/`SelectPrevious` intended-vs-actual gap is explicit, so a future
  container-driven implementation is an additive change, not a silent contract break.
- The initial-current selector no longer reads as self-contradictory.
- No code changes: this ADR is documentation-only plus the one new `COMP-027` test
  (asserting already-shipped wiring). The Python group-child `can_select` hardening
  is a separate, pre-existing per-flavor nuance and is out of scope here.

## 5. Alternatives considered

- **A public observable `Parent` property** — rejected: it would change the public
  `IComponentVM` surface and imply a `PropertyChangedMessage("Parent")` that no
  flavor emits. Declaring the internal back-reference matches reality at zero risk.
- **A `HUB-NNN` for `whenPropertyChanged`** — rejected: the helper is an ergonomic
  wrapper over the conformance-tested `Messages` stream; a conformance ID would
  duplicate the contract, contradicting the ADR-0032 precedent that these helpers are
  informative.
- **Defining real `SelectNext`/`SelectPrevious` navigation now** — deferred: it
  requires the container to drive sibling movement and is an additive feature, not a
  reconciliation; documenting the inert base is the accurate, minimal step.
