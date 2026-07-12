# 7.2. C\#

## Snapshot

- Install: `dotnet add package VMx`
- Publication status: package name is documented, but the core NuGet package is
  not published yet; use a project or local source reference until a
  `csharp-v*` release publishes it.
- Reactive primitive: `System.Reactive`
- Naming idiom: PascalCase

## What To Reach For

C# is the most direct fit when you want .NET host integration, `ICommand`-style
UI binding, or desktop MVVM with WPF or Avalonia. The README also documents
companion assemblies for DI and notifications.

## Imperative Engine Bridge

`SubscribeValue` returns `IDisposable` and uses
`EqualityComparer<TValue>.Default` unless an `IEqualityComparer<TValue>` is
supplied:

```csharp
using VMx.Messages;

IDisposable exposureSubscription = cameraVm.SubscribeValue(
    vm => vm.Model.Exposure,
    (exposure, _) => material.Uniforms.Exposure.Value = exposure,
    fireImmediately: true);

// Host adapter disposal:
exposureSubscription.Dispose();
```

The host adapter owns the handle. The callback receives `(current, previous)`;
immediate delivery uses the initial value for both. The selector reevaluates
after every property message from this fixed VM, not on every render frame.

## Pointers

- Flavor README:
  [langs/csharp/README.md](../../../langs/csharp/README.md)
- Getting started guide:
  [docs/getting-started/csharp.md](../../getting-started/csharp.md)
- Example portfolio:
  [Examples overview](../examples/index.md)
- Flagship Notes Workspace:
  [Notes Workspace](../examples/notes-workspace.md)
- Avalonia recipe:
  [docs/integration/avalonia.md](../../integration/avalonia.md)

## Current Example Coverage

- Console: `examples/csharp/console/HelloVMx/`
- WPF Todo app: `examples/csharp/wpf/TodoApp/`
- Avalonia flagship: `examples/csharp/avalonia/NotesShowcase/`

Use the site's [Smaller Examples](../examples/smaller-examples.md) page for the
short demos and [Integration Recipes](../integration-recipes.md) for host
wiring routes.
