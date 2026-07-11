# ADR 0089 — Add atomic ObservableList replacement

**Status:** Accepted (2026-07-10)
**Spec version:** introduced in 3.9.0

## 1. Context

Refreshing an observable list by clearing it and adding every new item emits
one reset plus one add and `Count` notification per element. That is correct for
independent mutations but wasteful when the semantic operation is “the list is
now this snapshot.” NNx Studio's run-history refresh used that pattern and
caused 14 adapter-visible changes for 13 stored runs.

All five flavors already coalesce granular list mutations inside a ref-counted
batch. Consumers could wrap clear-plus-add themselves, but doing so repeats the
same snapshot, nesting, failure, and event-ordering decisions at every refresh
site.

## 2. Decision

Add `ReplaceAll` / `replace_all` / `replaceAll` to `ObservableList<T>` in all
five flavors. The input is fully materialized before the backing list changes.
This makes self/view input safe and, where iteration can fail, leaves the list
and notification streams unchanged when materialization fails.

Empty-to-empty replacement is the sole no-op. Every other call is an effective
bulk mutation and emits exactly one `Reset`, including equal-count and
element-for-element identical non-empty contents. The contract deliberately
does not compare elements or constrain `T` with equality.

No granular add, remove, or replace events escape. When cardinality changes,
the spec-literal `Count` notification follows `Reset`; when it does not, only
`Reset` fires. Both observers see the final contents.

Replacement participates in the list's existing batch depth. Inside a batch it
marks the batch dirty and only the outermost exit publishes. Exceptional exit
after a mutation still closes every entered scope, emits the same outermost
`Reset`/optional `Count`, and rethrows the original failure. Rust therefore
makes its existing `batch_update` unwind-safe and tracks the outer count so a
count-preserving batch does not emit `Count`; Swift's closure becomes
`throws`/`rethrows` without changing nonthrowing call sites.

## 3. Consequences

- `COL-040..047` cover growth, shrink, equal/identical contents, empty cases,
  input snapshotting, nesting, exceptional exit, and final-state ordering.
- Adapters receive one coarse replacement signal instead of O(n) granular
  signals and may choose reset or keyed reconciliation above VMx.
- A temporary NNx Studio pilot at base commit
  `d304336799d4f377c9dd34a465072dd697a8fd7b` replaced its four-line
  clear-plus-loop refresh with one `replaceAll(runs)` call. Package typecheck
  and all 322 viewmodel tests passed; a focused 13-to-13 refresh test measured
  adapter-visible collection events falling from 14 to exactly one Reset. No
  NNx change was pushed.
- A caller that needs equality-based suppression must decide equality outside
  the unconstrained generic list and skip the call.
- The specification and stable flavors advance to 3.9.0; pre-1.0 Rust advances
  to 0.9.0.

## 4. Rejected alternatives

### 4.1 Suppress element-for-element identical replacements

Rejected. It would add an equality constraint to a currently unconstrained
primitive or introduce flavor-specific identity/equality behavior.

### 4.2 Implement only TypeScript convenience sugar

Rejected. Notification cardinality and ordering are observable semantics, so
the operation belongs to the language-neutral contract and all full-parity
flavors.

### 4.3 Expose granular range payloads

Rejected for this operation. `replaceAll` describes a complete snapshot and
the existing Reset contract is already the portable signal for bulk changes.
