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
// IDispatcher: a singleton RxDispatcher bound to SynchronizationContext.Current.
services.AddVMx();
```

An overload accepts options, for example to supply your own dispatcher factory.
Applications that construct their hub and dispatcher directly do not need this
package.

## Documentation

- [Getting started with C#, including dependency injection](https://thekaveh.github.io/VMx/getting-started/csharp/)
- [Changelog](https://github.com/thekaveh/VMx/blob/main/langs/csharp/CHANGELOG.md)
- [Source and issues](https://github.com/thekaveh/VMx)

Licensed under the [Apache License 2.0](https://github.com/thekaveh/VMx/blob/main/LICENSE).
