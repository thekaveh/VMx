# 2. Installation

VMx has five catalog-complete source flavors. C#, Python, and Swift implement
v3.22.0; TypeScript 3.23.0 implements spec 3.22.0, and Rust 0.25.0
declares `MIN_SPEC_VERSION = "3.22.0"`. “Catalog-complete” means all 396 library
IDs are represented; it does not hide the documented
[Rust surface-convergence backlog](../maintenance/2026-07-16-rust-capability-parity.md).
Public package availability can lag the source tree, so check the flavor README
and registry before pinning a release.

| Flavor     | Source tree   | Public package status               |
| ---------- | ------------- | ----------------------------------- |
| C#         | v3.22.0       | NuGet package not published yet     |
| Python     | v3.22.0       | `vmx` latest published: 3.1.0       |
| TypeScript | v3.23.0       | npm package not published yet       |
| Swift      | v3.22.0       | SwiftPM release 3.20.0              |
| Rust       | 0.25.0        | crates.io package not published yet |

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
