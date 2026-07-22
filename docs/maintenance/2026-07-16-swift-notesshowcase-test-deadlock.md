# 2026-07 Swift NotesShowcase Test Deadlock

Filed: **2026-07-16**; fix implemented: **2026-07-18**; CI verification pending.
The Swift flagship example
test suite (`examples/swift/notes-showcase`, CI job `examples (notes-showcase)` in `.github/workflows/swift.yml`) deadlocked because three
awaited commands also awaited notification resolution. The maintenance run
identified the command-completion defect and implemented its correction. A
fresh green CI example-test run is still required before this record can call
the incident resolved.

## 1. Symptom

On the `swift` workflow's `examples (notes-showcase)` job the test target builds
successfully and then hangs indefinitely with no test output:

```
[19/20] Linking NotesShowcasePackageTests
Build complete! (11.71s)
##[error]The operation was canceled.        <- 6 hours later
Terminate orphan process: pid (…) (xctest)
```

The `xctest` process spawned but never flushed a test banner before the first
awaited command suspended. That initially resembled a startup deadlock, but the
source-history comparison and command semantics identified a later test-body
suspension whose output remained buffered.

## 2. Timeline

- `2026-07-13`: the job passed in ~78 seconds.
- `2026-07-16`: the job began hanging for the full 6-hour job limit and was
  cancelled by timeout. This coincides with the previous maintenance run landing
  on `develop`; the hang persisted until the notification-await fix.

## 3. Scope

The prior VMx Swift library CI suite passed while the example job hung, so the
defect is specific to an awaited command in the example's test body rather than
package loading or test startup. The example test target exercises the
CRUD/command surface (`Sources/NotesShowcaseCore/ViewModels/NoteVM.swift`,
`Tests/NotesShowcaseTests/NoteVMTests.swift`,
`Tests/NotesShowcaseTests/CapabilityActionsVMTests.swift`).

## 4. Resolution

`NoteFormVM.approveAsync`, `NoteVM._performDelete`, and
`NotebooksRootVM._performAdd` had begun awaiting `NotificationHub.post`.
`post` intentionally suspends until the user resolves the notification, so the
originating save/delete/add command never completed while its toast remained
visible. Publication now uses a strict-concurrency-safe, non-blocking helper.
The existing awaited command tests are direct regression coverage: each
previously suspended before its assertion.

The workflow retains its 30-minute job bound and now runs the example tests with
`--parallel`, which prints per-case execution and makes any future hang
attributable in the logs. A complete strict-concurrency release build passes
locally. Full XCTest execution still requires an accepted local Xcode license;
CI supplies the authoritative runtime verification.

## 5. Investigation Evidence

The last successful run preceded commit `b0f8619f` (`serialize flagship UI mutations`). That change replaced fire-and-forget notification publication with
three direct awaits. GitHub logs show the test binary linked successfully and
then remained alive until timeout, consistent with the first awaited command
waiting for a notification reaction that a headless test never supplies.
