# 7.2. C\#

## 7.2.1. Snapshot

- Install and package status: see [Installation](../installation.md) and
  [Availability](../index.md#11-availability).
- Target frameworks: `netstandard2.0` and `net8.0`
- Companion assemblies: `VMx.Extensions.DependencyInjection`
  (`services.AddVMx(...)`) and `VMx.Notifications` (opt-in
  `INotificationHub`); their NuGet pages appear with their first publication
- Reactive primitive: `System.Reactive`
- Naming idiom: PascalCase
- Hub delivery: see
  [Callback-Safe Transition Ordering](../architecture/lifecycle-messaging.md#541-callback-safe-transition-ordering)

## 7.2.2. What To Reach For

C# is the most direct fit when you want .NET host integration, `ICommand`-style
UI binding, or desktop MVVM with WPF or Avalonia. The companion assemblies add
dependency-injection registration and opt-in notifications.

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
notes.ReplaceAll(serverSnapshot); // one Reset, even for identical non-empty input
```

Invalid indices throw before mutation. Equal-index Move, empty Clear, and
empty-to-empty ReplaceAll are no-ops. Removal targets the first equal value and
returns `false` when absent. Messages keep `Index` and add `OldIndex` /
`NewIndex`. The collection never disposes or reparents its items.

Choose `ObservableList<T>` instead for list-local batching and the `Count`
channel. Choose a Group or Composite child collection for VM lifecycle
ownership.

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
Local delivery is immediate and precedes optional hub publication. An open hub
transaction defers only the hub message. The keyed type has no batch, `Count`
notification channel, VM lifecycle interface, or item ownership.

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

The callback receives `(current, previous)`; immediate delivery uses the
initial value for both. The selector reevaluates after every property message
from this fixed VM, not on every render frame. Pass `equalityComparer:` for
custom equality. The host adapter owns the handle; VMx does not attach it to
the observed VM's lifetime.

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
