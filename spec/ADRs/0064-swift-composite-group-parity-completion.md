# ADR 0064 — Swift Phase-3 Inc-6 composite/group parity completion (COMP / GRP: full library parity)

**Status:** Accepted (2026-06-30)
**Spec version:** 3.0.0
**Relates-to:** [ADR-0006](0006-idiomatic-api-per-language.md) (idiomatic surface per
language), [ADR-0009](0009-cross-flavor-divergence-catalogue.md) (cross-flavor
divergence catalogue), [ADR-0014](0014-search-and-filter.md) (SearchableState),
[ADR-0016](0016-modeled-crud-commands.md) (ModeledCrudCommands),
[ADR-0030](0030-form-vm.md) (FormVM), [ADR-0037](0037-v2.5-maintenance-clarifications.md)
(Swift subset origin), [ADR-0053](0053-swift-converge-illegal-transition-and-non-child-current-to-throw.md)
(Swift throwing-convergence, CompositeMembershipError),
[ADR-0059](0059-swift-leaf-area-divergences.md) (Swift Phase-3 Inc-1 divergences),
[ADR-0060](0060-swift-collections-divergences.md) (Swift Phase-3 Inc-2 divergences),
[ADR-0061](0061-swift-hierarchical-threading-divergences.md) (Swift Phase-3 Inc-3
divergences), [ADR-0062](0062-swift-forms-commands-hub-divergences.md) (Swift
Phase-3 Inc-4 divergences),
[ADR-0063](0063-swift-notifications-dialogs-divergences.md) (Swift Phase-3 Inc-5
divergences)

## 1. Context

Phase 3, Increment 6 (`swift-parity-inc6`) closes the final 19 library conformance
IDs, bringing the Swift subset from 218 to **237 of 237 — full library parity**
with the C#, Python, and TypeScript flavors:

| Cluster                             | New IDs                     | Delta |
| ----------------------------------- | --------------------------- | ----- |
| Modeled composite (`CompositeVMOf`) | `COMP-007`                  | +1    |
| Throwing component selection        | `COMP-008`, `COMP-011`      | +2    |
| SearchableState (composite)         | `COMP-014..018`             | +5    |
| Modeled CRUD commands               | `COMP-019..024`, `COMP-027` | +7    |
| SearchableState (group)             | `GRP-007..010`              | +4    |

All 19 new IDs have test markers in `langs/swift/Tests/VMxTests/` and entries in
`langs/swift/conformance-subset.txt`.

The only remaining gap before total parity is the five `THEME-00x` flagship scenario
IDs, which live in example apps rather than the library conformance suite and are
deferred to Increment 7.

## 2. Decision

### 2.1 `CompositeVMOf<Model, VM: ComponentVMBase>` — `COMP-007`

`CompositeVMOf<Model, VM: ComponentVMBase>` is a `public final class` that
subclasses `CompositeVM<VM>`. It accepts a `childrenModels: () -> [Model]` closure
and a `childModelToChildViewModel: (Model) -> VM` mapper, then passes a single
`childrenFactory: { childrenModels().map(childModelToChildViewModel) }` closure
to `super.init`. No change to the `CompositeVM` base class was needed.

**Non-recursive generic (no CRTP relaxation).** The bound `VM: ComponentVMBase`
is non-self-referential. This is unlike `HierarchicalVM` (ADR-0061 §2.1), where
the Swift compiler rejected the CRTP `TVM: HierarchicalVM<TVM>` self-referential
constraint and required relaxation to `TVM: AnyObject`. `CompositeVMOf` has no
such constraint: the child type `VM` is simply required to be a `ComponentVMBase`
(a concrete class), which the Swift compiler accepts without restriction. Children
are typically `ComponentVMOf<Model>` instances and expose `.model` directly.

**Builder** (`CompositeVMOfBuilder<Model, VM>`): immutable copy-on-write; validates
fields in order `name → services → childrenModels → childModelToChildViewModel`;
provides a `withNullServices()` convenience that fills the services field with
`NullMessageHub.INSTANCE` + `NullDispatcher.INSTANCE`. All validation errors
throw `BuilderValidationError`.

**Consequence:** Future maintenance passes that see `CompositeVMOf` with a
`VM: ComponentVMBase` (not `VM: AnyObject`) bound must not widen it — the
non-recursive generic does not require the CRTP relaxation applied to
`HierarchicalVM`.

### 2.2 Throwing component selection — `COMP-008`, `COMP-011`

`CompositeVM` gains three new members:

- **`canSelectComponent(_ vm: Child) -> Bool`:** returns `true` when `vm` is a
  current child (`===` identity check) **and** `vm.status == .constructed`.
  This is explicitly distinct from the existing `canSetCurrent(_ vm: Child?) -> Bool`, which is a membership-only predicate with no status guard. The
  status check aligns with the spec contract that component selection is only
  meaningful when the child is in the fully constructed state.

- **`selectComponent(_ vm: Child) throws`:** guards on `canSelectComponent(vm)`;
  throws `CompositeMembershipError(memberName:compositeName:)` when the guard
  fails; calls `_setCurrent(vm)` on success. `selectChild` / `deselectChild`
  (the no-op `ParentVM` stubs used by the COMP-027 parent-link delegation) are
  unchanged.

- **`deselectComponent(_ vm: Child) throws`:** guards that `_current === vm`;
  throws `CompositeMembershipError` when `vm` is not the current selection;
  calls `_setCurrent(nil)` on success, leaving `current` unchanged when throwing.

**Continuing the ADR-0053 catchable-throw line.** All three methods use
`CompositeMembershipError` (a catchable Swift `Error`), matching the Swift
pattern established in ADR-0053 for `setCurrent` and lifecycle guards. The
other flavors surface `InvalidOperationException` (C#); this is a documented
forced divergence per ADR-0009 §2.

**Consequence:** Future maintenance passes that see `selectComponent`/
`deselectComponent` throwing `CompositeMembershipError` (not
`InvalidOperationException`) must consult ADR-0053 and this ADR §2.2. The
`canSelectComponent` status check (`status == .constructed`) is deliberate and
must not be collapsed into `canSetCurrent`.

### 2.3 `SearchableState<T>` covers COMP-014..018 and GRP-007..010 — no new production code

`SearchableState<T>` (already shipped in Inc-2, ADR-0060) covers all nine new IDs
without any production-code changes. Its Combine-native implementation uses a
`CurrentValueSubject<[T], Never>` backing the `filtered` publisher plus a
`PassthroughSubject` for force-immediate `search()` requests — the two are merged
via `Publishers.Merge` and then `filteredSubject.send(...)` is called synchronously.

The `items: () -> [T]` lazy closure re-reads the source on every recompute, so
COMP-018 (source mutation followed by explicit `search()`) is covered without
modification.

Tests use the synchronous `search()` bypass pattern (no `XCTestExpectation`
needed): set `searchTerm`, call `search()`, assert `filtered` last value. For tests
that pass `debounce: .milliseconds(0)`, the `search()` call is the actual driver;
the `.debounce` path is exercised separately and deferred until the scheduler
fires.

**Consequence:** Future maintenance passes that see COMP-014..018 / GRP-007..010
covered by `SearchableState` conformance tests (not new composite/group
production code) must not assume these IDs require new helpers — the existing
`SearchableState` already satisfies the spec contract.

### 2.4 `ModeledCrudCommands<VM>` covers COMP-019..024 and COMP-027 — no new production code

`ModeledCrudCommands<VM>` (already shipped in Inc-4, ADR-0062 §2.5) covers all
seven new IDs without any production-code changes:

- `COMP-019` — `createNewCommand.execute()` fires the create callback.
- `COMP-020` — `updateCurrentCommand.execute()` passes the current VM to the
  update callback.
- `COMP-021` — `updateCurrentCommand.canExecute()` returns `false` when
  `current()` is `nil`.
- `COMP-022` — `deleteCurrentCommand.execute()` passes the current VM to the
  delete callback.
- `COMP-023` — `deleteCurrentCommand.canExecute()` returns `false` when
  `current()` is `nil`.
- `COMP-024` — `deleteCurrentCommand` wrapped in `ConfirmationDecoratorCommand`;
  confirm gate blocks deletion when returning `false`; deletion proceeds when
  returning `true`.
- `COMP-027` — `add(child)` sets the child's `parent` reference; the parent
  link enables `canSelect`/`select` composition; `remove(child)` clears it.

**TypeScript phantom type parameter dropped (ADR-0006).** TypeScript's
`ModeledCrudCommands<M, VM>` carries a phantom model type parameter `M` for
type-inference convenience. Swift omits the phantom `M` because Swift's type
inference does not require it — `VM` already carries the model binding via
`ComponentVMOf<Model>`. This is a documented idiomatic difference per ADR-0006
(idiomatic surface per language), not a divergence from the spec behavior.

**Consequence:** Future maintenance passes that see `ModeledCrudCommands<VM>`
(not `ModeledCrudCommands<M, VM>`) in Swift must not add the phantom `M`
parameter — the single-parameter form is deliberate (ADR-0006 / ADR-0016).

## 3. Consequences

- The 19 new Swift conformance IDs (`COMP-007`, `COMP-008`, `COMP-011`,
  `COMP-014..024`, `COMP-027`, `GRP-007..010`) are claimed in
  `langs/swift/conformance-subset.txt` and verified by
  `tools/check-conformance-coverage.py`.
- **The Swift subset reaches 237 of 237 library conformance IDs — full library
  parity with the C#, Python, and TypeScript flavors.** This milestone closes
  Phase 3 Increment 6.
- The only remaining gap before total parity is the five `THEME-00x` flagship
  scenario IDs, which live in example apps and are deferred to Increment 7.
- Future maintenance passes that see `CompositeVMOf` with `VM: ComponentVMBase`
  must not widen to `VM: AnyObject` — the non-recursive generic does not require
  the CRTP relaxation applied to `HierarchicalVM` (§2.1).
- Future maintenance passes that see `canSelectComponent` checking
  `status == .constructed` must not simplify it to `canSetCurrent` — the
  status guard is load-bearing for COMP-008 (§2.2).
- Future maintenance passes that see `selectComponent`/`deselectComponent`
  throwing `CompositeMembershipError` must consult ADR-0053 §2 — this is the
  established Swift catchable-throw pattern, not a bug (§2.2).
- Future maintenance passes that see COMP-014..018 / GRP-007..010 in
  `SearchableState` conformance tests (no new production code) must consult §2.3.
- Future maintenance passes that see `ModeledCrudCommands<VM>` (no phantom `M`)
  must consult §2.4 and ADR-0006 — the single-parameter form is deliberate.

## 4. Rejected alternatives

1. **Widen `CompositeVMOf` bound to `VM: AnyObject` (CRTP relaxation as in
   `HierarchicalVM`).** Rejected: the Swift compiler accepts `VM: ComponentVMBase`
   without restriction. The CRTP relaxation in ADR-0061 was required specifically
   because `HierarchicalVM<TVM>` is self-referential; `CompositeVMOf` has no
   self-referential constraint. Widening to `AnyObject` would lose the
   `ComponentVMBase` API surface without any benefit.
1. **Alias `canSelectComponent` to `canSetCurrent`.** Rejected: `canSetCurrent`
   is a membership-only predicate. The spec requires `canSelectComponent` to also
   check `status == .constructed`. An alias would silently drop the status guard,
   making COMP-008 tests pass vacuously. The two predicates are intentionally
   distinct.
1. **Throw `InvalidOperationException` (matching C#).** Rejected: Swift does not
   have `InvalidOperationException`. `CompositeMembershipError` is the established
   Swift catchable error type for composite membership violations (ADR-0053 §2).
   Using a different error type would fragment the catchable-error surface for
   callers.
1. **Add a phantom `M` type parameter to `ModeledCrudCommands<VM>` (matching
   TypeScript).** Rejected: TypeScript's phantom `M` exists for type-inference
   ergonomics in a structural type system. Swift's type system does not require
   it. ADR-0006 mandates idiomatic surface per language; carrying a phantom
   parameter that serves no purpose in Swift's nominal type system would violate
   that principle.
