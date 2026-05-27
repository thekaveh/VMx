# Spec ↔ language compatibility matrix

Maintained by hand alongside spec releases.

## 1. Matrix

| spec  | csharp         | python         | typescript     |
| ----- | -------------- | -------------- | -------------- |
| 2.0.x | 2.0.0          | 2.0.0          | 2.0.0          |
| 1.1.x | 1.1.0 – 1.2.0  | 1.1.0 – 1.2.0  | 1.1.0 – 1.2.0  |
| 1.0.x | 1.0.0          | 1.0.0          | —              |

## 2. Notes

A `—` cell indicates no flavor has released against that spec version. Once a
flavor ships, its cell shows the version range that implements this spec major
(e.g. `1.0.0` or `1.0.0–1.2.x` once minor/patch releases follow).

## 3. C# companion packages

The C# core package `VMx` ships with two opt-in companion assemblies. Each
versions independently (per ADR-0009 / ADR-0013) but declares the spec
version it implements.

| Package                                                                                       | Current | Spec |
| --------------------------------------------------------------------------------------------- | ------- | ---- |
| [`VMx.Extensions.DependencyInjection`](https://www.nuget.org/packages/VMx.Extensions.DependencyInjection/) | 2.0.0   | 2.0.x |
| [`VMx.Notifications`](https://www.nuget.org/packages/VMx.Notifications/)                      | 1.0.0   | 2.0.x |
