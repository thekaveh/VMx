# ADR 0035 — Builder pattern audit follow-through

**Status:** Accepted (2026-05-31)
**Spec version:** introduced in 2.3.0
**Source:** `docs/superpowers/specs/2026-05-31-builder-pattern-audit.md` (local research artifact; not tracked)

## 1. Context

A comprehensive audit of how the builder pattern (and adjacent fluent-construction
patterns) is used across VMx surfaced a small but actionable set of substantive
findings:

1. **CP1 / GR2 — Spec gap.** `spec/10-builders.md §3` table says non-modeled
   `CompositeVM<VM>` and `GroupVM<VM>` require `Children(() -> ...)` at `Build()`.
   TypeScript enforces this; **C# and Python silently accept** a missing
   `Children` factory, raising the error later at `OnConstruct` rather than at
   `Build()`. The fix is the spec-correct behavior.

1. **SV1 — Cross-flavor Wither parity.** PR #8 added C# `WithNullServices()` —
   a chainable Wither extension on `ComponentVMBuilder` that wires
   `NullMessageHub.Instance` + `NullDispatcher.Instance` in one call. Python has
   the typed factory `null_message_hub_of[M]()` but lacks the *chainable Wither*
   convenience; TypeScript has neither. Add `with_null_services()` /
   `withNullServices()` Wither to Python + TS for parity.

1. **DP2 — DerivedProperty type-inference parity.** C# and TypeScript expose
   typed-arity factories (`DerivedProperty.From<T1, U>` … `From<T1..T5, U>`) so
   the compiler can infer source types from the call site. Python's
   `from_sources(...)` accepts a sequence of observables of any type. Add
   typed-arity factories `from_one[T1]` … `from_five[T1..T5]` to Python.

1. **BLD-005 — Additive setter retention conformance.** `spec/10-builders.md §2`
   documents that `RelayCommand.Triggers(...)` is **additive** (each call
   appends rather than overwrites). The current `BLD-001..004` conformance IDs
   cover the immutable / validation / repeatability / defaults invariants but
   not the additive-retention invariant. A regression flipping `Triggers` to
   overwrite-semantics would currently slip past CI. Add `BLD-005`.

1. **FV1 / FV2 — FormVMBuilder.** `FormVM<TM>` is constructed via a 5-parameter
   constructor (3 optional). All three flavors lack a builder; the C# and
   Python flavors use positional + default arguments, the TS flavor uses an
   options-object pattern. Add a `FormVMBuilder<TM>` across all three flavors
   for consistency with the rest of the VM family and to validate `Initial` +
   `Persister` at `Build()` rather than at runtime.

1. **H1 / H2 / H3 — HierarchicalVMBuilder.** `HierarchicalVM<TModel, TVM>` is
   constructed via a 7-parameter constructor (4 optional). Same pattern as
   FormVM: no builder in any flavor, ad-hoc divergence between positional (C#,
   Python) and options-object (TS). Add a `HierarchicalVMBuilder<TModel, TVM>`
   across all three. For the two flavors that today auto-default `hub` and
   `dispatcher` when omitted (Python, TS), also add a `.WithDefaultServices()`
   Wither so consumers can opt in *explicitly* — making implicit default
   behavior visible.

1. **Spec table.** `spec/10-builders.md §3` does not currently have a row for
   `HierarchicalVM<M, VM>` or `FormVM<TM>`. Add both, including the new
   builders' required fields.

1. **ADR-0027 doc note.** ADR-0027's fluent command extensions intentionally
   manifest as method-chain (C#) vs free-function composition (Python, TS) per
   ADR-0006's idiomatic-per-language stance. A future reader could mistake the
   syntactic divergence for a parity gap. The decision is already correct;
   ADR-0027 just needs an explicit "shape may differ per ADR-0006" sentence
   so the parity is documented.

## 2. Decision

Ship the eight items above as **VMx spec 2.3.0** and all three flavors at
**2.3.0**, all changes additive at the type / surface level (no breaking
changes for consumers who do not currently call buggy paths). The single
behavior change is CP1 / GR2: C# and Python `CompositeVMBuilder<VM>.Build()`
and `GroupVMBuilder<VM>.Build()` will now raise `BuilderValidationException` /
`BuilderValidationError` when `Children` is unset — bringing them into
compliance with TS and the spec's existing §3 table. Existing code that calls
`Build()` without `Children` was already buggy (would fail at `OnConstruct`);
the fix moves the failure earlier.

Per-item disposition:

- **CP1 / GR2** — C# and Python `CompositeVMBuilder<VM>` + `GroupVMBuilder<VM>`
  validate `Children` at `Build()` (matches TS + spec §3).
- **SV1** — Python `with_null_services()` and TS `withNullServices()` Wither
  methods added to the component builders that already have C# equivalents.
- **DP2** — Python `from_one[T1]` … `from_five[T1..T5]` typed factory
  *module-level functions* (exported alongside `DerivedProperty` from
  `vmx.properties` and re-exported from the top-level `vmx` package),
  plus a `from_many` alias for `from_sources` (parity with C#'s `FromMany`).
  Module-level is the idiomatic Python surface for these helpers — it matches
  the existing ADR-0027 fluent command extensions (`confirm`, `precede_with`,
  etc.) and avoids the awkward `DerivedProperty.from_one(...)` classmethod
  ergonomics on a generic class. C#'s typed-arity factories remain `static`
  methods on `DerivedProperty`; TS's remain named exports. The existing
  variadic `from_sources` is retained for arbitrary-N consumers.
- **BLD-005** — Add to `spec/10 §6` and `spec/12 §6` conformance catalog; one
  test per flavor asserting `Triggers(o1).Triggers(o2)` retains both `o1` and
  `o2` (cumulative).
- **FV1 / FV2** — `FormVMBuilder<TM>` exists in C#, Python, TypeScript with
  the same required (`Initial`, `Persister`) + optional (`Hub`, `Strict`,
  `Snapshotter`) surface. C# additionally exposes a `WithFormPersister(IFormPersister<TM>)`
  shortcut Wither for the typed-persister overload.
- **H1 / H2 / H3** — `HierarchicalVMBuilder<TModel, TVM>` exists in all three
  flavors with required (`Model`, `ChildrenFactory`, `Services`) + optional
  (`Name`, `Hint`, `EagerChildren`) surface. Python + TS gain
  `.WithDefaultServices()` Wither. Spec §3 table gains a row for both
  `HierarchicalVM` and `FormVM`.
- **ADR-0027 doc note** — One sentence added to ADR-0027.

The audit's deferred (Tier 4 YAGNI) items — `SV2` (WithNullNotifications
family), `CMD4` (`pipe()` helper), `MT1` (TS builder base class) — are
**not** in scope here; the audit explicitly marks them for "defer until
demand surfaces." This ADR holds the position that those should not ship
without a concrete consumer need.

## 3. Consequences

- New conformance IDs: `BLD-005`, `FORM-011..013` (FormVM builder
  validate/repeat/defaults), `HIER-015..017` (HierarchicalVM builder
  validate/repeat/defaults). Running total: `220 + 1 + 3 + 3 = 227`.
- All three flavors bump minor to **2.3.0**; spec to **2.3.0**.
- Compatibility matrix gains a `2.3.x` row.
- `CompositeVMBuilder<VM>.Build()` and `GroupVMBuilder<VM>.Build()` in C# and
  Python now eagerly validate `Children`. This is a behavior change for any
  caller that was relying on lazy validation — but every such caller's code
  was already broken (would throw at `OnConstruct`); the new behavior fails
  earlier with a more helpful message.
- Future builder additions for new VM family members follow the same pattern
  established here; spec/10 §3 table is the single source of truth for
  required-field validation contracts.
