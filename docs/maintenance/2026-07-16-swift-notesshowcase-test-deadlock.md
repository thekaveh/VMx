# 2026-07 Swift NotesShowcase Test Deadlock

Filed: **2026-07-16**. The Swift flagship example test suite
(`examples/swift/notes-showcase`, CI job `examples (notes-showcase)` in
`.github/workflows/swift.yml`) deadlocks at XCTest process startup. This is a
pre-existing defect on `develop`, not a regression from the maintenance run that
filed it; it requires a focused fix with a local Swift toolchain.

## 1. Symptom

On the `swift` workflow's `examples (notes-showcase)` job the test target builds
successfully and then hangs indefinitely with no test output:

```
[19/20] Linking NotesShowcasePackageTests
Build complete! (11.71s)
##[error]The operation was canceled.        <- 6 hours later
Terminate orphan process: pid (…) (xctest)
```

The `xctest` process spawns but never prints even the `Test Suite 'All tests' started` banner, so the deadlock is at process startup — before the first test
case runs — consistent with a static/global initializer or a main-thread
synchronization deadlock in the test bundle, not a slow or failing assertion.

## 2. Timeline

- `2026-07-13`: the job passed in ~78 seconds.
- `2026-07-16`: the job began hanging for the full 6-hour job limit and was
  cancelled by timeout. This coincides with the previous maintenance run landing
  on `develop`; the hang has persisted there since.

## 3. Scope

The VMx Swift library's own test suite (`langs/swift`, run by the `build & test`
jobs via `swift test --parallel`) passes, so the deadlock is specific to the
example test target's load/startup path, which links the library plus the
example's own view-model and test code. The example test target references the
CRUD/command surface (`Sources/NotesShowcaseCore/ViewModels/NoteVM.swift`,
`Tests/NotesShowcaseTests/NoteVMTests.swift`,
`Tests/NotesShowcaseTests/CapabilityActionsVMTests.swift`).

## 4. Mitigation applied

`.github/workflows/swift.yml` now sets `timeout-minutes: 30` on the Swift jobs so
a future recurrence fails fast (minutes) instead of consuming a 6-hour runner
slot. This does not fix the deadlock; it bounds its blast radius.

## 5. Proposed investigation

The deadlock is only reproducible under XCTest (it needs a full Xcode toolchain
with the license accepted; `swift build` alone does not run it). Reproduce
`swift test` locally on the example package, attach with a debugger at the hang,
and inspect the main-thread and actor state at startup. Likely candidates: a
`@MainActor`-isolated global or `static let` in the test target, or a
`DispatchQueue.main.sync` reached during test-bundle load while XCTest holds the
main thread. Bisecting the example against the `2026-07-13` passing state narrows
the introducing change.
