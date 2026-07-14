# 7.2. C\#

## 7.2.1. Snapshot

- Install: `dotnet add package VMx`
- Publication status: package name is documented, but the core NuGet package is
  not published yet; use a project or local source reference until a
  `csharp-v*` release publishes it.
- Reactive primitive: `System.Reactive`
- Naming idiom: PascalCase

## 7.2.2. What To Reach For

C# is the most direct fit when you want .NET host integration, `ICommand`-style
UI binding, or desktop MVVM with WPF or Avalonia. The README also documents
companion assemblies for DI and notifications.

## 7.2.3. Serviced Collections

`ServicedObservableCollection<T>` is an `ObservableCollection<T>` with normal
local `CollectionChanged` delivery plus equivalent messages on an optional
hub. Its complete surface includes inherited `Add`, `Remove`, `RemoveAt`, `Move`,
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

Add `KeyedServicedObservableCollection<TKey,TItem>` when that same ordered,
caller-owned list also needs stable-key access:

```csharp
var notesById = new KeyedServicedObservableCollection<Guid, Note>(
    note => note.Id,
    hub);
notesById.Add(first);
bool found = notesById.TryGetValue(first.Id, out Note? note);
bool added = notesById.Upsert(revised); // false: Replace at the same position
bool removed = notesById.RemoveKey(first.Id);
```

`ContainsKey` tests membership; an optional comparer follows the hub argument.
The projected key is captured until indexed replacement or delete-then-add, so
mutating `Id` does not silently rekey the membership. Duplicate projection and
projector failure occur before mutation. Key lookup and target discovery are
expected O(1), append is amortized O(1), and ordered middle shifts remain O(n).
Local delivery is immediate and precedes optional hub publication; an existing
hub transaction defers only the hub message. The keyed type still has no batch,
`Count` notification channel, VM lifecycle interface, or item ownership.

## 7.2.4. Imperative Engine Bridge

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

## 7.2.5. Pointers

- Flavor README:
  [langs/csharp/README.md](../../../langs/csharp/README.md)
- Getting started guide:
  [Getting Started with VMx — C#](../getting-started/csharp.md)
- Example portfolio:
  [Examples overview](../examples/index.md)
- Flagship Notes Workspace:
  [Notes Workspace](../examples/notes-workspace.md)
- Avalonia recipe:
  [Avalonia Integration](../integration/avalonia.md)

## 7.2.6. Current Example Coverage

- Console: `examples/csharp/console/HelloVMx/`
- WPF Todo app: `examples/csharp/wpf/TodoApp/`
- Avalonia flagship: `examples/csharp/avalonia/NotesShowcase/`

Use the site's [Smaller Examples](../examples/smaller-examples.md) page for the
short demos and [Integration Recipes](../integration/index.md) for host
wiring routes.
