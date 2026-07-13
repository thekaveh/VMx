# SwiftPM Release Channel Design

## 1. Context

VMx Swift 3.20.0 is a complete SwiftPM package under `langs/swift`, but the
public repository root has no `Package.swift`. SwiftPM resolves a remote package
from the tagged repository root, so consumers cannot use the documented
`https://github.com/thekaveh/VMx.git` URL. The operational `swift-v*` tags that
trigger the release workflow are also not semantic-version tags that SwiftPM
can select.

Issue #58 corrects distribution only. It does not change VMx behavior, the
language-neutral specification, conformance IDs, or supported platform floors.

## 2. Decision

### 2.1 Root facade manifest

Add a root `Package.swift` with the same package name, product, tools version,
platform floors, targets, dependencies, and resource rules as
`langs/swift/Package.swift`. Its only intentional difference is that target
paths are rooted at `langs/swift/`:

- library target: `langs/swift/Sources/VMx`
- test target: `langs/swift/Tests/VMxTests`
- processed resources: `Resources` relative to the library target

The facade references the existing source and resource files. It does not copy,
wrap, or re-export the VMx module.

### 2.2 Structural parity gate

Add `tools/check-swift-package-sync.py`. It runs
`swift package dump-package` for the root and nested packages, normalizes only
the expected `langs/swift/` path prefix, and compares the complete dumped
package structures. Any product, target, dependency, platform, tools-version,
or resource-rule drift fails with an actionable diff.

The checker runs in Swift CI and the Swift release job before either manifest is
built. Unit tests cover equal manifests after path normalization and meaningful
drift diagnostics.

### 2.3 Immutable dual-tag release

The first operational release is Swift 3.20.0, matching
`VMxVersion.current`. Two immutable tags must be created atomically on the same
verified `main` commit:

- `v3.20.0`: semantic-version tag resolved by SwiftPM
- `swift-v3.20.0`: operational tag that triggers the Swift release job and owns
  the GitHub Release

The release job fetches `v3.20.0`, requires it to exist at `GITHUB_SHA`, checks
that both tags match `VMxVersion.current`, and refuses to create a release on a
tag mismatch or non-main commit. Existing tags, especially `v3.1.0`, are never
moved or reused.

### 2.4 Release verification flow

The Swift release job performs these gates in order:

1. Verify the operational tag commit is reachable from `origin/main`.
1. Verify `vX.Y.Z` exists at the same commit as `swift-vX.Y.Z`.
1. Run the manifest parity checker.
1. Release-build and test both the root and nested packages on full Xcode.
1. Confirm all four JSON fixtures exist in each package's built resource bundle.
1. Clone/resolve the public repository from a completely fresh temporary Swift
   package using `.package(url: ..., from: "X.Y.Z")`.
1. Build and run a consumer executable that imports `VMx`, checks
   `VMxVersion.current`, and completes construct/destruct/dispose. This lifecycle
   round trip loads the bundled lifecycle transition fixture.
1. Create `Swift vX.Y.Z (SwiftPM)` from the matching Swift changelog section.

The GitHub Release is created only after the public remote-consumer smoke test
passes.

## 3. Documentation and publication phases

The preparation PR documents the future tag procedure and keeps public status
truthful until the tag exists. After the preparation changes reach `main`, push
the two tags together, wait for the release workflow, and verify the public URL
from a second clean consumer.

Only after that evidence exists, a ticket-scoped documentation PR changes the
README, Swift README/runbook, compatibility matrix, canonical installation and
Swift pages, generated `.io` site, and wiki from “source only” to “released
3.20.0.” The three generated surfaces continue to derive from canonical docs.

## 4. Failure handling

- A missing or mismatched semantic tag stops before build or release creation.
- Manifest drift prints the normalized structural difference and stops CI.
- A root or nested build/test/resource failure stops before remote resolution.
- A public clone, dependency resolution, lifecycle, or version failure stops
  before release creation.
- Tags are immutable. Any defect after publication is corrected with a new
  patch version; no published tag is moved.
- Local Command Line Tools can build Swift but cannot import XCTest in this
  environment. Full tests remain mandatory in macOS CI and are never reported
  as locally passing when XCTest is unavailable.

## 5. Rejected alternatives

### 5.1 Symlink or generate one manifest from the other

Rejected. The two package roots require different target paths, SwiftPM does
not provide a supported local manifest-inclusion mechanism, and a symlink makes
relative-path interpretation dependent on checkout behavior. A structural dump
comparison gives deterministic drift protection without hidden generation.

### 5.2 Wrapper target at repository root

Rejected. Swift packages cannot re-export a dependency product as the same VMx
module without adding wrapper source or changing consumer imports. The facade
must expose the real target directly.

### 5.3 Dedicated Swift release repository

Rejected for this milestone. It would require cross-repository source/resource
synchronization and separate credentials while providing no API benefit over a
root facade.

## 6. Acceptance evidence

Completion requires:

- root and nested manifest dumps compare equal after path normalization;
- both packages release-build, and full Xcode tests pass in CI;
- all four bundled fixtures are present;
- `v3.20.0` and `swift-v3.20.0` resolve to one verified main commit;
- the GitHub Release exists at `swift-v3.20.0`;
- a clean public consumer imports VMx and completes the lifecycle smoke test;
- repo docs, `.io`, and wiki show the verified URL, version, platforms, and tag
  model with no stale “not published” claim.
