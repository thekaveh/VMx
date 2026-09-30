# VMx

![VMx](https://raw.githubusercontent.com/thekaveh/VMx/main/assets/vmx-poster.png)

VMx is a lifecycle-aware MVVM viewmodel framework built on `System.Reactive`.
This package is the C# flavor of one language-neutral specification that also
ships for Python, TypeScript, Swift, and Rust.

It provides:

- a five-state construction lifecycle with reversible construct and destruct
  and a depth-first dispose cascade;
- a reactive message hub for property, lifecycle, and collection changes;
- `ComponentVM<M>`, selectable `CompositeVM<T>`, `GroupVM<T>`, and fixed-arity
  aggregate viewmodels;
- `RelayCommand`, async and composite commands, and confirmation decorators;
- forms, dialogs, derived properties, paging, and search helpers.

Viewmodels implement `INotifyPropertyChanged`, so WPF, Avalonia, and .NET MAUI
bind to them directly.

```csharp
using VMx.Components;
using VMx.Services;

var hub = new MessageHub();
var note = ComponentVM<string>.Builder()
    .Name("note")
    .Services(hub, RxDispatcher.Immediate())
    .Model("draft")
    .Build();
note.Construct();
```

## Companion packages

- [VMx.Notifications](https://www.nuget.org/packages/VMx.Notifications) — a
  notification and confirmation hub.
- [VMx.Extensions.DependencyInjection](https://www.nuget.org/packages/VMx.Extensions.DependencyInjection)
  — `IServiceCollection.AddVMx()` registration.

## Documentation

- [Getting started with C#](https://thekaveh.github.io/VMx/getting-started/csharp/)
- [Installation](https://thekaveh.github.io/VMx/installation/)
- [Documentation site](https://thekaveh.github.io/VMx/)
- [Changelog](https://github.com/thekaveh/VMx/blob/main/langs/csharp/CHANGELOG.md)
- [Source and issues](https://github.com/thekaveh/VMx)

Licensed under the [Apache License 2.0](https://github.com/thekaveh/VMx/blob/main/LICENSE).
