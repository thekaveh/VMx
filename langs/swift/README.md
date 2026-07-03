# VMx — Swift

Hierarchical lifecycle-aware MVVM viewmodel framework for Swift,
spec-compatible with the C# / Python / TypeScript flavors.

## 1. Status

**v3.1.0 — total parity.** Covers **all 281 of 281** library conformance IDs
from `spec-v3.1.0` plus the 5 `THEME-00x` scenario IDs exercised by the
`examples/swift/notes-showcase/` flagship app (ADR-0067) = **286 total**, at
full parity with C#, Python, and TypeScript. Library IDs accumulated
incrementally (recounted honestly in ADR-0037; +COMP-025/COMP-026 added per
ADR-0042; +LIFE-008 via the v3 throwing-convergence in ADR-0053; +50 leaf-area
IDs via Phase-3 Inc-1 — ADR-0059; +30 collections IDs via Phase-3 Inc-2 —
ADR-0060; +29 hierarchical/threading/expand-collapse IDs via Phase-3 Inc-3 —
ADR-0061; +40 forms/commands/hub IDs via Phase-3 Inc-4 — ADR-0062; +25
notifications/dialogs IDs via Phase-3 Inc-5 — ADR-0063; +19 composite/group
IDs via Phase-3 Inc-6 — ADR-0064; +44 v3.1 upstream-consumer IDs via
ADR-0068..ADR-0079): the lifecycle state machine, the modeled
and unmodeled `ComponentVM`, `CompositeVM`, `CompositeVMOf`, `GroupVM`,
`AggregateVM1..6`, `RelayCommand`, `RelayCommandOf<T>`, `AsyncRelayCommand`,
`CompositeCommand`, `DecoratorCommand`, `ConfirmationDecoratorCommand`,
`ModeledCrudCommands`, fluent command helpers, the immutable fluent builders,
`DerivedProperty<T>`, the 22 capability micro-interfaces, null objects
(`NullMessageHub`, `NullDispatcher`, `NullLocalizer`), localization hook
(`Localizer` / `NullLocalizer`), tree utilities (`walk`, `find`,
`walkExpanded`), hub property accessors, forwarding decorators
(`ForwardingComponentVM`, `ForwardingCompositeVM`), observable collections
(`ObservableList`, `ObservableDictionary`, `ServicedObservableCollection`,
`PagedComposition`, collection-changed events, batch updates, auto-construct),
`ExpandableState` + expand/collapse traversal, `HierarchicalVM` (tree identity,
lazy/eager construction, structural mutation, builder, capability composition),
threading contracts (`ManualScheduler`, `VirtualTimeScheduler`, foreground
dispatch, async selection), `SearchableState` (composite and group contexts),
message hub semantics, `FormVM` (snapshot/dirty/approve/deny lifecycle), dialog
service (`DialogService` / `NullDialogService`), and the notifications
sub-package (`NotificationHub`, `NotificationVM`, `ConfirmationVM`,
`makeConfirm` bridge). Requires Swift 5.9+, Combine, iOS 16 / macOS 13 /
tvOS 16 / watchOS 9. The notes-showcase flagship (SwiftUI + Combine, macOS)
is at `examples/swift/notes-showcase/`; see §5.

## 2. Install

The source tree currently implements v3.1.0. SwiftPM consumes VMx from git
tags; use the versioned dependency after a `swift-v*` release publishes it.

Add VMx as a Swift Package dependency in `Package.swift`:

```swift
dependencies: [
    .package(url: "https://github.com/thekaveh/VMx.git", from: "X.Y.Z")
],
targets: [
    .target(name: "MyApp", dependencies: [
        .product(name: "VMx", package: "VMx")
    ])
]
```

Or in Xcode: **File → Add Package Dependencies → enter the repo URL**.

For local development from a checked-out clone:

```swift
dependencies: [
    .package(path: "/path/to/VMx/langs/swift")
]
```

## 3. Quick start

```swift
import VMx

struct TabModel: Equatable {
    let title: String
}

// 1. Services (a hub + a dispatcher).
let hub = MessageHub()
let dispatcher = ImmediateDispatcher.INSTANCE

// 2. Build leaves: name, model, services, optional modeledHinter.
let tab1 = try ComponentVMOf<TabModel>.builder()
    .name("home")
    .model(TabModel(title: "Home"))
    .modeledHinter { $0.title }
    .services(hub: hub, dispatcher: dispatcher)
    .build()

let tab2 = try ComponentVMOf<TabModel>.builder()
    .name("settings")
    .model(TabModel(title: "Settings"))
    .services(hub: hub, dispatcher: dispatcher)
    .build()

// 3. Build a composite over the leaves.
let tabs = try CompositeVM<ComponentVMOf<TabModel>>.builder()
    .name("tab-bar")
    .services(hub: hub, dispatcher: dispatcher)
    .children { [tab1, tab2] }
    .build()

// 4. Transition the lifecycle from .destructed → .constructed before use.
//    Lifecycle ops are throwing in v3 (ADR-0053): an illegal transition raises
//    a catchable `StatusTransitionError` instead of trapping.
try tabs.construct()
print(tabs.status)              // ConstructionStatus.constructed

tabs.current = tab2             // setter traps on a non-child; use
                               // try tabs.setCurrent(tab2) for a catchable check
print(tabs.current?.model.title) // "Settings"

tabs.dispose()                  // dispose() is terminal/idempotent — never throws
hub.dispose()
```

The C# / Python / TypeScript flavors mirror this shape — only the
identifier casing differs (per ADR-0006: Swift uses **camelCase**,
matching the TypeScript flavor).

See [docs/integration/swiftui.md](../../docs/integration/swiftui.md) for
a one-page SwiftUI integration recipe.

### 3.1 Cross-language naming

| Concept             | C#                  | Python             | TypeScript         | Swift              |
| ------------------- | ------------------- | ------------------ | ------------------ | ------------------ |
| Unmodeled VM        | `ComponentVM`       | `ComponentVM`      | `ComponentVM`      | `ComponentVM`      |
| Modeled VM          | `ComponentVM<M>`    | `ComponentVMOf[M]` | `ComponentVMOf<M>` | `ComponentVMOf<M>` |
| Status property     | `Status`            | `status`           | `status`           | `status`           |
| Builder entrypoint  | `Builder()`         | `builder()`        | `builder()`        | `builder()`        |
| Null hub singleton  | `NullMessageHub.Instance` | `NULL_MESSAGE_HUB` | `NullMessageHub.INSTANCE` | `NullMessageHub.INSTANCE` |

## 4. API surface

```swift
import VMx
```

Key exports:

| Export                          | Description                                      |
| ------------------------------- | ------------------------------------------------ |
| `ComponentVM`                   | Leaf viewmodel (no model)                        |
| `ComponentVMOf<M>`              | Leaf viewmodel with a typed model                |
| `ReadonlyComponentVMOf<M>`      | Leaf VM with externally read-only model          |
| `CompositeVM<VM>`               | Homogeneous-child container + `current` slot     |
| `GroupVM<VM>`                   | Homogeneous peer container (no current)          |
| `AggregateVM1..6<...>`          | Fixed-arity heterogeneous component slots        |
| `RelayCommand`                  | Executable command with `canExecute`             |
| `MessageHub` / `NullMessageHub.INSTANCE` | Combine-backed pub/sub + null variant   |
| `Dispatcher`                    | Foreground/background work scheduler protocol    |
| `DefaultDispatcher`             | Main + global-userInitiated Dispatch wrapper     |
| `ImmediateDispatcher.INSTANCE`  | Synchronous test dispatcher                      |
| `NullDispatcher.INSTANCE`       | Null-object variant per ADR-0017                 |
| `ConstructionStatus`            | 5-state lifecycle enum                           |
| `StatusTransitionError`         | Thrown on an illegal lifecycle op / `LIFE-008` guard (catchable — ADR-0053) |
| `CompositeMembershipError`      | Thrown by `CompositeVM.setCurrent(_:)` on a non-child (ADR-0053) |
| `BuilderValidationError`        | Thrown when a builder is missing a required field |

## 5. Conformance — total parity (286)

This flavor implements **all 281 library conformance IDs** from the
cross-language conformance catalog (Inc-0: 44 base IDs per ADR-0037/ADR-0053;
Inc-1: +50 leaf-area IDs per ADR-0059; Inc-2: +30 collections IDs per ADR-0060;
Inc-3: +29 hierarchical/threading/expand-collapse IDs per ADR-0061;
Inc-4: +40 forms/commands/hub IDs per ADR-0062;
Inc-5: +25 notifications/dialogs IDs per ADR-0063;
Inc-6: +19 composite/group IDs per ADR-0064;
Inc-7: +44 v3.1 upstream-consumer IDs per ADR-0068..ADR-0079). The covered IDs are:

```
LIFE-001..014   lifecycle state machine + fixture-driven transition table
                (LIFE-005/006/008 assert catchable throws — ADR-0053;
                LIFE-011 fixture-backed table now covered via Bundle.module)
CVM-001..006    ComponentVM / ComponentVMOf identity + model
                (CVM-003: read-only model setter still traps —
                Swift setters cannot throw — per ADR-0053)
COMP-001/002,   CollectionChanged events on CompositeVM (Inc-2 — ADR-0060)
COMP-003..005,  select-through-child + lifecycle cascades +
COMP-025/026    builder `current(selector)` / `onCurrentChanged(callback)` hooks
COMP-012/013    autoConstructOnAdd + BatchUpdateHandle (Inc-2 — ADR-0060;
                assertionFailure on construct failure; explicit dispose() safety net)
GRP-001..004    group surface contract + lifecycle cascades + CollectionChanged (Inc-2)
GRP-005/006     autoConstructOnAdd + BatchUpdateHandle on GroupVM (Inc-2 — ADR-0060)
GRP-011         group children are non-selectable peers (ADR-0079)
AGG-001..006    AggregateVM1..AggregateVM6 parametric coverage
CMD-001..004, 006   RelayCommand task + predicate + triggers (Inc-0)
BLD-001..006    builders immutable + validation + defaults + options factories
PROP-001..004   hub property-change accessors
NULL-001..003   NullMessageHub + NullDispatcher null-object contracts
LOC-001..003    Localizer protocol + NullLocalizer null-object (no I-prefix — ADR-0006)
UTIL-001..003   walk (DFS, nil-slot skip) + find (short-circuit) tree utilities
                (materialized arrays)
FWD-001..003    ForwardingComponentVM + ForwardingCompositeVM decorators
                (name/hint copied at super.init — non-overridable let — ADR-0059;
                composite surface mirrors real CompositeVM)
DPROP-001..012  DerivedProperty<T> — setValue(_:) throws / value is a throwing property;
                distinct-until-changed via valueEquals closure (ADR-0059)
CAP-001..022    22 capability micro-interfaces — generic verbs use associatedtype
                Item (PAT); opt-in by structural conformance (as?/is); reactive
                state via Combine publishers (ADR-0059)
COL-001..023    ObservableList, ObservableDictionary, ServicedObservableCollection,
                PagedComposition (Inc-2 — ADR-0060):
                "Count" channel is spec-literal (not Swift-idiomatic "count");
                ObservableDictionary null-key enforcement is structural
                (non-optional generic key + struct CompositeKey: Hashable);
                PagedComposition uses setSource(_:) (value-semantics);
                CollectionChangedEvent/Message are value-type structs with
                CollectionChangedAction enum + named-struct per-mutation payloads
EXP-001..005    ExpandableState machine (isExpanded / toggle / expand / collapse)
                + walkExpanded DFS expansion-gated traversal (Inc-3)
HIER-001..009   HierarchicalVM tree identity — recursive CRTP constraint,
                parent/depth/path/isLeaf/isRoot/isFirst/isLast, lazy + eager
                child construction, depth-first ordering (Inc-3)
HIER-010/011    addChild/removeChild/reparentChild hub notifications —
                PropertyChangedMessage("parent") + TreeStructureChangedMessage
                (added/removed/reparented shapes) (Inc-3)
HIER-012        walkExpanded honors ExpandableState gate: collapsed node pruned,
                expanded node descends; HierarchicalVM conforms to _TreeContainer
                (Inc-3 capability composition)
HIER-013        SearchableState composed over materialized children filters by
                search term (Inc-3 capability composition)
HIER-015        HierarchicalVMBuilder<M, VM>.build() validates required fields —
                model / childrenFactory / services / vmFactory (vmFactory required
                because TVM: AnyObject has no init surface — ADR-0061 §2.2) (Inc-3)
HIER-016        HierarchicalVMBuilder repeated identical build() calls each return
                a fresh TVM instance (Inc-3)
HIER-017        HierarchicalVMBuilder field defaults — name defaults to
                String(describing: TVM.self); eagerChildren defaults to false (Inc-3)
HIER-018        reparentChild self/ancestor guard — throws HierarchyError,
                tree unchanged, no message published on rejection (Inc-3)
THR-001..004    Threading contracts — PropertyChanged foreground scheduling,
                background construct deferral, CollectionChanged foreground
                scheduling, ObserveOn subscriber scheduling; tested via
                hand-rolled ManualScheduler + ManualDispatcher (no Combine
                TestScheduler — ADR-0061 §2.7) (Inc-3)
COMP-006        Previous child's isCurrent flip dispatched through foreground
                target (dispatcher.scheduleForeground) — ManualDispatcher test
                confirms 0 emissions before flush, 1 after (Inc-3)
COMP-009        setCurrent(_:) throws CompositeMembershipError on a non-child;
                canSetCurrent(_:) pre-flight predicate (ADR-0053) (Inc-3)
COMP-010        asyncSelection opt-in builder flag — defers the full current-change
                through foreground target; TOCTOU guard drops stale selection if
                child removed before flush (Inc-3 — ADR-0061 §2.8)
CMD-005         RelayCommandOf<T> — parameterized relay command; canExecute/execute
                take a T parameter; does NOT conform to Command (mirrors TS's distinct
                ICommandOf<T> surface); canonical name RelayCommandOf<T> — no OfT
                alias (ADR-0052) (Inc-4 — ADR-0062 §2.5)
CMD-007         truth-table fixture verification — loads command-truthtable.json
                from Bundle.module (Inc-4 — ADR-0062 §2.5)
CMD-008..011    fluent command helpers — confirm, precedeWith, succeedWith, wrapWith
                (Inc-4)
CMD-012         AsyncRelayCommand — Task-based cancellable body + Combine channels
                (canExecuteChanged, errors); cooperative Task.isCancelled /
                checkCancellation; default cancel completes normally; throwOnCancel()
                opt-in rethrows; fire-and-forget execute() routes CancellationError
                to errors when throwOnCancel (Inc-4 — ADR-0062 §2.1)
CMDD-001..003   CompositeCommand — canExecute OR-gate, execute skips disabled
                inners, canExecuteChanged merges inners (Publishers.MergeMany)
                (Inc-4)
CMDD-004..006   DecoratorCommand — canExecute AND-gate, pre→defer(post)→inner
                execution order, no-op when disabled; postExecute guaranteed via
                defer (ADR-0062 §2.5) (Inc-4)
CMDD-007..010   ConfirmationDecoratorCommand — confirm typed () async throws -> Bool;
                execute() fire-and-forget via Task; failures route to Combine errors
                channel (CMDD-010 — ADR-0062 §2.2); CMDD-009 composition with
                DecoratorCommand (Inc-4)
HIER-014        ModeledCrudCommands compose onto HierarchicalVM and mutate the tree
                (Inc-4)
HUB-001..006    MessageHub synchronous delivery, hot (no replay), FIFO ordering,
                cancel-in-handler safe, multiple-subscriber fan-out,
                message-ordering fixture (HUB-006 from Bundle.module) (Inc-4)
HUB-007         subscribe(_:) opt-in isolation — catchable errors path; raw messages
                Combine-sink divergence documented (non-throwing sinks / trapping
                handlers uncatchable on the raw path — ADR-0062 §2.4) (Inc-4)
FORM-001..015   FormVM<Model> standalone final class (NOT ComponentVMOf subclass —
                ADR-0030; FormVM has no lifecycle); isDirty via injectable equals
                closure (Equatable-default convenience init); snapshotter identity-
                default for value types, injectable for reference members;
                approveAsync captures model snapshot before await, mutates only on
                success; onApproved / approveErrors sealed Combine channels;
                approveCommand fire-and-forget surfaces failures on approveErrors
                (FORM-015); strict canExecute gating via isDirty transition triggers;
                FormVMBuilder with validation, hub / strict / snapshotter / equals
                overrides (Inc-4 — ADR-0062 §2.3)
DIA-001..008    DialogService protocol — methods are async, NOT throws (DIA-007
                non-throwing safe-default alignment — ADR-0063 §2.1); file-picker
                methods return String? (cross-flavor fixture parity, not URL?);
                NullDialogService returns nil/false/no-op with INSTANCE singleton;
                confirmWithDialogService fluent overload wraps ConfirmationDecoratorCommand
                with a dialog-confirm gate (DIA-008); no Combine publishers on the
                dialog surface (request/response async — deliberate counterpart to
                the stream-based notification hub) (Inc-5 — ADR-0063)
NOTIF-001..008  Notification final class (identity-distinct, ObjectIdentifier-keyed
                waiters — struct rejected, ADR-0063 §2.3); post suspends via
                withCheckedContinuation, store-then-emit ordering guarantees
                waiter registered before pending snapshot emitted; pending via
                Combine CurrentValueSubject (replay-latest); snapshots and
                continuation resumes emitted outside NSLock (re-entrancy safety
                — ADR-0063 §2.3); NotificationHubProtocol + NotificationHub
                (Inc-5 — ADR-0063)
NOTIF-009       NullNotificationHub — INSTANCE singleton; pending via
                Just([]).eraseToAnyPublisher() (synchronous, always-empty);
                post returns .approve immediately (no suspension) (Inc-5)
NOTIF-010       makeConfirm bridge — free function wrapping hub.post/resolve into
                an async Bool gate (Inc-5)
NOTIF-011..016  NotificationVM (open class) + ConfirmationVM (final class :
                NotificationVM) — opacity/remaining decay driven by hand-rolled
                VirtualTimeScheduler (Combine has no framework virtual-time
                scheduler — ADR-0063 §2.4); time in TimeInterval seconds (ADR-0009
                time divergence vs TS lifespanMs); single-resolution guard
                (isResolved flag) across dismiss/command/timer/external-resolve
                paths; ConfirmationVM.armsExpiryTimer() overridden false (no
                auto-dismiss); propertyChanged emits Swift-idiomatic names
                ("isResolved" / "remaining" / "opacity") (Inc-5 — ADR-0063 §2.4)
NOTIF-017       NotificationHub dispose — in-flight post waiters resume .pending;
                pending completes via subject.send(completion: .finished);
                post-after-dispose returns .pending without enqueuing (double-check
                inside withCheckedContinuation closes the dispose-races-post race);
                idempotent; dispose() on concrete class only (not on protocol —
                matches TS shape; NullNotificationHub unaffected) (Inc-5 —
                ADR-0063 §2.5)
COMP-007        CompositeVMOf<Model, VM: ComponentVMBase> — modeled composite;
                non-recursive generic (VM: ComponentVMBase, no CRTP relaxation
                needed — unlike HierarchicalVM in ADR-0061); childrenFactory route
                to super.init; CompositeVMOfBuilder with copy-on-write validation
                (name → services → childrenModels → childModelToChildViewModel);
                children are typically ComponentVMOf<Model> exposing .model (Inc-6
                — ADR-0064 §2.1)
COMP-008        selectComponent(_:) throws CompositeMembershipError when vm is not
                a member or status != .constructed; canSelectComponent(_:) = member
                AND status == .constructed (distinct from canSetCurrent — membership
                only) (Inc-6 — ADR-0064 §2.2)
COMP-011        deselectComponent(_:) throws CompositeMembershipError when vm is not
                the current selection; current unchanged on throw; calls _setCurrent(nil)
                on success (Inc-6 — ADR-0064 §2.2)
COMP-014..018   SearchableState<T> composite context — filtered items by search term;
                CurrentValueSubject backing + PassthroughSubject force-immediate
                merge; synchronous search() bypass; lazy items closure re-reads on
                recompute (Inc-6 — ADR-0064 §2.3)
COMP-019..024   ModeledCrudCommands<VM> — createNewCommand, updateCurrentCommand,
                deleteCurrentCommand (canExecute false when current nil);
                ConfirmationDecoratorCommand wrapping for COMP-024; no phantom M
                parameter (ADR-0006) (Inc-6 — ADR-0064 §2.4)
COMP-027        add/remove parent-link wiring — add(child) sets child.parent;
                remove(child) clears it; canSelect/select composition enabled by
                parent reference (Inc-6 — ADR-0064 §2.4)
GRP-007..010    SearchableState<T> group context — same Combine-native implementation
                as COMP-014..018; GRP-010 uses Int(t) ?? 0 numeric-term predicate
                (Swift equivalent of TS Number(t) || 0) (Inc-6 — ADR-0064 §2.3)
CMD-013         disposed RelayCommand / RelayCommandOf<T> are inert (ADR-0068)
COL-024..031    TokenPagedComposition cursor flow and source observation (ADR-0069)
COMP-028..037   FilteredCompositeVM and ScoredFilteredCompositeVM (ADR-0070)
FORM-016..023   declarative FormVM field/model validation (ADR-0071)
DIA-009..013    ModalVM / BasicModalVM presentation lifecycle (ADR-0072)
HIER-019..022   explicit child-cache invalidation (ADR-0073)
DISC-001..006   DiscriminatorVM active key + modal stack coordinator (ADR-0075)
```

**THEME scenario IDs (example app — not scraped by the library coverage gate):**

- `THEME-001..005` — covered by `ThemeVMTests.swift` in
  `examples/swift/notes-showcase/NotesShowcaseTests/`; validated by the
  `examples (notes-showcase)` CI job in `.github/workflows/swift.yml`.

**All 281 library conformance IDs are covered, and the 5 `THEME-00x` scenario IDs are covered by the `examples/swift/notes-showcase/` flagship. Swift is at total parity (286) with C#, Python, and TypeScript.**

Run the suite:

```bash
swift test
```

## 6. Development

```bash
# From this directory
swift build
swift test
```

## 7. License

Apache-2.0 — see [`LICENSE`](../../LICENSE) and [`NOTICE`](../../NOTICE).
