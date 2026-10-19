# 9.4. .NET MAUI Integration

Wire a `ComponentVM<M>` to a .NET MAUI page (desktop and mobile XAML) through
the same `INotifyPropertyChanged` adapter as WPF.

## 9.4.1. Reactivity primitive

MAUI binds through `INotifyPropertyChanged` and `ICommand`, as WPF does. The
shared rules are in [WPF: Reactivity primitive](wpf.md#931-reactivity-primitive).

## 9.4.2. Mapping

The [shared XAML mapping](wpf.md#932-mapping) applies. MAUI adds these rows:

| MAUI                                 | VMx                                                                 |
| ------------------------------------ | ------------------------------------------------------------------- |
| `ObservableCollection<T>`            | `ServicedObservableCollection<T>` or wrap an `ObservableList<T>`    |
| `MainThread.BeginInvokeOnMainThread` | `SynchronizationContextScheduler` created on the UI thread (`host`) |
| page `BindingContext`                | the `BindableVm<M>` adapter                                         |

## 9.4.3. Adapter skeleton

MAUI uses the [XAML adapter](wpf.md#933-xaml-adapter) `BindableVm<M>`
unchanged, with the same four rules. `XamlRecipeTests.cs` executes the adapter
on test schedulers. CI has no MAUI host, so the `BindingContext` statement
below runs against a stand-in page.

Create the adapter on the main thread, for example in the page constructor,
and set it as the page's `BindingContext`:

<!-- checked-snippet: langs/csharp/tests/VMx.Tests/Integration/XamlRecipeTests.cs#maui-binding-context -->

```csharp
BindingContext = new BindableVm<Note>(
    vm, new SynchronizationContextScheduler(SynchronizationContext.Current!));
```

## 9.4.4. Fuller example

There is no MAUI Notes-Showcase. For copyable starting points, see the WPF
TodoApp in [wpf.md](wpf.md) and the Avalonia flagship in
[avalonia.md](avalonia.md). Microsoft's
[MAUI MVVM docs](https://learn.microsoft.com/dotnet/maui/fundamentals/data-binding/)
cover the framework-side mechanics.
