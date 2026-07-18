# Spec ↔ language compatibility matrix

Updated alongside spec and flavor releases.

## 1. Matrix

| spec  | python          | csharp          | typescript      | swift           | rust          |
| ----- | --------------- | --------------- | --------------- | --------------- | ------------- |
| 3.22.x | 3.22.0[^current] <!-- x-release-please-version --> | 3.22.0[^current] | 3.23.0[^current] | 3.22.0[^swift] | 0.25.0[^rust] |
| 3.21.x | —               | —               | —               | —               | —             |
| 3.20.x[^legacy-semantic-tag-only] | —               | —               | —               | 3.20.0[^swift] | 0.20.0–0.22.0[^rust-source] |
| 3.19.x | —               | —               | —               | —               | 0.19.0[^rust-source] |
| 3.18.x | —               | —               | —               | —               | 0.18.0[^rust-source] |
| 3.17.x | —               | —               | —               | —               | 0.17.0[^rust-source] |
| 3.16.x | —               | —               | —               | —               | 0.16.0[^rust-source] |
| 3.15.x | —               | —               | —               | —               | 0.15.0[^rust-source] |
| 3.14.x | —               | —               | —               | —               | 0.14.0[^rust-source] |
| 3.13.x | —               | —               | —               | —               | 0.13.0[^rust-source] |
| 3.3.x | —               | —               | —               | —               | 0.3.0        |
| 3.2.x | —               | —               | —               | —               | 0.2.0        |
| 3.1.x | 3.1.0           | —               | —               | —               | 0.1.0        |
| 2.6.x | 2.6.1           | 2.6.0           | 2.6.0           | 2.6.0 (subset)  | —             |
| 2.4.x | 2.4.0           | 2.4.0           | 2.4.0           | 2.4.0 (subset)  | —             |
| 2.3.x | 2.3.0           | 2.3.0           | 2.3.0           | —               | —             |
| 2.2.x | 2.2.0           | 2.2.0           | 2.2.0           | —               | —             |
| 2.1.x | 2.1.0           | 2.1.0           | 2.1.0           | —               | —             |
| 2.0.x | 2.0.0           | 2.0.0           | 2.0.0           | —               | —             |
| 1.0.x | 1.0.0           | 1.0.0           | —               | —               | —             |

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
`KeyedServicedObservableCollection`,
`PagedComposition`, collection-changed events, batch updates,
auto-construct), `ExpandableState` + expand/collapse traversal,
`HierarchicalVM` (tree identity, lazy/eager construction, structural
mutation, builder, capability composition), threading contracts
(`ManualScheduler`, `VirtualTimeScheduler`, foreground dispatch, async
selection), `SearchableState` (composite and group contexts),
`AsyncResourceVM` (cancellable latest-wins async acquisition), message hub
semantics, `FormVM` (snapshot/dirty/approve/deny lifecycle), dialog
service (`DialogService` / `NullDialogService`), and the notifications
sub-package (`NotificationHub`, `NotificationVM`, `ConfirmationVM`,
`makeConfirm` bridge) —
**396 of 396 library conformance IDs + 5 `THEME-00x` scenario IDs = 401 total
(Swift UI-backed total parity) as of ADR-0066/ADR-0067 and ADR-0068..ADR-0100** (library IDs: base 44 per
ADR-0037/ADR-0053; +50 leaf-area IDs per ADR-0059; +30 collections IDs per
ADR-0060; +29 hierarchical/threading/expand-collapse IDs per ADR-0061;
+40 forms/commands/hub IDs per ADR-0062; +25 notifications/dialogs IDs per
ADR-0063; +19 composite/group IDs per ADR-0064; +44 v3.1 library IDs per
ADR-0068..ADR-0079; +6 hub-transaction IDs per ADR-0082; +3 dual-channel
notification-helper IDs per ADR-0083; +6 cross-cutting disposal IDs per
ADR-0084; +8 VM-collection move IDs per ADR-0085; +6 imperative-command-requery
IDs per ADR-0086; +6 FormVM reset IDs per ADR-0087; +8 hierarchical batch-attach
IDs per ADR-0088; +8 whole-list replacement IDs per ADR-0089; +7 owned-resource
and public-hub IDs per ADR-0090; +1 inert modeled-assignment ID per ADR-0091;
+1 settled FormVM model-publication ID per ADR-0092;
+1 explicit modeled-component republish ID per ADR-0093;
+4 fixed-source selected-state subscription IDs per ADR-0095;
+8 serviced-collection parity IDs per ADR-0096;
+9 keyed serviced-collection IDs per ADR-0097;
+10 dynamic aggregate-change-stream IDs per ADR-0098;
+7 searchable-source-reactivity IDs per ADR-0099;
+11 async-resource IDs per ADR-0100;
+4 atomic container-ownership IDs per ADR-0107;
+1 canonical forwarding-ownership ID per ADR-0124;
THEME-001..005 covered by the
`examples/swift/notes-showcase/` flagship — ADR-0067). Swift has member-level
parity with C#, Python, and TypeScript. Rust is catalog-complete but retains the
documented source-surface convergence backlog. See `langs/swift/README.md` §5
and `docs/maintenance/2026-07-16-rust-capability-parity.md`.

[^current]: C# and Python are on the 3.22.0 in-development source line.
TypeScript 3.23.0 implements spec 3.22.0. Python's latest PyPI release remains
3.1.0; C# and TypeScript public
packages remain pending. Their release jobs refuse to green-skip a publish
without configured credentials.

[^swift]: Swift 3.22.0 is the current source line. Swift 3.20.0 remains publicly
installable from the repository root through
the immutable `v3.20.0` semantic tag. The matching `swift-v3.20.0` operational
tag and [GitHub Release](https://github.com/thekaveh/VMx/releases/tag/swift-v3.20.0)
point to the same `main` commit.

[^rust]: Rust is a source-tree, catalog-complete flavor promoted by ADR-0081. It
is at source version 0.25.0, declares `MIN_SPEC_VERSION = "3.22.0"`, and carries
behavioral tests for all 396 library conformance IDs. Residual member and edge-
behavior convergence is tracked in
`docs/maintenance/2026-07-16-rust-capability-parity.md`; it has not yet been
published to crates.io.

[^rust-source]: Rust `0.13.0`, `0.14.0`, `0.15.0`, `0.16.0`, `0.17.0`,
`0.18.0`, and `0.19.0` record historical source-tree parity for spec 3.13.x
through 3.19.x.
They were not published to crates.io and do not imply
corresponding `rust-v*` tags or releases.

The same source-only history applies to Rust `0.20.0` through `0.22.0` for
spec 3.20.x. The untagged C# `3.20.0–3.20.1`, Python `3.20.0–3.20.1`,
TypeScript `3.20.0–3.21.1`, and Swift `3.20.1` source lines are intentionally
not listed as releases in the matrix.

[^legacy-semantic-tag-only]: Spec 3.20.0 predates the duplicate operational
`spec-v*` tag convention. Its immutable `v3.20.0` semantic tag is the release
tag; no `spec-v3.20.0` tag was created.

## 3. C# companion packages

The C# core package `VMx` ships with two opt-in companion assemblies. Each
versions independently (per ADR-0009 / ADR-0013) but declares the spec
version it implements.

| Package                                | Current | Spec  |
| -------------------------------------- | ------- | ----- |
| `VMx.Extensions.DependencyInjection`   | 2.1.1   | 2.1.x |
| `VMx.Notifications`                    | 1.2.0   | 2.6.x |

> **Note:** These names become registry links only after their first NuGet
> publication. Companion packages (`VMx.Notifications`, `VMx.Extensions.DependencyInjection`) version
> independently from `VMx` core, starting from 1.0.0 (per ADR-0013). The `1.2.0` shown above is not
> a divergence from the spec — it is the companion package's own version counter. The **Spec**
> column is the spec revision each companion's own feature surface implements; it is not the core
> dependency floor. As built at HEAD both companions reference the `VMx` 3.22.0 core project and
> pack with a `VMx >= 3.22.0` NuGet dependency. The DI companion uses packaging-only patch 2.1.1
> because the historical core tag `csharp-v2.1.0` is immutable. Future companion releases use
> package-specific `csharp-notifications-v*` and `csharp-dependency-injection-v*` tags, preventing
> that legacy cross-package collision; the already-advanced DI version is not rewound. These source
> versions do not claim that the packages have been published.
