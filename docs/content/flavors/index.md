# 7.1. Language Flavors

VMx ships one language-neutral specification through five idiomatic source
surfaces: C#, Python, TypeScript, Swift, and Rust. The conceptual shape stays
aligned; naming, package workflow, and host integration follow the local
language.

## 7.1.1. At A Glance

| Flavor     | Reactive primitive |
| ---------- | ------------------ |
| C#         | `System.Reactive`  |
| Python     | `reactivex`        |
| TypeScript | `rxjs`             |
| Swift      | `Combine`          |
| Rust       | VMx-owned facade   |

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
  library conformance catalog. The
  [Rust parity ledger](../../maintenance/2026-07-16-rust-capability-parity.md)
  lists the open Rust public-surface and behavior items and the recorded
  differences.
- Public naming follows each language idiom (ADR-0006).
  [Cross-Language Naming](cross-language-naming.md) gives the casing, the
  spelling of each concept, and the one structural naming divergence.

For source-tree status and the long-form API surface, use the flavor READMEs in
the repository:
[C#](../../../langs/csharp/README.md),
[Python](../../../langs/python/README.md),
[TypeScript](../../../langs/typescript/README.md),
[Swift](../../../langs/swift/README.md),
[Rust](../../../langs/rust/README.md).
