# VMx — C# flavor

The C# implementation of the VMx hierarchical MVVM framework, published as the `VMx` NuGet package.

- Target frameworks: `netstandard2.0`, `net8.0`
- See the language-neutral spec at [`/spec/`](../../spec).

## Status

**v1.1.0** — implements `spec-v1.1.0` end-to-end. 75/75 conformance IDs pass
(89 test methods). Multi-targets `netstandard2.0` and `net8.0`. Optional
companion package `VMx.Extensions.DependencyInjection` provides
`services.AddVMx(...)`.

See [`docs/getting-started/csharp.md`](../../docs/getting-started/csharp.md) for a tutorial.

## Build and test

```bash
dotnet restore
dotnet build
dotnet test
dotnet format --verify-no-changes
```
