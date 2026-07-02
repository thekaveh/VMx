# Installation

VMx has four source flavors. The source tree implements v3.1.0 for C#,
Python, TypeScript, and Swift. Public package availability can lag the source
tree; check the flavor README and registry before pinning a release.

| Flavor     | Source tree | Public package status           |
| ---------- | ----------- | ------------------------------- |
| C#         | v3.1.0      | NuGet package not published yet |
| Python     | v3.1.0      | `vmx` latest published: 2.6.1   |
| TypeScript | v3.1.0      | npm package not published yet   |
| Swift      | v3.1.0      | SwiftPM tag not published yet   |

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

## Notes

- C# uses `System.Reactive`.
- Python uses `reactivex`.
- TypeScript uses `rxjs`.
- Swift uses `Combine`.
