# 7.1. Language Flavors

VMx ships one language-neutral specification through five idiomatic source
surfaces: C#, Python, TypeScript, Swift, and Rust. The conceptual shape stays
aligned; naming, package workflow, and host integration follow the local
language.

## 7.1.1. At A Glance

| Flavor     | Reactive primitive | Naming idiom |
| ---------- | ------------------ | ------------ |
| C#         | `System.Reactive`  | PascalCase   |
| Python     | `reactivex`        | snake_case   |
| TypeScript | `rxjs`             | camelCase    |
| Swift      | `Combine`          | camelCase    |
| Rust       | VMx-owned facade   | snake_case   |

Package status for each flavor is in [Availability](../index.md#11-availability).
[Installation](../installation.md) gives the package and source-checkout steps.

## 7.1.2. Reading Path

- Start with the page for your flavor when you need package and
  host-integration pointers.
- Use [Cross-Language Naming](cross-language-naming.md) when you are translating
  an idea or snippet across flavors.
- Use [Quickstart](../getting-started/index.md) when you want the smallest same-shape setup
  before diving into flavor-specific details.

## 7.1.3. Flavor Pages

- [C#](csharp.md)
- [Python](python.md)
- [TypeScript](typescript.md)
- [Swift](swift.md)
- [Rust](rust.md)

## 7.1.4. Common Rules

- All five catalog-complete source flavors target the same VM family model and
  425-ID library conformance catalog. The
  [Rust parity ledger](../../maintenance/2026-07-16-rust-capability-parity.md)
  (open items and recorded differences in §12.4.7 and §12.7–§12.12) tracks the remaining Rust
  public-surface and behavior gaps.
- Public naming follows ADR-0006: PascalCase in C#, snake_case in Python,
  camelCase in TypeScript and Swift, and snake_case for Rust methods with
  Rust-style type names such as `ComponentVm`.
- The substantive naming divergence is the modeled leaf/container type: C# and
  Rust retain `ComponentVM<M>` / `ComponentVm<M>`, while Python, TypeScript,
  and Swift use `ComponentVMOf[...]` / `ComponentVMOf<...>`.

For source-tree status and the long-form API surface, use the flavor READMEs in
the repository:
[C#](../../../langs/csharp/README.md),
[Python](../../../langs/python/README.md),
[TypeScript](../../../langs/typescript/README.md),
[Swift](../../../langs/swift/README.md),
[Rust](../../../langs/rust/README.md).
