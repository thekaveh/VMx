# spec/ADRs/

Architecture Decision Records (ADRs) for the VMx spec. Each ADR is a small,
self-contained markdown file numbered `NNNN-kebab-title.md`.

ADRs capture the *why* behind every normative spec change. Per the spec
discipline rule (CONTRIBUTING §3), any modification to a `spec/NN-*.md`
chapter requires a new ADR in the same PR. Exempt paths — `spec/README.md`,
`spec/VERSION`, `spec/ADRs/**`, `spec/fixtures/**`, `spec/proposals/**`, and
`spec/12-conformance.md` — are enforced by
`.github/workflows/spec-discipline.yml`; typo-only chapter changes can be
waived by a maintainer via the `no-adr-needed` label.

## 1. Index

ADRs are sorted by number (chronological by acceptance), not by importance —
later ADRs build on earlier ones. For a topical overview, follow the
cross-references each ADR carries.

| #                                                                | Title                                                                                                | Spec version | Status                            |
| ---------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- | ------------ | --------------------------------- |
| [0001](0001-drop-comscore.md)                                    | Drop comScore baggage from v1                                                                        | 1.0.0        | Accepted                          |
| [0002](0002-rx-as-reactive-primitive.md)                         | Rx as the reactive primitive                                                                         | 1.0.0        | Accepted                          |
| [0003](0003-constructor-injection.md)                            | Constructor injection for services                                                                   | 1.0.0        | Accepted                          |
| [0004](0004-langs-folder-layout.md)                              | `langs/<flavor>/` folder layout                                                                      | 1.0.0        | Accepted                          |
| [0005](0005-drop-virtualization-from-core.md)                    | Virtualization is out of scope                                                                       | 1.0.0        | Accepted                          |
| [0006](0006-idiomatic-api-per-language.md)                       | Idiomatic per-language surface                                                                       | 1.0.0        | Accepted                          |
| [0007](0007-aggregate-vm-arity-1-to-5.md)                        | `AggregateVM` arities 1–5                                                                            | 1.0.0        | Accepted (§4 superseded by 0034)  |
| [0008](0008-async-lifecycle-methods.md)                          | Async lifecycle methods                                                                              | 1.1.0        | Accepted                          |
| [0009](0009-cross-flavor-divergence-catalogue.md)                | Cross-flavor divergence catalogue                                                                    | 1.1.0        | Accepted                          |
| [0010](0010-capability-micro-interfaces.md)                      | 20 capability micro-interfaces                                                                       | 2.0.0        | Accepted                          |
| [0011](0011-derived-properties.md)                               | N-source derived properties                                                                          | 2.0.0        | Accepted                          |
| [0012](0012-command-decorators.md)                               | Command decorators (Confirmation, Logging)                                                           | 2.0.0        | Accepted                          |
| [0013](0013-notification-service.md)                             | Opt-in `VMx.Notifications` sub-package                                                               | 2.0.0        | Accepted                          |
| [0014](0014-search-and-filter.md)                                | `SearchableState` helper                                                                             | 2.0.0        | Accepted                          |
| [0015](0015-expand-collapse-state.md)                            | `ExpandableState` helper                                                                             | 2.0.0        | Accepted                          |
| [0016](0016-modeled-crud-commands.md)                            | `ModeledCrudCommands<M, VM>` helper                                                                  | 2.0.0        | Accepted                          |
| [0017](0017-null-object-services.md)                             | Null-object service convention                                                                       | 2.0.0        | Accepted                          |
| [0018](0018-flat-vm-hierarchy-vs-old-chain.md)                   | Flat VM hierarchy vs the 2012 chain                                                                  | 2.0.0        | Accepted                          |
| [0019](0019-localization-hooks.md)                               | `ILocalizer` hook + `NullLocalizer`                                                                  | 2.0.0        | Accepted                          |
| [0020](0020-v2.0-spec-text-refresh.md)                           | Spec text refresh for v2.0                                                                           | 2.0.0        | Accepted                          |
| [0021](0021-post-v2.0-editorial-polish.md)                       | Post-v2.0 editorial polish                                                                           | 2.0.0        | Accepted                          |
| [0022](0022-filterable-capability.md)                            | `IFilterable<T>` capability                                                                          | 2.1.0        | Accepted                          |
| [0023](0023-paging-capability-and-paged-composition.md)          | Paging (`IPageable` + `PagedComposition`)                                                            | 2.1.0        | Accepted                          |
| [0024](0024-hub-aware-observable-collection.md)                  | `ServicedObservableCollection<T>`                                                                    | 2.1.0        | Accepted                          |
| [0025](0025-multi-key-observable-dictionary.md)                  | `ObservableDictionary` (multi-key)                                                                   | 2.1.0        | Accepted                          |
| [0026](0026-granular-observable-list.md)                         | `ObservableList<T>` granular events                                                                  | 2.1.0        | Accepted                          |
| [0027](0027-fluent-command-extensions.md)                        | Fluent command extension methods                                                                     | 2.1.0        | Accepted                          |
| [0028](0028-hierarchical-vm.md)                                  | `HierarchicalVM` (recursive composite)                                                               | 2.1.0        | Accepted                          |
| [0029](0029-dialog-service-in-core.md)                           | `IDialogService` in core                                                                             | 2.1.0        | Accepted                          |
| [0030](0030-form-vm.md)                                          | `FormVM<TM>` (snapshot/revert lifecycle)                                                             | 2.1.0        | Accepted                          |
| [0031](0031-notification-rendering-vms.md)                       | Notification rendering VMs                                                                           | 2.1.0        | Accepted                          |
| [0032](0032-property-value-changed-messages.md)                  | `PropertyValueChangedMessages` helper (informative)                                                  | 2.1.0        | Accepted                          |
| [0033](0033-linq-utility-helpers-csharp-only.md)                 | LINQ utility helpers (C# only)                                                                       | 2.1.0        | Accepted                          |
| [0034](0034-aggregate-vm6.md)                                    | Extend `AggregateVM` arity to 6                                                                      | 2.2.0        | Accepted                          |
| [0035](0035-builder-audit-followthrough.md)                      | Builder pattern audit follow-through (v2.3.0)                                                        | 2.3.0        | Accepted                          |
| [0036](0036-v2.4-platform-and-theming.md)                        | v2.4.0 platform expansion + theming as a VM concern                                                  | 2.4.0        | Accepted (§2.E corrected by 0037) |
| [0037](0037-v2.5-maintenance-clarifications.md)                  | v2.5.0 maintenance clarifications and additions                                                      | 2.5.0        | Accepted                          |
| [0038](0038-spec-accuracy-corrections-and-form-014.md)           | Spec accuracy corrections (ch. 14/16/20/21), FORM-014                                                | 2.5.0        | Accepted                          |
| [0039](0039-property-changing-not-supported.md)                  | `INotifyPropertyChanging` not supported (teaching)                                                   | 2.6.0        | Accepted                          |
| [0040](0040-iproperty-not-adopted.md)                            | `IProperty<T>` reactive backing-field not adopted                                                    | 2.6.0        | Accepted                          |
| [0041](0041-single-disposable-lifecycle.md)                      | Single disposable lifecycle (no two-tier bags)                                                       | 2.6.0        | Accepted                          |
| [0042](0042-composite-builder-current-and-on-current-changed.md) | `CompositeVMBuilder.Current` + `OnCurrentChanged`                                                    | 2.6.0        | Accepted                          |
| [0043](0043-relicense-apache-2.0.md)                             | Relicense from MIT to Apache-2.0                                                                     | —            | Accepted                          |
| [0044](0044-v2.6-spec-accuracy-clarifications.md)                | v2.6 spec-accuracy clarifications (ch. 02 / 15)                                                      | 2.6.0        | Accepted                          |
| [0045](0045-v2.6-spec-accuracy-clarifications-2.md)              | v2.6 spec-accuracy clarifications (ch. 06 / 20 / 21)                                                 | 2.6.0        | Accepted                          |
| [0046](0046-v2.6-pagecount-clarification.md)                     | v2.6 spec-accuracy clarification (ch. 14 PageCount)                                                  | 2.6.0        | Accepted                          |
| [0047](0047-v3-lifecycle-threading-semantics.md)                 | v3 lifecycle/threading — atomic transitions, fg-marshalling, transactional rollback (LIFE-014)       | 3.0.0        | Accepted                          |
| [0048](0048-v3-form-vm-semantics.md)                             | v3 FormVM — injectable deep-equal `IsDirty`, deep default snapshot, approve error channel (FORM-015) | 3.0.0        | Accepted                          |

## 2. Format

Each ADR starts with a YAML-like preamble:

```markdown
# ADR NNNN — Short imperative title

**Status:** Accepted (YYYY-MM-DD)
**Spec version:** introduced in X.Y.Z

## 1. Context
...

## 2. Decision
...

## 3. Consequences
...

## 4. Rejected alternatives (optional)
...
```

The preamble fields are stable so tooling can parse them; the body is
hierarchically numbered (matching the documentation conventions used
elsewhere in the spec).
