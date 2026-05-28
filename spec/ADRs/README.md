# spec/ADRs/

Architecture Decision Records (ADRs) for the VMx spec. Each ADR is a small,
self-contained markdown file numbered `NNNN-kebab-title.md`.

ADRs capture the *why* behind every normative spec change. Per the spec
discipline rule in `CLAUDE.md`, any modification to a `spec/NN-*.md` chapter
requires a new ADR in the same PR. The exemption list (typos, README,
VERSION, fixtures, the conformance catalog) is enforced by
`.github/workflows/spec-discipline.yml`.

## 1. Index

ADRs are sorted by number (chronological by acceptance), not by importance —
later ADRs build on earlier ones. For a topical overview, follow the
cross-references each ADR carries.

| #                                                       | Title                                      | Spec version | Status   |
| ------------------------------------------------------- | ------------------------------------------ | ------------ | -------- |
| [0001](0001-drop-comscore.md)                           | Drop comScore baggage from v1              | 1.0.0        | Accepted |
| [0002](0002-rx-as-reactive-primitive.md)                | Rx as the reactive primitive               | 1.0.0        | Accepted |
| [0003](0003-constructor-injection.md)                   | Constructor injection for services         | 1.0.0        | Accepted |
| [0004](0004-langs-folder-layout.md)                     | `langs/<flavor>/` folder layout            | 1.0.0        | Accepted |
| [0005](0005-drop-virtualization-from-core.md)           | Virtualization is out of scope             | 1.0.0        | Accepted |
| [0006](0006-idiomatic-api-per-language.md)              | Idiomatic per-language surface             | 1.0.0        | Accepted |
| [0007](0007-aggregate-vm-arity-1-to-5.md)               | `AggregateVM` arities 1–5                  | 1.0.0        | Accepted |
| [0008](0008-async-lifecycle-methods.md)                 | Async lifecycle methods                    | 1.0.0        | Accepted |
| [0009](0009-cross-flavor-divergence-catalogue.md)       | Cross-flavor divergence catalogue          | 1.1.0        | Accepted |
| [0010](0010-capability-micro-interfaces.md)             | 20 capability micro-interfaces             | 2.0.0        | Accepted |
| [0011](0011-derived-properties.md)                      | N-source derived properties                | 2.0.0        | Accepted |
| [0012](0012-command-decorators.md)                      | Command decorators (Confirmation, Logging) | 2.0.0        | Accepted |
| [0013](0013-notification-service.md)                    | Opt-in `VMx.Notifications` sub-package     | 2.0.0        | Accepted |
| [0014](0014-search-and-filter.md)                       | `SearchableState` helper                   | 2.0.0        | Accepted |
| [0015](0015-expand-collapse-state.md)                   | `ExpandableState` helper                   | 2.0.0        | Accepted |
| [0016](0016-modeled-crud-commands.md)                   | `ModeledCrudCommands<M, VM>` helper        | 2.0.0        | Accepted |
| [0017](0017-null-object-services.md)                    | Null-object service convention             | 2.0.0        | Accepted |
| [0018](0018-flat-vm-hierarchy-vs-old-chain.md)          | Flat VM hierarchy vs the 2012 chain        | 2.0.0        | Accepted |
| [0019](0019-localization-hooks.md)                      | `ILocalizer` hook + `NullLocalizer`        | 2.0.0        | Accepted |
| [0020](0020-v2.0-spec-text-refresh.md)                  | Spec text refresh for v2.0                 | 2.0.0        | Accepted |
| [0021](0021-post-v2.0-editorial-polish.md)              | Post-v2.0 editorial polish                 | 2.0.0        | Accepted |
| [0022](0022-filterable-capability.md)                   | `IFilterable<T>` capability                | 2.1.0        | Accepted |
| [0023](0023-paging-capability-and-paged-composition.md) | Paging (`IPageable` + `PagedComposition`)  | 2.1.0        | Accepted |

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
