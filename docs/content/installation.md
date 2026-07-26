# 2. Installation

VMx has five catalog-complete source flavors implementing spec 3.23.0. Their
current package source versions are listed below; Rust 0.27.0
declares `MIN_SPEC_VERSION = "3.23.0"`. All five implement the canonical
concepts and behavior, with intentional flavor idioms documented by ADR; the
completed [Rust convergence ledger](../maintenance/2026-07-16-rust-capability-parity.md)
records the focused 0.27.0 evidence. Public package availability can lag the
source tree, so check the flavor README and registry before pinning a release.

| Flavor     | Source tree   | Public package status               |
| ---------- | ------------- | ----------------------------------- |
| C#         | v3.23.0       | NuGet package not published yet     |
| Python     | v3.23.0       | `vmx` latest published: 3.1.0       |
| TypeScript | v3.24.0       | npm package not published yet       |
| Swift      | v3.24.0       | SwiftPM release 3.20.0              |
| Rust       | 0.27.0        | crates.io package not published yet |

=== "C#"

    The package command applies after the first NuGet publication:

    ```bash
    dotnet add package VMx
    ```

    Until then, clone VMx beside the consumer and use a project reference:

    ```bash
    dotnet add MyApp.csproj reference ../VMx/langs/csharp/src/VMx/VMx.csproj
    ```

=== "Python"

    ```bash
    pip install vmx
    # or
    uv add vmx
    ```

=== "TypeScript"

    The registry command applies after the first npm publication:

    ```bash
    npm install @thekaveh/vmx rxjs
    ```

    Until then, clone VMx beside the consumer, prepare its package, and install
    the local directory:

    ```bash
    npm --prefix ../VMx/langs/typescript ci
    npm --prefix ../VMx/langs/typescript run build
    npm install ../VMx/langs/typescript rxjs
    ```

=== "Swift"

    ```swift
    dependencies: [
        .package(url: "https://github.com/thekaveh/VMx.git", from: "3.20.0")
    ],
    targets: [
        .target(name: "MyApp", dependencies: [
            .product(name: "VMx", package: "vmx")
        ])
    ]
    ```

    SwiftPM resolves `v3.20.0`. The matching `swift-v3.20.0` GitHub Release
    contains the Swift changelog notes. Supported floors are iOS 16, macOS 13,
    tvOS 16, and watchOS 9.

=== "Rust"

    Clone VMx beside the consumer and use the unpublished crate by path:

    ```toml
    vmx-rs = { path = "../VMx/langs/rust" }
    ```

## 2.1. Notes

- C# uses `System.Reactive`.
- Python uses `reactivex`.
- TypeScript uses `rxjs`.
- Swift uses `Combine`.
- Rust uses its VMx-owned hot-stream facade.
