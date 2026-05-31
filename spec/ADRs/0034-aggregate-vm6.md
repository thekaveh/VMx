# ADR 0034 — Extend `AggregateVM` arity to 6

**Status:** Accepted (2026-05-30)
**Spec version:** introduced in 2.2.0
**Supersedes:** ADR-0007 §4 ("a future spec major version could lift the cap. v2.0 chose not to; any such change would land in a future major (v3.0 or later).") — only that specific clause.

## 1. Context

The notes-showcase example portfolio
(`spec/proposals/2026-05-29-notes-showcase-scenario.md`) needs a root
`WorkspaceVM` that heterogeneously composes six children: notebooks tree,
notes view, note form, status bar, notifications, and capability actions
bar. `AggregateVM1..5` (ADR-0007) does not fit; nor does `CompositeVM<VM>`
(uniform children) or `GroupVM<VM>` (peer-uniform). The natural answer
is one more arity.

ADR-0007 §4 anticipated lifting the cap only in a future major version.
That stance assumed lifting the cap meant changing the architecture
(e.g., variadic generics). Adding a single new explicit `AggregateVM6`
class is purely additive — no breaking change to consumers of
`AggregateVM1..5`. The "future major" clause is over-conservative for
this kind of change.

## 2. Decision

Add `AggregateVM6<VM1, VM2, VM3, VM4, VM5, VM6>` to every language
flavor, mirroring the existing `AggregateVM5` design (heterogeneous
fixed-arity, automatic lifecycle cascade). Ship the change as a **minor
spec bump (2.2.0)** because it is additive: existing code using
`AggregateVM1..5` is unaffected.

The arity cap is now **6**. Future needs beyond 6 follow the same
precedent: add the next class as a minor bump. The recurring soft signal
from ADR-0007 still applies — when children are homogeneous, prefer
`CompositeVM<VM>` or `GroupVM<VM>`; aggregate-of-aggregate composition
is also a valid escape hatch when only a few of the children share type.

## 3. Consequences

- `AggregateVM6` exists in every language flavor at the spec ≥ 2.2.0
  level.
- The conformance catalog gains `AGG-006` (one new ID, total
  `219 + 1 = 220`).
- The compatibility matrix gains a `2.2.x` row.
- ADR-0007 §4's "future major" clause is superseded by this ADR.
- Future arities (7, 8, …) follow the same precedent if and when a real
  example or consumer surfaces the need; each adds one new ID to the
  conformance catalog.
