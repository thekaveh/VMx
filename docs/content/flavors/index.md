# 7.1. Language Flavors

VMx ships one language-neutral specification through five idiomatic source
surfaces: C#, Python, TypeScript, Swift, and Rust. The conceptual shape stays
aligned; naming, package workflow, and host integration follow the local
language.

## 7.1.1. At A Glance

| Flavor     | Package status                                                          | Reactive primitive | Naming idiom |
| ---------- | ----------------------------------------------------------------------- | ------------------ | ------------ |
| C#         | `VMx` package name reserved in docs; source-tree/local reference today  | `System.Reactive`  | PascalCase   |
| Python     | `vmx` published on PyPI; source tree may be ahead of latest release     | `reactivex`        | snake_case   |
| TypeScript | `@thekaveh/vmx` package name defined; source-tree/local workspace today | `rxjs`             | camelCase    |
| Swift      | VMx 3.20.0 released through repository-root SwiftPM tags                | `Combine`          | camelCase    |
| Rust       | `vmx-rs` crate in source tree; crates.io release not published          | VMx-owned facade   | snake_case   |

## 7.1.2. Reading Path

- Start with the page for your flavor when you need install, package-status,
  and host-integration pointers.
- Use [Cross-Language Naming](cross-language-naming.md) when you are translating
  an idea or snippet across flavors.
- Use [Quickstart](../quickstart.md) when you want the smallest same-shape setup
  before diving into flavor-specific details.

## 7.1.3. Flavor Pages

- [C#](csharp.md)
- [Python](python.md)
- [TypeScript](typescript.md)
- [Swift](swift.md)
- [Rust](rust.md)

## 7.1.4. Common Rules

- All five full-parity source flavors target the same VM family model,
  lifecycle semantics, and 391-ID library conformance catalog.
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
