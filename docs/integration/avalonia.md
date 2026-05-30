# Avalonia integration

Cross-platform XAML for desktop (Win/macOS/Linux), mobile, and browser
via Avalonia 11+. Wires a `ComponentVM<M>` through an
`INotifyPropertyChanged` adapter, similar to WPF.

## Reactivity primitive

Avalonia bindings observe `INotifyPropertyChanged.PropertyChanged` and
`ICommand`. Avalonia ships its own `Dispatcher` for marshalling work
back to the UI thread.

## Mapping

| Avalonia                                   | VMx                                                           |
| ------------------------------------------ | ------------------------------------------------------------- |
| `INotifyPropertyChanged`                   | `PropertyChangedMessage<T>` on `IMessageHub`                  |
| `ICommand`                                 | `RelayCommand` / `RelayCommand<T>`                            |
| `AvaloniaList<T>` / `ObservableCollection` | `ServicedObservableCollection<T>` or wrap `ObservableList<T>` |
| `Dispatcher.UIThread.Post`                 | `IDispatcher.Foreground` scheduler                            |

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
            .ObserveOn(AvaloniaScheduler.Instance)
            .Subscribe(m => PropertyChanged?.Invoke(this,
                new PropertyChangedEventArgs(m.PropertyName)));
    }

    public M Model { get => _vm.Model; set => _vm.Model = value; }
    public string Name => _vm.Name;

    public event PropertyChangedEventHandler? PropertyChanged;
    public void Dispose() => _sub.Dispose();
}
```

Bind in XAML: `<TextBlock Text="{Binding Model.Title}"/>`. For lists,
wrap a `ServicedObservableCollection<T>` and observe its
`CollectionChangedMessage` to refresh an `AvaloniaList<T>`.

## Fuller example

The Notes-Showcase Avalonia app demonstrates the end-to-end pattern
(WorkspaceVM + AggregateVM + ConfirmationDecoratorCommand). It lands in
**v2.2.0** via the `examples-notes-showcase` branch.
