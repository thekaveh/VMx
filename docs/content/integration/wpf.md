# 9.3. WPF Integration

Wire a `ComponentVM<M>` to a WPF view via `INotifyPropertyChanged` and the
existing `RelayCommand` infrastructure. WPF is Windows-only; for
cross-platform XAML, see [avalonia.md](avalonia.md).

## 9.3.1. Reactivity primitive

WPF data binding observes `INotifyPropertyChanged.PropertyChanged` events.
`ComponentVMBase` already implements `INotifyPropertyChanged`. A setter such as
`Model` publishes a `PropertyChangedMessage` to the hub and then raises
`PropertyChanged`. A lifecycle transition publishes a
`ConstructionStatusChangedMessage` to the hub and then raises `PropertyChanged`
for `Status` and `IsConstructed`. `Status` is computed, so the hub never
carries a `PropertyChangedMessage` for it.

## 9.3.2. Mapping

| WPF                        | VMx                                                                 |
| -------------------------- | ------------------------------------------------------------------- |
| `INotifyPropertyChanged`   | `ComponentVMBase.PropertyChanged` (implemented by every VM)         |
| `ICommand`                 | `RelayCommand` / `RelayCommand<T>` (already implements `ICommand`)  |
| `INotifyCollectionChanged` | `CollectionChangedMessage` on the hub                               |
| Dispatcher thread          | `SynchronizationContextScheduler` created on the UI thread (`host`) |

## 9.3.3. Adapter skeleton

The adapter below is the exact file that `VMx.Tests` executes
(`Integration/XamlRecipeTests.cs`) and that CI runs against real WPF bindings
on a Dispatcher thread (`examples/csharp/wpf/RecipeHostCheck`).

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

Create the adapter on the UI thread, where WPF installs its
`DispatcherSynchronizationContext`:

<!-- checked-snippet: examples/csharp/wpf/RecipeHostCheck/Program.cs#wpf-create-adapter -->

```csharp
var adapter = new BindableVm<Note>(
    vm, new SynchronizationContextScheduler(SynchronizationContext.Current!));
```

Then in XAML: `<TextBlock Text="{Binding Model.Title}"/>`,
`<TextBlock Text="{Binding Status}"/>`, and
`<Button Command="{Binding SaveCommand}"/>` where `SaveCommand` is a
`RelayCommand` exposed by your domain wrapper.

- **One notification path.** Forward `PropertyChanged` only. Forwarding the
  hub's `PropertyChangedMessage` as well notifies `Model` twice, and the hub
  never carries `Status`.
- **Current values at once.** `Model`, `Name`, and `Status` read through to the
  VM, so a binding shows the VM's current values as soon as it attaches.
- **UI thread only.** The VM raises `PropertyChanged` on the thread that made
  the change, such as a worker or a background construct. The adapter re-raises
  each notification through `host`, so bound state is only touched on the UI
  thread. The dispatcher's `Foreground` scheduler decides where VMx completes
  lifecycle work; it does not move your subscriptions.
- **Borrowed lifetime.** `Dispose()` detaches the adapter and nothing else. The
  code that created the VM constructs and disposes it.

## 9.3.4. Fuller example

[`examples/csharp/wpf/TodoApp/`](../../../examples/csharp/wpf/TodoApp/) — a
working WPF Todo app demonstrating `RelayCommand` + `IMessageHub` with
per-item `ComponentVM<TodoItem>` children in an `ObservableCollection`.
Its `TodoItemVM` maps the hub's `Model` message to its projected `Title` and
`Done` properties; it shows no lifecycle status.
