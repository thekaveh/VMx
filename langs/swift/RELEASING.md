# Releasing the `VMx` Swift package

This runbook documents Swift flavor releases. SwiftPM consumes VMx directly from
git tags; there is no NuGet/PyPI/npm-style central registry publish step.

The repository-root `Package.swift` is the public SwiftPM entry point. It
references the existing sources, tests, and resources under `langs/swift`; it
does not copy them. `tools/check-swift-package-sync.py` compares SwiftPM's
evaluated root and nested package structures so either manifest cannot drift.

The release pipeline is **manual dual-tag driven**. SwiftPM resolves the
semantic `v<X.Y.Z>` tag, while `swift-v<X.Y.Z>` triggers
`.github/workflows/release.yml` and owns the GitHub Release. Both immutable tags
must be pushed together at the same verified `main` commit.

## 1. Prerequisites

- Full Xcode is available in CI (`macos-latest`) so root and nested
  `swift test --parallel` runs can load XCTest. Local Command Line Tools are
  enough for `swift build`, but not always for `swift test`.
- `VMxVersion.current` and `VMxVersion.minSpecVersion` in
  `Sources/VMx/Version.swift` match the intended release.
- `langs/swift/CHANGELOG.md` has the complete release entry. The README,
  compatibility matrix, site, and wiki must remain truthful about source-only
  status until the public tag and clean-consumer checks succeed.
- The release version has never been tagged. Never move or reuse an existing
  `v*` or `swift-v*` tag.

## 2. Cutting a Release

1. Land all intended changes on `main` through the normal develop-to-main PR
   flow. Confirm `origin/main` and `origin/develop` are content-identical.
2. Confirm manifest parity and the declared version:

   ```bash
   python3 tools/check-swift-package-sync.py
   sed -nE 's/^[[:space:]]*public static let current = "([^"]+)".*/\1/p' \
     langs/swift/Sources/VMx/Version.swift
   ```

3. Fetch the verified main commit and create both tags without checking out or
   modifying the primary workspace:

   ```bash
   git fetch --prune origin main
   release_sha="$(git rev-parse origin/main)"
   git tag vX.Y.Z "$release_sha"
   git tag swift-vX.Y.Z "$release_sha"
   git push --atomic origin vX.Y.Z swift-vX.Y.Z
   ```

4. Watch <https://github.com/thekaveh/VMx/actions?query=workflow%3Arelease>.
   Do not update publication-status docs or close the issue until this run and
   an independent clean-consumer verification both pass.

## 3. What the Pipeline Does

1. Verifies the operational tag commit is reachable from `origin/main`.
2. Fetches `v<X.Y.Z>` and requires it to point at the same commit as
   `swift-v<X.Y.Z>`.
3. Requires both tag versions to equal `VMxVersion.current`.
4. Compares the evaluated root and nested manifests.
5. Release-builds and tests both package roots on full Xcode. These tests load
   all four bundled conformance fixtures.
6. Creates a completely fresh package using
   `.package(url: "https://github.com/thekaveh/VMx.git", from: "X.Y.Z")`.
   It builds from the public URL, verifies all four JSON files are in the built
   resource bundle, imports VMx, checks the resolved version, and executes a
   construct/destruct/dispose lifecycle round trip.
7. Extracts the matching Swift changelog section and creates a GitHub Release
   titled `Swift v<X.Y.Z> (SwiftPM)` only after every earlier gate passes.

## 4. Verifying a Release

Run a second clean consumer independently of the release workflow:

```bash
python3 tools/smoke-swiftpm-consumer.py \
  --url https://github.com/thekaveh/VMx.git \
  --version X.Y.Z
git ls-remote --tags origin refs/tags/vX.Y.Z refs/tags/swift-vX.Y.Z
gh release view swift-vX.Y.Z
```

Then update the README, Swift README, compatibility matrix, canonical
installation/Swift docs, `.io` site, and wiki with the verified version and
working dependency form through a second feature-to-develop-to-main PR pair.

## 5. Failure Modes

- **Either tag exists:** stop. Never move, delete, or reuse it as a different
  release. If the existing tags do not already represent a verified release,
  fix on `main` and cut a new patch version.
- **Tag is not on main or tags differ:** the release job fails before build.
  Fix on `main`, bump the patch version, and create a new pair.
- **Manifest parity, build, test, resource, or public-consumer failure:** fix on
  a ticket branch, promote through develop and main, bump the patch version, and
  cut a new immutable pair.
- **GitHub Release creation failed after every verification passed:** inspect
  the Actions log and repository permissions. Do not move either tag; retry the
  release creation only for the same verified commit and notes.
