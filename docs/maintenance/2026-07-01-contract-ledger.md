# 2026-07-01 Maintenance Contract Ledger

This ledger records external dependency and tool contracts checked during the
maintenance run on `maintenance`. It is not a release note; update it when a
pinned tool, package-manager contract, or workflow integration changes.

## 1. Scope

The run checked package-manager, CI, and example-app contracts that VMx consumes
directly: NuGet restore/lock behavior, npm lockfiles and publish flags, SwiftPM
build/test entry points, uv-based Python tooling, and GitHub Actions release
steps. No live registry publish was performed.

## 2. Verified Contracts

| Area                       | Pin source                                                                  | Contract checked                                                                                                                                                                                                               | Evidence                                                                                |
| -------------------------- | --------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------- |
| TypeScript package build   | `langs/typescript/package-lock.json`; `package.json` override for `esbuild` | Node floor remains `>=20`; `esbuild` resolves to `0.28.1`; package still builds dual ESM/CJS and audits cleanly.                                                                                                               | `npm run build`; `npm audit --package-lock-only --audit-level=low`                      |
| TypeScript console example | `examples/typescript/console/hello-vmx/package-lock.json`                   | Local `file:../../../../langs/typescript` dependency resolves as `@thekaveh/vmx` `3.1.0`; runtime uses local `tsx`; required `rxjs` is installed.                                                                              | `npm ci`; `npm run typecheck`; `npm start`                                              |
| TypeScript React example   | `examples/typescript/react/notes-showcase/package-lock.json`                | React/Vite test stack remains lockfile-backed and compatible with the local VMx package.                                                                                                                                       | `npm audit --package-lock-only --audit-level=moderate`; `npm run typecheck`; `npm test` |
| C# Avalonia example        | `examples/csharp/avalonia/**/packages.lock.json`                            | Avalonia packages resolve to `11.3.18`; test stack resolves to `Microsoft.NET.Test.Sdk` `17.14.1`, `xunit` `2.9.3`, `xunit.runner.visualstudio` `2.8.2`, `coverlet.msbuild` `6.0.4`, and `Microsoft.Reactive.Testing` `6.1.0`. | `dotnet restore --locked-mode`; `dotnet build`; `dotnet test`                           |
| C# WPF example             | `examples/csharp/wpf/TodoApp/WpfTodoApp.csproj`                             | Non-Windows builds compile as a library without WPF app entry points; Windows keeps `WinExe` behavior.                                                                                                                         | `dotnet build examples/csharp/wpf/TodoApp/WpfTodoApp.csproj`                            |
| Python tooling             | `.github/workflows/python.yml`; `langs/python/pyproject.toml`               | CI uses `astral-sh/setup-uv` pinned to commit `caf0cab7a618c569241d31dcd442f54681755d39`; local commands match uv project invocation.                                                                                          | `uv run pytest`; `uv run ruff check`; `uv run mypy --strict src/vmx`                    |
| SwiftPM                    | `langs/swift/Package.swift`; `examples/swift/notes-showcase/Package.swift`  | Library resources and example targets build with SwiftPM; XCTest remains a full-Xcode/CI-only local limitation when CommandLineTools lacks `XCTest`.                                                                           | `swift build` in both packages                                                          |
| GitHub release workflows   | `.github/workflows/release.yml`                                             | C# and TypeScript release jobs verify tag/package version agreement; npm publish uses `--provenance`; Swift release runs `swift build && swift test --parallel` before creating the release.                                   | Static workflow trace plus local command validation where available                     |

## 3. Open Follow-Up

Actions pinned only by moving major tags, such as `actions/checkout@v4` and
`actions/setup-node@v4`, are accepted as the repository's current GitHub Actions
policy. Tightening every action to a commit SHA would be a separate supply-chain
hardening change and should be reviewed as its own PR.
