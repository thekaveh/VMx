# ADR-0067 — Swift notes-showcase flagship (total parity)

- **Status:** Accepted
- **Date:** 2026-06-30
- **Flavor:** Swift only (example app; no spec change, no library-conformance change)

## 1. Context

Three flavors ship a flagship notes-showcase example app hosting the `THEME-001..005` scenario conformance IDs: C#/Avalonia (`examples/csharp/avalonia/NotesShowcase`), Python/Textual, TypeScript/React. Swift reached full **library** parity (237/237) in Phase 3 (ADRs 0059–0065) but shipped no flagship, so the five `THEME-00x` scenario IDs — which live in the example apps, not the library catalog — remained the only gap before **total** parity. `tools/check-showcase-parity.py` recognized only three flavors.

## 2. Decision

Ship a fourth flagship: a macOS-SwiftUI notes-showcase at `examples/swift/notes-showcase/`, a faithful port of the canonical C#/Avalonia app, built entirely on the now-complete VMx Swift library.

- **SwiftPM package, three targets:** `NotesShowcaseCore` (the VM layer — models, the 11 canonical viewmodels, messages, an `actor`-based `InMemoryNoteRepository`; pure, no SwiftUI, buildable on CommandLineTools), `NotesShowcase` (the `@main` SwiftUI app + views + the Combine→SwiftUI bridge), and `NotesShowcaseTests` (the 11 per-slug XCTest files incl. `ThemeVMTests` with `THEME-001..005`). It depends on the in-repo library via `.package(path: "../../../langs/swift")`.
- **The Combine→SwiftUI binding bridge is net-new** (the library ships no SwiftUI dependency, ADR-0036 "no new core types"): small `ObservableObject` wrappers (`BindableVM`/`BindableCollection`/`BindableCommand`/`BindableDerived`) subscribe the VMs' Combine publishers (`propertyChanged`/`collectionChanged`/`canExecuteChanged`/`DerivedProperty.valueChanged`), delivering on the main run loop and re-emitting `objectWillChange`; a `ThemeAdapter` maps `ThemeModel` → SwiftUI theme tokens. Views use `@StateObject`/`@ObservedObject` + live VM getters.
- **Depends on ADR-0066:** the showcase viewmodels subclass `ComponentVMBase` in their own module and publish hub messages / fire `propertyChanged` — enabled by the cross-module-subclassing visibility widening in ADR-0066.
- **`ThemeVM` THEME-002 shape:** `RelayCommand.execute()` is non-throwing, so the unknown-preset throw is exposed via a `public func applyPreset(_:) throws` (throwing `ThemeError.unknownPreset` without emitting); `setThemeCommand` wraps it (swallowing in the fire-and-forget command path), and the THEME-002 test asserts on `applyPreset` directly. The other THEME IDs drive the commands.
- **Determinism:** the showcase uses `ImmediateDispatcher` + zero repo delays in tests; async VM mutations marshal their emits via `dispatcher.scheduleForeground` (the foreground-scheduler analogue of the C# `_dispatcher.Foreground.Schedule`).
- **Tooling + CI:** `tools/check-showcase-parity.py` gains a `swift` flavor (`<Pascal>Tests.swift` stems, same convention as C#) — now "11 slugs x 4 flavors"; `.github/workflows/swift.yml` gains an `examples (notes-showcase)` job (macos-latest — SwiftUI/Combine are Apple-only) that builds the package and runs the XCTests, plus an `examples/swift/**` path trigger.

## 3. Consequences

- **Swift reaches total parity: 237 library conformance IDs + the 5 `THEME-00x` scenario IDs = 242**, at parity with C#/Python/TypeScript. The Phase-3 Swift parity effort is complete.
- `THEME-001..005` are exercised by `ThemeVMTests.swift` in the flagship; per spec/tool convention they carry no scraped conformance marker (the library coverage gate excludes `THEME`), and are validated behaviorally by the passing `examples` CI job + the showcase-parity file-existence check.
- The example CI runs only on macOS (SwiftUI/Combine), consistent with the library's macos-latest-only policy; `swift test` and the SwiftUI target cannot be built on a CommandLineTools-only host, so they are CI-gated.
- Several latent issues surfaced and were fixed while wiring the flagship (each caught by the `examples` CI job the library-only build could not exercise): the cross-module-subclassing library gap (ADR-0066); a cross-executor `Array` data race in the notes-view delete path; `Task.yield()` being an unreliable drain for nested cooperative-pool chains on CI runners (replaced with real-time `Task.sleep` in tests); and missing hub `PropertyChangedMessage` emits on notebook-tree mutations.

## 4. Alternatives considered

- **Minimal THEME-only example (a standalone `ThemeVM` + 5 tests, no SwiftUI app).** Rejected in favor of a faithful flagship peer to the other three (the maintainer chose the full flagship); the THEME-only path would close the conformance gap but not give Swift a runnable showcase or `check-showcase-parity` recognition.
- **A SwiftUI bridge in the library.** Rejected: ADR-0036 keeps theming/showcase concerns out of the core (`no new core types`); the bridge is an example-app concern and lives in the app target.
