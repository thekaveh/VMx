# Spec ↔ language compatibility matrix

Maintained by hand alongside spec releases.

## 1. Matrix

| spec  | csharp         | python         | typescript     | swift          |
| ----- | -------------- | -------------- | -------------- | -------------- |
| 2.6.x | 2.6.0          | 2.6.1          | 2.6.0          | 2.6.0 (subset) |
| 2.5.x | 2.5.0          | 2.5.0          | 2.5.0          | 2.5.0 (subset) |
| 2.4.x | 2.4.0          | 2.4.0          | 2.4.0          | 2.4.0 (subset) |
| 2.3.x | 2.3.0          | 2.3.0          | 2.3.0          | —              |
| 2.2.x | 2.2.0          | 2.2.0          | 2.2.0          | —              |
| 2.1.x | 2.1.0          | 2.1.0          | 2.1.0          | —              |
| 2.0.x | 2.0.0          | 2.0.0          | 2.0.0          | —              |
| 1.1.x | 1.1.0 – 1.2.0  | 1.1.0 – 1.2.0  | 1.1.0 – 1.2.0  | —              |
| 1.0.x | 1.0.0          | 1.0.0          | —              | —              |

## 2. Notes

A `—` cell indicates no flavor has released against that spec version. Once a
flavor ships, its cell shows the version range that implements this spec major
(e.g. `1.0.0` or `1.0.0–1.2.x` once minor/patch releases follow).

The Swift flavor's `(subset)` entries cover the lifecycle, leaf
ComponentVM, Composite, Group, Aggregate (arity 1–6), RelayCommand, and
builder areas (41 conformance IDs as of 2.6.0 — recounted honestly in
ADR-0037; +COMP-025/COMP-026 added in 2.6.0 per ADR-0042). Full
conformance parity with the other flavors lands in a follow-up Swift
release; see `langs/swift/README.md` §5 for the in / deferred matrix.

## 3. C# companion packages

The C# core package `VMx` ships with two opt-in companion assemblies. Each
versions independently (per ADR-0009 / ADR-0013) but declares the spec
version it implements.

| Package                                                                                       | Current | Spec |
| --------------------------------------------------------------------------------------------- | ------- | ---- |
| [`VMx.Extensions.DependencyInjection`](https://www.nuget.org/packages/VMx.Extensions.DependencyInjection/) | 2.1.0   | 2.1.x |
| [`VMx.Notifications`](https://www.nuget.org/packages/VMx.Notifications/)                      | 1.2.0   | 2.6.x |
