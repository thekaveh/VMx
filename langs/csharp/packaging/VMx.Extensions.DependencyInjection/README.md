# VMx.Extensions.DependencyInjection

`Microsoft.Extensions.DependencyInjection` registration for
[VMx](https://www.nuget.org/packages/VMx), the lifecycle-aware MVVM viewmodel
framework. This package depends on `VMx` and registers its services in an
`IServiceCollection`:

```csharp
using Microsoft.Extensions.DependencyInjection;
using VMx.Extensions.DependencyInjection;

var services = new ServiceCollection();

// IMessageHub: a singleton MessageHub.
// IDispatcher: a singleton RxDispatcher on the SynchronizationContext that is
// current when AddVMx runs, typically the UI thread's.
services.AddVMx();
```

`AddVMx` takes an optional `configure` action; `options.UseDispatcher(...)`
supplies your own dispatcher factory. Registrations use `TryAdd`, so services
registered before `AddVMx` win and a second call adds nothing. Applications
that construct their hub and dispatcher directly do not need this package.

## Documentation

- [Getting started with C#, including dependency injection](https://github.com/thekaveh/VMx/blob/main/docs/content/getting-started/csharp.md)
- [Changelog](https://github.com/thekaveh/VMx/blob/main/langs/csharp/CHANGELOG.md)
- [Source and issues](https://github.com/thekaveh/VMx)

Licensed under the [Apache License 2.0](https://github.com/thekaveh/VMx/blob/main/LICENSE).
