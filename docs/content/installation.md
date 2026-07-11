# 2. Installation

VMx has five full-parity source flavors. The source tree implements v3.10.0 for
C#, Python, TypeScript, and Swift; Rust declares `MIN_SPEC_VERSION = "3.10.0"`
from crate version 0.10.0. Public package availability can lag the source tree;
check the flavor README and registry before pinning a release.

| Flavor     | Source tree   | Public package status               |
| ---------- | ------------- | ----------------------------------- |
| C#         | v3.10.0       | NuGet package not published yet     |
| Python     | v3.10.0       | `vmx` latest published: 3.1.0       |
| TypeScript | v3.10.0       | npm package not published yet       |
| Swift      | v3.10.0       | SwiftPM tag not published yet       |
| Rust       | 0.10.0        | crates.io package not published yet |

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
    .package(url: "https://github.com/thekaveh/VMx.git", from: "3.1.0")
    ```

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
