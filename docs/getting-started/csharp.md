# Getting Started with VMx — C\#

This tutorial walks you through building viewmodels with the VMx C# library.
You will build a `ComponentVM<UserModel>`, a `RelayCommand` with a reactive
trigger, and a `CompositeVM<TabVM>` with tab selection — all in a console or
unit-test project.

> For the normative contracts behind each type, see `spec/05-component-vm.md`,
> `spec/04-commands.md`, and `spec/06-composite-vm.md`.

______________________________________________________________________

## 1. Install

The source tree currently implements v3.8.0. The NuGet package is not published
yet; use the package command after a `csharp-v*` release publishes it.

```bash
dotnet add package VMx
```

For local development from a checked-out clone, reference the project directly:

```xml
<!-- In your .csproj -->
<ItemGroup>
  <ProjectReference Include="path/to/langs/csharp/src/VMx/VMx.csproj" />
</ItemGroup>
```

______________________________________________________________________

## 2. Wire up `IMessageHub` and `IDispatcher`

Every viewmodel needs two services: a hub that carries messages between
viewmodels and a dispatcher that knows about your UI thread.

### 2.1 Option A — manual construction (console / tests)

```csharp
using VMx.Services;

// Both foreground and background = immediate (deterministic for console / tests).
// Mirrors RxDispatcher.immediate() in Python and TypeScript.
IDispatcher dispatcher = RxDispatcher.Immediate();

IMessageHub hub = new MessageHub();
```

### 2.2 Option B — dependency injection (`VMx.Extensions.DependencyInjection`)

Add the optional DI package:

```xml
<ProjectReference Include="path/to/langs/csharp/src/VMx.Extensions.DependencyInjection/
    VMx.Extensions.DependencyInjection.csproj" />
```

Then register in your host startup (WPF, MAUI, ASP.NET, etc.):

```csharp
using Microsoft.Extensions.DependencyInjection;
using VMx.Extensions.DependencyInjection;

var services = new ServiceCollection();

// IMessageHub → singleton MessageHub
// IDispatcher → singleton RxDispatcher bound to SynchronizationContext.Current
services.AddVMx();

// Or supply your own dispatcher factory:
services.AddVMx(opts =>
    opts.UseDispatcher(_ => new RxDispatcher(
        foreground: new SynchronizationContextScheduler(SynchronizationContext.Current!),
        background: TaskPoolScheduler.Default)));

var provider = services.BuildServiceProvider();
var hub        = provider.GetRequiredService<IMessageHub>();
var dispatcher = provider.GetRequiredService<IDispatcher>();
```

______________________________________________________________________

## 3. Build a `ComponentVM<UserModel>`

`ComponentVM<M>` is the primary leaf viewmodel. It holds a typed model,
fires `IPropertyChangedMessage` on the hub when the model changes, and
participates in the five-state lifecycle (Destructed, Constructing,
Constructed, Destructing) plus terminal Disposed.

```csharp
using VMx.Components;
using VMx.Messages;
using VMx.Services;

// A simple domain model — use your own real types here.
public record UserModel(string Name, string Email);

// Build the viewmodel — builder is immutable; every setter returns a new instance.
ComponentVM<UserModel> userVM =
    ComponentVM<UserModel>.Builder()
        .Name("user-card")
        .Model(new UserModel("Alice", "alice@example.com"))
        .Services(hub, dispatcher)
        // Optional: derive a display hint from the model.
        .ModeledHinter(m => m.Name)
        // Optional: callback when Model is set to a new value.
        .OnModelChanged(m => Console.WriteLine($"Model updated → {m.Name}"))
        .OnConstruct(() => Console.WriteLine("user-card constructed"))
        .OnDestruct(() => Console.WriteLine("user-card destructed"))
        .Build();

// Subscribe to PropertyChangedMessage BEFORE constructing so you don't miss it.
hub.Messages
   .OfType<IPropertyChangedMessage<IComponentVM>>()
   .Where(msg => msg.Sender == userVM)
   .Subscribe(msg =>
       Console.WriteLine($"Property '{msg.PropertyName}' changed on {msg.Sender.Name}"));

// Construct transitions the VM: Destructed → Constructing → Constructed.
// The VM publishes ConstructionStatusChangedMessage on the hub for each
// transition and fires its OnConstruct callback when entering Constructing.
userVM.Construct();

// Update the model — triggers OnModelChanged and publishes PropertyChangedMessage.
userVM.Model = new UserModel("Alice Smith", "asmith@example.com");

Console.WriteLine(userVM.ModeledHint);  // "Alice Smith"  (ModeledHinter result)
```

> See `spec/05-component-vm.md` for the full `IComponentVM<M>` contract and
> `spec/03-messages.md` for the message schema.

______________________________________________________________________

## 4. Build a `RelayCommand`

`RelayCommand` wraps a nullable `Action`, an optional `Func<bool>` predicate,
and a set of `IObservable<Unit>` triggers that re-evaluate `CanExecute`.

```csharp
using System.Reactive;
using System.Reactive.Subjects;
using System.Windows.Input;
using VMx.Commands;
using VMx.Services;

// A subject you fire whenever the predicate outcome may have changed.
var canSaveTrigger = new Subject<Unit>();

bool isDirty = false;

ICommand saveCommand =
    RelayCommand.Builder()
        .Task(() =>
        {
            Console.WriteLine("Saving…");
            isDirty = false;
            canSaveTrigger.OnNext(Unit.Default);   // re-evaluate CanExecute
        })
        .Predicate(() => isDirty)
        .Triggers(canSaveTrigger)
        .Build();

// CanExecute is false until isDirty is true.
Console.WriteLine(saveCommand.CanExecute(null));   // False

isDirty = true;
canSaveTrigger.OnNext(Unit.Default);               // fires CanExecuteChanged
Console.WriteLine(saveCommand.CanExecute(null));   // True

saveCommand.Execute(null);                         // prints "Saving…"
Console.WriteLine(saveCommand.CanExecute(null));   // False again

// Dispose to unsubscribe all trigger subscriptions.
((IDisposable)saveCommand).Dispose();
```

> See `spec/04-commands.md` for the full command contract including
> the "predicate-false gates Execute" rule (CMD-003).

______________________________________________________________________

## 5. Build a `CompositeVM<TabVM>`

`CompositeVM<VM>` owns an ordered child collection and a `Current` selection.
Children are built ahead of time and handed in via a factory; the factory runs
lazily on the first `Construct`.

```csharp
using VMx.Components;
using VMx.Composites;
using VMx.Messages;

// A tab viewmodel — a ComponentVM wrapping a tab model.
public record TabModel(string Title);

// Build two tab children. They share the same hub and dispatcher.
ComponentVM<TabModel> tab1 =
    ComponentVM<TabModel>.Builder()
        .Name("home-tab")
        .Model(new TabModel("Home"))
        .Services(hub, dispatcher)
        .Build();

ComponentVM<TabModel> tab2 =
    ComponentVM<TabModel>.Builder()
        .Name("settings-tab")
        .Model(new TabModel("Settings"))
        .Services(hub, dispatcher)
        .Build();

// Build the composite. The children factory is evaluated on Construct.
CompositeVM<ComponentVM<TabModel>> tabs =
    CompositeVM<ComponentVM<TabModel>>.Builder()
        .Name("tab-bar")
        .Services(hub, dispatcher)
        .Children(() => [tab1, tab2])
        .OnConstruct(() => Console.WriteLine("tab-bar ready"))
        .Build();

// Watch for Current changes on the hub.
hub.Messages
   .OfType<IPropertyChangedMessage<IComponentVM>>()
   .Where(msg => msg.Sender == tabs && msg.PropertyName == nameof(tabs.Current))
   .Subscribe(msg =>
   {
       Console.WriteLine($"Selected tab: {tabs.Current?.Model.Title ?? "(none)"}");
   });

// Construct cascades: the composite constructs itself, then each child.
tabs.Construct();

// Select a tab — publishes PropertyChangedMessage for Current, sets child.IsCurrent.
tabs.Current = tab2;  // prints "Selected tab: Settings"
tabs.Current = tab1;  // prints "Selected tab: Home"
```

> See `spec/06-composite-vm.md` for the full `ICompositeVM<VM>` contract,
> including the `IList<VM>` / `INotifyCollectionChanged` semantics.

______________________________________________________________________

## 6. Lifecycle and cleanup

Every VM follows a five-state lifecycle: `Destructed → Constructing → Constructed → Destructing → Destructed`, plus the terminal `Disposed`.

```csharp
// States are exposed via IComponentVM.Status (a ConstructionStatus enum).
Console.WriteLine(userVM.Status);  // Constructed (after Construct())

// Reconstruct is Destruct + Construct in one call. It is only valid from
// Constructed (CanReconstruct is true iff Status == Constructed); it
// round-trips through Destructed and back to Constructed.
userVM.Reconstruct();
Console.WriteLine(userVM.Status);  // Constructed

// Destruct transitions back to Destructed and runs OnDestruct.
userVM.Destruct();
Console.WriteLine(userVM.Status);  // Destructed

// Dispose is terminal and idempotent. Calling Construct() or Destruct() on a
// disposed VM raises StatusTransitionException.
userVM.Dispose();
Console.WriteLine(userVM.Status);  // Disposed

// CompositeVM.Dispose() disposes children then itself.
tabs.Dispose();

// MessageHub.Dispose() completes the underlying Rx Subject.
((IDisposable)hub).Dispose();
```

> See `spec/02-lifecycle.md` for the transition table and the
> `StatusTransitionException` rules (LIFE-001 through LIFE-014).

______________________________________________________________________

## 7. Threading

`IDispatcher` pairs two Rx schedulers:

| Scheduler               | Typical mapping                                |
| ----------------------- | ---------------------------------------------- |
| `dispatcher.Foreground` | UI thread (SynchronizationContext, Dispatcher) |
| `dispatcher.Background` | Task pool / background threads                 |

All hub observations delivered on `Foreground` are safe to bind directly to UI
controls. Use `ObserveOn` to marshal:

```csharp
hub.Messages
   .OfType<IPropertyChangedMessage<IComponentVM>>()
   .ObserveOn(dispatcher.Foreground)     // marshal to UI thread
   .Subscribe(msg => UpdateLabel(msg));  // safe to touch UI here
```

For background work (e.g. loading data before a Construct):

```csharp
Observable
    .Start(() => LoadFromDatabase(), dispatcher.Background)
    .ObserveOn(dispatcher.Foreground)
    .Subscribe(data =>
    {
        userVM.Model = data;
        userVM.Construct();
    });
```

> See `spec/11-threading.md` for the `THR-001..THR-004` conformance rules.

______________________________________________________________________

## 8. Where to go next

| Resource                      | Path                                        |
| ----------------------------- | ------------------------------------------- |
| Spec overview                 | `spec/00-overview.md`                       |
| Lifecycle contract            | `spec/02-lifecycle.md`                      |
| Message schema                | `spec/03-messages.md`                       |
| Commands                      | `spec/04-commands.md`                       |
| ComponentVM contract          | `spec/05-component-vm.md`                   |
| CompositeVM contract          | `spec/06-composite-vm.md`                   |
| Builder spec                  | `spec/10-builders.md`                       |
| Threading rules               | `spec/11-threading.md`                      |
| Tree utilities (`walk/find`)  | `spec/13-tree-utilities.md`                 |
| Architecture decision records | `spec/ADRs/`                                |
| Console example               | `examples/csharp/console/HelloVMx/`         |
| WPF MVVM example              | `examples/csharp/wpf/TodoApp/`              |
| Conformance test suite        | `langs/csharp/tests/VMx.Conformance.Tests/` |
