# ADR 0188 — A refused child `select()` and a selection while `Destructing` are silent

- **Status:** Accepted
- **Date:** 2026-11-09
- **Spec version:** 3.30.0 (chapter 05 §6; chapter 06 §3, §3.1, §4.3 and §5)
- **Extends:** [ADR-0173](0173-selection-commits-without-a-membership-transaction.md)
  §2 and §2.1. Related: #1424, #1425, #1229.

## 1. Context

ADR-0173 states the rules for every selection path of a `CompositeVM`. Two
gaps remained.

- **The child `select()` channel (#1424).** Chapter 05 §6 says that
  `select()` calls `parent.select_component(this)`, and chapter 06 §3.1 says
  that a refused `select_component` raises. The flavors give three results.
  C# raises `InvalidOperationException` for every refused child `select()`
  and `deselect()`. Swift and Rust discard every refusal. Python and
  TypeScript return silently for a non-member and for a member that is not
  `Constructed`. They raise for a `Constructed` member while disposal of the
  composite is pending, and inside the caller's own uncommitted membership
  transaction. Python checks that transaction before membership, and
  TypeScript checks membership first. Only the ADR-0009 catalogue records
  these results.
- **A selection while `Destructing` (#1425).** `destruct()` clears `Current`
  first (chapter 06 §5, `COMP-005`). ADR-0173 §2.1 accepted that a consumer
  selection after the clear is not refused. A selection from
  `OnCurrentChanged(null)` commits, because leases nest (§4.3 rule 5). So
  does a selection from a child's destruct hook or from another thread during
  the child walk. `destruct()` can then return with `Current` set, against
  `COMP-005`. A fallback handler that selects the first child when it
  receives null is enough. ADR-0173 said that a status check needs the
  lifecycle status under the membership gate.

## 2. Decision

Decided under the owner's 2026-11-07 delegation: every flavor follows the
same rule, and the simplest rule wins.

### 2.1. Rules

1. **A refused child `select()` or `deselect()` is silent.** The child
   `select()` and `deselect()` paths run the checks of `select_component` and
   `deselect_component`. When the parent refuses, the call changes nothing
   and raises nothing, in every flavor. This covers every refusal. The refused
   child can be a non-member, a member that is not `Constructed`, or, for
   `deselect()`, a child that is not current. The composite can have a
   pending disposal. The caller can be inside its own uncommitted membership
   transaction (§4.3 rule 4). A check can also fail at the commit. `can_select()` and `can_deselect()` tell a caller in
   advance.
1. **A selection while `Destructing` is silent.** While the composite is
   `Destructing`, a non-null selection that §4.3 rules 2, 3 and 4 admit
   changes nothing and raises nothing. The rule covers the setter,
   `select_component`, the child `select` path, and the `AsyncSelection(true)`
   call and its delivery. `can_select_component` returns `false`. A null
   clear commits as usual. The rule also applies in the destruct phase of
   `reconstruct()`. It replaces the ADR-0173 §2.1 bullet *A selection during
   `Destructing`*.
1. **Order.** Rule 2 applies after the other refusals. A non-member, a
   pending disposal and the caller's own transaction keep their errors while
   the composite is `Destructing`. `select_component` keeps its predicate
   error for a child that is not `Constructed`.
1. **Sound check.** The composite enters `Destructing` before its destruct
   clear. The clear and every selection commit take the coordination lane and
   the membership gate. A commit that reads `Destructing` under the gate
   therefore cannot commit after the clear. Every flavor reads its own
   status under the gate. No flag is needed, so nothing resets at
   `Destructed`, at the rollback, or at `Disposed`.

### 2.2. Decided under the owner's delegation

- **Silent, not raising, for the child path.** Silent is the result that
  Swift and Rust already give for every refusal, and that Python and
  TypeScript give for most. A Swift `select()` cannot throw, so a raising
  rule would need a trap there. `COMP-027` already calls `select()` a no-op
  after removal. C# changes most: `SelectChild` and `DeselectChild` stop
  throwing.
- **Silent, not raising, while `Destructing`.** A raising rule would make a
  common fallback handler fail every `destruct()` and `reconstruct()`: the
  error escapes `OnCurrentChanged(null)` and rolls the destruct back. A
  selection during teardown has no useful effect, so ignoring it keeps
  teardown safe. The Swift `current` setter cannot throw. A silent rule is therefore
  the only rule that is the same in all five flavors without a trap.
  The construct walk's assignment and an asynchronous delivery already use
  silent refusals for lifecycle windows.
- **No refusal before the destruct clear.** A selection made between the
  `Destructing` publication and the clear is refused too, because the status
  is already `Destructing`. The clear would clear it anyway, so this has no
  other effect.
- **Selection after the destruct.** A composite that is `Destructed` keeps
  its current selection rules. Its initial status is `Destructed`, and
  consumers select before the first `construct()`.
- **Conformance IDs.** `COMP-051` covers rule 2 on one thread: a selection
  from `OnCurrentChanged(null)` and from a child's destruct hook. `COMP-052`
  covers rule 1 with the refusals that one thread can reach. The
  cross-thread cases stay regression tests in each flavor.

## 3. Flavor impact

The implementation PR confirms the exact sites.

- **C#.** `IParentCompositeVM.SelectChild` and `DeselectChild` call a
  non-throwing selection path. `SelectionRefusalLocked` and
  `CanSelectComponent` add the `Destructing` check after the other
  refusals, and the commit returns without a change for it.
  `SelectComponent` checks `Destructing` before it raises the predicate
  error.
- **Python.** `select_child` and `deselect_child` stop raising: the rule 4
  check, the pending-disposal refusal and the commit-time refusal return
  silently. `_selection_refusal_locked` gains the `Destructing` result, and
  `can_select_component` returns `False` for it.
- **TypeScript.** `selectChild` and `deselectChild` stop throwing for the
  rule 4 window and a pending disposal. `_setCurrent`, `#deliverSelection`
  and `canSelectComponent` add the `Destructing` check.
- **Swift.** `selectChild` and `deselectChild` already discard refusals.
  `_commitSelectionLocked` returns a new `.ignored` outcome for a non-null
  value while the composite is `Destructing`. It reads the composite's own
  status under `membershipGate`. `ContainerSupport.registerLateStartLocked`
  and the construct seal already take the lifecycle lock under that gate.
- **Rust.** `select_via_parent` and `deselect_via_parent` already discard
  refusals. `validate_locked` and `can_select` gain the `Destructing` check,
  and the request returns `Ok(())` without a change for it.

The ADR-0009 bullet *Runtime `select_child`/`deselect_child` on a
member-but-not-Constructed child* is removed: no divergence remains.

## 4. Conformance

`COMP-051` and `COMP-052` are new. The catalog grows by these two IDs and by
the two IDs of ADR-0189, from 451 to 455 library IDs (460 in total).

## 5. Consequences

- A C# child `select()` or `deselect()` no longer throws. Code that caught
  `InvalidOperationException` from it gets no error.
- A Python or TypeScript child `select()` no longer raises inside the
  caller's own uncommitted transaction or while disposal is pending.
- `destruct()` and `reconstruct()` always return with `Current` null, also
  when a consumer selects during the destruct. `COMP-005` holds without the
  assumption that ADR-0173 recorded.
- `can_select_component` returns `false` for every child while the
  composite is `Destructing`.
