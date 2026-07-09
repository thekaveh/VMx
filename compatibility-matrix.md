# Spec ↔ language compatibility matrix

Maintained by hand alongside spec releases.

## 1. Matrix

| spec  | csharp          | python          | typescript      | swift           | rust                 |
| ----- | --------------- | --------------- | --------------- | --------------- | -------------------- |
| 3.1.x | 3.1.0[^current] | 3.1.0[^current] | 3.1.0[^current] | 3.1.0[^current] | 0.1.0-preview[^rust] |
| 2.6.x | 2.6.0           | 2.6.1           | 2.6.0           | 2.6.0 (subset)  | —                    |
| 2.4.x | 2.4.0           | 2.4.0           | 2.4.0           | 2.4.0 (subset)  | —                    |
| 2.3.x | 2.3.0           | 2.3.0           | 2.3.0           | —               | —                    |
| 2.2.x | 2.2.0           | 2.2.0           | 2.2.0           | —               | —                    |
| 2.1.x | 2.1.0           | 2.1.0           | 2.1.0           | —               | —                    |
| 2.0.x | 2.0.0           | 2.0.0           | 2.0.0           | —               | —                    |
| 1.0.x | 1.0.0           | 1.0.0           | —               | —               | —                    |

## 2. Notes

A `—` cell indicates no flavor has released against that spec version. Once a
flavor ships, its cell shows the version range that implements this spec major
(e.g. `1.0.0` or `1.0.0–1.2.x` once minor/patch releases follow).

The Swift flavor covers the lifecycle, leaf ComponentVM, Composite
(`CompositeVMOf`), Group, Aggregate (arity 1–6), RelayCommand,
`RelayCommandOf<T>`, `AsyncRelayCommand`, `CompositeCommand`,
`DecoratorCommand`, `ConfirmationDecoratorCommand`, `ModeledCrudCommands`,
fluent command helpers, builders, hub property accessors, null objects,
localization, tree utilities, forwarding decorators, `DerivedProperty<T>`,
the 22 capability micro-interfaces, observable collections
(`ObservableList`, `ObservableDictionary`, `ServicedObservableCollection`,
`PagedComposition`, collection-changed events, batch updates,
auto-construct), `ExpandableState` + expand/collapse traversal,
`HierarchicalVM` (tree identity, lazy/eager construction, structural
mutation, builder, capability composition), threading contracts
(`ManualScheduler`, `VirtualTimeScheduler`, foreground dispatch, async
selection), `SearchableState` (composite and group contexts), message hub
semantics, `FormVM` (snapshot/dirty/approve/deny lifecycle), dialog
service (`DialogService` / `NullDialogService`), and the notifications
sub-package (`NotificationHub`, `NotificationVM`, `ConfirmationVM`,
`makeConfirm` bridge) —
**281 of 281 library conformance IDs + 5 `THEME-00x` scenario IDs = 286 total
(total parity) as of ADR-0066/ADR-0067 and ADR-0068..ADR-0079** (library IDs: base 44 per
ADR-0037/ADR-0053; +50 leaf-area IDs per ADR-0059; +30 collections IDs per
ADR-0060; +29 hierarchical/threading/expand-collapse IDs per ADR-0061;
+40 forms/commands/hub IDs per ADR-0062; +25 notifications/dialogs IDs per
ADR-0063; +19 composite/group IDs per ADR-0064; +44 v3.1 library IDs per
ADR-0068..ADR-0079; THEME-001..005 covered by the
`examples/swift/notes-showcase/` flagship — ADR-0067). Swift is at full parity
with C#, Python, and TypeScript. See `langs/swift/README.md` §5.

[^current]: 3.1.0 — current development line. `spec-v3.1.0`, `v3.1.0`, and
`python-v3.1.0` are tagged, and `vmx` 3.1.0 is published on PyPI. The
`csharp-v3.1.0`, `typescript-v3.1.0`, and `swift-v3.1.0` tags are not yet
created: C#/TypeScript/Swift 3.1.0 live in source and publish once their
registry credentials are configured (the C#/TS release jobs deliberately
refuse to green-skip a publish without `NUGET_API_KEY` / `NPM_TOKEN`).

[^rust]: Rust is a source-tree preview flavor introduced by ADR-0080. It
declares `MIN_SPEC_VERSION = "3.1.0"` and carries 281 conformance catalog
markers, but its behavioral assertions are still being expanded before it
is advertised as stable full parity or published to crates.io.

## 3. C# companion packages

The C# core package `VMx` ships with two opt-in companion assemblies. Each
versions independently (per ADR-0009 / ADR-0013) but declares the spec
version it implements.

| Package                                                                                                    | Current | Spec  |
| ---------------------------------------------------------------------------------------------------------- | ------- | ----- |
| [`VMx.Extensions.DependencyInjection`](https://www.nuget.org/packages/VMx.Extensions.DependencyInjection/) | 2.1.0   | 2.1.x |
| [`VMx.Notifications`](https://www.nuget.org/packages/VMx.Notifications/)                                   | 1.2.0   | 2.6.x |

> **Note:** Companion packages (`VMx.Notifications`, `VMx.Extensions.DependencyInjection`) version
> independently from `VMx` core, starting from 1.0.0 (per ADR-0013). The `1.2.0` shown above is not
> a divergence from the spec — it is the companion package's own version counter. The **Spec**
> column is the spec revision each companion's own feature surface implements; it is not the core
> dependency floor. As built at HEAD both companions reference the `VMx` 3.1.0 core project, so a
> published companion would carry a `VMx >= 3.1.0` NuGet dependency — the raised floor to record in
> the C# `CHANGELOG.md` when the first C# packages are cut.
