# ADR 0042 — `CompositeVMBuilder` initial-current selector and `OnCurrentChanged` callback

**Status:** Accepted (2026-06-13)
**Spec version:** 2.6.0 (additive minor)
**Related:** ADR-0035 (builder audit follow-through), `spec/proposals/2026-06-13-vmx-absorption-audit-followup.md` §5 D2/D3

## 1. Context

Today, consumers wiring a `CompositeVM<VM>` who want a specific child selected at construction time have to either:

1. Call `composite.SelectComponent(theInitialChild)` after `Construct()` returns (extra step, easy to forget, requires materializing the child reference).
1. Override `CompositeVM` and set `Current` inside an `OnConstruct` callback (heavyweight for what should be declarative).

Consumers wanting to react to `Current` changes subscribe to `PropertyChangedMessage<CompositeVM<VM>>` from the hub filtered on `PropertyName == "Current"` and pluck out `args.NewValue` from a sender lookup. Workable, verbose. The `dotnet-tag/VMx` ancestor (audited 2026-06-13) exposed both ergonomics directly on the builder; this ADR brings them forward.

## 2. Decision

Add two methods to `CompositeVMBuilder<VM>` and `CompositeVMOfMBuilder<M, VM>` in all four flavors:

- `Current(Func<IEnumerable<VM>, VM?> selector)` — runs after children are constructed but before the composite reaches `Constructed`. If the selector returns a child contained in the composite, that child becomes `Current`; otherwise `Current` is null and the call is a no-op.
- `OnCurrentChanged(Action<VM?> callback)` — invoked synchronously after every `Current` state change (including the initial transition driven by `Current(selector)`), before the next user action observes the change. Receives the new `Current` value (may be `null`).

Both methods are additive, default-null, and immutable-with-clone (BLD-001).

## 3. Rationale

- **Declarative replaces imperative.** `Current(selector)` removes the post-build `SelectComponent(...)` step.
- **Symmetric with existing hooks.** `OnCurrentChanged` mirrors `OnModelChanged` (already on `ComponentVMOfBuilder`) and `OnConstruct`/`OnDestruct` (already on `CompositeVMBuilder`).
- **Backward compatible.** Both methods are optional; existing builders without the calls behave identically to v2.5.0.
- **Cross-flavor symmetric.** ADR-0006 (idiomatic-per-language) accommodates: Python `current(selector: Callable[[Iterable[VM]], VM | None])` and `on_current_changed(callback: Callable[[VM | None], None])`; TS `current(selector: (xs: Iterable<VM>) => VM | undefined)` and `onCurrentChanged(cb: (vm: VM | undefined) => void)`; Swift `current(_ selector: @escaping ([Child]) -> Child?)` and `onCurrentChanged(_ cb: @escaping (Child?) -> Void)`.

## 4. Consequences

- `spec/06-composite-vm.md` §3 (`Current` contract) gains a new subsection §3.X documenting the builder hooks.
- New conformance IDs `CVM-007` (initial-current selector) and `CVM-008` (OnCurrentChanged callback fires on Current change) in `spec/12-conformance.md`.
- Per-flavor implementations land in `langs/csharp/src/VMx/Composites/CompositeVMBuilder.cs` (and `CompositeVMOfMBuilder`), `langs/python/src/vmx/composites/builders.py`, `langs/typescript/src/composites/compositeVM.ts` (inline builder), `langs/swift/Sources/VMx/Builders/CompositeVMBuilder.swift`.
- Conformance stubs (`CVM-007`, `CVM-008`) ship in C# / Python / TypeScript per `spec-discipline.yml`.
- Spec version 2.5.0 → 2.6.0 (additive minor). Each flavor package version bumps to 2.6.0 (per README §6.1).

## 5. Operational details

### 5.1 Selector evaluation order

The selector is invoked from within the composite's construct phase **after** all children have transitioned to `Constructed`. The composite is in `Constructing` state when the selector runs. The selector's return value is set via the existing `SelectComponent` path (which raises `PropertyChangedMessage("Current")` on the hub). Then the composite transitions to `Constructed`.

### 5.2 Callback invocation timing

The callback runs synchronously **after** the `Current` field is updated and **after** the hub publishes `PropertyChangedMessage("Current")`. Order: state update → hub publish → callback. This order ensures hub subscribers and direct-callback subscribers observe the same value.

### 5.3 Disposal

The callback registration is owned by the composite for its lifetime. No explicit subscription is exposed; the callback reference is released when the composite is disposed.

### 5.4 Null and out-of-set selector returns

If the selector returns `null` or a child not contained in the composite, `Current` is left at its prior value (initially `null`). The callback does NOT fire in this case (no change occurred). This matches the existing `SelectComponent(null)` and `SelectComponent(unknown)` semantics.
