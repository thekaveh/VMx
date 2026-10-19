# 9.2. Avalonia Integration

Wire a `ComponentVM<M>` to an Avalonia 12 view. Avalonia targets desktop
(Windows, macOS, Linux), mobile, and browser. VMx tests exercise Avalonia only
on its headless platform; the mobile and browser targets are framework
capabilities that VMx tests do not exercise.

## 9.2.1. Reactivity primitive

Avalonia binds through `INotifyPropertyChanged` and `ICommand`, as WPF does.
The shared rules are in [WPF: Reactivity primitive](wpf.md#931-reactivity-primitive).
Avalonia marshals work to the UI thread through `Dispatcher.UIThread`. On that
thread, `SynchronizationContext.Current` is an `AvaloniaSynchronizationContext`
that posts to it.

## 9.2.2. Mapping

The [shared XAML mapping](wpf.md#932-mapping) applies. Avalonia adds these rows:

| Avalonia                                   | VMx                                                                 |
| ------------------------------------------ | ------------------------------------------------------------------- |
| `AvaloniaList<T>` / `ObservableCollection` | `ServicedObservableCollection<T>` or wrap `ObservableList<T>`       |
| `Dispatcher.UIThread`                      | `SynchronizationContextScheduler` created on the UI thread (`host`) |

## 9.2.3. Adapter skeleton

Avalonia uses the [XAML adapter](wpf.md#933-xaml-adapter) `BindableVm<M>`
unchanged, with the same four rules. The Avalonia showcase tests
(`NotesShowcase.Tests/Views/AvaloniaRecipeTests.cs`) run it against real
Avalonia bindings on Avalonia's headless UI thread.

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

## 9.2.4. Fuller example

[`examples/csharp/avalonia/NotesShowcase/`](../../../examples/csharp/avalonia/NotesShowcase/) —
the Notes-Showcase Avalonia flagship: end-to-end `WorkspaceVM`,
`AggregateVM6`, `ConfirmationDecoratorCommand`, and `ThemeVM`.
