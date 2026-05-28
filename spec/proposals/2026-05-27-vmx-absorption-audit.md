# Proposal — VMx Absorption Audit (Post-v2.0)

**Status:** Proposal (not yet accepted)
**Date:** 2026-05-27
**Target spec version:** 2.1.0
**Sources audited:**

- `/Users/kaveh/repos/VMx.old/` — the 2012 C# WPF/Silverlight predecessor
- `/Users/kaveh/repos/My.Architecture.New/` — a parallel/sibling iteration of the same framework
- `/Users/kaveh/repos/My.Architecture.View/` — small View-side companion to the above
- `/Users/kaveh/repos/GuideArch.Old/` — Silverlight-era architecture decision app, embeds its own VMx fork
- `/Users/kaveh/repos/GuideArch/` — the current/upgraded version of the same app, builds its own MVVM stack (no VMx reference)

**Predecessor:** This audit subsumes `spec/proposals/hierarchical-vm.md`. The hierarchical proposal is accepted as item C1 here and will be replaced by an ADR + chapter when this audit is acted on.

## 1. Executive summary

After deep-reading all five codebases, the verdict is that the v2.0 rewrite already
absorbs the substantial majority of patterns from this lineage. The remaining
qualifying candidates fall into 15 distinct items across three priority tiers
(Critical 5, Important 6, Minor 4). Most candidates are *confirmed* by multiple
codebases, not invented by one — they represent the recurring pain points that
the framework has historically been asked to solve. One framework iteration
(`My.Architecture.New`) added zero novel concepts and serves only as
confirmation. The two GuideArch apps surface the genuinely new ground: a
dialog/file abstraction, paging, composite-key observable collections, and
granular collection notifications.

This document is the *menu* — what should be added, why, where, and at what cost.
A separate implementation plan (per `superpowers:writing-plans`) will follow
adoption.

## 2. Methodology

Three parallel deep-read agents catalogued the four newly-audited repos. Each
candidate was cross-referenced against (a) the v2.0 spec, (b) the existing
ADRs (especially the rejection-recording ones like 0003, 0005, 0018), and (c)
the prior VMx.old candidate punchlist from this conversation. An item only
qualifies as *new* if it is not already in the v2.0 spec and not deliberately
rejected by an existing ADR.

App-level domain logic (architecture decision modeling, candidate analysis,
constraint solving in GuideArch) was scoped out per the user's broad-but-
framework-focused scope decision. App-level *reusable infrastructure* (custom
collections, base ViewModels, dialog services) was scoped in.

## 3. Source matrix

A high-density view of where each candidate appears. ✓ = present, "\*" = present but commented-out / stubbed, blank = absent. "v2.0" column shows whether the v2.0 rewrite already covers it.

| #   | Candidate                                                             | VMx.old | My.Arch.New | My.Arch.View            | GuideArch.Old                            | GuideArch                       | v2.0               |
| --- | --------------------------------------------------------------------- | ------- | ----------- | ----------------------- | ---------------------------------------- | ------------------------------- | ------------------ |
| C1  | HierarchicalVM                                                        | \*      | \*          |                         | (graph VMs simulate)                     | (graph VMs simulate)            | proposal only      |
| C2  | DialogService / file-and-dialog abstraction                           |         |             | \* (`IDialogueFactory`) | (`DialogService` singleton)              | ✓ (own impl)                    | —                  |
| C3  | Paging (`IPageable` + paged composition)                              |         |             |                         | ✓ (embedded VMx + `Composition` wrapper) | ✓ (`Composition`)               | —                  |
| C4  | FormVM (snapshot/revert)                                              | ✓       | ✓           |                         | (uses VMx FormVM)                        |                                 | —                  |
| C5  | NotificationVM / ConfirmationVM (auto-dismiss render-side VMs)        | ✓       | ✓           |                         |                                          |                                 | — (hub only)       |
| I1  | Fluent command extensions (`.Confirm()`, `.SucceedWith()`, …)         | ✓       | ✓           |                         | ✓                                        | ✓                               | —                  |
| I2  | Hub-aware observable collection (`ServicedObservableCollection`)      | ✓       | ✓           |                         |                                          |                                 | —                  |
| I3  | Multi-key observable dictionary                                       |         |             |                         | ✓ (`ObservableDictionary<K1,K2,V>`)      |                                 | —                  |
| I4  | Granular collection notifications (`RaiseItemAdded/Removed/Replaced`) |         |             |                         | ✓ (`ObservableList<T>`)                  |                                 | —                  |
| I5  | `IFilterable<T>` (predicate-based, distinct from search-by-string)    |         |             |                         | ✓ (embedded VMx)                         | ✓ (in `Composition`)            | —                  |
| I6  | Service-as-VM adapter (NotificationServiceVM-style)                   | ✓       |             |                         |                                          |                                 | —                  |
| M1  | `PropertyValueChangedMessages<P>` (observable returning value)        | ✓       | ✓           |                         | ✓                                        | ✓                               | —                  |
| M2  | Reactive-init-token pattern (avoid double-subscribe)                  |         |             |                         | ✓                                        | ✓                               | —                  |
| M3  | `RelayCommand` auto-resubscribe to a property                         |         |             |                         | (in `Command`)                           | ✓ (`Command(...,obs,propName)`) | partial (triggers) |
| M4  | `CartesianProduct` / `Sample` / `Product` LINQ helpers                |         |             |                         | ✓                                        | ✓                               | —                  |

## 4. Already absorbed and deliberately rejected (recap)

This audit does **not** revisit:

- Concepts already in the v2.0 spec under any name. See `spec/00-overview.md` and the prior conversation summary.
- Concepts explicitly rejected by an existing ADR:
  - MEF `[Import]` / service locator / `Singleton<T>` → ADR-0003 (constructor injection).
  - Virtualization → ADR-0005 (out of scope).
  - Deep inheritance chain (`Unit` → `ObservableBase` → `VMBase` → `VM` → `MVMx`) → ADR-0018 (flat hierarchy).
  - `Expression<Func<T,P>>`-based property notification → ADR-0018 (replaced by `IMessageHub`).
  - Numbered `Composition1..11` slots in MVMxBase → ADR-0007 (`AggregateVM<VM1..VM5>` arity cap).

If the reader believes an existing ADR was wrongly decided in light of new
evidence, that belongs in a *separate* superseding ADR, not in this audit.

## 5. Adopted candidates — Critical tier

These five items are *essential* for the GuideArch family of apps to be
rewriteable on a future VMx without falling back to ad-hoc local infrastructure.

### C1 — `HierarchicalVM`

**Subsumes:** `spec/proposals/hierarchical-vm.md` (now superseded).

**Sources:**

- `VMx.old/ToDo/HierarchicalViewModel.cs` (commented-out reference design)
- `VMx.old/ToDo/HierarchicalViewModelBase.cs`, `HierarchicalViewModelContainer.cs`
- `My.Architecture.New/ToDo/HierarchicalViewModel.cs` (also commented-out, parallel attempt)
- Indirect evidence: `GuideArch/.../ViewModels/MainViewModel.cs` exposes `CandidateGraphViewModel` and `CriticalDecisionGraphViewModel` for tree-shaped views; today these would require manual recursive nesting of `CompositeVM<M, VM>`

**What it is:** A first-class tree-structured VM where each node may contain
children of the same VM type. The 2012 commented-out implementation answers most
of the open design questions in the existing hierarchical-vm proposal — eager
child loading, depth-first construction order, parent-change events on the hub,
root traversal cached.

**Proposed shape:** As per the existing `hierarchical-vm.md` proposal §3,
unchanged. Recursive generic constraint per flavor (C# `where TVM : HierarchicalVM<TModel, TVM>`, Python `T = TypeVar("T", bound=HierarchicalVM)`, TS
`T extends HierarchicalVM<TModel, T>`). Members: `Children`, `Parent`, `Depth`,
`Path`, `IsLeaf`, `IsRoot`, plus convenience `IsFirst`, `IsLast` from the
reference design.

**Spec impact:** New chapter `18-hierarchical-vm.md`. Extends `13-tree-utilities.md` (`walk`, `walk_expanded` natively support `HierarchicalVM`). Extends `06-composite-vm.md` (mention `HierarchicalVM` as the recursive specialization). Optionally extends `14-capabilities.md` (does `HierarchicalVM` auto-implement `IExpandable`? — design question retained from prior proposal).

**ADR:** New ADR resolving the prior proposal's six open questions. Working title: *0022 — HierarchicalVM (recursive composite specialization)*.

**Conformance IDs:** New prefix `HIER-NNN`. Suggested coverage ~12 IDs: identity, recursion, parent/depth/path invariants, eager-vs-lazy decision, construct order, hub messages on structural change, search/expand integration, lifecycle propagation, modeled vs non-modeled variant.

**Per-flavor impact:** New `hierarchical/` directory in all three flavors. Recursive generic ergonomics differ — captured in ADR-0009 (cross-flavor divergence catalogue) update.

**Diagrams:** One tree-structure diagram in `18-hierarchical-vm.md`; one construct-order sequence diagram.

**Test approach:** Conformance stubs in all three flavors. Per-flavor unit tests covering: recursive construction, parent/child invariants under mutation, depth/path recomputation on reparent (if allowed), hub message ordering on structural change, integration with `ExpandableState` and `SearchableState`.

### C2 — `IDialogService` (in core)

**Sources:**

- `GuideArch/GuideArch.Presentation/ViewModels/DialogService.cs` — singleton with file open/save, confirm prompt, generic notify
- `My.Architecture.View/IDialogueFactory.cs` — commented stub for a dialog factory
- `GuideArch.Old/...` (uses message-box-style flows via embedded VMx services)

**What it is:** A host-side contract for *modal* user interactions distinct from
the notification hub (which is fire-and-forget toast/banner). The dialog service
covers (a) file open/save dialogs (returning a stream or path), (b)
confirmation prompts (returning a boolean reaction synchronously-blocking the
caller), (c) free-form notify/alert. Concrete adapters per host (WPF, Avalonia,
console, test) live downstream; the core defines only the contract and a
`NullDialogService` per the ADR-0017 convention.

**Decision deviation from §3 draft:** The audit initially recommended this as
an opt-in companion package (`VMx.Dialogs`). The user has chosen to put it in
core. The downside is core surface growth; the upside is no extra packaging
infrastructure and discoverability. The contract is small and host-agnostic, so
the core-surface cost is contained.

**Proposed shape:** Async-returning methods. File operations return per-flavor
stream/path; confirm returns `Task<bool>` (C#) / `Awaitable[bool]` (Py) /
`Promise<boolean>` (TS); notify returns `Task` (fire-and-forget but awaitable).

```
IDialogService:
    PickFileToOpen(filter?, title?) -> Path?
    PickFileToSave(filter?, title?, suggestedName?) -> Path?
    Confirm(message, title?) -> bool
    Notify(message, title?, severity?) -> void
```

**Spec impact:** New chapter `19-dialogs.md`.

**ADR:** *0023 — Dialog service in core (host-modal interactions distinct from notification hub)*.

**Conformance IDs:** New prefix `DIA-NNN`. Suggested ~8 IDs: contract surface, `NullDialogService` behaviour (no-op / returns sensible defaults), reentrancy guarantees, cancellation semantics, async ordering vs the notification hub.

**Per-flavor impact:** New `dialogs/` directory in each flavor (contracts +
null impl). No host adapters in this repo; downstream consumers wire them.
`AggregateVM` consumers gain a way to ask for files and confirmations without
inventing their own.

**Diagrams:** Sequence diagram showing `IDialogService` vs `INotificationHub`
distinct responsibilities; flowchart for confirm-driven command execution.

**Test approach:** Conformance stubs in all flavors. Unit tests for
`NullDialogService` (deterministic no-op behaviour). Integration test wiring a
`ConfirmationDecoratorCommand` to `IDialogService.Confirm()` — this becomes a
canonical example.

### C3 — Paging (`IPageable` and a `PagedComposition` helper)

**Sources:**

- `GuideArch.Old/VMx/Contract/Receivers.cs` lines 241-260 (`IPageable` interface)
- `GuideArch.Old/VMx/Contract/IObservableComposition.cs` (paged composition contract)
- `GuideArch.Old/GuideArch.Presentation/ViewModels/Composition.cs` (wraps `PagedCollectionView`)
- `GuideArch/GuideArch.Presentation/ViewModels/Composition.cs` (mainline duplicate)

**What it is:** A capability interface declaring page size, current page index,
total pages, and navigation methods; plus a `PagedComposition` helper analogous
to `SearchableState` / `ExpandableState` that decorates a `CompositeVM` /
`GroupVM` with paged-view semantics. The paged view does not mutate the
underlying composition — it filters by index range.

**Proposed shape:**

```
IPageable:
    PageSize: int          # mutable; 0 means "all in one page"
    CurrentPageIndex: int  # mutable; clamped to [0, PageCount-1]
    PageCount: int         # derived; depends on item count and PageSize
    IsPagingEnabled: bool  # derived: PageSize > 0
    MoveToFirstPage(), MoveToPreviousPage(), MoveToNextPage(), MoveToLastPage()

PagedComposition<TVM>:
    Source: IComposition<TVM>      # adapted composition
    CurrentPage: IEnumerable<TVM>  # the current page slice
    # exposes IPageable surface
```

**Spec impact:** Section in the new collections chapter `21-collections.md`
(paging is a collection-view behavior; reduces chapter sprawl; conceptually
cohesive with the other collection primitives in that chapter). Extends
`14-capabilities.md` (`IPageable` joins the 20 capabilities — becomes 21).

**ADR:** *0024 — Paging helper (capability + decorator)*.

**Conformance IDs:** `COL-NNN` range (paging folded into COL- per Stage 0 decision). Suggested ~6 IDs: clamping behavior,
page-count derivation, navigation no-op at bounds, composition with `SearchableState`,
`PageSize = 0` semantics, empty-source behavior.

**Per-flavor impact:** New file in `collections/` per Stage 1 Substage 1C.

**Diagrams:** Diagram showing how `PagedComposition` slices a
`CompositeVM<M, VM>` without mutating it; interaction with `SearchableState`.

**Test approach:** Conformance stubs + unit tests for clamping, navigation,
page-count derivation under add/remove, ordering with `SearchableState`.

### C4 — `FormVM` (snapshot / revert)

**Sources:**

- `VMx.old/ViewModel/FormVM.cs` (DomainContext-coupled implementation)
- `My.Architecture.New/ViewModel/FormVM.cs` (DbContext-coupled)
- `VMx.old/Contract/ViewModel/IFormVM.cs`

**What it is:** A concrete VM that wraps a domain model with edit-lifecycle
semantics. On construction, it snapshots the model. It exposes `Approve` and
`Deny` (a.k.a. Cancel) commands. `Deny` reverts the in-memory model to the
snapshot via a flavor-idiomatic property-copy mechanism. `Approve` persists the
edited model via a consumer-supplied delegate or service.

The 2012 implementations couple to specific ORMs (WCF RIA `DomainContext` / EF
`DbContext`). The v2.x version MUST be ORM-agnostic: persistence is a
delegate or `IFormPersister<TM>` collaborator.

**Proposed shape:**

```
FormVM<TM>:
    Model: TM                      # the live, editable model
    Snapshot: TM                   # private; the original copy
    IsDirty: bool                  # derived: structural inequality of Model vs Snapshot
    DenyCommand: ICommand          # reverts Model to Snapshot, raises hub messages
    ApproveCommand: ICommand       # invokes consumer-supplied persist delegate
    OnApproved: event/observable   # fires after successful persist
```

**Spec impact:** New chapter `20-form-vm.md`.

**ADR:** *0025 — FormVM (snapshot/revert edit lifecycle, ORM-agnostic)*.

**Conformance IDs:** New prefix `FORM-NNN`. Suggested ~10 IDs: snapshot
identity, deep-vs-shallow snapshot policy (configurable), revert behaviour,
dirty detection, `ApproveCommand.CanExecute` is false when not dirty (optional
strict mode), hub messages on revert, persist failure handling, integration
with `IDialogService.Confirm()`.

**Per-flavor impact:** New `forms/` directory in each flavor.

**Diagrams:** State diagram (`Pristine` → `Dirty` → `Approved` / `Reverted`).

**Test approach:** Conformance + unit tests: snapshot-on-construct, revert with
nested object graphs, persist delegate invocation, persist failure (no state
mutation), hub message ordering.

### C5 — `NotificationVM` and `ConfirmationVM` (render-side VMs with auto-dismiss)

**Sources:**

- `VMx.old/ViewModel/NotificationVM.cs` (60-second auto-fade via Rx timer)
- `VMx.old/ViewModel/ConfirmationVM.cs` (300-second timeout; dual approve/cancel)
- `My.Architecture.New/ViewModel/NotificationVM.cs`, `ConfirmationVM.cs`
- `My.Architecture.New/Primitives/NotificationM.cs`, `ConfirmationM.cs`

**What it is:** Concrete render-side ViewModels that consume a
`Notification` from the notification hub and expose UI-bindable state:
`Opacity`, `Message`, `Type`, dismiss commands, and an auto-dismiss timer
tied to a configurable `Lifespan`. v2.0 has the *hub* and the *data*; it does
not have the *VM* that renders. Applications currently have to invent one.

**Proposed shape:**

```
NotificationVM:
    Notification: Notification     # the data
    Lifespan: TimeSpan             # configurable; default per type
    RemainingTime: TimeSpan        # derived, ticks down
    Opacity: double                # derived: RemainingTime / Lifespan
    DismissCommand: ICommand       # resolves the hub notification with Approve

ConfirmationVM : NotificationVM
    ApproveCommand: ICommand
    RejectCommand: ICommand        # resolves with Reject
    # Lifespan default is longer than NotificationVM
```

**Spec impact:** Extends `16-notifications.md`. No new chapter — the
notification hub already has a chapter and these VMs are its rendering
companions.

**ADR:** *0026 — Notification rendering VMs (NotificationVM, ConfirmationVM)*.

**Conformance IDs:** Extension to existing `NOTIF-` range. Suggested ~6 new
IDs: opacity decay, auto-dismiss on lifespan expiry, ConfirmationVM dual-action,
manual dismiss cancels timer, hub resolution propagates to VM state, deterministic
behavior under a fake clock (testability).

**Per-flavor impact:** New files in each flavor's `notifications/` subpackage.

**Diagrams:** Lifespan / opacity timeline.

**Test approach:** Per-flavor tests using fake-clock / virtual-time
schedulers (Rx has these built in). Conformance stubs.

## 6. Adopted candidates — Important tier

### I1 — Fluent command extensions

**Sources:**

- `VMx.old/Extensions/CommandExtensions.cs` (`.Confirm(msg)`, `.SucceedWith()`, `.PrecedeWith()`)
- `My.Architecture.New/Extensions/CommandExtensions.cs` (adds `.WrapWith(canPredicate, pre, post)`)
- `GuideArch.Old/Extensions/...` (equivalent)
- `GuideArch/GuideArch.Presentation/ViewModels/Command.cs` lines 191-209 (equivalent)

**What it is:** Three to four one-line extension methods on `ICommand` that
construct the existing decorator commands fluently:

```
cmd.Confirm("Are you sure?")          # → ConfirmationDecoratorCommand
cmd.PrecedeWith(otherCmd)             # → CompositeCommand(otherCmd, cmd)
cmd.SucceedWith(otherCmd)             # → CompositeCommand(cmd, otherCmd)
cmd.WrapWith(predicate, pre, post)    # → DecoratorCommand
```

Pure ergonomics on top of the decorators already in v2.0. The `.Confirm()` form
will hook into either a confirm delegate (matching `ConfirmationDecoratorCommand`'s
delegate-shaped contract per ADR-0012) or into `IDialogService.Confirm` (per
new ADR-0023). The choice — which is the default, which is opt-in — is the
ADR-resolved question.

**Spec impact:** Extends `04-commands.md` with a fluent-extensions subsection.

**ADR:** *0027 — Fluent command extensions*.

**Conformance IDs:** Extension to existing `CMD-` range (new IDs in the same prefix).

**Per-flavor impact:** Each flavor adds the methods idiomatically (C# extension
methods, Python module-level functions or method-style on the base class, TS
prototype or standalone functions).

**Diagrams:** None.

**Test approach:** Unit tests asserting the fluent forms construct the same
graph as the explicit constructors. Conformance stubs.

### I2 — `ServicedObservableCollection` (hub-aware collection)

**Sources:**

- `VMx.old/Primitives/ServicedObservableCollection.cs`
- `My.Architecture.New/Primitives/MessagingAwareObservableCollection.cs`

**What it is:** An `ObservableCollection<T>` that publishes its
`CollectionChanged` and `PropertyChanged` events through `IMessageHub` in
addition to (or instead of — design choice for ADR) the local events. Useful
when collection mutations need to drive cross-VM messaging without bespoke
event-forwarding.

**Spec impact:** Belongs in the new collections chapter `21-collections.md`.

**ADR:** *0028 — Hub-aware observable collection*.

**Conformance IDs:** New prefix `COL-NNN` (shared with I3 and I4 since they
all live in one collections chapter). Suggested IDs for this item: ~4 — basic
publish, ordering vs local handlers, null-hub fallback (no-op), threading.

**Per-flavor impact:** New file in each flavor's `collections/` directory
(this directory already exists in Python and TS per CLAUDE.md; C# uses
`Collections/` per ADR-0006 idiom).

**Diagrams:** None.

**Test approach:** Unit tests with a stub `IMessageHub` capturing published
messages; verify both add/remove/replace/reset events and PropertyChanged for
`Count` propagate.

### I3 — Multi-key observable dictionary

**Sources:**

- `GuideArch.Old/GuideArch.Model/Core/ObservableDictionary/ObservableDictionary.cs` — two-key (`K1, K2`) dictionary
- `GuideArch.Old/GuideArch.Model/Core/Dictionary/Dictionary.cs` — non-observable sparse-matrix backing

**What it is:** An observable dictionary keyed by a composite tuple. The 2012
implementation is two-key; the generalization to N-key (via a `Tuple<...>` or
per-flavor key-tuple idiom) is straightforward. Use case is any
matrix-/grid-shaped data binding — GuideArch uses it for
`decision × property → coefficient`.

**Generalization decision (for the ADR):**

1. Ship as concrete `ObservableDictionary<K1, K2, V>` (two-key only) — narrow but
   common.
1. Ship as `ObservableDictionary<TKey, V>` where `TKey` is a value-tuple — flexible.
1. Ship a base + thin two-key/three-key wrappers.

The ADR will pick. The audit slightly leans option 3 (ergonomic for the common case, extensible), but does not insist.

**Spec impact:** Section in collections chapter.

**ADR:** *0029 — Multi-key observable dictionary*.

**Conformance IDs:** `COL-NNN` range (shared). Suggested ~6 IDs: key insertion,
key removal, value replacement, distinct-key observables (the 2012 design
exposes `Keys1` and `Keys2` as observable collections), enumeration order,
hub messages.

**Per-flavor impact:** Per-flavor key-tuple idiom (C# `ValueTuple`, Python
`tuple[K1, K2]`, TS `[K1, K2]` tuple).

**Diagrams:** Grid diagram showing the two-key indexing.

**Test approach:** Unit + conformance, including coverage of distinct-key observable views.

### I4 — Granular collection notifications (`ObservableList<T>`)

**Sources:**

- `GuideArch.Old/GuideArch.Model/Core/ObservableList/ObservableList.cs`

**What it is:** A collection that raises granular notifications
(`ItemAdded(item, index)`, `ItemRemoved(item, index)`,
`ItemReplaced(newItem, oldItem, index)`, `CollectionReset()`) instead of (or in
addition to) the single coarse-grained `CollectionChanged` event with a
`NotifyCollectionChangedAction` discriminator. Better for diffing-driven UIs
and animations.

In v2.0, `CompositeVM`'s `BatchUpdate()` (per the existing spec) collapses many
mutations into a single `Reset`. `ObservableList<T>` is the inverse trade-off:
fine-grained per-mutation events.

**Spec impact:** Section in collections chapter.

**ADR:** *0030 — Granular collection notifications (`ObservableList<T>`)*.

**Conformance IDs:** `COL-NNN` range. Suggested ~5 IDs: per-event payload
shape, ordering with `PropertyChanged("Count")`, interaction with
`BatchUpdate()` semantics, opt-in / opt-out (does it raise the legacy event
too?).

**Per-flavor impact:** Per-flavor file in `collections/`.

**Test approach:** Unit + conformance covering each event payload and
ordering.

### I5 — `IFilterable<T>` (predicate-based)

**Sources:**

- `GuideArch.Old/VMx/Contract/Receivers.cs` lines 228-239
- `GuideArch.Old/GuideArch.Presentation/ViewModels/Composition.cs` (uses it)

**What it is:** A capability interface for collections / compositions that
support filtering by an arbitrary predicate. Distinct from `SearchableState`,
which filters by a search string + consumer predicate. `IFilterable<T>` is the
underlying contract that `SearchableState` could itself implement, or that a
consumer can use directly without the search-term ergonomics.

**Proposed shape:**

```
IFilterable<T>:
    Filter: Predicate<T>?     # null means "no filter"
    CanFilter(): bool         # whether filtering is currently allowed
```

**Spec impact:** Add to `14-capabilities.md`. `SearchableState` reframed as a
predicate-builder over `IFilterable<T>` (no breaking change — the
`SearchableState` surface stays the same, the underlying capability is exposed).

**ADR:** *0031 — `IFilterable<T>` capability*.

**Conformance IDs:** Extend `CAP-NNN` range (CAP-021).

**Per-flavor impact:** Per-flavor declaration in `capabilities/`.

**Test approach:** Conformance + a sanity test verifying `SearchableState`
satisfies the capability when built with default options.

### I6 — Service-as-VM adapter pattern

**Sources:**

- `VMx.old/Services/NotificationServiceVM.cs`

**What it is:** A recipe (not a new type) for wrapping a service whose state is
a collection (e.g., `INotificationHub.Pending`) as a `CompositeVM<M, VM>`,
projecting each service item into a child VM. The 2012 implementation is
specific to notifications; the pattern generalizes.

**Spec impact:** Recipe document — section in the notifications chapter, or a
new appendix-style chapter for cross-cutting recipes. Recommendation: a
"Patterns" section at the end of `16-notifications.md` with one canonical example.
Generalization to other services left as documentation, not normative spec.

**ADR:** Optional. If kept as recipe-only, no ADR. If formalized as a typed
adapter base class, *0032 — Service-as-VM adapter*.

**Conformance IDs:** None if recipe-only; a small number under `NOTIF-` if formalized.

**Per-flavor impact:** Example code per flavor in the chapter.

**Test approach:** Example test demonstrating the pattern wires `INotificationHub.Pending` to a `CompositeVM<Notification, NotificationVM>` (canonical sample).

## 7. Adopted candidates — Minor tier

### M1 — `PropertyValueChangedMessages<P>` (value-returning observable)

**Sources:**

- `VMx.old/Extensions/PropertyExtensions.cs`
- `My.Architecture.New/Extensions/...` (equivalent)
- `GuideArch.Old/Extensions/System.ComponentModel.cs` lines 126-131
- `GuideArch/Extensions/System.ComponentModel.cs` lines 126-131

**What it is:** A small ergonomic over `IMessageHub`: instead of subscribing to
`PropertyChangedMessage<TSource, TProperty>` and extracting `args.Value`,
provide an extension/helper that returns `IObservable<TProperty>` directly.

**Spec impact:** Extends `03-messages.md` (small subsection). Or — and the ADR
will decide — packaged as an extension method, not a spec-normative concept.

**ADR:** *0033 — Value-returning property-change observable helper*. May be
"informative" only (i.e., not a normative spec addition) — that's the cleanest
decision unless the helper has cross-flavor parity tests.

**Conformance IDs:** Likely none (helper, not contract). If included, extend `HUB-`.

**Per-flavor impact:** One small file per flavor's `messages/` or
`extensions/`.

**Test approach:** Per-flavor unit tests; no conformance.

### M2 — Reactive-init-token pattern (recipe)

**Sources:**

- `GuideArch/GuideArch.Presentation/ViewModels/ViewModelBase.cs` lines 107-111
- `GuideArch.Old/GuideArch.Presentation/ViewModels/MainViewModel.cs` lines 331-335

**What it is:** A pattern for ensuring a derived property's source-observable
subscription is created at most once per consumer-property-access, by storing
the subscription's `IDisposable` token keyed by the property name. Prevents
double-subscription bugs in lazy-initialization patterns.

In v2.0, `DerivedProperty<TValue>` (per ADR-0011) likely subsumes this
internally. If so: document as a recipe with a note that
`DerivedProperty` handles it for you. If not (or if there's still a gap):
small helper.

**Spec impact:** Documentation only — recipe in `15-derived-properties.md`.

**ADR:** None (recipe).

**Conformance IDs:** None.

**Per-flavor impact:** None unless gap exists.

**Test approach:** Verify (via `DerivedProperty` test) that double-subscription does not occur on repeated property reads. If gap exists, add a helper and tests.

### M3 — `RelayCommand` auto-resubscribe to a property

**Sources:**

- `GuideArch/GuideArch.Presentation/ViewModels/Command.cs` constructor overload `Command(Action, Func<bool>, INotifyPropertyChanged, string)` — lines 16-23

**What it is:** A constructor overload that auto-fires `CanExecuteChanged` when
a specified observable raises a `PropertyChanged` for a specified property name.
Per the existing `04-commands.md`, `RelayCommand` already supports arbitrary
`IObservable<Unit>` triggers; this is just an ergonomic shortcut around a
common case (trigger from "this VM's `IsX` property changing"). The audit
recommends verifying whether the existing triggers cover the use case
adequately; if so, no new code, possibly a small example added to the commands
chapter. If not, a small ergonomic addition.

**Spec impact:** Documentation only (verify gap first).

**ADR:** None unless gap exists.

**Conformance IDs:** None.

**Per-flavor impact:** None unless gap exists.

**Test approach:** Investigation, then test.

### M4 — `CartesianProduct` / `Sample` / `Product` LINQ helpers

**Sources:**

- `GuideArch.Old/Extensions/System.Linq.cs` lines 32-51
- `GuideArch/Extensions/System.Linq.cs` lines 32-51

**What it is:** Three generic LINQ-style helpers used by GuideArch's domain
code. `CartesianProduct` produces the cross-product of N sequences; `Sample`
takes every n-th element; `Product` is the multiplicative analogue of `Sum`.

These are not framework concepts — they're generic collection utilities. The
user has elected to include them. Per ADR-0006 (idiomatic API per language),
each flavor implements them idiomatically — but Python and TypeScript already
have library-standard or trivial equivalents (`itertools.product`,
`functools.reduce(operator.mul, ...)`, etc.). Recommendation: C# only (since
Python and TS have built-ins or trivial equivalents). The ADR records that
asymmetry.

**Spec impact:** None (utility helpers, not normative). Could live in `langs/csharp/src/VMx/Extensions/` (separate optional namespace) or in the `VMx.Extensions.DependencyInjection` companion package.

**ADR:** *0034 — LINQ utility helpers (C# only)*. Records the asymmetry.

**Conformance IDs:** None.

**Per-flavor impact:** C# only.

**Test approach:** C# unit tests.

## 8. Out of scope

- The **WPF View framework** from `My.Architecture.View/` (`ConceptualPanel`,
  `LogicalPanel`, `DisconnectedUIElementCollection`,
  `SurrogateVisualParentElement`, `DegenerateSibling`). Sophisticated WPF
  visual-tree work — but VMx is framework-neutral by design (ADR-0006 and the
  presentation-framework-neutrality goal in `00-overview.md`). The user has
  elected not to ship a `VMx.Wpf` companion package. These patterns remain in
  the historical record only.

- All items in §4 (already absorbed; deliberately rejected). These are not
  re-litigated by this audit.

- Domain logic from any audited app (architecture decision modeling,
  candidate solving, constraint analysis in GuideArch). Out of scope by the
  framework-only convention.

- Silverlight / WCF RIA Services-era integration patterns. Obsolete.

- `MetroButton` and other custom WPF controls; `ErrorWindow` global exception
  display; console host bootstrap. App-specific.

## 9. Cross-cutting placement: chapter and ADR numbering

This audit, if fully adopted, introduces:

- **4 new chapters** at the next available numbers (current top is `17-localization.md`):
  - `18-hierarchical-vm.md` (C1)
  - `19-dialogs.md` (C2)
  - `20-form-vm.md` (C4)
  - `21-collections.md` (I2, I3, I4 — and C3 paging as §5)
- **Extensions to existing chapters:**
  - `04-commands.md` — fluent extensions (I1), `RelayCommand` triggers example (M3)
  - `06-composite-vm.md` — cross-reference HierarchicalVM
  - `13-tree-utilities.md` — `walk` / `walk_expanded` extension to HierarchicalVM
  - `14-capabilities.md` — adds `IFilterable<T>` (I5, capability 21) and `IPageable` (C3, capability 22)
  - `15-derived-properties.md` — init-token recipe (M2)
  - `16-notifications.md` — NotificationVM / ConfirmationVM (C5), service-as-VM recipe (I6)
- **13 new ADRs** (0022-0034) per the per-candidate listings above. Recipe-only items (I6, M2, M3) may not need an ADR; the final count depends on those decisions.
- **~65 new conformance IDs** (rough breakdown: HIER ~12, DIA ~8, FORM ~10, COL ~21 [including ~6 for paging], extensions to CMD/CAP/NOTIF ~12). Exact counts will be set per-ADR.

**Paging placement (decided — Stage 0):** Paging (C3) lands as §5 of
`21-collections.md`, not as a standalone chapter. Rationale: paging is a
collection-view behavior, conceptually cohesive with `ServicedObservableCollection`,
`ObservableList`, and `ObservableDictionary`. Folding it in reduces chapter sprawl
and leaves the four new chapters as 18-hierarchical-vm, 19-dialogs, 20-form-vm,
21-collections. ADR-0024 documents the capability + helper together.

## 10. Spec versioning

**Decision:** The target spec version is **2.1.0**. Each active flavor moves
to its own **2.1.0**, matching the lockstep convention used through v2.0.

This change is **additive** — no existing IDs change, no existing contracts
break, no existing API is removed. By the SemVer policy in `spec/README.md`
§2, additive changes warrant a spec minor bump, not a major bump.

**Considered and rejected: 3.0.0.** Two arguments were raised for a major
bump: (1) the audit introduces 4 new chapters and ~75 new conformance IDs —
a materially larger surface than a typical minor; (2) several new capabilities
(`IPageable`, `IFilterable<T>`) join the capability set in `ADR-0010`,
making the catalog-shift visible. Neither argument outweighs SemVer-policy
alignment: size is not a SemVer trigger; the catalog growth is additive, not
breaking. Using 3.0.0 as a size signal would violate the policy's stated rule
and set a precedent that decouples version semantics from compatibility
guarantees. 3.0.0 is therefore rejected.

Per `CLAUDE.md`, each flavor versions independently but a spec major bump
forces a major bump in every active flavor. With a 2.1.0 minor bump, each
flavor is free to choose its own next version. All three active flavors
(csharp, python, typescript) will move to 2.1.0. This will be recorded in
`compatibility-matrix.md` as part of the release stage.

## 11. Documentation and diagram update plan

The user explicitly asked for "all applicable documentation and diagrams of
the repo to also get updated". Concrete files:

- `spec/VERSION` — bump.
- `spec/README.md` — add new chapters to `§1.2 Chapters (v2.0 additions)` (and
  consider renaming the subsection to `§1.2 Chapters (v2.x additions)`); add
  the new ADR range to `§1.3`.
- `spec/00-overview.md` — refresh the concept inventory; mention `HierarchicalVM`,
  `FormVM`, `IDialogService` in the overview.
- `spec/01-concepts.md` — extend the VM-types section to include
  `HierarchicalVM` and `FormVM`; document `NotificationVM` / `ConfirmationVM` as
  hub-adjacent rendering VMs.
- `spec/12-conformance.md` — add new IDs (~75) under their new prefixes; the
  catalog gains ~50% in size.
- `spec/ADRs/README.md` — register the new ADRs.
- `compatibility-matrix.md` — bump spec version + per-flavor versions; add a
  row per new chapter.
- Each flavor's top-level `README.md` (if present) — mention new features.
- Each flavor's package version file (`Directory.Packages.props` for C#,
  `pyproject.toml` for Python, `package.json` for TS) — bump.

**New diagrams to author** (one per new normative concept; rendered in
markdown via mermaid or PNG-with-source per existing repo convention — to be
checked when implementing):

1. `HierarchicalVM` tree structure + construct-order sequence — for `18-hierarchical-vm.md`.
1. `IDialogService` vs `INotificationHub` responsibility split — for `19-dialogs.md`.
1. `PagedComposition` slicing — for paging section.
1. `FormVM` state diagram (`Pristine` → `Dirty` → `Approved` / `Reverted`) — for `20-form-vm.md`.
1. `NotificationVM` lifespan / opacity timeline — for `16-notifications.md` extension.
1. Multi-key dictionary grid — for collections chapter.

Existing diagrams (if any are present in the spec — to be confirmed during
implementation) that reference the VM hierarchy will need refreshes to add
`HierarchicalVM` and `FormVM`.

## 12. Test coverage plan

The user asked for "ample test coverage for all added". The plan, at the
audit level, is:

**Conformance tests** (mandatory, enforced by `tools/check-conformance-coverage.py`):

- Every new normative ID gets a stub in all three flavor conformance trees
  (`langs/csharp/tests/conformance`, `langs/python/tests/conformance`,
  `langs/typescript/tests/conformance`). Per existing CI rule
  (`.github/workflows/spec-discipline.yml`), the stub-in-every-flavor rule is
  enforced in the same PR that adds the ID.
- ~65 new IDs × 3 flavors = ~195 new conformance test stubs. Each grows into
  a real test as the implementation lands.

**Per-flavor unit tests** (beyond conformance):

- Target: ~90% line coverage of new code in each flavor. Python's current
  suite is 475 tests at v2.0.0 (per `CLAUDE.md`) — this audit's adoption
  likely pushes that to ~700+.
- Special focus on:
  - Recursive lifecycle in `HierarchicalVM`.
  - Snapshot-revert edge cases in `FormVM` (nested objects, collections-as-properties).
  - Fake-clock / virtual-time tests for `NotificationVM` auto-dismiss.
  - Concurrent mutation tests for `ServicedObservableCollection`.
  - Boundary tests for `PagedComposition` (empty source, page-size > count, etc.).

**Integration tests:**

- Cross-feature interactions: `HierarchicalVM` + `ExpandableState` +
  `SearchableState`; `FormVM` + `ConfirmationDecoratorCommand` +
  `IDialogService.Confirm`; `PagedComposition` over a `SearchableState`-filtered source.

**CI gates** (already in place; no changes required by this audit):

- `tools/check-conformance-coverage.py --require csharp --require python --require typescript`
- Per-flavor type/lint/test pipelines (mypy strict, ruff, dotnet format, eslint, etc.)
- The existing `.github/workflows/spec-discipline.yml` ADR-required rule applies to every spec change in this audit.

## 13. Suggested phasing (high level)

The `superpowers:writing-plans` skill will produce the detailed plan. At the
audit level, the suggested high-level phasing — driven by the user's
"no merge to main until fully done" preference and the strict-clean-pass-gate
preference — is one long-running feature branch with these stages, each
ending in a multi-agent parallel audit (per the user's "thorough review before
shipping" preference):

1. **Stage 1 — Foundations**: Capability additions (`IPageable`, `IFilterable<T>`),
   collections chapter (I2 + I3 + I4 + C3 paging), fluent command extensions (I1).
   These are the cheapest, highest-leverage items.
1. **Stage 2 — HierarchicalVM** (C1). Largest single concept. Significant
   per-flavor implementation work.
1. **Stage 3 — Forms & Dialogs**: `FormVM` (C4) and `IDialogService` (C2). Often
   used together; testable together.
1. **Stage 4 — Notification VMs**: `NotificationVM` / `ConfirmationVM` (C5);
   service-as-VM recipe (I6).
1. **Stage 5 — Minors and polish**: M1, M2 (verify-or-add), M3 (verify-or-add),
   M4 (C# only), final documentation pass, diagram pass, README pass.
1. **Stage 6 — Release**: Final cross-flavor audit, conformance coverage
   verification, version bumps, compatibility-matrix update, release notes,
   merge to main.

Phasing is a suggestion; `writing-plans` may reshuffle based on dependency
analysis.

## 14. Acceptance criteria for the audit cycle

The whole adoption cycle is "done" when:

- All adopted candidates have either landed code or a documented decision-not-to-implement (for the verify-first items M2 and M3).
- All new conformance IDs have passing tests in all three flavors.
- `tools/check-conformance-coverage.py --require csharp --require python --require typescript` is clean.
- Spec is at the chosen version; each flavor's package is at the matching version; `compatibility-matrix.md` reflects it.
- All new chapters are written, with diagrams.
- `spec/README.md`, `spec/00-overview.md`, `spec/01-concepts.md`, `spec/ADRs/README.md` are updated.
- Multi-agent parallel audit (per user preference) returns a clean punchlist at the required number of consecutive zero-finding passes.
- The proposal file `spec/proposals/hierarchical-vm.md` is removed (superseded by chapter 18 + ADR 0022). This audit file itself becomes historical reference after acceptance.

## 15. References

- `spec/proposals/hierarchical-vm.md` — superseded by C1.
- `spec/ADRs/0003-constructor-injection.md` — basis for rejecting MEF / FactoryService.
- `spec/ADRs/0005-drop-virtualization-from-core.md` — rejection ADR; this audit does not revisit.
- `spec/ADRs/0006-idiomatic-api-per-language.md` — basis for asymmetric per-flavor decisions (e.g., M4 C#-only).
- `spec/ADRs/0010-capability-micro-interfaces.md` — basis for `IPageable` and `IFilterable<T>` joining the capability set.
- `spec/ADRs/0012-command-decorators.md` — basis I1 builds on.
- `spec/ADRs/0013-notification-service.md` — basis C5 and I6 extend.
- `spec/ADRs/0017-null-object-services.md` — basis for `NullDialogService` in C2.
- `spec/ADRs/0018-flat-vm-hierarchy-vs-old-chain.md` — basis for rejecting deep inheritance in any new VMs added by this audit.
- `CLAUDE.md` — project-level discipline (spec-discipline CI, conformance coverage, behavior-change workflow).
- `compatibility-matrix.md` — version coordination.
