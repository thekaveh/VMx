# WPF integration

Wire a `ComponentVM<M>` to a WPF view via `INotifyPropertyChanged` and the
existing `RelayCommand` infrastructure. WPF is Windows-only; for
cross-platform XAML, see [avalonia.md](avalonia.md).

## Reactivity primitive

WPF data binding observes `INotifyPropertyChanged.PropertyChanged` events.
VMx VMs publish `PropertyChangedMessage<TValue>(sender, propertyName, newValue)`
to their `IMessageHub` instead. The adapter translates one to the other.

## Mapping

| WPF                        | VMx                                                                |
| -------------------------- | ------------------------------------------------------------------ |
| `INotifyPropertyChanged`   | `PropertyChangedMessage<T>` on `IMessageHub`                       |
| `ICommand`                 | `RelayCommand` / `RelayCommand<T>` (already implements `ICommand`) |
| `INotifyCollectionChanged` | `CollectionChangedMessage` on the hub                              |
| `Dispatcher.Invoke`        | `IDispatcher.Foreground` scheduler                                 |

## Adapter skeleton

```csharp
public sealed class BindableVm<M> : INotifyPropertyChanged, IDisposable
{
    private readonly ComponentVM<M> _vm;
    private readonly IDisposable _sub;

    public BindableVm(ComponentVM<M> vm, IMessageHub hub)
    {
        _vm = vm;
        _sub = hub.Messages
            .OfType<PropertyChangedMessage<object>>()
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

Then in XAML: `<TextBlock Text="{Binding Model.Title}"/>` and
`<Button Command="{Binding SaveCommand}"/>` where `SaveCommand` is a
`RelayCommand` exposed by your domain wrapper.

## Fuller example

[`examples/csharp/WpfTodoApp/`](../../examples/csharp/WpfTodoApp/) — a
working WPF Todo app backed by a `CompositeVM<TodoVM>`.
