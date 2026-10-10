# 2. Installation

Python and Swift install from public registries. C#, TypeScript, the React
adapter, and Rust are complete in source but not yet published, so a project
uses them from a VMx checkout until their first registry release. Every flavor
implements spec 3.25.0; check the flavor README and registry before pinning a
release.

Run the commands below from your own project's directory. The source-checkout
commands assume VMx is cloned beside that project:

```bash
git clone https://github.com/thekaveh/VMx.git ../VMx
```

| Flavor     | Source tree   | Public package status               |
| ---------- | ------------- | ----------------------------------- |
| C#         | v3.25.0       | NuGet package not published yet     |
| Python     | v3.25.0       | PyPI release 3.23.0                  |
| TypeScript | v3.26.0       | npm package not published yet       |
| React adapter | v0.1.1 in source | publication waits for core npm #57 |
| Swift      | v3.26.0       | SwiftPM release 3.24.0              |
| Rust       | 0.31.0        | crates.io package not published yet |

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
    package payload. Consumers upgrading an older VMx line should also read
    [Upgrading TypeScript and React Consumers](getting-started/upgrading-typescript.md).

    ```bash
    npm --prefix ../VMx/langs/typescript ci
    npm --prefix ../VMx/langs/typescript run build
    npm --prefix ../VMx/packages/react ci
    npm --prefix ../VMx/packages/react run build
    mkdir -p /tmp/vmx-packs
    npm pack ../VMx/langs/typescript --pack-destination /tmp/vmx-packs
    npm pack ../VMx/packages/react --pack-destination /tmp/vmx-packs
    npm install /tmp/vmx-packs/thekaveh-vmx-3.26.0.tgz \
      /tmp/vmx-packs/thekaveh-vmx-react-0.1.1.tgz \
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
