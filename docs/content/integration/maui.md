# 9.4. .NET MAUI Integration

Wire a `ComponentVM<M>` to a .NET MAUI page (desktop + mobile XAML)
through the same `INotifyPropertyChanged` adapter used for WPF and
Avalonia.

## 9.4.1. Reactivity primitive

MAUI's XAML data binding observes `INotifyPropertyChanged.PropertyChanged`
and `ICommand`. MAUI also exposes `IDispatcher` (its own type) for
marshalling work back to the UI thread.

## 9.4.2. Mapping

| MAUI                                 | VMx                                                                |
| ------------------------------------ | ------------------------------------------------------------------ |
| `INotifyPropertyChanged`             | `PropertyChangedMessage<T>` on `IMessageHub`                       |
| `ICommand`                           | `RelayCommand` / `RelayCommand<T>` (already implements `ICommand`) |
| `ObservableCollection<T>`            | `ServicedObservableCollection<T>` or wrap an `ObservableList<T>`   |
| `MainThread.BeginInvokeOnMainThread` | `IDispatcher.Foreground` scheduler                                 |

## 9.4.3. Adapter skeleton

```csharp
public sealed class BindableVm<M> : INotifyPropertyChanged, IDisposable
{
    private readonly ComponentVM<M> _vm;
    private readonly IDisposable _sub;

    public BindableVm(ComponentVM<M> vm, IMessageHub hub)
    {
        _vm = vm;
        _sub = hub.Messages
            .OfType<IPropertyChangedMessage<IComponentVM>>()
            .Where(m => ReferenceEquals(m.Sender, vm))
            .Subscribe(m => PropertyChanged?.Invoke(this,
                new PropertyChangedEventArgs(m.PropertyName)));
    }

    public M Model { get => _vm.Model; set => _vm.Model = value; }
    public string Name => _vm.Name;
    public ConstructionStatus Status => _vm.Status;

    public event PropertyChangedEventHandler? PropertyChanged;
    public void Dispose() => _sub.Dispose();
}
```

Set the page `BindingContext` to a `BindableVm<MyModel>` instance. Use
`SynchronizationContextScheduler` (Foreground) so subscribers observe
property changes on the MAUI UI thread.

## 9.4.4. Fuller example

No MAUI Notes-Showcase ships yet. The WPF and Avalonia adapters share
the same shape — see [wpf.md](wpf.md) and [avalonia.md](avalonia.md) for
copyable starting points. Microsoft's
[MAUI MVVM docs](https://learn.microsoft.com/dotnet/maui/fundamentals/data-binding/)
cover the framework-side mechanics.
