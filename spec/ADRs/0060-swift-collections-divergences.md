# ADR 0060 — Swift Phase-3 Inc-2 forced divergences (collections: COL / COMP-001/002/012/013 / GRP-001/005/006)

**Status:** Accepted (2026-06-29)
**Spec version:** 3.0.0 (subset — Phase 3, Increment 2)
**Relates-to:** [ADR-0006](0006-idiomatic-api-per-language.md) (idiomatic surface per
language), [ADR-0009](0009-cross-flavor-divergence-catalogue.md) (cross-flavor
divergence catalogue), [ADR-0037](0037-v2.5-maintenance-clarifications.md) (Swift
subset origin), [ADR-0051](0051-v3-tree-collections-capability-and-spec-organization-gaps.md)
(v3 collections reconciliation), [ADR-0059](0059-swift-leaf-area-divergences.md)
(Swift Phase-3 Inc-1 divergences)

## 1. Context

Phase 3, Increment 2 (`swift-parity-inc2`) ports the observable-collections
area to Swift, expanding the Swift conformance subset from 94 to 124 IDs:

| Area | New IDs                                        | Delta |
| ---- | ---------------------------------------------- | ----- |
| COMP | `COMP-001`, `COMP-002`, `COMP-012`, `COMP-013` | +4    |
| GRP  | `GRP-001`, `GRP-005`, `GRP-006`                | +3    |
| COL  | `COL-001..023`                                 | +23   |

All 30 new IDs have test markers in
`langs/swift/Tests/VMxTests/` and entries in
`langs/swift/conformance-subset.txt`.

Swift's type system, value-semantics, and absence of
`using`/`Symbol.dispose` resource management require idiomatic adaptations
across every new area. These are **forced divergences**, not defects — each
preserves the observable behavior mandated by the spec while remaining
idiomatic Swift. This ADR records them per ADR-0009 §2 so they are not
re-litigated as bugs in future maintenance passes.

## 2. Decision

Accept the following idiomatic divergences; they are normatively equivalent
to the canonical TypeScript reference implementation unless stated otherwise.

### 2.1 The `"Count"` channel name — `COL-008`, `COL-009`, `COL-023`

**Divergence:** `ObservableList.propertyChanged` emits the literal string
`"Count"` (capital C) whenever the list length changes, while the Swift
property exposing the length is named `count` (lower-case, per Swift idiom).
This is the **one spec-literal exception** to ADR-0006's idiomatic-naming
rule: `spec/21 §3.3` mandates the channel name `"Count"` verbatim across all
flavors so that cross-flavor subscribers can filter on a single constant.

**Rationale:** A subscriber written in any flavor (C#, Python, TypeScript, or
Swift) that watches for `propertyChanged` events with name `"Count"` must
receive the same string regardless of which flavor's `ObservableList` produced
the event. Making it lowercase (`"count"`) in Swift would silently break
cross-flavor observers and diverge from the spec contract in a way that cannot
be detected at compile time.

**Consequence:** The Swift property is `var count: Int`, but the message
channel name is the string literal `"Count"`. Tests for `COL-008` / `COL-009`
/ `COL-023` assert `"Count"` (capital C) explicitly.

### 2.2 `BatchUpdateHandle` explicit dispose — `COMP-013`, `GRP-006`

**Divergence:** TypeScript uses `Symbol.dispose` + `using` declarations
(ES2025 explicit resource management); C# uses `IDisposable` + `using`
statements. Swift has neither construct. `BatchUpdateHandle` instead exposes
a plain `dispose()` method that callers invoke explicitly when the batch
window is complete.

**Safety net:** `BatchUpdateHandle` provides a `deinit { dispose() }` so that
a handle dropped without an explicit `dispose()` call (e.g., in a test that
throws early) still closes the batch and does not leave `CompositeVM` /
`GroupVM` permanently suppressed. The `deinit` is a best-effort fallback; the
idiomatic usage pattern remains explicit `handle.dispose()` after the batch
mutations.

**Consequence:** Callers write:

```swift
let handle = composite.batchUpdate()
composite.add(child1)
composite.add(child2)
handle.dispose()               // explicit; deinit fires if this is skipped
```

rather than the TypeScript `using handle = composite.batchUpdate()` or C#
`using var handle = composite.BatchUpdate()`. The batch semantics —
`collectionChanged` suppressed until `dispose()` is called — are identical.

### 2.3 `autoConstructOnAdd` error surfacing — `COMP-012`, `GRP-005`

**Divergence:** The spec requires that when `autoConstructOnAdd` is `true` the
container automatically constructs each child as it is added. `construct()` is
a throwing call (ADR-0053). However, the `add(_:)` method on
`CompositeVM<VM>` and `GroupVM<VM>` is **non-throwing** (consistent with the
other three full-parity flavors and required by the `Collection`-like usage
pattern).

**Resolution:** When `autoConstructOnAdd` is `true`, Swift wraps the
`construct()` call:

```swift
do {
    try child.construct()
} catch {
    assertionFailure("autoConstructOnAdd: construct() failed — \(error)")
}
```

`assertionFailure` surfaces the failure during debug builds and in the test
suite (where assertions are enabled), without marking `add(_:)` `throws`.
The child remains unconstructed on failure; the container is not in an
inconsistent state. Release builds that somehow reach this path (a lifecycle
violation) continue silently — this mirrors the spec's own relaxed error
contract for `autoConstructOnAdd` (no mandatory error propagation path is
specified).

**Consequence:** Tests for `COMP-012` / `GRP-005` confirm that adding a
constructable child with `autoConstructOnAdd: true` results in the child being
`.constructed`; tests that inject a failing child confirm the
`assertionFailure` fires in debug mode.

### 2.4 `ObservableDictionary` null-key and composite-key encoding — `COL-010..015`, `COL-022`

**Two sub-divergences, both behaviorally identical to the TypeScript reference:**

**a) Null-key enforcement is structural, not a runtime check.**
TypeScript, Python, and C# guard against `null`/`None` keys at runtime with
an explicit precondition. In Swift, dictionary keys must be `Hashable` and are
non-optional in the generic signature (`ObservableDictionary<TKey1: Hashable, TKey2: Hashable, TValue>` — a two-key dictionary). A `nil` key is unrepresentable at the type level; the Swift compiler
rejects code that tries to pass `nil` as a key. No runtime guard is needed,
and no runtime guard is added. This is a stricter (compile-time) enforcement
of the same invariant.

**b) Composite keys use a value-type `struct CompositeKey: Hashable`.**
TypeScript's multi-key dictionary encodes composite keys as length-prefixed
serialized strings (collision-proof by construction). Swift does not have
string-serialized key encoding as an idiomatic pattern. Instead,
`ObservableDictionary` uses an internal `struct CompositeKey: Hashable` whose
`hashValue` and `==` derive from the ordered tuple of constituent key values.
The collision guarantee is identical (two distinct key tuples produce distinct
`CompositeKey` values), and the encoding is invisible to callers — the public
API accepts the constituent keys as separate arguments.

> **Amended by ADR-0111 (2026-07-15):** TypeScript's length prefix prevented
> boundary collisions but not `String()` coercion collisions across primitive
> types, object identities, or symbol identities. TypeScript now uses nested
> native `Map` storage; Swift's `CompositeKey` decision remains unchanged.

### 2.5 `PagedComposition` source mutation — `COL-016..021`

**Divergence:** The TypeScript / C# / Python implementations of
`PagedComposition` observe a **mutable reactive source** (an `ObservableList`
or equivalent) and update the page window automatically when the source
changes. Swift arrays are value types; there is no reactive handle to a
"living" mutable array that can be observed.

**Resolution:** `PagedComposition` exposes an explicit `setSource(_:)` method.
Callers call `setSource(_:)` whenever the underlying array changes (e.g.,
after a filter or sort operation). The paged view recomputes the window
synchronously on each `setSource(_:)` call and emits `propertyChanged` events
(`"pageCount"` / `"currentPageIndex"` / `"items"`) for whatever changed —
`PagedComposition` has no `collectionChanged` publisher of its own.

**Clamping and pageCount rules** are shared with the `Pageable` capability
(`CAP-022`): `currentPageIndex` is clamped to `[0, max(0, pageCount - 1)]` and
`pageCount` is `ceil(source.count / pageSize)` (0 when the source is empty and
paging is enabled; 1 when paging is disabled). These rules are conformance-
tested across `COL-016` (clamp-on-shrink), `COL-017` (pageCount formula),
`COL-018` (navigation no-ops at bounds), `COL-019` (`pageSize == 0` disables
paging), and `COL-020` (empty source ⇒ `pageCount == 0`, `items == []`).

### 2.6 Collection event value types and named-struct payloads — `COL-001..009`, `COL-016..023`

**Divergence:** The spec defines `CollectionChangedEvent` and
`CollectionChangedMessage` with per-mutation payload shapes. TypeScript
uses discriminated union types with named tuple-like payloads; C# uses class
hierarchies; Python uses dataclasses.

**Swift resolution:**

- `CollectionChangedAction` is a Swift `enum` with cases
  `.add`, `.remove`, `.replace`, `.reset`.
- `CollectionChangedEvent` and `CollectionChangedMessage` are `struct` value
  types (not classes), consistent with Swift's preference for value semantics
  in event/message carriers.
- The granular per-mutation payloads on `ObservableList` /
  `ObservableDictionary` (`ItemAddedEvent`, `ItemRemovedEvent`,
  `ItemReplacedEvent`, `DictionaryItemAddedEvent`, …) are separate named
  `struct` types rather than named tuples. Swift has no named-tuple syntax
  equivalent to TypeScript's `{ item: T; index: number }` inline type; named
  structs are the idiomatic substitute, are equally type-safe, and remain
  `Equatable`/`Hashable` when their fields are.

**Consequence:** `CollectionChangedAction` is a *plain* enum (no associated
values); the payload lives in the `CollectionChangedEvent` struct's fields
(`newItems` / `oldItems` / `newIndex` / `oldIndex`). Consumers switch on the
discriminator and read the fields:

```swift
composite.collectionChanged
    .sink { event in
        switch event.action {
        case .add:     print("added \(event.newItems) at \(event.newIndex)")
        case .remove:  print("removed \(event.oldItems) at \(event.oldIndex)")
        case .replace: print("replaced at \(event.newIndex)")
        case .reset:   print("reset")
        }
    }
```

The granular `ObservableList` publishers instead carry their own payload
struct directly, e.g. `list.itemAdded.sink { e in /* e.item, e.index */ }`.

This is functionally identical to the TypeScript discriminated-union pattern.

## 3. Consequences

- The 30 new Swift conformance IDs (`COMP-001`, `COMP-002`, `COMP-012`,
  `COMP-013`, `GRP-001`, `GRP-005`, `GRP-006`, `COL-001..023`) are claimed
  in `langs/swift/conformance-subset.txt` and verified by
  `tools/check-conformance-coverage.py`.
- The Swift subset grows from 94 to **124 of 237** library IDs.
- The remaining 113 IDs (`HUB-*`, `THR-*`, `HIER-*`, `DIA-*`, `FORM-*`,
  `NOTIF-*`, `CMDD-*`, `CMD-005/007`, `COMP-006/007/008/010/011`,
  `COMP-014..024`, `GRP-007..010`, `EXP-*`) are deferred to subsequent
  increments. In particular:
  - `COMP-006/010` (foreground-dispatch / async selection) are deferred to
    Increment 3 (threading).
  - `COMP-007` (modeled composite) is deferred.
  - `COMP-008/011` (selection-membership validation) are deferred.
  - `COMP-014..024` and `GRP-007..010` (SearchableState / CRUD context IDs)
    land with forms/hub in Increment 4.
- Future maintenance passes that see "`ObservableDictionary` has no nil-key
  guard" or "`add(_:)` does not propagate `construct()` failures" must consult
  this ADR before filing a bug — these are documented, deliberate choices.
- The `"Count"` channel name is the **sole spec-literal exception** to the
  idiomatic-naming rule (ADR-0006); all other channel names follow the Swift
  `camelCase` convention. Any review finding "the channel name should be
  `count`" must be rejected with reference to `spec/21 §3.3` and this ADR.

## 4. Rejected alternatives

1. **Make `add(_:)` throwing when `autoConstructOnAdd` is true.** Rejected:
   it would require callers to `try` every `add` call even when
   `autoConstructOnAdd` is `false`, and diverges from all three full-parity
   flavors where `add` is non-throwing.
1. **Use `withExtendedLifetime` / `defer` for `BatchUpdateHandle` cleanup.**
   Rejected: `withExtendedLifetime` does not call `dispose()`; `defer`
   requires the caller to already hold a reference. A `deinit` safety net
   inside the handle itself is the correct Swift pattern for resource cleanup
   that must happen regardless of control flow.
1. **Use `Optional<Key>` to allow nil keys in `ObservableDictionary`.**
   Rejected: it would require every lookup to unwrap an optional key, adds
   runtime overhead on every call, and makes the nil-key error a runtime
   `fatalError` at best — the structural enforcement (non-optional generic
   key) is strictly better.
1. **Serialize composite keys as strings (matching TypeScript).** Rejected:
   string serialization is not idiomatic Swift, introduces encoding edge-cases
   (special characters, encoding collisions across key types), and is
   invisible to callers in any case — `struct CompositeKey: Hashable` achieves
   the same collision-proof guarantee more reliably.
1. **Observe a `CurrentValueSubject<[T], Never>` as the reactive source for
   `PagedComposition`.** Rejected: it couples `PagedComposition` to Combine's
   Subject type, complicates memory management, and forces callers to wrap
   plain arrays in a `Subject` even when they never mutate the source
   reactively. An explicit `setSource(_:)` is simpler and equally correct.
