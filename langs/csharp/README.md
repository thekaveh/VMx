# vmx — C#

Hierarchical lifecycle-aware MVVM viewmodel framework for .NET,
spec-compatible with the Python and TypeScript flavors.

## 1. Status

**v2.0.0** — implements `spec-v2.0.0` end-to-end. 152/152 conformance IDs
pass (166 test methods). Multi-targets `netstandard2.0` and `net8.0`.
Two companion assemblies ship: `VMx.Extensions.DependencyInjection`
(`services.AddVMx(...)`) and `VMx.Notifications` (opt-in
`INotificationHub`).

## 2. Install

```bash
dotnet add package VMx

# Optional DI integration (Microsoft.Extensions.DependencyInjection)
dotnet add package VMx.Extensions.DependencyInjection
```

## 3. Quick start

```csharp
using VMx.Components;
using VMx.Composites;
using VMx.Services;

var hub = new MessageHub();
var dispatcher = RxDispatcher.Immediate();

public record TabModel(string Title);

var home = ComponentVM<TabModel>.Builder()
    .Name("home").Model(new TabModel("Home")).Services(hub, dispatcher).Build();

var settings = ComponentVM<TabModel>.Builder()
    .Name("settings").Model(new TabModel("Settings")).Services(hub, dispatcher).Build();

var tabs = CompositeVM<ComponentVM<TabModel>>.Builder()
    .Name("tab-bar")
    .Services(hub, dispatcher)
    .Children(() => new[] { home, settings })
    .Build();

tabs.Construct();

tabs.Current = settings;
Console.WriteLine(tabs.Current?.Model.Title);  // "Settings"

tabs.Dispose();
hub.Dispose();
```

See [docs/getting-started/csharp.md](../../docs/getting-started/csharp.md)
for the full walkthrough.

## 4. API surface

The public API lives under the `VMx.*` namespaces:

| Export                          | Description                                       |
| ------------------------------- | ------------------------------------------------- |
| `ComponentVM` / `<M>`           | Leaf viewmodel (non-modeled / modeled)            |
| `ReadonlyComponentVM<M>`        | Leaf VM with read-only model                      |
| `CompositeVM<VM>` / `<M,VM>`    | Ordered collection of children + current slot     |
| `GroupVM<VM>`                   | Collection without current selection              |
| `AggregateVM1..5<…>`            | Fixed-arity named component slots                 |
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
| `SearchableState<TItem>`        | Debounced filter helper (spec v2.0)               |
| `ILocalizer` / `NullLocalizer`  | i18n hook + null-default (spec v2.0)              |
| 20× capability interfaces       | `VMx.Capabilities.*` — opt-in (spec v2.0)         |

The companion package `VMx.Extensions.DependencyInjection` adds:

| Export                         | Description                                       |
| ------------------------------ | ------------------------------------------------- |
| `services.AddVMx(…)`           | Registers `IMessageHub` and `IDispatcher`         |

The companion package `VMx.Notifications` (spec v2.0) adds:

| Export                                                   | Description                            |
| -------------------------------------------------------- | -------------------------------------- |
| `Notification` / `NotificationType` / `NotificationReaction` | Notification primitives            |
| `INotificationHub` / `NotificationHub` / `NullNotificationHub` | Async notification hub + null variant |
| `ConfirmHelper.MakeConfirm(hub, prompt)`                 | Bridge to `ConfirmationDecoratorCommand` |

## 5. Conformance

All 152 conformance IDs from `spec/12-conformance.md` are covered (171 test
methods, since some IDs are validated by multiple scenarios).

```
v1.x   LIFE-001..013  HUB-001..007  PROP-001..004  CMD-001..007
       CVM-001..006   COMP-001..013 GRP-001..006   AGG-001..005
       FWD-001..003   BLD-001..004  THR-001..004   UTIL-001..003
v2.0   CAP-001..020   NULL-001..003 DPROP-001..012 CMDD-001..009
       NOTIF-001..010 COMP-014..024 GRP-007..010   EXP-001..005
       LOC-001..003
```

Run the suite:

```bash
dotnet test
```

## 6. Development

```bash
# From this directory
dotnet restore
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

MIT — see [`LICENSE`](../../LICENSE).
