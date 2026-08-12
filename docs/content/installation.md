# 2. Installation

VMx has five catalog-complete source flavors implementing spec 3.23.0. Their
current package source versions are listed below; Rust 0.29.0
declares `MIN_SPEC_VERSION = "3.23.0"`. All five implement the canonical
concepts and behavior, with intentional flavor idioms documented by ADR; the
completed [Rust convergence ledger](../maintenance/2026-07-16-rust-capability-parity.md)
records the focused 0.27.0 evidence. Public package availability can lag the
source tree, so check the flavor README and registry before pinning a release.

| Flavor     | Source tree   | Public package status               |
| ---------- | ------------- | ----------------------------------- |
| C#         | v3.23.0       | NuGet package not published yet     |
| Python     | v3.23.0       | PyPI release 3.23.0                  |
| TypeScript | v3.24.0       | npm package not published yet       |
| React adapter | v0.1.0 in source | publication waits for core npm #57 |
| Swift      | v3.24.0       | SwiftPM release 3.24.0              |
| Rust       | 0.29.0        | crates.io package not published yet |

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

    # Official React bindings (after core and adapter publication)
    npm install @thekaveh/vmx-react react use-sync-external-store
    ```

    Until then, clone VMx beside the consumer and install packed tarballs. Do
    not link the live adapter directory: a source checkout's React dev dependency
    can conflict with a React 18 consumer, while the tarball matches the public
    package payload.

    ```bash
    npm --prefix ../VMx/langs/typescript ci
    npm --prefix ../VMx/langs/typescript run build
    npm --prefix ../VMx/packages/react ci
    npm --prefix ../VMx/packages/react run build
    mkdir -p /tmp/vmx-packs
    npm pack ../VMx/langs/typescript --pack-destination /tmp/vmx-packs
    npm pack ../VMx/packages/react --pack-destination /tmp/vmx-packs
    npm install /tmp/vmx-packs/thekaveh-vmx-3.24.0.tgz \
      /tmp/vmx-packs/thekaveh-vmx-react-0.1.0.tgz \
      react rxjs use-sync-external-store
    ```

=== "Swift"

    ```swift
    dependencies: [
        .package(url: "https://github.com/thekaveh/VMx.git", from: "3.24.0")
    ],
    targets: [
        .target(name: "MyApp", dependencies: [
            .product(name: "VMx", package: "vmx")
        ])
    ]
    ```

    SwiftPM resolves `v3.24.0`. The matching `swift-v3.24.0` GitHub Release
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
