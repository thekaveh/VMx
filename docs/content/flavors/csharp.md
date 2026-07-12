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

## Serviced Collections

`ServicedObservableCollection<T>` is an `ObservableCollection<T>` with normal
local `CollectionChanged` delivery plus equivalent messages on an optional
hub. Its v3.16 surface includes inherited `Add`, `Remove`, `RemoveAt`, `Move`,
`Clear`, the indexer, and named `Replace` / `ReplaceAll`:

```csharp
var notes = new ServicedObservableCollection<Note>(hub);
notes.Add(first);
notes.Add(second);
notes.Replace(0, revised);
notes.Move(0, notes.Count - 1);    // one Move locally, then on the hub
notes.ReplaceAll(serverSnapshot); // one Reset
```

Invalid indices throw before mutation; equal-index Move and empty Clear are
no-ops. Removal targets the first equal value and returns `false` when absent.
The collection never disposes or reparents its items.

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
