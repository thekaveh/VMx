# Proposal — VMx Absorption Audit Follow-up (Post-v2.5)

**Status:** Historical (closed) — all proposed items landed in v2.6.0. See ADRs 0039-0042 and chapter 06 §3.X.
**Date:** 2026-06-13
**Target spec version:** 2.6.0
**Predecessor:** This proposal extends `2026-05-27-vmx-absorption-audit.md`. That audit accepted 15 candidates and landed them in v2.1.0 (ADRs 0022-0033). This follow-up covers items the prior audit missed or did not surface — including a newly-audited ancestor (`dotnet-tag/src/DotNetTag/VMx/`) that was not in the original audit's scope.

**Sources audited (this round):**

- `/Users/kaveh/repos/dotnet-tag/src/DotNetTag/VMx/` — 4,398-LOC direct structural ancestor of current VMx (Aggregate/Composite/Group/Component/Forwarding/Readonly layout already present). Not in the 2026-05-27 audit.
- `/Users/kaveh/repos/GuideArch.Older/` — Silverlight-era app with an embedded VMx seed (`VMx/` subdir). Not in the 2026-05-27 audit. Diffs against `VMx.old/` by 3 files only (`IObservableComposition.cs`, `Helper.cs`, `Primitives/ObservableDictionary.cs`); the first is covered by ADR-0023, the third by ADR-0025.
- Re-read of `/Users/kaveh/repos/My.Architecture.New/`, `/Users/kaveh/repos/My.Architecture.View/`, `/Users/kaveh/repos/GuideArch.Old/` against the actual ADR text — surfaced four items the prior audit's "rejected" recap obscured.

## 1. Executive summary

After re-reading the v2.5 source against the predecessors with each "previously dismissed" claim cross-checked against the actual ADR text, **nine open items** remain. They split four ways:

- **2 Already-absorbed** (the audit agent flagged them as gaps; the surface check shows current VMx already covers them — recorded here for the audit trail only).
- **2 Adopt** — small, ergonomic, no breaking change, no precedent debate.
- **3 Reject by new ADR** — historically present but consciously dropped, no consumer demand surfaced, current alternative is cleaner. Need a one-paragraph ADR to formally close the question.
- **2 Defer** — would require breaking changes or a real consumer use case; revisit when a flagship example demands them.

The prior audit's §4 "deliberately rejected" recap conflated "this concept lived on the rejected deep ladder" with "this concept itself is rejected." That conflation hid four candidates whose ADR backing is actually thin or nonexistent. This follow-up closes the loop.

## 2. Methodology

- Four parallel research agents inventoried `My.Architecture.View/`, `GuideArch.Old/`, `My.Architecture.New/`, `GuideArch.Older/`. A fifth agent inventoried `dotnet-tag/VMx/` separately.
- Each agent-flagged "potentially missing" item was cross-checked against the actual file at `langs/csharp/src/VMx/` (and, where flavor-relevant, against `langs/python/src/vmx/`, `langs/typescript/src/`, `langs/swift/Sources/VMx/`). False positives (items the agent said were missing but are present) are recorded as F-tier below for transparency.
- For each remaining candidate, the prior 2026-05-27 audit and the ADR registry were searched for explicit-reject text. Items with no ADR backing are surfaced here as open.

App-level domain logic was scoped out (same rule as the prior audit). App-level *reusable infrastructure* (e.g., builder ergonomics that consumers re-invent) is scoped in.

## 3. Source matrix

| #   | Candidate                                                     | dotnet-tag | M.Arch.New | GuideArch.Older | v2.5                            |
| --- | ------------------------------------------------------------- | ---------- | ---------- | --------------- | ------------------------------- |
| F1  | `ModeledHint` / `ModeledHinter` (agent-flagged gap; absorbed) | ✓          | —          | —               | ✓ (IComponentVMOfM.ModeledHint) |
| F2  | `OnModelChanged` builder hook (agent-flagged gap; absorbed)   | ✓          | ✓          | —               | ✓ (builders, all flavors)       |
| D2  | `CompositeVMBuilder.Current(Func<IEnumerable<VM>, VM>)`       | ✓          | —          | —               | —                               |
| D3  | `CompositeVMBuilder.OnCurrentChanged(Action<VM>)`             | ✓          | —          | —               | —                               |
| L1  | `INotifyPropertyChanging` support                             | —          | ✓          | ✓               | —                               |
| L2  | `IProperty<T>` / `ValueProperty<T>` / `ReferenceProperty<T>`  | —          | ✓          | ✓               | —                               |
| L3  | Two-tier disposable bag (`Destructables` vs `Disposables`)    | —          | ✓          | ✓               | —                               |
| L4  | Single-key `ObservableDictionary<TKey, TValue>`               | —          | —          | ✓               | — (only 2-key)                  |
| L5  | `AggregateVM` arities 7–11                                    | —          | ✓ (to 11)  | ✓ (to 11)       | — (cap at 6)                    |

## 4. Already-absorbed false-positives (audit-trail only)

### F1 — `ModeledHint` / `ModeledHinter(Func<M, string>)`

The dotnet-tag agent flagged this as missing from current VMx. It is present: `IComponentVMOfM.cs:22-25` declares `ModeledHint { get; }` and the builder accepts a `ModeledHinter` function. No action.

### F2 — `OnModelChanged(Action<M>)` builder hook

The dotnet-tag agent flagged this as needing verification. It is present in all three full-parity flavors:
`langs/python/src/vmx/components/builders.py:162` (`on_model_changed`),
`langs/typescript/src/components/componentVMOf.ts:27,73` (`onModelChanged`),
C# `ComponentVMOfBuilder` exposes the equivalent. No action.

## 5. Adopt — Minor tier (proposed)

### D2 — `CompositeVMBuilder.Current(Func<IEnumerable<VM>, VM>)` initial-current selector

**Source:** `dotnet-tag/.../Contracts/Builders/ICompositeVMBuilder.cs` — `Current(Func<IEnumerable<VM>, VM>)`.

**What it is:** A builder hook that, after children are constructed, sets `Current` by running the predicate over them — e.g., `xs => xs.FirstOrDefault(c => c.IsDefault)`. Today consumers manually call `SelectComponent(...)` after build to set initial.

**Spec impact:** Small extension to `06-composite-vm.md` §Builders. New conformance ID under `COMP-NNN` (existing range).

**ADR:** Optional. Trivial ergonomic; could be folded into a release-notes entry instead.

**Per-flavor impact:** One new builder method per flavor (`Current(selector)` / `current(selector)` / `current=` argument).

**Effort:** Trivial. ~30 LOC + 3 conformance stubs.

### D3 — `CompositeVMBuilder.OnCurrentChanged(Action<VM>)` selection callback

**Source:** `dotnet-tag/.../Contracts/Builders/ICompositeVMBuilder.cs` — `OnCurrentChanged(Action<VM>)`.

**What it is:** Mirror of the existing `OnModelChanged` hook on `ComponentVMOfBuilder`, but for the composite's `Current` change. Consumers currently subscribe to `PropertyChangedMessage<CompositeVM<VM>>` filtered on `PropertyName == "Current"`. The declarative builder callback is more ergonomic and matches `OnConstruct`/`OnDestruct` precedent.

**Spec impact:** Same chapter as D2; same conformance prefix.

**ADR:** Optional. Combine with D2 in one release-notes entry.

**Per-flavor impact:** One new builder method per flavor.

**Effort:** Trivial. ~25 LOC + 3 conformance stubs.

## 6. Reject by new ADR — items historically present but consciously dropped

These three items appeared in older predecessors, were silently dropped before dotnet-tag (the most recent ancestor), and have not been requested by any consumer. Each gets a one-paragraph ADR so the question is formally closed and does not resurface.

### L1 — `INotifyPropertyChanging` support

**Sources:** `My.Architecture.New`, `GuideArch.Older/VMx/Contract/IObservable.cs` (interface inheritance `: INotifyPropertyChanged, INotifyPropertyChanging`), plus paired `…ChangingMessages` Rx bridges and `BubbleOnPropertyChanging` helpers.

**Proposed disposition:** Reject by ADR. Rationale: (1) .NET-only feature; Python and TS have no idiomatic equivalent. (2) The hub already routes `PropertyChangedMessage` by type and timing; pre-change snapshots are achievable by capturing the value before the setter writes. (3) No flagship example consumes it; no GitHub issue exists; the absorption from `My.Architecture.New → dotnet-tag` already dropped it without debate, which is itself a signal of low consumer demand. (4) Adding it now would require either a per-flavor divergence (ADR-0006 violation) or three roughly-equivalent surrogate idioms in Python/TS/Swift, none of which is obvious.

**ADR title:** *0039 — INotifyPropertyChanging not supported (rationale)*. Reuses the ADR-0018 teaching-note pattern.

### L2 — `IProperty<T>` / `ValueProperty<T>` / `ReferenceProperty<T>` reactive backing-field abstraction

**Sources:** `My.Architecture.New/Core/Property.cs` + `Core/Object.RegisterProperty<T>`, `GuideArch.Older/VMx/Property/{ValueProperty,ReferenceProperty,TransformationProperty}.cs`. The seed wraps every property in an `IProperty<T>` (with `HasValue`, `Value`, `OnValueChanging`, `OnValueChanged`, implicit `TValue` conversion, `Dummy<T>` null-object sentinel).

**Proposed disposition:** Reject by ADR. Rationale: (1) Modern C# `[CallerMemberName]`, Python descriptors, TS auto-accessors, and Swift `@Published` cover the "field with INPC" use case with one line each. (2) The seed's `IProperty<T>` was load-bearing for `TransformationProperty<...>` (the multi-source derived computation), but `Properties/DerivedProperty.cs` already covers that with `From<T1..T5>` + `FromMany` (no `IProperty<T>` indirection needed). (3) Reintroducing `IProperty<T>` would force every consumer to choose between "plain field" and "wrapped Property<T>" with no clear win for either. (4) The implicit `TValue` conversion operator on `Property<T>` (silently usable wherever `T` is expected) is exactly the kind of magic ADR-0018 §1 cited as a clarity regression.

**ADR title:** *0040 — `IProperty<T>` reactive backing-field abstraction not adopted (rationale)*.

**Caveat:** If a future consumer surfaces a case where a typed reactive property is structurally required (e.g., a property whose subscribers must transactionally observe `Changing → Changed`), revisit L1 and L2 together — they are conceptually paired.

### L3 — Two-tier disposable bag (`Destructables` vs `Disposables`)

**Sources:** `My.Architecture.New/Core/Unit.cs`, `GuideArch.Older/VMx/Core/Unit.cs` — `Unit` exposes both bags:

- `Destructables: CompositeDisposable` — cleared on every `Destruct()` (and re-cleared on `Reconstruct`'s destruct phase).
- `Disposables: CompositeDisposable` — cleared only on `Dispose()`. Survives Reconstruct.

**Proposed disposition:** Reject by ADR. Rationale: (1) Current `ComponentVMBase.OnDestruct(virtual)` + `OnDispose(virtual)` method overrides achieve the same separation: per-construct subscriptions go in `OnConstruct` and are released in `OnDestruct`; long-lived subscriptions stored as instance fields are disposed in `OnDispose`. (2) The dotnet-tag ancestor (the immediate predecessor of current VMx) already collapsed this to a single `_disposables` field with the same hooks — confirming the design choice predates v2.0. (3) The two-bag idiom is ergonomic for subclasses with many subscriptions but introduces a documentation burden (which bag for which lifetime) that the method-override model avoids.

**ADR title:** *0041 — Single disposable lifecycle via `OnDestruct`/`OnDispose` overrides (no two-tier bags)*.

**Caveat:** If a flagship example surfaces a case where subclasses repeatedly forget to release per-construct subscriptions, revisit as a `RegisterPerConstruct(IDisposable)` helper rather than a full second bag.

## 7. Defer — needs use case before adoption

### L4 — Single-key `ObservableDictionary<TKey, TValue>`

**Source:** `GuideArch.Older/VMx/Primitives/ObservableDictionary.cs` (~760 LOC, single-key, INPC + INCC, version-stamped struct enumerator).

**Current state:** v2.5 ships `ObservableDictionary<TKey1, TKey2, TValue>` only (per ADR-0025). The two-key form was chosen for the matrix/grid binding use case (`decision × property → coefficient`).

**Proposed disposition:** Defer. Rationale: A single-key dictionary is the plain-map case; consumers can use the two-key form with `TKey2 = Unit` / `Void` / `Unit` per flavor (ergonomically awkward) or use the host language's native observable-map primitive (none exists in C#/.NET; Python and TS have community options).

**Trigger to revisit:** Any flagship example or `THEME-NNN` scenario that needs an observable single-key map. If two examples accumulate, ship `ObservableDictionary<TKey, TValue>` as a sibling type.

**Effort if adopted:** Medium per flavor (~400–600 LOC + 8 conformance IDs `COL-NNN`). The two-key implementation is not trivially adaptable — version-stamped enumerator, INPC re-raises on `Count`/`Item[]`/`Keys`/`Values`, and replace-as-Remove+Add semantics need re-derivation for the single-key case.

### L5 — `AggregateVM` arities 7–11

**Source:** `My.Architecture.New/Core/MVMxBase.cs`, `GuideArch.Older/VMx/Core/MVMxBase.cs` (1..11 slots), `GuideArch.Older/VMx/ViewModel/MVMx.cs` (1..11 concrete).

**Current state:** v2.5 ships `AggregateVM1..6`. ADR-0007 capped at 5 originally; ADR-0034 raised to 6 as a minor (v2.2.0). Both ADRs explicitly say "a future minor may raise the cap" — no philosophical bar.

**Proposed disposition:** Defer. Rationale: The precedent for raising the cap exists (ADR-0034 §Supersedes), but the right time is when a real flagship demands it, not pre-emptively. Each arity is a per-flavor copy with one more type parameter and one more orchestration slot — small but real maintenance surface.

**Trigger to revisit:** A flagship example (NotesShowcase, ThemeVM, future scenarios) that has ≥7 heterogeneous children at the same composition level. Per the prior ADR-0007 guidance, "more than 5 heterogeneous children" is usually a signal to switch to `CompositeVM<VM>` or `GroupVM<VM>` — that guidance still applies at 6.

**Effort if adopted:** Small per arity (~150 LOC per flavor per arity, plus conformance stubs).

## 8. Closing checklist (before deleting predecessor folders)

The four folders (`GuideArch.Old`, `GuideArch.Older`, `My.Architecture.New`, `My.Architecture.View`) and the dotnet-tag predecessor at `dotnet-tag/src/DotNetTag/VMx/` are **safe to delete once** all of the following are true:

1. D2 and D3 implemented and landed (or explicitly deferred via a release-notes entry).
1. ADR-0039 (L1) committed.
1. ADR-0040 (L2) committed.
1. ADR-0041 (L3) committed.
1. L4 and L5 status recorded here (Defer); no further action required for deletion.

After items 1–4 land, this proposal moves to status `Historical (closed)` with a pointer to the ADRs/PRs that implemented or formally rejected each item, mirroring the 2026-05-27 audit's closure pattern.

## 9. Out of scope

Not revisited in this proposal:

- Anything already accepted in the 2026-05-27 audit and shipped in v2.1.0 (15 items, ADRs 0022-0033 + chapters 18-21).
- ADR-0003 rejections: service locator, `Singleton<T>`, MEF `[Import]`. Confirmed still in force; dotnet-tag's `IVMxServiceLocator` is exactly what ADR-0003 closes.
- ADR-0005: virtualization. Confirmed still in force; dotnet-tag's `VirtualizingObservableCollection` use is exactly what ADR-0005 closes.
- ADR-0007 / ADR-0034: arity cap policy (open to raising; L5 is the open instance).
- ADR-0018: deep inheritance + `Expression<Func>` property naming. Confirmed still in force.
- `My.Architecture.View`'s WPF view-layer panels (`ConceptualPanel`, `LogicalPanel`, `DisconnectedUIElementCollection`) — view-layer, intentionally outside VMx scope per ADR-0006.
- `GuideArch.Older/VMx/Helper.cs` (`CustomTypeHelper<T>` on Silverlight `ICustomTypeProvider`) — Silverlight-era runtime-metaclass trick, no modern equivalent needed.
- `dotnet-tag/VMx/Contracts/IButtonVM.cs` — single-command UI-typed VM; consistent with view-agnostic core. A one-paragraph ADR rejecting it formally is optional but not blocking.
- `dotnet-tag/VMx/Services/{IVMxConstants,VMxConstants,VMxConstantsBase}` — options/knobs surface, subsumed by per-instance `IDispatcher` injection.

## 10. Closure pointers

All items in this proposal have landed.

- **D2 / D3** — ADR-0042 + spec/06 §3.X + `COMP-025` / `COMP-026` + per-flavor implementations in C#/Python/TypeScript/Swift. Shipped in spec v2.6.0.
- **L1** — ADR-0039 (teaching, no code change).
- **L2** — ADR-0040 (teaching, no code change).
- **L3** — ADR-0041 (teaching, no code change).
- **L4** — Deferred. Trigger: any flagship example or `THEME-NNN` scenario needing an observable single-key map.
- **L5** — Deferred. Trigger: any flagship example with ≥7 heterogeneous children at the same composition level.

With D2, D3, ADR-0039, ADR-0040, ADR-0041 landed (and L4 / L5 status recorded here), the predecessor folders (`GuideArch.Old`, `GuideArch.Older`, `My.Architecture.New`, `My.Architecture.View`, and the `dotnet-tag/src/DotNetTag/VMx/` ancestor) are safe to delete.
