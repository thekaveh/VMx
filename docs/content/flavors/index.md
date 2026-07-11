# 7.1. Language Flavors

VMx ships one language-neutral specification through five idiomatic source
surfaces: C#, Python, TypeScript, Swift, and Rust. The conceptual shape stays
aligned; naming, package workflow, and host integration follow the local
language.

## At A Glance

| Flavor     | Package status                                                          | Reactive primitive  | Naming idiom |
| ---------- | ----------------------------------------------------------------------- | ------------------- | ------------ |
| C#         | `VMx` package name reserved in docs; source-tree/local reference today  | `System.Reactive`   | PascalCase   |
| Python     | `vmx` published on PyPI; source tree may be ahead of latest release     | `reactivex`         | snake_case   |
| TypeScript | `@thekaveh/vmx` package name defined; source-tree/local workspace today | `rxjs`              | camelCase    |
| Swift      | SwiftPM package from repo tags after release                            | `Combine`           | camelCase    |
| Rust       | `vmx-rs` crate in source tree; crates.io release not published          | VMx facade / rxrust | snake_case   |

## Reading Path

- Start with the page for your flavor when you need install, package-status,
  and host-integration pointers.
- Use [Cross-Language Naming](cross-language-naming.md) when you are translating
  an idea or snippet across flavors.
- Use [Quickstart](../quickstart.md) when you want the smallest same-shape setup
  before diving into flavor-specific details.

## Flavor Pages

- [C#](csharp.md)
- [Python](python.md)
- [TypeScript](typescript.md)
- [Swift](swift.md)
- [Rust](rust.md)

## Common Rules

- All five full-parity source flavors target the same VM family model,
  lifecycle semantics, and 332-ID library conformance catalog.
- Public naming follows ADR-0006: PascalCase in C#, snake_case in Python,
  camelCase in TypeScript and Swift, and snake_case for Rust methods with
  Rust-style type names such as `ComponentVm`.
- The substantive naming divergence is the modeled leaf/container type:
  `ComponentVM<M>` in C# versus `ComponentVMOf[...]` / `ComponentVMOf<...>` in
  Python, TypeScript, and Swift.

For source-tree status and the long-form API surface, use the flavor READMEs in
the repository:
[C#](../../../langs/csharp/README.md),
[Python](../../../langs/python/README.md),
[TypeScript](../../../langs/typescript/README.md),
[Swift](../../../langs/swift/README.md),
[Rust](../../../langs/rust/README.md).
