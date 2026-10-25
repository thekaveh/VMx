# vmx — C#

Hierarchical lifecycle-aware MVVM viewmodel framework for .NET,
spec-compatible with the Python, TypeScript, Swift, and Rust flavors.

## 1. Status

**v3.30.0** — implements `spec-v3.30.0` end-to-end. 426/426 library conformance IDs
pass. Multi-targets `netstandard2.0` and `net8.0`.
Two companion assemblies ship: `VMx.Extensions.DependencyInjection`
(`services.AddVMx(...)`) at `2.1.1` and `VMx.Notifications` (opt-in
`INotificationHub`) at `1.2.0` (min spec 2.6.0). Each is independently
versioned per ADR-0009 / ADR-0013 and stays on its own release line
(the DI companion does not pull the core bump); see
[`compatibility-matrix.md`](../../compatibility-matrix.md).

## 2. Install

The source tree implements v3.30.0. The NuGet package is not published. Use a
project reference until a `csharp-v*` release tag publishes it.

```bash
# After the first NuGet publication
dotnet add package VMx

# Optional DI integration (Microsoft.Extensions.DependencyInjection)
dotnet add package VMx.Extensions.DependencyInjection

# Source checkout (VMx cloned beside the consumer)
dotnet add MyApp.csproj reference ../VMx/langs/csharp/src/VMx/VMx.csproj
```

## 3. Quick start

The minimum-viable shape is `imports → services → builder
(name + model + services + optional hinter) → Construct() → read Status`:

```csharp
using VMx.Components;
using VMx.Composites;
using VMx.Lifecycle;
using VMx.Services;

// 1. Services (a hub + a dispatcher). Production code injects real services;
//    component-builder tests and samples can use .WithNullServices() instead (see below).
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
Console.WriteLine(tabs.Current?.Model.Title);  // Settings

tabs.Dispose();
hub.Dispose();

// Type declarations follow the top-level statements in Program.cs.
public record TabModel(string Title);
```

> **Tip — test/sample VMs:** the `ComponentVMBuilder`,
> `ComponentVMBuilder<M>`, and `ReadonlyComponentVMBuilder<M>` builders have a
> one-line `.WithNullServices()` extension. It wires
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

The concepts are identical across the five flavors; identifier casing follows
each language idiom (ADR-0006). See the
[cross-language naming table](../../docs/content/flavors/cross-language-naming.md).

### 3.2 Subclassing & composition

`ComponentVM<M>`, `ComponentVM`, and `ReadonlyComponentVM<M>` are all
declared `sealed` by design (ADR-0018). Downstream code
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
        SaveCommand = RelayCommand.Builder()
            .Task(Save)
            .Predicate(() => Inner.IsConstructed)
            .Build();
    }

    public string Title => Inner.Model.Title;
    public RelayCommand SaveCommand { get; }

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
| `AggregateVM1..6<…>`            | Fixed-arity named component slots (ADR-0034) |
| `ForwardingComponentVM<M>`      | Decorator for `IComponentVM<M>`                   |
| `ForwardingCompositeVM<VM>`     | Decorator for composites                          |
| `RelayCommand` / `<T>`          | Executable command with `CanExecute` predicate    |
| `CompositeCommand`              | Aggregate N inner commands            |
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
| `Tree.WalkExpanded(root)`       | DFS walk gated on `IExpandable.IsExpanded` |
| `Tree.Find(root, predicate)`    | Short-circuit tree search                         |
| `DerivedProperty<TValue>`       | N-source computed value               |
| `ExpandableState`               | `IExpandable`+`ICollapsible` helper   |
| `SearchableState<TItem>`        | Debounced filter + optional source signal |
| `AsyncResourceVM<T>`            | Cancellable latest-wins async value state |
| `ILocalizer` / `NullLocalizer`  | i18n hook + null-default              |
| 22× capability interfaces       | `VMx.Capabilities.*` — opt-in        |
| `HierarchicalVM<TModel, TVM>`   | Recursive tree VM with key-aware `AttachMany`     |
| `TreeStructureChangedMessage`   | Tree-structural-change notification   |
| `FormVM<TM>` / `IFormPersister<TM>` | Snapshot/revert form lifecycle    |
| `IDialogService` / `NullDialogService` | File/confirm/notify dialogs + null |
| `ServicedObservableCollection<T>` | Complete local-before-hub mutation surface |
| `KeyedServicedObservableCollection<TKey, TItem>` | Ordered serviced surface plus captured-key index |
| `IObservableMembershipSource<T>` / `AggregateChangeStream<T>` | Dynamic membership-and-item fan-in with provenance |
| `ObservableList<T>`             | Granular events + atomic `ReplaceAll`             |
| `ObservableDictionary<K1, K2, V>` | Multi-key observable dictionary     |
| `PagedComposition<TVM>`         | Pageable iterable decorator           |
| Fluent command extensions       | `Confirm` / `PrecedeWith` / `SucceedWith` / `WrapWith` on `ICommand` |
| `PropertyValueChangedMessagesFor` | Hub extension yielding `IObservable<TProperty>` of property-value snapshots |
| `SubscribeValue`                | Fixed-VM selected-state bridge returning `IDisposable` |

### 4.1 Serviced collections

`ServicedObservableCollection<T>` is an ordered, caller-owned collection with
local `CollectionChanged` events and equivalent messages on an optional hub.
`KeyedServicedObservableCollection<TKey,TItem>` adds a captured stable-key
index (`TryGetValue`, `Upsert`, `RemoveKey`, `ContainsKey`).

Empty-to-empty `ReplaceAll` is a no-op; any other `ReplaceAll` emits one Reset,
even for identical input. Messages keep `Index` and add `OldIndex` /
`NewIndex`. Use `ObservableList<T>` for list-local batching and the `Count`
channel. Use a Group/Composite child collection for VM lifecycle ownership.
See [C# serviced collections](../../docs/content/flavors/csharp.md#723-serviced-collections).

### 4.2 Imperative engine bridge

`SubscribeValue` pushes a selected value from one fixed VM into an imperative
host as `(current, previous)` and returns an `IDisposable` that the host owns.
VMx does not attach that handle to the observed VM's lifetime. See
[C# imperative engine bridge](../../docs/content/flavors/csharp.md#724-imperative-engine-bridge).

## 5. Companion packages

`VMx.Extensions.DependencyInjection` adds:

| Export                         | Description                                       |
| ------------------------------ | ------------------------------------------------- |
| `services.AddVMx(…)`           | Registers `IMessageHub` and `IDispatcher`         |

`VMx.Notifications` adds:

| Export                                                   | Description                            |
| -------------------------------------------------------- | -------------------------------------- |
| `Notification` / `NotificationType` / `NotificationReaction` | Notification primitives            |
| `INotificationHub` / `NotificationHub` / `NullNotificationHub` | Async notification hub + null variant |
| `ConfirmHelper.MakeConfirm(hub, prompt)`                 | Bridge to `ConfirmationDecoratorCommand` |
| `NotificationVM`                                         | Render-side VM for `Notification`      |
| `ConfirmationVM`                                         | Render-side VM with Approve/Reject     |

## 6. Conformance

Implements all 426 library conformance IDs; THEME scenario IDs live in the
example apps. See [`spec/12-conformance.md`](../../spec/12-conformance.md).

Run the suite:

```bash
dotnet test
```

## 7. Development

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

## 8. License

Apache-2.0 — see [`LICENSE`](../../LICENSE) and [`NOTICE`](../../NOTICE).
