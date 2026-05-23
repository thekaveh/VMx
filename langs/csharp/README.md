# vmx — C#

Hierarchical lifecycle-aware MVVM viewmodel framework for .NET,
spec-compatible with the Python and TypeScript flavors.

## Status

**v1.1.0** — implements `spec-v1.1.0` end-to-end. 75/75 conformance IDs pass
(89 test methods). Multi-targets `netstandard2.0` and `net8.0`. Optional
companion package `VMx.Extensions.DependencyInjection` provides
`services.AddVMx(...)`.

## Install

```bash
dotnet add package VMx

# Optional DI integration (Microsoft.Extensions.DependencyInjection)
dotnet add package VMx.Extensions.DependencyInjection
```

## Quick start

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

## API surface

The public API lives under the `VMx.*` namespaces:

| Export                          | Description                                       |
| ------------------------------- | ------------------------------------------------- |
| `ComponentVM<M>`                | Leaf viewmodel with a typed model                 |
| `ReadonlyComponentVM<M>`        | Leaf VM with read-only model                      |
| `CompositeVM<VM>`               | Ordered collection of children + current slot     |
| `CompositeVM<M, VM>`            | Model-driven composite                            |
| `GroupVM<VM>`                   | Collection without current selection              |
| `AggregateVM1..5<…>`            | Fixed-arity named component slots                 |
| `ForwardingComponentVM<M>`      | Decorator for `IComponentVM<M>`                   |
| `ForwardingCompositeVM<VM>`     | Decorator for composites                          |
| `RelayCommand`                  | Executable command with `CanExecute` predicate    |
| `RelayCommand<T>`               | Typed command with an argument                    |
| `MessageHub` / `IMessageHub`    | Pub/sub hub backed by `System.Reactive`           |
| `RxDispatcher` / `IDispatcher`  | Foreground/background scheduler pair              |
| `ConstructionStatus`            | 5-state lifecycle enum                            |
| `StatusTransitionException`     | Thrown on illegal lifecycle operations            |
| `BuilderValidationException`    | Thrown when a builder is missing required fields  |
| `Tree.Walk(root)`               | DFS pre-order tree traversal                      |
| `Tree.Find(root, predicate)`    | Short-circuit tree search                         |

The companion package `VMx.Extensions.DependencyInjection` adds:

| Export                         | Description                                       |
| ------------------------------ | ------------------------------------------------- |
| `services.AddVMx(…)`           | Registers `IMessageHub` and `IDispatcher`         |

## Conformance

All 75 conformance IDs from `spec/12-conformance.md` are covered (89 test
methods, since some IDs are validated by multiple scenarios).

```
LIFE-001..013  HUB-001..007  PROP-001..004  CMD-001..007
CVM-001..006   COMP-001..013 GRP-001..006   AGG-001..005
FWD-001..003   BLD-001..004  THR-001..004   UTIL-001..003
```

Run the suite:

```bash
dotnet test
```

## Development

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

## License

MIT — see [`LICENSE`](../../LICENSE).
