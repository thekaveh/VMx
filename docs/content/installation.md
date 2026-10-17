# 2. Installation

Python, Swift, TypeScript, and the React adapter install from public registries.
C# and Rust are complete in source but not yet published, so a project uses
them from a VMx checkout until their first registry release. Every flavor's
source line implements spec 3.29.0. A published package can implement an
earlier spec version. The repository's
[`compatibility-matrix.md`](../../compatibility-matrix.md) lists the spec
version of each release.

Run the commands below from your own project's directory. The source-checkout
commands assume VMx is cloned beside that project:

```bash
git clone https://github.com/thekaveh/VMx.git ../VMx
```

| Flavor     | Source tree   | Public package status               |
| ---------- | ------------- | ----------------------------------- |
| C#         | v3.29.0       | NuGet package not published yet     |
| Python     | v3.29.0       | PyPI release 3.23.0                  |
| TypeScript | v3.30.0       | npm release 3.30.0                  |
| React adapter | v0.1.1     | npm release 0.1.1                   |
| Swift      | v3.30.0       | SwiftPM release 3.24.0              |
| Rust       | 0.35.0        | crates.io package not published yet |

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

    ```bash
    npm install @thekaveh/vmx rxjs

    # Official React bindings
    npm install @thekaveh/vmx-react react use-sync-external-store
    ```

    Consumers upgrading an older VMx line should also read
    [Upgrading TypeScript and React Consumers](getting-started/upgrading-typescript.md).

    To use an unreleased source line instead, clone VMx beside the consumer and
    install packed tarballs. Do not link the live adapter directory: a source
    checkout's React dev dependency can conflict with a React 18 consumer, while
    the tarball matches the public package payload.

    ```bash
    npm --prefix ../VMx/langs/typescript ci
    npm --prefix ../VMx/langs/typescript run build
    npm --prefix ../VMx/packages/react ci
    npm --prefix ../VMx/packages/react run build
    rm -rf /tmp/vmx-packs && mkdir -p /tmp/vmx-packs
    npm pack ../VMx/langs/typescript --pack-destination /tmp/vmx-packs
    npm pack ../VMx/packages/react --pack-destination /tmp/vmx-packs
    npm install /tmp/vmx-packs/thekaveh-vmx-[0-9]*.tgz \
      /tmp/vmx-packs/thekaveh-vmx-react-[0-9]*.tgz \
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
