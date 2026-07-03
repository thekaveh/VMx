# ADR 0055 — v3 positional-options construction for the common VMs (additive, alongside the builders)

**Status:** Accepted (2026-06-28)
**Spec version:** 3.0.0

## 1. Context

VMx constructs every VM through a fluent, immutable, copy-on-write builder
(`spec/10-builders.md`, ADR-0035). The builder is fully general — order-independent
setters, required-field validation on `Build()`, reusable instances — but it is
**heavy ceremony for the trivial case**. Even a leaf VM requires the full
`Builder().Name(…).Services(hub, dispatcher).Model(…).Build()` chain, and the
copy-on-write machinery is ~1,000–1,200 LOC per flavor.

The merged framework critique
(`docs/audit/2026-06-27-vmx-merged-critique.md`) raises this as:

- **VMX-020** (csharp/python/typescript/swift, Important) — "Immutable copy-on-write
  builders are large (~1,000–1,200 LOC/flavor) with a 4-call+`Build` happy-path
  ceremony." The recommended fix is to *add a positional-options ctor or DI-aware
  builder as an additive shortcut* — not to remove the builder. It is part of the
  report's broader **B2 builder-ceremony** theme (see also VMX-021, the
  `Services(IServiceProvider)` overload already shipped).

Removing the builder would be needlessly breaking and would lose its generality
(every optional field, the additive command setters, the DI overload). The defect
is *ceremony for the common case*, not the builder itself.

## 2. Decision

### 2.1 Add an additive positional-options construction form for the common VMs

For the **common VM types** — `ComponentVM` / `ComponentVM<M>`, `CompositeVM<VM>`,
and `GroupVM<VM>` — each flavor gains a one-call construction form alongside (not
replacing) the fluent builder:

- **C#** — a static `Create(options)` factory taking an options `record` with
  `init` properties: `ComponentVMOptions`, `ComponentVMOptions<M>`,
  `CompositeVMOptions<VM>`, `GroupVMOptions<VM>`. Example:
  `ComponentVM.Create(new ComponentVMOptions { Name = "vm", Hub = hub, Dispatcher = dispatcher })`.
- **Python** — a `create(...)` classmethod taking keyword-only arguments:
  `ComponentVMOf.create(name="vm", hub=hub, dispatcher=dispatcher, model=m)`.
- **TypeScript** — a static `create(options)` factory taking an options object
  (with exported `ComponentVMOptions` / `ComponentVMOfOptions<M>` /
  `CompositeVMOptions<VM>` / `GroupVMOptions<VM>` interfaces):
  `ComponentVMOf.create({ name, hub, dispatcher, model })`.

### 2.2 The fluent builders remain unchanged

This is **purely additive**. No builder setter, validation, default, or
immutability semantic changes. The builder stays the canonical, fully-general
construction path and the *only* form for the less-common VMs
(`ReadonlyComponentVM<M>`, `CompositeVM<M, VM>`, `AggregateVMN`, `FormVM<TM>`,
`HierarchicalVM<M, VM>`) until/unless they grow their own options form.

### 2.3 Identical validation and result — by delegation

The options form **delegates to the same builder internally**. Therefore:

- the **same required fields** are validated — a missing `Name`/`Services` (and
  `Children` for `CompositeVM<VM>`/`GroupVM<VM>`) raises the identical
  `BuilderValidationError` (Python/TS) / `BuilderValidationException` (C#) that
  `Build()` raises (`spec/10 §3`); and
- the produced VM is **indistinguishable** from one built via the fluent path with
  the same inputs (`Name`, `Hint`, `Type`, wired services, model, children,
  callbacks, lifecycle behaviour).

The one documented nuance: the modeled `ComponentVM<M>` form supplies the model as
a normal field/parameter (C# `Model` defaults to `default(M)`; Python/TS require it
in the options type). The builder's "you must call `Model(...)`" step is a
fluent-path concern; every other required field is validated identically.

### 2.4 Swift deferred (Phase 3) — subsequently shipped

Swift did **not** gain the options form in this change; it was folded into the
tracked Swift full-parity work (ADR-0037 §2.6 / Phase 3). **Subsequently shipped:**
Phase 3 added the positional-options `create(_:)` factory to all four common Swift
VMs (`ComponentVMOf.create(ComponentVMOfOptions)`, and the `ComponentVM` /
`CompositeVM` / `GroupVM` options structs + factories); this equivalence is pinned by
`BLD-006` (ADR-0079). No conformance ID gated it originally, so the parity cutover
left this note stale.

### 2.5 Spec and conformance

- `spec/10-builders.md` gains §7 documenting the additive positional-options form
  and the equivalence/validation contract; the chapter intro is reworded from
  "Every VMx VM … is constructed via a fluent immutable builder" to "can be
  constructed via …".
- `spec/05`, `spec/06`, `spec/07` each gain a one-line pointer to §7.

**No new conformance ID is introduced.** The construction form adds no new
*normative behaviour* — it is a second spelling of an already-conformance-covered
construction with already-conformance-covered validation (`BLD-001..005`). The
equivalence ("`create` produces a VM equal to the builder's, and validates the
same required fields") is pinned by per-flavor construction-equivalence unit tests
(C# `OptionsFactoryTests`, Python `test_options_factory.py`, TypeScript
`optionsFactory.test.ts`) rather than a cross-flavor ID, keeping the catalogue
free of a redundant presence-only entry.

## 3. Rationale

The builder's value is generality; its cost is ceremony in the 80% case. An
options DTO collapses the happy path to a single call while *reusing* the builder
for validation and construction, so there is exactly one source of truth for
"what a valid VM is" and zero behavioural drift between the two forms. Delegation
(rather than a parallel constructor) is what makes the equivalence guarantee free.
Keeping the form to the common VMs avoids a large surface expansion for VMs that
are rarely hand-constructed.

## 4. Consequences

- Public surface grows by one factory + one options type per common VM per flavor
  (C#/Python/TypeScript). All are additive; no existing call site changes.
- The builders are retained in full; the ~1,000–1,200 LOC/flavor figure is
  unchanged (the win is caller ergonomics, not builder LOC). A future ADR may
  thin the builders, but that is out of scope here.
- Swift carries a tracked gap (the options form) into Phase 3.
- Future parity audits should treat the options form as required for the common
  VMs in C#/Python/TypeScript and as a known-deferred item for Swift.

## 5. Rejected alternatives

- **Remove the builders, ship only positional options.** Needlessly breaking and
  loses the builder's generality (additive command setters, the DI overload,
  order-independent partial configuration). VMX-020 explicitly asks for an
  *additive* shortcut.
- **A parallel constructor that does not delegate to the builder.** Duplicates the
  required-field validation and invites drift between the two construction paths;
  delegation makes the "identical VM" guarantee structural.
- **Add the options form to every VM (readonly/modeled-composite/aggregate/form/
  hierarchical) now.** Larger surface for VMs that are seldom hand-built; deferred
  until demand appears. The builder remains their construction path.
- **Introduce a new conformance ID for the options form.** It would assert
  presence/equivalence already implied by `BLD-001..005`; a per-flavor equivalence
  test is the right granularity and avoids a redundant catalogue entry.
