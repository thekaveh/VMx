# ADR 0058 — v3 holds the line on the explicit `AggregateVM1..6` surface

**Status:** Accepted (2026-06-28)
**Spec version:** affirmed for 3.0.0 (no surface change)
**Relates-to:** [ADR-0007](0007-aggregate-vm-arity-1-to-5.md) (rejected variadic
generics; explicit arities 1–5), [ADR-0034](0034-aggregate-vm6.md) (added arity
6 as an additive minor bump), [ADR-0006](0006-idiomatic-api-per-language.md)
(one symmetric shape, idiomatic surface per flavor)

## 1. Context

The v3 merged critique (`docs/audit/2026-06-27-vmx-merged-critique.md`,
**VMX-019**, Important/minor) flags that `AggregateVM1` through `AggregateVM6`
are hand-cloned across all four flavors — a verified **~3,951 LOC** of
near-identical per-arity classes (Python 1,104 / C# 1,329 / TS 833 / Swift 685).
Each `AggregateVMN<VM1..VMN>` is a `ComponentVMBase` subclass with N typed
`ComponentN` accessors, a per-arity nested copy-on-write builder, and a
hand-written construct/destruct/dispose cascade. The audit recommends either
collapsing to a single tuple/variadic `AggregateVM<TTuple>` per flavor **or**
holding the cap at 5/6 and routing extra children through `CompositeVM`/`GroupVM`
— it explicitly accepts either outcome.

This is the single largest, highest-blast-radius change available in the v3
effort: a variadic/tuple rewrite would replace the type-safe public API in every
flavor and reimplement the most lifecycle-sensitive code in the framework. ADR-0007
already considered and **rejected** variadic generics (C# has none; the asymmetric
"variadic where supported" option would break the ADR-0006 symmetric-shape goal),
and ADR-0034 established that arity growth is handled additively — one explicit
class per minor bump — not by re-architecting to variadics.

## 2. Decision

**Hold the line.** v3 keeps the explicit, arity-typed
`AggregateVM1`…`AggregateVM6` public API in all four flavors. The hand-clone is
re-affirmed as the **deliberate, accepted cost** of compile-time arity-typed
safety with uniform cross-flavor parity, not accidental boilerplate. No public
API changes, no conformance-ID changes, no version bump. VMX-019 is **resolved as
WONTFIX (by design)**.

No internal dedup (shared private base / mixin / source generator) is applied in
this ADR either — see §3.5 for why the only plausibly-safe partial dedup was also
declined.

## 3. Per-flavor feasibility & risk assessment

### 3.1 C# — variadic rewrite infeasible; tuple rewrite is a regression

C# has **no variadic generics** (re-confirmed; the language still cannot express
`AggregateVM<VM1..VMN>`). The only "one class" shapes are:

- A tuple-based `AggregateVM<TTuple>`, which replaces the type-safe
  `AggregateVM2<A,B>` with tuple-soup `AggregateVM<(A,B)>` and **destroys the
  named, individually-typed `Component1`/`Component2` accessors** that consumers
  and the tree utilities bind to — a major ergonomic regression plus a total
  reimplementation of the lifecycle cascade.
- A roslyn **source generator** could emit the six classes from a template and
  dedup the *source* internally, but it adds a build-time toolchain dependency
  (analyzer project, generator debugging, IDE/CI generator-cache friction,
  `TreatWarningsAsErrors` interplay) — disproportionate machinery for a
  Minor-severity LOC finding, and it would not reduce the *public* surface at all.

Verdict: **reject** both. Hold the explicit classes.

### 3.2 Python — `TypeVarTuple` unavailable at the supported floor

`langs/python/pyproject.toml` declares `requires-python = ">=3.10"`.
`TypeVarTuple` (PEP 646), the only path to genuine variadic generics, requires
**3.11+**. A full variadic rewrite would therefore force a **breaking bump of the
consumer Python floor (3.10 → 3.11)** to pay down a Minor LOC finding — not a
trade v3 should make. Even on 3.11+, `TypeVarTuple` cannot ergonomically express
per-slot typed `component_1`…`component_n` accessors (no positional indexing of an
unpacked `*Ts` into distinct attribute types), so the typed surface would still
regress to a tuple.

Verdict: **reject**. Hold the explicit classes.

### 3.3 TypeScript — variadic tuples possible but accessors are load-bearing

TS *can* express variadic tuple types, but the per-arity builders and the named
`component1`…`componentN` accessors are **load-bearing for tree traversal**: the
`walk` family now consumes the typed `components()` accessor (VMX-023), and a
variadic rewrite would drop the named getters in favour of index access into a
tuple, a public-surface regression for the same Minor finding.

Verdict: **reject** the full rewrite. Hold the explicit classes.

### 3.4 Swift — parameter packs available but parity-breaking

Swift's package floor is `swift-tools-version: 5.9`, so value/type **parameter
packs are available**. A variadic `AggregateVM<each C>` is technically the most
feasible single-class rewrite of the four. But Swift is the **documented subset
flavor**; rewriting only Swift to a pack-based aggregate while C#/Python/TS keep
explicit arities would **break the ADR-0006 symmetric-shape goal** and the
cross-flavor parity that lets the conformance fixtures describe one shape. A
Swift-only divergence here buys nothing the other three can share.

Verdict: **reject**. Hold the explicit classes for cross-flavor parity.

### 3.5 Internal dedup (no public-API change) — also declined

The brief permits a *clean, low-risk* internal dedup (shared private base/mixin
for the repeated construct/dispose plumbing) if it keeps the public API and all
`AGG-*` tests green. We assessed it and **decline it** in every flavor:

- The dominant body is the **construct cascade** (`_onConstruct`): a per-slot
  factory call → `hub.send(PropertyChangedMessage … "componentN")` with a
  **literal property-name string** → `_raisePropertyChanged` → then a *second*
  pass calling `construct()` on each slot, preceded by a reconstruct pre-dispose
  of the previous slot instances. The literal channel names, the two-phase
  (all-factories-then-all-constructs) ordering, the reconstruct pre-dispose, and
  the LIFE-013 depth-first `dispose` ordering are all **behaviour-observable and
  conformance-tested**. Hoisting this into a shared base requires storing
  factories + channel names in an ordered list and writing slots back through a
  generic setter — which cannot preserve the per-slot *typed* `ComponentN` field
  without reflection.
- This exact plumbing has **historically drifted**: prior maintenance passes fixed
  AggregateVM `walk`/`dispose` drift and Python `AggregateVM1..6` LIFE-013
  dispose-ordering bugs. That track record is direct evidence the code is fragile
  to refactor and is held in shape by the per-arity explicitness, not in spite of
  it.
- The only *partially* safe reduction — looping `_onDestruct`/`dispose`/the
  reconstruct pre-dispose over the **already-existing** typed slot accessor
  (`components()` / `EnumerateSlots()`, added for VMX-023/137) — saves a marginal
  handful of lines per arity while coupling the lifecycle cascade to the traversal
  accessor on conformance-load-bearing code. The benefit does not justify the new
  coupling on the framework's most drift-prone path.

Decision: **decision-only**, no code change to any flavor.

## 4. Consequences

- `AggregateVM1`…`AggregateVM6` remain the public surface in all four flavors; the
  ~3,951 LOC hand-clone is an **accepted, documented cost**, not a defect.
- The arity-typed `ComponentN` accessors and per-arity builders are preserved
  exactly; consumers and tree utilities are unaffected.
- Future arities (7, 8, …) continue to follow the **ADR-0034 precedent**: add one
  explicit additive class per minor bump *if and when* a real consumer surfaces
  the need; do not re-architect to variadics. The typed `components()` /
  `EnumerateSlots()` accessor already decouples tree traversal from a hard-coded
  arity (VMX-023/137), so arity growth no longer ripples into `walk`.
- `spec/08-aggregate-vm.md` gains a short note recording that the arity-1..6
  surface is a deliberate design choice (this ADR), so the explicitness is not
  re-litigated as boilerplate in a later audit.
- No conformance IDs change; `AGG-001`…`AGG-006` continue to cover the surface.

## 5. Rejected alternatives

1. **Single tuple/variadic `AggregateVM<TTuple>` per flavor.** Rejected per §3:
   infeasible in C# (no variadics) and Python (3.10 floor < TypeVarTuple's 3.11),
   and a named-accessor + parity regression in TS/Swift — all to pay down a Minor
   LOC finding.
1. **C# source generator to emit the six classes.** Rejected: adds build-toolchain
   complexity and generator-debugging cost without reducing the public surface
   (§3.1).
1. **Shared private base/mixin for construct/dispose plumbing.** Rejected: the
   cascade is behaviour-observable, conformance-tested, and historically
   drift-prone; the only safe partial reduction is marginal and adds coupling
   (§3.5).
1. **Hard-cap arity at 5 and remove `AggregateVM6`.** Rejected: arity 6 already
   ships (ADR-0034) and backs the `WorkspaceVM` flagship; removing it would be a
   breaking change with no benefit.
