# Avalonia integration

Cross-platform XAML for desktop (Win/macOS/Linux), mobile, and browser
via Avalonia 11+. Wires a `ComponentVM<M>` through an
`INotifyPropertyChanged` adapter, similar to WPF.

## 1. Reactivity primitive

Avalonia bindings observe `INotifyPropertyChanged.PropertyChanged` and
`ICommand`. Avalonia ships its own `Dispatcher` for marshalling work
back to the UI thread.

## 2. Mapping

| Avalonia                                   | VMx                                                           |
| ------------------------------------------ | ------------------------------------------------------------- |
| `INotifyPropertyChanged`                   | `PropertyChangedMessage<T>` on `IMessageHub`                  |
| `ICommand`                                 | `RelayCommand` / `RelayCommand<T>`                            |
| `AvaloniaList<T>` / `ObservableCollection` | `ServicedObservableCollection<T>` or wrap `ObservableList<T>` |
| `Dispatcher.UIThread.Post`                 | `IDispatcher.Foreground` scheduler                            |

## 3. Adapter skeleton

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

## 4. Fuller example

[`examples/csharp/avalonia/NotesShowcase/`](../../examples/csharp/avalonia/NotesShowcase/) —
the Notes-Showcase Avalonia flagship: end-to-end `WorkspaceVM` +
`AggregateVM6` + `ConfirmationDecoratorCommand` pattern (shipped in
v2.2.0; `ThemeVM` added in v2.4.0).
