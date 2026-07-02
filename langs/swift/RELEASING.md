# Releasing the `VMx` Swift package

This runbook documents Swift flavor releases. SwiftPM consumes VMx directly from
git tags; there is no NuGet/PyPI/npm-style central registry publish step.

The release pipeline is **manual tag-driven**: push a `swift-v<X.Y.Z>` tag on
`main` and `.github/workflows/release.yml` builds, tests, verifies the declared
version, and creates a GitHub Release for SwiftPM consumers.

## 1. Prerequisites

- Full Xcode is available in CI (`macos-latest`) so `swift test` can load
  XCTest. Local Command Line Tools are enough for `swift build`, but not always
  for `swift test`.
- `VMxVersion.current` and `VMxVersion.minSpecVersion` in
  `Sources/VMx/Version.swift` match the intended release.
- `langs/swift/CHANGELOG.md`, `compatibility-matrix.md`, and the root README
  have the release entry and parity counts.

## 2. Cutting a Release

1. Land all intended changes on `main`.
2. Confirm the version:

   ```bash
   sed -nE 's/^[[:space:]]*public static let current = "([^"]+)".*/\1/p' \
     langs/swift/Sources/VMx/Version.swift
   ```

3. Tag and push from an up-to-date `main`:

   ```bash
   git checkout main
   git pull --ff-only origin main
   git tag swift-vX.Y.Z
   git push origin swift-vX.Y.Z
   ```

4. Watch <https://github.com/thekaveh/VMx/actions?query=workflow%3Arelease>.

## 3. What the Pipeline Does

1. Verifies the tag commit is reachable from `origin/main`.
2. Runs `swift build && swift test --parallel` in `langs/swift`.
3. Verifies `swift-v<X.Y.Z>` matches `VMxVersion.current`.
4. Creates a GitHub Release titled `Swift v<X.Y.Z> (SwiftPM)`.

## 4. Verifying a Release

```bash
mkdir /tmp/vmx-swift-verify && cd /tmp/vmx-swift-verify
swift package init --type executable
# Edit Package.swift to add:
# .package(url: "https://github.com/thekaveh/VMx", from: "X.Y.Z")
swift build
gh release view swift-vX.Y.Z
```

## 5. Failure Modes

- **Tag is not on main:** delete the tag locally and remotely, update `main`,
  recreate it on the intended commit, then push again.
- **`swift test` failed:** fix the failure on `main` and cut a new patch tag.
- **Version mismatch:** update `VMxVersion.current`, changelog, and matrix on
  `main`; then recreate the tag.
