# 9.4. .NET MAUI Integration

Wire a `ComponentVM<M>` to a .NET MAUI page (desktop + mobile XAML)
through the same `INotifyPropertyChanged` adapter used for WPF.

## 9.4.1. Reactivity primitive

MAUI's XAML data binding observes `INotifyPropertyChanged.PropertyChanged`
and `ICommand`. `ComponentVMBase` already implements `INotifyPropertyChanged`:
a setter such as `Model` raises it after publishing its `PropertyChangedMessage`
to the hub, and every lifecycle transition raises it for `Status` after
publishing a `ConstructionStatusChangedMessage`. The hub never carries a
`PropertyChangedMessage` for `Status`.

## 9.4.2. Mapping

| MAUI                                 | VMx                                                                 |
| ------------------------------------ | ------------------------------------------------------------------- |
| `INotifyPropertyChanged`             | `ComponentVMBase.PropertyChanged` (implemented by every VM)         |
| `ICommand`                           | `RelayCommand` / `RelayCommand<T>` (already implements `ICommand`)  |
| `ObservableCollection<T>`            | `ServicedObservableCollection<T>` or wrap an `ObservableList<T>`    |
| `MainThread.BeginInvokeOnMainThread` | `SynchronizationContextScheduler` created on the UI thread (`host`) |

## 9.4.3. Adapter skeleton

MAUI uses the WPF adapter unchanged. It is the exact file that `VMx.Tests`
executes (`Integration/XamlRecipeTests.cs`). CI has no MAUI host, so the
adapter runs there against a scheduler-driven host thread and, for WPF, a real
Dispatcher.

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

Create the adapter on the main thread, for example in the page constructor,
and set it as the page's `BindingContext`:

<!-- checked-snippet: langs/csharp/tests/VMx.Tests/Integration/XamlRecipeTests.cs#maui-binding-context -->

```csharp
BindingContext = new BindableVm<Note>(
    vm, new SynchronizationContextScheduler(SynchronizationContext.Current!));
```

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

## 9.4.4. Fuller example

No MAUI Notes-Showcase ships yet. The WPF and Avalonia adapters share
the same shape — see [wpf.md](wpf.md) and [avalonia.md](avalonia.md) for
copyable starting points. Microsoft's
[MAUI MVVM docs](https://learn.microsoft.com/dotnet/maui/fundamentals/data-binding/)
cover the framework-side mechanics.
