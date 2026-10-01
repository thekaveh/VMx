# 9.2. Avalonia Integration

Cross-platform XAML for desktop (Win/macOS/Linux), mobile, and browser
via Avalonia 12. Wires a `ComponentVM<M>` through the same
`INotifyPropertyChanged` adapter that WPF and MAUI use.

## 9.2.1. Reactivity primitive

Avalonia bindings observe `INotifyPropertyChanged.PropertyChanged` and
`ICommand`. `ComponentVMBase` already implements `INotifyPropertyChanged`: a
setter such as `Model` raises `PropertyChanged` after publishing its hub
message, and every lifecycle transition raises `PropertyChanged` for `Status`.
Avalonia marshals work to the UI thread through `Dispatcher.UIThread`, and on
that thread `SynchronizationContext.Current` is an
`AvaloniaSynchronizationContext` that posts to it.

## 9.2.2. Mapping

| Avalonia                                   | VMx                                                                 |
| ------------------------------------------ | ------------------------------------------------------------------- |
| `INotifyPropertyChanged`                   | `ComponentVMBase.PropertyChanged` (implemented by every VM)         |
| `ICommand`                                 | `RelayCommand` / `RelayCommand<T>` (already implements `ICommand`)  |
| `AvaloniaList<T>` / `ObservableCollection` | `ServicedObservableCollection<T>` or wrap `ObservableList<T>`       |
| `Dispatcher.UIThread`                      | `SynchronizationContextScheduler` created on the UI thread (`host`) |

## 9.2.3. Adapter skeleton

Avalonia uses the same adapter as WPF and MAUI. It is the exact file that
`VMx.Tests` executes, and that the Avalonia showcase tests
(`NotesShowcase.Tests/Views/AvaloniaRecipeTests.cs`) run against real Avalonia
bindings on Avalonia's headless UI thread.

<!-- checked-snippet: langs/csharp/tests/VMx.Tests/Integration/BindableVm.cs#xaml-adapter -->

```csharp
using System.ComponentModel;
using System.Reactive.Concurrency;
using System.Reactive.Linq;
using VMx.Components;
using VMx.Lifecycle;

/// <summary>
/// Binds a borrowed <see cref="ComponentVM{M}"/> to XAML. The VM's creator
/// constructs and disposes it; this adapter only observes it.
/// </summary>
public sealed class BindableVm<M> : INotifyPropertyChanged, IDisposable
{
    private readonly ComponentVM<M> _vm;
    private readonly IDisposable _subscription;

    /// <param name="vm">The VM to show.</param>
    /// <param name="host">
    /// The UI thread's scheduler, for example a
    /// <see cref="SynchronizationContextScheduler"/> created on the UI thread.
    /// </param>
    public BindableVm(ComponentVM<M> vm, IScheduler host)
    {
        _vm = vm;
        // ComponentVM<M> implements INotifyPropertyChanged: it raises Model on
        // assignment and Status on every lifecycle transition, on the thread
        // that made the change. Forward each notification on the UI thread.
        // Hub messages are not forwarded: the hub carries no Status change,
        // and its Model message would notify a second time.
        _subscription = Observable
            .FromEventPattern<PropertyChangedEventHandler, PropertyChangedEventArgs>(
                handler => vm.PropertyChanged += handler,
                handler => vm.PropertyChanged -= handler)
            .ObserveOn(host)
            .Subscribe(change => PropertyChanged?.Invoke(this, change.EventArgs));
    }

    /// <summary>The VM's model; assigning it replaces the VM's model.</summary>
    public M Model
    {
        get => _vm.Model;
        set => _vm.Model = value;
    }

    /// <summary>The VM's name.</summary>
    public string Name => _vm.Name;

    /// <summary>The VM's lifecycle status.</summary>
    public ConstructionStatus Status => _vm.Status;

    /// <inheritdoc/>
    public event PropertyChangedEventHandler? PropertyChanged;

    /// <summary>Stops observing the VM without changing its lifecycle.</summary>
    public void Dispose() => _subscription.Dispose();
}
```

Create the adapter on Avalonia's UI thread, for example in a view's
constructor. There `SynchronizationContext.Current` posts to
`Dispatcher.UIThread`, so no extra scheduler package is needed:

<!-- checked-snippet: examples/csharp/avalonia/NotesShowcase.Tests/Views/AvaloniaRecipeTests.cs#avalonia-create-adapter -->

```csharp
var adapter = new BindableVm<Note>(
    vm, new SynchronizationContextScheduler(SynchronizationContext.Current!));
```

Then in XAML: `<TextBlock Text="{Binding Model.Title}"/>`,
`<TextBlock Text="{Binding Status}"/>`, and
`<Button Command="{Binding SaveCommand}"/>` where `SaveCommand` is a
`RelayCommand` exposed by your domain wrapper. For lists, wrap a
`ServicedObservableCollection<T>` and observe its `CollectionChangedMessage` to
refresh an `AvaloniaList<T>`.

- **One notification path.** Forward `PropertyChanged` only. Forwarding the
  hub's `PropertyChangedMessage` as well notifies `Model` twice, and the hub
  never carries `Status`.
- **Current values at once.** `Model`, `Name`, and `Status` read through to the
  VM, so a binding shows the VM's current values as soon as it attaches.
- **UI thread only.** The VM raises `PropertyChanged` on the thread that made
  the change. The adapter re-raises each notification through `host`, so a
  change made on a worker reaches the binding later, on the UI thread.
- **Borrowed lifetime.** `Dispose()` detaches the adapter and nothing else. The
  code that created the VM constructs and disposes it.

## 9.2.4. Fuller example

[`examples/csharp/avalonia/NotesShowcase/`](../../../examples/csharp/avalonia/NotesShowcase/) —
the Notes-Showcase Avalonia flagship: end-to-end `WorkspaceVM` +
`AggregateVM6` + `ConfirmationDecoratorCommand` pattern (shipped in
v2.2.0; `ThemeVM` added in v2.4.0).
