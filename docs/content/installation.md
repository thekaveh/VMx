# 2. Installation

VMx has five full-parity source flavors. C#, Python, and Swift implement
v3.20.0; TypeScript 3.21.0 still implements spec 3.20.0, and Rust 0.20.0
declares `MIN_SPEC_VERSION = "3.20.0"`. Public package availability can lag the
source tree, so check the flavor README and registry before pinning a release.

| Flavor     | Source tree   | Public package status               |
| ---------- | ------------- | ----------------------------------- |
| C#         | v3.20.0       | NuGet package not published yet     |
| Python     | v3.20.0       | `vmx` latest published: 3.1.0       |
| TypeScript | v3.21.0       | npm package not published yet       |
| Swift      | v3.20.0       | SwiftPM release 3.20.0              |
| Rust       | 0.20.0        | crates.io package not published yet |

=== "C#"

    ```bash
    dotnet add package VMx
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

    ```toml
    vmx-rs = { path = "langs/rust" }
    ```

## Notes

- C# uses `System.Reactive`.
- Python uses `reactivex`.
- TypeScript uses `rxjs`.
- Swift uses `Combine`.
- Rust uses a VMx-owned facade over `rxrust`.
