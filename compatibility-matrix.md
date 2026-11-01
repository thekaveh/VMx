# Spec ↔ language compatibility matrix

Updated alongside spec and flavor releases.

## 1. Matrix

| spec  | python          | csharp          | typescript      | swift           | rust          |
| ----- | --------------- | --------------- | --------------- | --------------- | ------------- |
| 3.30.x | 3.30.0[^current] <!-- x-release-please-version --> | 3.30.0[^current] | 3.31.0[^current] | 3.31.0[^current] | 0.36.0[^rust] |
| 3.29.x | —[^source-3-29] | —[^source-3-29] | 3.30.0[^typescript-3-30] | —[^source-3-29] | 0.35.0[^source-3-29] |
| 3.28.x | —[^source-3-24-28] | —[^source-3-24-28] | —[^source-3-24-28] | —[^source-3-24-28] | 0.34.0[^source-3-24-28] |
| 3.27.x | —[^source-3-24-28] | —[^source-3-24-28] | —[^source-3-24-28] | —[^source-3-24-28] | 0.33.0[^source-3-24-28] |
| 3.26.x | —[^source-3-24-28] | —[^source-3-24-28] | —[^source-3-24-28] | —[^source-3-24-28] | 0.32.0[^source-3-24-28] |
| 3.25.x | —[^source-3-24-28] | —[^source-3-24-28] | —[^source-3-24-28] | —[^source-3-24-28] | 0.31.0[^source-3-24-28] |
| 3.24.x | —[^source-3-24-28] | —[^source-3-24-28] | —[^source-3-24-28] | —[^source-3-24-28] | 0.30.0[^source-3-24-28] |
| 3.23.x | 3.23.0–3.23.1[^python-3-23-1] | —[^source-3-23] | —[^source-3-23] | 3.24.0[^swift] | 0.27.0–0.29.0[^source-3-23] |
| 3.22.x[^source-only] | 3.22.0–3.22.1 | 3.22.0–3.22.1 | 3.23.0–3.23.1 | 3.22.0–3.23.0 | 0.24.0–0.26.0 |
| 3.21.x | —               | —               | —               | —               | 0.23.0[^rust-source] |
| 3.20.x[^legacy-semantic-tag-only] | —               | —               | —               | 3.20.0         | 0.20.0–0.22.0[^rust-source] |
| 3.19.x | —               | —               | —               | —               | 0.19.0[^rust-source] |
| 3.18.x | —               | —               | —               | —               | 0.18.0[^rust-source] |
| 3.17.x | —               | —               | —               | —               | 0.17.0[^rust-source] |
| 3.16.x | —               | —               | —               | —               | 0.16.0[^rust-source] |
| 3.15.x | —               | —               | —               | —               | 0.15.0[^rust-source] |
| 3.14.x | —               | —               | —               | —               | 0.14.0[^rust-source] |
| 3.13.x | —               | —               | —               | —               | 0.13.0[^rust-source] |
| 3.3.x | —               | —               | —               | —               | 0.3.0        |
| 3.2.x | —               | —               | —               | —               | 0.2.0        |
| 3.1.x | 3.1.0           | —               | —               | —               | 0.1.0        |
| 2.6.x | 2.6.1           | 2.6.0           | 2.6.0           | 2.6.0 (subset)  | —             |
| 2.4.x | 2.4.0           | 2.4.0           | 2.4.0           | 2.4.0 (subset)  | —             |
| 2.3.x | 2.3.0           | 2.3.0           | 2.3.0           | —               | —             |
| 2.2.x | 2.2.0           | 2.2.0           | 2.2.0           | —               | —             |
| 2.1.x | 2.1.0           | 2.1.0           | 2.1.0           | —               | —             |
| 2.0.x | 2.0.0           | 2.0.0           | 2.0.0           | —               | —             |
| 1.0.x | 1.0.0           | 1.0.0           | —               | —               | —             |

## 2. Notes

A `—` cell indicates that this flavor has no version for that spec line. A
cell shows the version range of the flavor that implements the spec line (e.g.
`1.0.0` or `1.0.0–1.2.x` once minor/patch releases follow). A cell with a
source footnote names an unreleased source version.

Every flavor covers all 444 library conformance IDs. The five `THEME-00x`
scenario IDs live in the flagship example apps. `spec/HISTORY.md` records the
release and ADR that added each group of IDs. Swift has member-level parity with C#,
Python, and TypeScript. Rust's remaining public-surface and behavior gaps are
the open items §12.4.7 and §12.7–§12.13 in
`docs/maintenance/2026-07-16-rust-capability-parity.md`.

[^current]: C# 3.30.0, Python 3.30.0, TypeScript 3.31.0, and Swift 3.31.0 are
the unreleased source lines implementing spec 3.30.0. Python 3.23.0 is publicly
installable from PyPI, Swift 3.24.0 through SwiftPM, and TypeScript 3.30.0 from
npm. The C# public package remains pending; its release job refuses to
green-skip a publish without configured credentials.

[^typescript-3-30]: TypeScript 3.30.0 implements spec 3.29.0 and is published on
npm as `@thekaveh/vmx` (`typescript-v3.30.0`, 2026-10-16).

[^source-3-29]: C# 3.29.0, Python 3.29.0, Swift 3.30.0, and Rust 0.35.0
implemented spec 3.29.x as validated source lines but were never tagged or
published. The Rust cell records source history, as for earlier Rust rows.

[^swift]: Swift 3.24.0 is publicly installable from the repository root through
the immutable `v3.24.0` semantic tag. The matching `swift-v3.24.0` operational
tag and [GitHub Release](https://github.com/thekaveh/VMx/releases/tag/swift-v3.24.0)
point to the same verified `main` commit.

[^rust]: Rust is a source-tree, catalog-complete flavor promoted by ADR-0081. It
is at source version 0.36.0, declares `MIN_SPEC_VERSION = "3.30.0"`, and carries
behavioral tests for all 444 library conformance IDs. The parity ledger
`docs/maintenance/2026-07-16-rust-capability-parity.md` records its member
evidence and open items §12.4.7 and §12.7–§12.13. Rust is not published to crates.io.

[^rust-source]: Rust `0.13.0`, `0.14.0`, `0.15.0`, `0.16.0`, `0.17.0`,
`0.18.0`, and `0.19.0` record historical source-tree parity for spec 3.13.x
through 3.19.x.
They were not published to crates.io and do not imply
corresponding `rust-v*` tags or releases.

The same source-only history applies to Rust `0.20.0` through `0.22.0` for
spec 3.20.x and to Rust `0.23.0` for spec 3.21.x. The untagged C# `3.20.0–3.20.1`, Python `3.20.0–3.20.1`,
TypeScript `3.20.0–3.21.1`, and Swift `3.20.1` source lines, and the untagged
spec 3.21.x lines (C# `3.21.0`, Python `3.21.0`, TypeScript `3.22.0`, and Swift
`3.21.0`), are intentionally not listed as releases in the matrix.

[^source-only]: Spec 3.22.x and its listed flavor versions were validated source
lines but were never tagged or published. They remain compatibility history,
not release claims.

[^python-3-23-1]: Python 3.23.1 is tagged (`python-v3.23.1`) and has a GitHub
Release, but its PyPI upload failed; PyPI's latest Python release is 3.23.0.

[^source-3-23]: C# 3.23.0, Python 3.23.2–3.23.3, TypeScript 3.24.0–3.24.1,
and Rust 0.27.0–0.29.0 implemented spec 3.23.x as validated source lines but
were never tagged or published, so the row lists only the tagged Python and
Swift releases. The Rust versions are recorded as source history, as for
earlier Rust rows.

[^source-3-24-28]: Spec 3.24.x to 3.28.x exist only as validated source lines.
They were never tagged or published, so these rows list no releases. The Rust
cells record source history, as for earlier Rust rows. The other flavors'
source versions per spec line are:

    - 3.24.x: C# 3.24.0, Python 3.24.0, TypeScript 3.25.0, Swift 3.25.0.
    - 3.25.x: C# 3.25.0, Python 3.25.0, TypeScript 3.26.0, Swift 3.26.0.
    - 3.26.x: C# 3.26.0, Python 3.26.0, TypeScript 3.27.0, Swift 3.27.0.
    - 3.27.x: C# 3.27.0, Python 3.27.0, TypeScript 3.28.0, Swift 3.28.0.
    - 3.28.x: C# 3.28.0, Python 3.28.0, TypeScript 3.29.0, Swift 3.29.0.

[^legacy-semantic-tag-only]: Spec 3.20.0 predates the canonical `spec-v*`
namespace and has no `spec-v3.20.0` tag. The existing immutable `v3.20.0` tag
belongs to the Swift 3.20.0 package for SwiftPM; it is historical evidence, not
a namespace future specification releases reuse.

## 2.1. React adapter compatibility

| Adapter | VMx TypeScript | React | RxJS | Registry status |
| --- | --- | --- | --- | --- |
| 0.1.1 | ^3.24.1 | ^18.3.1 or ^19.0.0 | ^7.8.0 | published on npm (`react-v0.1.1`, 2026-10-16) |

`@thekaveh/vmx-react` uses independent SemVer and `react-v*` release tags. A
core release requires an adapter release only when the supported API or peer
range changes.

## 3. C# companion packages

The C# core package `VMx` ships with two opt-in companion assemblies. Each
versions independently (per ADR-0009 / ADR-0013) but declares the spec
version it implements.

| Package                                | Current | Spec  |
| -------------------------------------- | ------- | ----- |
| `VMx.Extensions.DependencyInjection`   | 2.1.1   | 2.1.x |
| `VMx.Notifications`                    | 1.2.0   | 2.6.x |

> **Note:** These names become registry links only after their first NuGet
> publication. Companion packages (`VMx.Notifications`, `VMx.Extensions.DependencyInjection`) version
> independently from `VMx` core, starting from 1.0.0 (per ADR-0013). The `1.2.0` shown above is not
> a divergence from the spec — it is the companion package's own version counter. The **Spec**
> column is the spec revision each companion's own feature surface implements; it is not the core
> dependency floor. As built at HEAD both companions reference the `VMx` 3.30.0 core project and
> pack with a `VMx >= 3.30.0` NuGet dependency. The DI companion uses packaging-only patch 2.1.1
> because the historical core tag `csharp-v2.1.0` is immutable. Future companion releases use
> package-specific `csharp-notifications-v*` and `csharp-dependency-injection-v*` tags, preventing
> that legacy cross-package collision; the already-advanced DI version is not rewound. These source
> versions do not claim that the packages have been published.
