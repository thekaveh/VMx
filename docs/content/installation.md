# 2. Installation

This page lists every way to add VMx to a project, flavor by flavor. The
[Availability](index.md#11-availability) table on the home page shows which
packages are public and which source line each flavor carries. Every flavor's
source line implements spec 3.30.0. A published package can implement an
earlier spec version. The repository's
[`compatibility-matrix.md`](../../compatibility-matrix.md) lists the spec
version of each release.

Run the commands below from your own project directory. The source-checkout
commands assume VMx is cloned beside that project:

```bash
git clone https://github.com/thekaveh/VMx.git ../VMx
```

Minimum runtimes:

- C#: .NET 8, or any runtime that supports .NET Standard 2.0
- Python: 3.10
- TypeScript and the React adapter: Node.js 20.5.0, with RxJS 7.8
- Swift: iOS 16, macOS 13, tvOS 16, or watchOS 9
- Rust: 1.88, edition 2021

=== "C#"

    The NuGet package is not published. Reference the VMx project from a
    checkout:

    ```bash
    dotnet add MyApp.csproj reference ../VMx/langs/csharp/src/VMx/VMx.csproj
    ```

    The equivalent entry in the `.csproj` file is:

    ```xml
    <ItemGroup>
      <ProjectReference Include="../VMx/langs/csharp/src/VMx/VMx.csproj" />
    </ItemGroup>
    ```

    The optional dependency-injection package has its own project:

    ```bash
    dotnet add MyApp.csproj reference ../VMx/langs/csharp/src/VMx.Extensions.DependencyInjection/VMx.Extensions.DependencyInjection.csproj
    ```

    The optional notifications package also has its own project:

    ```bash
    dotnet add MyApp.csproj reference ../VMx/langs/csharp/src/VMx.Notifications/VMx.Notifications.csproj
    ```

    After the first NuGet publication, install the package instead:

    ```bash
    dotnet add package VMx
    ```

=== "Python"

    Install the public package from PyPI:

    ```bash
    pip install vmx
    # or
    uv add vmx
    ```

    Pin `vmx==3.23.0` to reproduce the released PyPI behavior.

    To use the source line, install the checkout in editable mode:

    ```bash
    uv add --editable ../VMx/langs/python
    # or
    pip install -e ../VMx/langs/python
    ```

=== "TypeScript"

    ```bash
    npm install @thekaveh/vmx rxjs

    # Official React bindings
    npm install @thekaveh/vmx-react react use-sync-external-store
    ```

    Consumers upgrading an older VMx line should also read
    [Upgrading TypeScript and React Consumers](getting-started/upgrading-typescript.md).

    To use an unreleased source line, build VMx and install packed tarballs.
    The source tree does not contain the built `dist/` output. Do not link the
    live adapter directory: a checkout's React dev dependency can conflict with
    a React 18 consumer. A tarball matches the public package payload.

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
    npm ls react   # expect one React version
    ```

=== "Swift"

    Add the package to `Package.swift`. The consumer manifest must declare
    platforms at or above the VMx minimums:

    ```swift
    platforms: [.iOS(.v16), .macOS(.v13), .tvOS(.v16), .watchOS(.v9)],
    dependencies: [
        .package(url: "https://github.com/thekaveh/VMx.git", from: "3.24.0")
    ],
    targets: [
        .target(name: "MyApp", dependencies: [
            .product(name: "VMx", package: "vmx")
        ])
    ]
    ```

    In Xcode, select **File → Add Package Dependencies** and enter
    `https://github.com/thekaveh/VMx.git`.

    SwiftPM resolves the tag `v3.24.0`, which implements spec 3.23.x. The
    matching `swift-v3.24.0` GitHub Release contains the Swift changelog
    notes. The lowercase `package: "vmx"` value is SwiftPM's repository
    identity. The library product and the imported module are `VMx`.

    The package declares `swift-tools-version: 5.9`. CI builds and tests only
    with Swift 6.0 (Xcode 16.0) and later, so earlier compilers are untested.

    To use the source line, depend on the checkout by path. The product
    declaration stays the same:

    ```swift
    .package(path: "../VMx")
    ```

=== "Rust"

    The crate is not published to crates.io. Its package name is `vmx-rs`,
    and code imports it as `vmx`. Depend on a checkout by path:

    ```toml
    [dependencies]
    vmx-rs = { path = "../VMx/langs/rust" }
    ```

    Or depend on the repository by git:

    ```toml
    [dependencies]
    vmx-rs = { git = "https://github.com/thekaveh/VMx.git" }
    ```
