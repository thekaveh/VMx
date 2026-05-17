# VMx — C# flavor

The C# implementation of the VMx hierarchical MVVM framework, published as the `VMx` NuGet package.

- Target frameworks: `netstandard2.0`, `net8.0`
- See the language-neutral spec at [`/spec/`](../../spec) and the design doc at
  [`/docs/superpowers/specs/2026-05-16-vmx-multilang-revival-design.md`](../../docs/superpowers/specs/2026-05-16-vmx-multilang-revival-design.md).

## Build and test

```bash
dotnet restore
dotnet build
dotnet test
dotnet format --verify-no-changes
```
