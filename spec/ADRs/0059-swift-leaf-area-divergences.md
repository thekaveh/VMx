# ADR 0059 — Swift Phase-3 Inc-1 forced divergences (leaf areas: FWD / DPROP / CAP / NULL / LOC / UTIL / PROP)

**Status:** Accepted (2026-06-29)
**Spec version:** 3.0.0 (subset — Phase 3, Increment 1)
**Relates-to:** [ADR-0006](0006-idiomatic-api-per-language.md) (idiomatic surface per
language), [ADR-0009](0009-cross-flavor-divergence-catalogue.md) (cross-flavor
divergence catalogue), [ADR-0037](0037-v2.5-maintenance-clarifications.md) (Swift
subset origin), [ADR-0053](0053-swift-converge-illegal-transition-and-non-child-current-to-throw.md)
(Swift v3 throwing-convergence), [ADR-0057](0057-v3-capability-micro-interface-granularity.md)
(capability granularity), [ADR-0058](0058-v3-hold-explicit-aggregate-arity-surface.md)
(aggregate arity)

## 1. Context

Phase 3, Increment 1 (`swift-parity-inc1`) ports six leaf areas to Swift,
expanding the Swift conformance subset from 44 to 94 IDs:

| Area  | New IDs          | Delta |
| ----- | ---------------- | ----- |
| NULL  | `NULL-001..003`  | +3    |
| LOC   | `LOC-001..003`   | +3    |
| UTIL  | `UTIL-001..003`  | +3    |
| FWD   | `FWD-001..003`   | +3    |
| PROP  | `PROP-001..004`  | +4    |
| DPROP | `DPROP-001..012` | +12   |
| CAP   | `CAP-001..022`   | +22   |

All 50 new IDs have test markers in
`langs/swift/Tests/VMxTests/` and entries in
`langs/swift/conformance-subset.txt`.

Swift's type system, Combine framework, and protocol semantics require
idiomatic adaptations in every area above. These are **forced divergences**,
not defects — each preserves the observable behavior mandated by the spec
while remaining idiomatic Swift. This ADR records them per ADR-0009 §2 so
they are not re-litigated as bugs in future maintenance passes.

## 2. Decision

Accept the following idiomatic divergences; they are normatively equivalent
to the canonical TypeScript reference implementation unless stated otherwise.

### 2.1 Forwarding — `FWD-001..003`

**Divergence:** `name` and `hint` are non-overridable `let` constants on
`ComponentVMBase`. A `ForwardingComponentVM` therefore cannot override them
at the property level. Instead, the decorator copies `name` and `hint` from
the wrapped component in `super.init(…)`, so the values are identical to the
wrapped component's and never diverge at runtime.

**`FWD-002` (`modeledHint` forwarding):** The TypeScript reference overrides
`hint` (a single string property). Swift's `ComponentVMBase` exposes
`modeledHint` as an overridable computed member. The Swift forwarder overrides
`modeledHint` instead, which is the semantically equivalent extension point.

**`isConstructed` override:** `isConstructed` reads the base's private
`_status` field, not the overridable `status` computed property. The Swift
forwarder must override `isConstructed` explicitly to delegate to the wrapped
component; relying on the inherited implementation would return the decorator's
own construction state, not the wrapped component's.

**Composite surface:** `ForwardingCompositeVM` mirrors the real
`CompositeVM<VM>` public surface (`count`, `at(_:)`, `current`, `setCurrent`,
`canSetCurrent`, `currentChild`, `selectChild`, `deselectChild`, `add`,
`remove`, `removeAt`, `construct`, `destruct`, `dispose`, status, name/hint),
plus `Sequence` conformance that forwards iteration to the wrapped children.
It does **not** expose `setAt`, because `CompositeVM<VM>` in Swift does not have
that member. (`collectionChanged`/`batchUpdate` were added to `CompositeVM<VM>`
in Increment 2 — ADR-0060 — so the earlier "deferred" note for those two is
superseded; `ForwardingCompositeVM` now forwards them, plus the `insert`,
`clear`, `replace`, and `move` canonical container mutators and the typed
`canSelectComponent`/`selectComponent`/`deselectComponent` surface, to the
wrapped composite — an is-a decorator cannot omit inherited members without
leaving live-but-wrong ones.) Only the `setAt` positional-set mutator remains a
known deferred API-surface gap in Swift's `CompositeVM`/`GroupVM` — see ADR-0009's
known-gaps list.

### 2.2 DerivedProperty — `DPROP-001..012`

**`setValue` throws `DerivedPropertyError.cannotSet`:** Swift has no throwing
property setters (the language does not permit `set throws` on a stored or
computed property). The spec mandates that assigning to a derived property's
`value` is an error. Swift implements this as a standalone `setValue(_:)` method
that throws `DerivedPropertyError.cannotSet`, matching the intent while
remaining idiomatic. Tests for `DPROP-008` call `setValue(_:)` and catch the
error.

**`value` throws `DerivedPropertyError.noValueYet` before first emission:**
`value` is a throwing computed property (`var value: TValue { get throws }`),
read as `try dp.value`. Before any upstream source emits, reading `value`
throws `.noValueYet`. After the first emission the value is cached and
subsequent reads succeed. (Swift permits `get throws` on a property, so unlike
`setValue` this stays a property rather than a method.)

**Distinct-until-changed via `valueEquals` closure:** Other flavors call
`.removeDuplicates()` directly on the Combine/RxJS/reactivex pipeline with
a user-supplied comparator. Swift's `DerivedProperty<TValue>` must remain
usable for **any** `TValue`, including types that do not conform to
`Equatable`. The class therefore stores an internal `valueEquals: (TValue, TValue) -> Bool` closure set at construction time. Factory methods
on an extension constrained to `TValue: Equatable` supply `==` as the
default closure; the unconstrained factory accepts an explicit comparator.
This keeps the class declaration non-constrained while still providing
distinct-until-changed when equality is available.

### 2.3 Capabilities — `CAP-001..022`

**Generic verbs use `associatedtype Item`:** The spec's parameterized
capability verbs (`Filterable<T>`, `Savable<T>`, `Deletable<T>`,
`Updatable<T>`, `Managable<T>`) cannot be expressed as generic protocols in
Swift — Swift protocols cannot have generic parameters. Each becomes a
protocol with `associatedtype Item`, making it a PAT (Protocol with
Associated Type). PATs are usable as **constraints** (`some Deletable`,
`any Deletable<T>` with Swift 5.7+ existential syntax) but cannot be stored
as bare `any Deletable` without an opaque or existential wrapper. This matches
the TypeScript surface for consumers who specify the concrete item type.

**Capability opt-in via structural conformance:** TypeScript's
`declareCapabilities`/`hasCapability` runtime registry is not replicated.
Swift enforces opt-in by **structural conformance**: a VM declares `: Selectable`
only if it genuinely supports `select()`. The capability check
(`coreVM as? Selectable`) succeeds if and only if the VM declared conformance.
Critically, `ComponentVMBase` carries `canSelect()`/`select()` **methods** but
does **not** declare `: Selectable`, so `coreVM as? Selectable == nil` for a
plain `ComponentVMBase` — this correctly proves that holding those methods does
not automatically opt a VM in. Tests for `CAP-019`/`CAP-020` (opt-in
enforcement) rely on this structural property.

**Reactive capability state uses Combine publishers:** `ExpandableState`
exposes `isExpandedChanged` as an `AnyPublisher<Bool, Never>` (not a raw
Subject). `SearchableState` exposes its `filtered` sequence similarly. This
matches the Combine-as-reactive-primitive decision (ADR-0002 / ADR-0036).

### 2.4 Localization — `LOC-001..003`

**No `I`-prefix on the protocol:** Per ADR-0006, Swift does not use the
`IFoo` naming convention for protocols. The localizer contract is `Localizer`
(not `ILocalizer`), consistent with every other Swift protocol in the library.
`NullLocalizer` returns the key string verbatim, matching the spec's null-object
contract.

### 2.5 Null objects and tree utilities — `NULL-001..003`, `UTIL-001..003`

**Null services:** All three `NULL-001..003` IDs exercise the two null service
singletons (`NullMessageHub.INSTANCE`, `NullDispatcher.INSTANCE`), which were
already shipped in the Inc-0 base — Increment 1 adds the conformance tests that
claim the three IDs; no new singleton pattern was needed. (The `NullLocalizer`
null-object is a separate area, claimed by `LOC-002`/`LOC-003`.)

**Tree utilities — materialized arrays:** `walk` (UTIL-001 DFS pre-order,
UTIL-002 nil-aggregate-slot skipping) and `find` (UTIL-003, short-circuiting)
return `[ComponentVMBase]` arrays / a `ComponentVMBase?` rather than lazy
sequences. The spec does not mandate laziness; C#'s LINQ and Python's
generators are lazy by idiom, but Swift's collection APIs conventionally
return `Array`. `find` still short-circuits (it recurses directly and returns
on the first match without materializing the whole tree). The result is
identical for non-infinite trees, which is the only supported case.

The utilities descend via an internal `_TreeContainer` **protocol**, conformed
by `CompositeVM`/`GroupVM` (through their public `count` + `at(_:)`) and
`AggregateVM1..6` (through their per-slot accessors, skipping empty/nil slots).
`walkExpanded` (expansion-gated traversal) depends on the expand/collapse
`EXP-*` area and was deferred from this increment to Increment 3 (ADR-0061),
where it was added. Like `walk`/`find`, it returns a materialized
`[ComponentVMBase]` array (same rationale as above), and `EXP-005` covers it.
Swift source comments cite this section (§2.5) for the materialized-array
decision.

### 2.6 Bundle layout for conformance fixtures

Both conformance fixtures (`lifecycle-transitions.json` and
`derived-properties.json`) are bundled as resources in the **library target**
(`Sources/VMx/Resources/`), loaded via `Bundle.module`. The **test target**
resource directory is intentionally kept empty to avoid shadowing the library
bundle — an XCTest host loads both bundles and the shadowing caused
`LIFE-011` (fixture-driven transition-table) to receive the wrong bundle
before this layout was established. This arrangement is the reason
`LIFE-011` moved from "deferred" to "covered" in Increment 1.

## 3. Consequences

- The 50 new Swift conformance IDs (`FWD-001..003`, `DPROP-001..012`,
  `CAP-001..022`, `NULL-001..003`, `LOC-001..003`, `UTIL-001..003`,
  `PROP-001..004`) are claimed in `langs/swift/conformance-subset.txt` and
  verified by `tools/check-conformance-coverage.py`.
- The Swift subset grows from 44 to **94 of 237** library IDs. The remaining
  143 IDs (`HUB-*`, `THR-*`, `COL-*`, `HIER-*`, `DIA-*`, `FORM-*`, `NOTIF-*`,
  `CMDD-*`, `CMD-005/007`, `COMP-001/002/006..010`, `GRP-001/005/006`,
  `EXP-*`) are deferred to subsequent increments.
- Consumers using `Filterable`/`Savable`/`Deletable`/`Updatable`/`Managable`
  must name the concrete item type at the use site (`some Deletable where Deletable.Item == MyModel`) — identical usage pattern to TypeScript's generic
  protocols at concrete call sites.
- `setValue(_:)` being a throwing method (rather than a throwing property
  setter, which Swift forbids) and `value` being a throwing property
  (`get throws`, read as `try dp.value`) are source-incompatible differences
  from other flavors; they are idiomatic Swift and consistent with ADR-0006's
  "idiomatic surface per language" principle.
- Future maintenance passes that see "ForwardingComponentVM does not override
  `hint`" or "`DerivedProperty.value` is read with `try`" must
  consult this ADR before filing a bug — these are documented, deliberate
  choices.

## 4. Rejected alternatives

1. **Override `name`/`hint` via Objective-C runtime swizzling.** Rejected:
   VMx targets pure Swift with no ObjC dependency; swizzling defeats the
   Swift optimizer and the `let` immutability contract.
1. **Make `DerivedProperty<TValue>` constrained to `Equatable`.** Rejected:
   it would prevent using `DerivedProperty` for non-`Equatable` value types
   (e.g., raw dictionaries, custom structs without `Equatable`). The closure
   approach is strictly more general.
1. **Replicate the TypeScript `declareCapabilities` registry in Swift.** Rejected:
   Swift's type system already encodes the capability contract via protocol
   conformance declarations; a parallel runtime registry would be redundant,
   error-prone (declarative conformance and imperative registration could
   diverge), and un-idiomatic.
1. **Return lazy sequences from `walk`/`find`.** Rejected: Swift's standard
   ergonomics favor `Array` for collection results; lazy sequence wrappers add
   type-system complexity (`LazySequence<…>`) without measurable benefit for
   finite VM trees.
