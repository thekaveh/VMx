# ADR 0052 — v3 public-surface breaking removals: deprecated aliases, off-domain helpers, and a HierarchicalVM footgun

**Status:** Accepted (2026-06-28)
**Spec version:** 3.0.0

## 1. Context

The v3 framework overhaul is the first major since the deferred-removal promises
recorded in ADR-0009 came due. The merged framework critique
(`docs/audit/2026-06-27-vmx-merged-critique.md`) flags four small public-surface
cleanups that were intentionally held back because they are **breaking** and a
major was not yet open:

- **VMX-095** (Python) — the parameterised relay command is exported under two
  names: the canonical `RelayCommandOf` / `RelayCommandOfBuilder` (parity with C#
  `RelayCommand<T>` and TypeScript `RelayCommandOf`) and the legacy v1.0.0
  `RelayCommandOfT` / `RelayCommandOfTBuilder` identity aliases. ADR-0009 §"deferred
  renames" planned the `OfT` removal for v2.0.0; it slipped to preserve downstream
  code and was re-deferred to v3.0.0.
- **VMX-068** (C#) — `VMx.Extensions/LinqHelpers.cs` ships `CartesianProduct` /
  `Sample` / `Product`, general-purpose `IEnumerable` helpers with no relationship
  to VMx's viewmodel domain. ADR-0033 admitted them as a C#-only convenience; the
  critique notes they pollute the library's public surface and are referenced by
  nothing but their own tests.
- **VMX-080** (Python) — `HierarchicalVM.__init__` defaulted `hub` to a fresh
  `MessageHub()` and `dispatcher` to `RxDispatcher.immediate()`. A tree node
  constructed without explicit services therefore silently got an **isolated** hub,
  so structural-change and property-changed messages never reached the application
  hub — a quiet wiring footgun. Every other VM, and the `HierarchicalVMBuilder`
  itself (HIER-015), already require services explicitly.
- **VMX-081** (Python) — the top-level `vmx` package re-exported a large, partly
  redundant surface: the six legacy `AggregateVMBuilder1..6` aliases (the same
  ADR-0009 deferred rename as VMX-095, now `AggregateVM1Builder..6Builder`), plus
  two ways to obtain a null hub at the package root (`NULL_MESSAGE_HUB` and the
  narrow-typing factory `null_message_hub_of`).

These are surface/ergonomics cleanups, not behavior changes to any normative
conformance contract; no spec chapter prose described the removed Python aliases or
the Python-only constructor default, so no `spec/NN-*.md` chapter changes
accompany them. Chapter 18 already specifies the builder's required
`Services(hub, dispatcher)` triple (HIER-015) and ADR-0003 mandates constructor
injection, so requiring services on the raw constructor brings Python in line with
the existing neutral spec rather than changing it.

## 2. Decision

All four removals land in v3.0.0. They are breaking by design; v3 is the
permitted window.

### 2.1 VMX-095 — remove the `RelayCommandOfT` aliases (Python)

The concrete classes are renamed to the canonical names: `RelayCommandOf[T]` and
`RelayCommandOfBuilder[T]`. The legacy `RelayCommandOfT` / `RelayCommandOfTBuilder`
identity aliases are deleted from `relay_command.py`, `vmx.commands`, and the
top-level `vmx` package.

*Migration:* replace `RelayCommandOfT` → `RelayCommandOf` and `RelayCommandOfTBuilder`
→ `RelayCommandOfBuilder`. The behavior, generic parameter, and builder fluent API
are unchanged.

### 2.2 VMX-068 — drop `LinqHelpers` (C#)

`VMx.Extensions/LinqHelpers.cs` and its test `LinqHelpersTests.cs` are deleted. A
repo-wide grep confirmed that nothing in the library, the conformance suite, the DI
companion package, or the example apps references `LinqHelpers`,
`CartesianProduct`, `Sample`, or `Product` — only the helper's own test did.
**Removal was chosen over relocating to a `VMx.Linq` namespace**: keeping
domain-unrelated combinatorics in the viewmodel library (even under a tidier
namespace) is surface VMx should not own, and ADR-0033's C#-only rationale already
acknowledged the helpers were a borderline inclusion.

*Migration:* the three helpers are one-liners over LINQ
(`SelectMany` for the cartesian product, `Where`+modulo for sampling,
`Aggregate(1, (a, x) => a * x)` for the product); inline them or move them into the
consuming project.

### 2.3 VMX-080 — require services on `HierarchicalVM` (Python)

`HierarchicalVM.__init__` now takes `hub: MessageHub[Any]` and
`dispatcher: Dispatcher` as **required** parameters (the `| None = None` defaults
and the internal `MessageHub()` / `RxDispatcher.immediate()` fabrication are
removed). A tree node can no longer silently acquire an isolated hub. The
`HierarchicalVMBuilder` is unchanged: it already required `services(hub, dispatcher)`
(HIER-015) and still offers the explicit `with_default_services()` Wither for code
that genuinely wants the convenience defaults — now the only, and visible, way to
opt into them.

*Migration:* pass `hub`/`dispatcher` explicitly (or use the builder). Subclasses
that defaulted these through to `super().__init__` should fabricate their own
default or, preferably, require the services themselves.

### 2.4 VMX-081 — trim the top-level `vmx` `__all__` (Python)

- The six legacy `AggregateVMBuilder1..6` aliases are removed; the concrete builders
  are renamed to the canonical `AggregateVM1Builder..6Builder` (parity with the
  TypeScript flavor and the C# nested `AggregateVM2.AggregateVM2Builder` shape) —
  the second half of the same ADR-0009 deferred rename as VMX-095.
- `null_message_hub_of` is removed from the top-level `vmx` package export so the
  package root offers exactly **one** null hub (`NULL_MESSAGE_HUB`). The factory is
  **not** deleted — it remains available from `vmx.services` for the narrow-typing
  case it uniquely serves (a `MessageHubProto[T]` bound to a `Message` subtype for
  `mypy --strict` consumers); it is simply no longer part of the headline surface.

*Migration:* replace `AggregateVMBuilderN` → `AggregateVMNBuilder`; change
`from vmx import null_message_hub_of` → `from vmx.services import null_message_hub_of`.

## 3. Consequences

- No `spec/NN-*.md` chapter changes and no conformance-ID changes: the four
  removals touch flavor-specific public surface and a Python-only constructor
  default, all already consistent with (or stricter than) the neutral spec. The
  catalog stays at 237 IDs.
- Python: `vmx.__all__` drops nine symbols (six aggregate-builder aliases, two
  `RelayCommandOfT` names, and `null_message_hub_of`). The full suite, `mypy --strict`, and ruff stay clean; affected internal tests/test-doubles were updated.
- C#: `VMx.Tests` loses the eleven `LinqHelpers` tests; the build, the full test
  run, and `dotnet format --verify-no-changes` stay clean. The now-empty
  `src/VMx/Extensions/` directory carries only the DI companion package's namespace
  elsewhere.
- These are breaking changes for downstream code that imported the legacy
  identifiers or relied on the implicit HierarchicalVM services; each item's
  migration is a mechanical rename or an explicit-wiring edit (see §2). The
  coordinated `spec/VERSION` / per-flavor package version bumps are handled by the
  v3 release task; this ADR's "Spec version: 3.0.0" records the line the change
  belongs to.

## 4. Rejected alternatives

- **Keep the deferred aliases another cycle (VMX-095/081).** Rejected: ADR-0009
  already slipped the removal once; v3 is the committed window, and carrying two
  names per builder indefinitely is exactly the redundant surface the critique
  flags.
- **Relocate `LinqHelpers` to a `VMx.Linq` namespace (VMX-068).** Rejected: a
  tidier namespace does not make general combinatorics part of a viewmodel
  framework's remit, and nothing depends on the helpers — relocation would preserve
  dead surface that the next audit would re-flag.
- **Keep the HierarchicalVM default services but warn on a cross-hub child add
  (VMX-080).** Rejected: a runtime warning is easy to miss and still admits the
  isolated-hub state. Required services match every other VM and the builder, and
  fail fast at construction.
- **Delete `null_message_hub_of` outright (VMX-081).** Rejected: it is not a pure
  alias of `NULL_MESSAGE_HUB` — it provides a `Message`-subtype-narrowed
  `MessageHubProto[T]` that the singleton cannot express for `mypy --strict`
  consumers. Demoting it from the package root removes the redundancy at the surface
  the critique measured while preserving the unique capability under `vmx.services`.
