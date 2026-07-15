# vmx — C#

Hierarchical lifecycle-aware MVVM viewmodel framework for .NET,
spec-compatible with the Python, TypeScript, Swift, and Rust flavors.

## 1. Status

**v3.22.0** — implements `spec-v3.22.0` end-to-end. 395/395 library conformance IDs
pass. Multi-targets `netstandard2.0` and `net8.0`.
Two companion assemblies ship: `VMx.Extensions.DependencyInjection`
(`services.AddVMx(...)`) at `2.1.1` and `VMx.Notifications` (opt-in
`INotificationHub`) at `1.2.0` (min spec 2.6.0). Each is independently
versioned per ADR-0009 / ADR-0013 and stays on its own release line
(the DI companion does not pull the core bump); see
`../../compatibility-matrix.md`. The Swift flavor is at total parity; see
`../swift/README.md` §5 for the current conformance matrix.

## 2. Install

The source tree currently implements v3.22.0. The NuGet package has not been
published yet; use a project reference for local development until a `csharp-v*`
release tag publishes it.

```bash
dotnet add package VMx

# Optional DI integration (Microsoft.Extensions.DependencyInjection)
dotnet add package VMx.Extensions.DependencyInjection
```

## 3. Quick start

The minimum-viable shape is `imports → services → builder
(name + model + services + optional hinter) → Construct() → read Status`:

```csharp
using VMx.Components;
using VMx.Composites;
using VMx.Lifecycle;
using VMx.Services;

public record TabModel(string Title);

// 1. Services (a hub + a dispatcher). Production code injects real services;
//    tests and samples can use .WithNullServices() instead (see below).
var hub = new MessageHub();
var dispatcher = RxDispatcher.Immediate();  // both schedulers = ImmediateScheduler.Instance

// 2. Build leaves: Name, Model, Services, optional ModeledHinter.
var home = ComponentVM<TabModel>.Builder()
    .Name("home")
    .Model(new TabModel("Home"))
    .ModeledHinter(m => m.Title)  // optional — defaults to _ => ""
    .Services(hub, dispatcher)
    .Build();

var settings = ComponentVM<TabModel>.Builder()
    .Name("settings").Model(new TabModel("Settings")).Services(hub, dispatcher).Build();

// 3. Build a composite over the leaves.
var tabs = CompositeVM<ComponentVM<TabModel>>.Builder()
    .Name("tab-bar")
    .Services(hub, dispatcher)
    .Children(() => new[] { home, settings })
    .Build();

// 4. Transition the lifecycle from Destructed → Constructed before use.
tabs.Construct();
Console.WriteLine(tabs.Status);  // Constructed

tabs.Current = settings;
Console.WriteLine(tabs.Current?.Model.Title);  // "Settings"

tabs.Dispose();
hub.Dispose();
```

> **Tip — test/sample VMs:** every builder also has a one-line
> `.WithNullServices()` extension that wires
> `NullMessageHub.Instance` + `NullDispatcher.Instance`, so you can write
> `ComponentVM<M>.Builder().Name("x").Model(m).WithNullServices().Build()`
> in tests, samples, and exploration without constructing real services.
> Production VMs should still call `.Services(hub, dispatcher)` with real
> services.

The Python and TypeScript flavors mirror this shape: see
[Python Quick start](../python/README.md#3-quick-start) and
[TypeScript Quick start](../typescript/README.md#3-quick-start) — only the
identifier casing differs.

See [Getting Started with VMx — C#](../../docs/content/getting-started/csharp.md)
for the full walkthrough.

### 3.1 Cross-language naming

The conceptual surface is identical across the five flavors; identifier
casing follows the per-language idiom (see ADR-0006).

| Concept             | C#                        | Python             | TypeScript               | Swift                     | Rust                     |
| ------------------- | ------------------------- | ------------------ | ------------------------ | ------------------------- | ------------------------ |
| Unmodeled VM        | `ComponentVM`             | `ComponentVM`      | `ComponentVM`            | `ComponentVM`             | `ComponentVm<()>`        |
| Modeled VM          | `ComponentVM<M>`          | `ComponentVMOf[M]` | `ComponentVMOf<M>`       | `ComponentVMOf<M>`        | `ComponentVm<M>`         |
| Status property     | `Status`                  | `status`           | `status`                 | `status`                  | `status()`               |
| Builder entrypoint  | `Builder()`               | `builder()`        | `builder()`              | `builder()`               | `builder()`              |
| Null hub singleton  | `NullMessageHub.Instance` | `NULL_MESSAGE_HUB` | `NullMessageHub.INSTANCE` | `NullMessageHub.INSTANCE` | `NullMessageHub::hub()`  |

C# uses PascalCase, Python and Rust use snake_case, TypeScript and Swift use
camelCase. The single substantive divergence is that C# names the modeled
variant with a generic-parameter suffix (`ComponentVM<M>`), while Python,
TypeScript, and Swift use a separate `ComponentVMOf` type because their
generics syntax cannot overload an unparameterised name.

### 3.2 Subclassing & composition

`ComponentVM<M>`, `ComponentVM`, and `ReadonlyComponentVM<M>` are all
declared `sealed` by design (ADR-0018 — the post-2012 flat hierarchy avoids
the inheritance fragility of the legacy chained-base VMx). Downstream code
that wants to extend a VM with domain-specific operations should use
**composition** rather than subclassing:

```csharp
public sealed class NoteVM
{
    public ComponentVM<Note> Inner { get; }

    public NoteVM(Note model, IMessageHub hub, IDispatcher dispatcher)
    {
        Inner = ComponentVM<Note>.Builder()
            .Name($"note-{model.Id}")
            .Model(model)
            .ModeledHinter(n => n.Title)
            .Services(hub, dispatcher)
            .Build();
    }

    public string Title => Inner.Model.Title;
    public RelayCommand SaveCommand => new(_ => Save(), _ => Inner.IsConstructed);

    private void Save() { /* domain operation */ }
}
```

The C#-specific `ConstructAsync()`, `DestructAsync()`, and
`ReconstructAsync()` methods complete after terminal lifecycle publication. If
a background hook or deferred child cascade fails, the VM publishes its
transactional rollback first and the returned task then faults with the
original exception (ADR-0109).

For aggregate trees, reach for `AggregateVM1..6<…>` (heterogeneous,
fixed-arity) or `CompositeVM<VM>` (homogeneous, variable-arity) instead
of subclassing.

For an end-to-end composition pattern across all four flagship flavors
(Avalonia, Textual, React, SwiftUI), see the Notes-Showcase Avalonia flagship at
[`examples/csharp/avalonia/NotesShowcase/`](../../examples/csharp/avalonia/NotesShowcase/),
with cross-flavor parity documented in
[`examples/notes-showcase-parity.md`](../../examples/notes-showcase-parity.md).

## 4. API surface

The public API lives under the `VMx.*` namespaces:

| Export                          | Description                                       |
| ------------------------------- | ------------------------------------------------- |
| `ComponentVM` / `<M>`           | Leaf viewmodel (non-modeled / modeled)            |
| `ReadonlyComponentVM<M>`        | Leaf VM with read-only model                      |
| `CompositeVM<VM>` / `<M,VM>`    | Ordered collection of children + current slot     |
| `GroupVM<VM>`                   | Collection without current selection              |
| `IVmCollection<VM>`            | Shared group/composite collection + atomic move   |
| `ISelectableVmCollection<VM>`  | Composite-only current-selection extension        |
| `AggregateVM1..6<…>`            | Fixed-arity named component slots (arity 6 new in 2.2.0; see ADR-0034) |
| `ForwardingComponentVM<M>`      | Decorator for `IComponentVM<M>`                   |
| `ForwardingCompositeVM<VM>`     | Decorator for composites                          |
| `RelayCommand` / `<T>`          | Executable command with `CanExecute` predicate    |
| `CompositeCommand`              | Aggregate N inner commands (spec v2.0)            |
| `DecoratorCommand`              | Wrap a command with pre/post + can-execute gate   |
| `ConfirmationDecoratorCommand`  | Wrap a command with an async confirm delegate     |
| `ModeledCrudCommands<M,VM>`     | Create / UpdateCurrent / DeleteCurrent helper     |
| `MessageHub` / `IMessageHub`    | Pub/sub hub backed by `System.Reactive`           |
| `NullMessageHub` (.Instance)    | Null-object variant per ADR-0017                  |
| `RxDispatcher` / `IDispatcher`  | Foreground/background scheduler pair              |
| `NullDispatcher` (.Instance)    | Null-object variant per ADR-0017                  |
| `ConstructionStatus`            | 5-state lifecycle enum                            |
| `StatusTransitionException`     | Thrown on illegal lifecycle operations            |
| `BuilderValidationException`    | Thrown when a builder is missing required fields  |
| `Tree.Walk(root)`               | DFS pre-order tree traversal                      |
| `Tree.WalkExpanded(root)`       | DFS walk gated on `IExpandable.IsExpanded` (v2.0) |
| `Tree.Find(root, predicate)`    | Short-circuit tree search                         |
| `DerivedProperty<TValue>`       | N-source computed value (spec v2.0)               |
| `ExpandableState`               | `IExpandable`+`ICollapsible` helper (spec v2.0)   |
| `SearchableState<TItem>`        | Debounced filter + optional source signal (v3.19) |
| `AsyncResourceVM<T>`            | Cancellable latest-wins async value state (v3.20) |
| `ILocalizer` / `NullLocalizer`  | i18n hook + null-default (spec v2.0)              |
| 22× capability interfaces       | `VMx.Capabilities.*` — opt-in (spec v2.0+)        |
| `HierarchicalVM<TModel, TVM>`   | Recursive tree VM with key-aware `AttachMany`     |
| `TreeStructureChangedMessage`   | Tree-structural-change notification (spec v2.1)   |
| `FormVM<TM>` / `IFormPersister<TM>` | Snapshot/revert form lifecycle (spec v2.1)    |
| `IDialogService` / `NullDialogService` | File/confirm/notify dialogs + null (spec v2.1) |
| `ServicedObservableCollection<T>` | Complete local-before-hub mutation surface (spec v3.16) |
| `KeyedServicedObservableCollection<TKey, TItem>` | Ordered serviced surface plus captured-key index (spec v3.17) |
| `IObservableMembershipSource<T>` / `AggregateChangeStream<T>` | Dynamic membership-and-item fan-in with provenance (spec v3.18) |
| `ObservableList<T>`             | Granular events + atomic `ReplaceAll`             |
| `ObservableDictionary<K1, K2, V>` | Multi-key observable dictionary (spec v2.1)     |
| `PagedComposition<TVM>`         | Pageable iterable decorator (spec v2.1)           |
| Fluent command extensions       | `Confirm` / `PrecedeWith` / `SucceedWith` / `WrapWith` on `ICommand` (spec v2.1) |
| `PropertyValueChangedMessagesFor` | Hub extension yielding `IObservable<TProperty>` of property-value snapshots (spec v2.1) |
| `SubscribeValue`                | Fixed-VM selected-state bridge returning `IDisposable` (spec v3.15) |

### 4.1 Serviced collections

Use `ServicedObservableCollection<T>` when an ordered, caller-owned collection
needs normal local `CollectionChanged` events plus equivalent messages on an
optional hub. It supports inherited `Add`, first-match `Remove`, `RemoveAt`,
the indexer, `Move`, and `Clear`, plus named `Replace` and snapshot-based
`ReplaceAll`:

```csharp
var notes = new ServicedObservableCollection<Note>(hub);
notes.Add(first);
notes.Add(second);
notes.Replace(0, revised);
notes.Move(0, notes.Count - 1);    // one Move locally, then on the hub
notes.ReplaceAll(serverSnapshot); // one Reset, even for identical non-empty input
```

Indexed failures are atomic. Equal-index Move, empty Clear, and empty-to-empty
ReplaceAll are no-ops. Messages retain `Index` and add `OldIndex` / `NewIndex`;
the collection never disposes or reparents its items. Choose `ObservableList<T>`
instead for list-local batching and the `Count` channel, or a Group/Composite
child collection for VM lifecycle ownership.

Choose `KeyedServicedObservableCollection<TKey,TItem>` when that same ordered
surface needs one stable domain-key index:

```csharp
var notesById = new KeyedServicedObservableCollection<Guid, Note>(
    note => note.Id, hub);
notesById.Add(first);
notesById.TryGetValue(first.Id, out Note? note);
bool added = notesById.Upsert(revised); // false: Replace at stable position
bool removed = notesById.RemoveKey(first.Id);
```

`ContainsKey` tests membership. Keys are captured until indexed replacement or
delete-then-add; mutating an item does not silently rekey it. Duplicate and
projector failures are atomic. Lookup/target discovery are expected O(1), while
ordered middle shifts remain O(n). Local delivery remains immediate before
optional hub delivery, and the collection never batches or owns item lifecycle.

### 4.2 Imperative engine bridge

Use `SubscribeValue` to push selected VM state into a renderer or other
imperative host without polling it every frame:

```csharp
using VMx.Messages;

IDisposable exposureSubscription = cameraVm.SubscribeValue(
    vm => vm.Model.Exposure,
    (exposure, _) => material.Uniforms.Exposure.Value = exposure,
    fireImmediately: true);

// When the host adapter is disposed:
exposureSubscription.Dispose();
```

The callback receives `(current, previous)`; immediate delivery passes the
initial value for both. The selector runs after every property message from
this fixed VM, and `EqualityComparer<TValue>.Default` suppresses unchanged
selections. Pass `equalityComparer:` for custom equality. The host owns the
returned `IDisposable`; VMx does not attach it to the observed VM's lifetime.

The companion package `VMx.Extensions.DependencyInjection` adds:

| Export                         | Description                                       |
| ------------------------------ | ------------------------------------------------- |
| `services.AddVMx(…)`           | Registers `IMessageHub` and `IDispatcher`         |

The companion package `VMx.Notifications` (spec v2.1+) adds:

| Export                                                   | Description                            |
| -------------------------------------------------------- | -------------------------------------- |
| `Notification` / `NotificationType` / `NotificationReaction` | Notification primitives            |
| `INotificationHub` / `NotificationHub` / `NullNotificationHub` | Async notification hub + null variant |
| `ConfirmHelper.MakeConfirm(hub, prompt)`                 | Bridge to `ConfirmationDecoratorCommand` |
| `NotificationVM`                                         | Render-side VM for `Notification` (spec v2.1) |
| `ConfirmationVM`                                         | Render-side VM with Approve/Reject (spec v2.1) |

## 5. Conformance

All 395 library conformance IDs from `spec/12-conformance.md` are covered (the 5 THEME scenario IDs live in the flagship example apps — see CONTRIBUTING §2.5).

```
v1.x   LIFE-001..013  HUB-001..007  PROP-001..004  CMD-001..007
       CVM-001..010   COMP-001..013 GRP-001..006   AGG-001..005
       FWD-001..003   BLD-001..004  THR-001..004   UTIL-001..003
v2.0   CAP-001..020   NULL-001..003 DPROP-001..012 CMDD-001..009
       NOTIF-001..010 COMP-014..024 GRP-007..010   EXP-001..005
       LOC-001..003
v2.1   HIER-001..014  DIA-001..008  FORM-001..010  NOTIF-011..016
       COL-001..023   CMD-008..011  CAP-021..022
v2.2   AGG-006
v2.3   BLD-005        FORM-011..013 HIER-015..017
v2.4   THEME-001..005
v2.5   HIER-018       NOTIF-017     FORM-014
v2.6   COMP-025..026
v3.0   LIFE-014       FORM-015      CMDD-010      COMP-027      CMD-012
v3.1   CMD-013        COL-024..031  COMP-028..037 FORM-016..023
       DIA-009..013   HIER-019..022 DISC-001..006 BLD-006 GRP-011
v3.2   HUB-008..013
v3.3   CVM-007..009
v3.4   DISP-001..006
v3.5   COL-032..039
v3.6   CMD-014..019
v3.7   FORM-024..029
v3.8   HIER-023..030
v3.9   COL-040..047
v3.10  DISP-007..013
v3.11  DISP-014
v3.12  FORM-030
v3.15  SUBV-001..004
v3.16  COL-048..055
v3.17  COL-056..064
v3.18  AGCH-001..010
```

Run the suite:

```bash
dotnet test
```

## 6. Development

```bash
# From this directory
dotnet restore VMx.sln --locked-mode
dotnet build
dotnet test
dotnet format --verify-no-changes
```

Central package versions live in [`Directory.Packages.props`](Directory.Packages.props);
shared build settings (TreatWarningsAsErrors, nullable, SourceLink, package
metadata) live in [`Directory.Build.props`](Directory.Build.props).

The `lifecycle-transitions.json` fixture from `spec/fixtures/` is embedded as
a resource via `<EmbeddedResource>` in `VMx.csproj` and consumed at runtime
by `LifecycleTransitionValidator`.

## 7. License

Apache-2.0 — see [`LICENSE`](../../LICENSE) and [`NOTICE`](../../NOTICE).
