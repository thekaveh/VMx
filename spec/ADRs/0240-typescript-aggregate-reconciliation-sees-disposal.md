# ADR 0240 — A TypeScript reconciliation that sees disposal releases what it staged

- **Status:** Accepted
- **Date:** 2026-11-21
- **Spec version:** 3.30.0 (chapter 21 §9.4 and §9.7, `AGCH-012`)
- **Amends:** [ADR-0214](0214-collection-paging-keyed-add-and-aggregate-gate-rules.md)
  Decision rule 4, for the TypeScript flavor. Related:
  [ADR-0098](0098-dynamic-aggregate-change-stream.md),
  [ADR-0192](0192-aggregate-change-stream-delivers-in-subscription-order.md),
  #1325, #1914.

## 1. Context

ADR-0214 rule 4 requires every flavor to check, under the aggregate gate, that
the aggregate is still open before a reconciliation commits. Its TypeScript
sentence says "TypeScript runs on one thread and needs no change."

One thread does not rule out re-entry. A TypeScript reconciliation calls
consumer code (chapter 21 §9.4): `source.snapshot()`, the selector, the selected
stream's `subscribe`, and the `unsubscribe` of a removed entry. Each of these can
call `dispose()` on the same aggregate. The defect in #1914 follows:

- The reconciliation checked only the structural version after staging. It then
  committed the staged entries and queued `Membership` ahead of `complete`.
- Nothing released the staged subscriptions. `dispose()` had already cleaned up
  the committed entries, and it does not see the staged plan.

Four new TypeScript tests in `AGCH-012` reproduced the defect before the fix.
The first failing assertion of each test was:

| Call-out that disposes the aggregate                      | Expected                               | Before the fix      |
| --------------------------------------------------------- | -------------------------------------- | ------------------- |
| `subscribe` of a selected stream                          | no live subscription                   | 1 live subscription |
| selector, for the first of two new members                | 1 selector call                        | 2 selector calls    |
| `source.snapshot()`                                       | 0 selector calls                       | 1 selector call     |
| teardown of a removed member, with one replacement member | no live subscription to the new member | 1 live subscription |

The issue's reproduction also records the event order `[membership, complete]`
for the first three paths, where `complete` alone is correct. The issue traced
the fourth path without reproducing it, and the test now reproduces it.

## 2. Decision

1. **A closed aggregate stages and commits nothing.** After each call-out, a
   reconciliation checks whether the aggregate has completed or failed
   (`#isClosed()`). When it has, the reconciliation stops and delivers nothing
   for that pulse:

   - after `source.snapshot()`, it stages nothing, so no selector call runs;
   - after each selector call, it stops before subscribing;
   - after each `subscribe`, and after the `unsubscribe` of an entry that had
     already ended, it stops staging;
   - after staging, it releases the staged plan and commits nothing, so no
     `Membership` is queued;
   - after the removal loop of the commit, it releases the staged plan, admits
     no staged entry, and returns `false`.

   The `complete` that `dispose()` queued is still delivered once.

1. **Staged entries join the plan before the first call-out.** A disposal inside
   a call-out then finds the entry in the plan, and the release unsubscribes the
   subscription it holds. An entry that has no subscription releases to nothing.

1. **Construction gets the same checks.** `#initialize` applies the same checks
   after the snapshot, after staging and at the commit. The choice is yes.
   Reason: the other flavors check the open state at each commit point, so one
   rule covers setup and later reconciliations. No consumer holds the aggregate
   before its constructor returns, so this check cannot be reached through the
   public API. No test drives it, and it changes no observable behavior.

1. **Rule 4 is amended for TypeScript.** The sentence "TypeScript runs on one
   thread and needs no change" is replaced. One thread still re-enters from
   call-outs, so TypeScript checks the open state after each call-out, and it
   commits nothing once the aggregate has closed. This is stricter than the
   other four flavors. Their code checks the open state at the top of the
   reconciliation loop and at the commit point only. Their staging loops call
   the selector and subscribe for each staged member with no check in between:
   C# `SubscribeEntry` in `langs/csharp/src/VMx/Collections/AggregateChangeStream.cs`,
   Python `_subscribe_entry` in `langs/python/src/vmx/collections/aggregate_change_stream.py`,
   the staging loop in `langs/swift/Sources/VMx/Collections/AggregateChangeStream.swift`,
   and the staging loop in `langs/rust/src/aggregate_change_stream.rs`. Their
   staged subscriptions are released at the commit point. The C#, Python, Swift
   and Rust text of rule 4 is unchanged, and this ADR changes none of their code.
   ADR-0214 carries the back-link in its Status line and its registry cell.

1. **No new conformance ID.** The four tests sit in the existing
   `describe("AGCH-012")`. `AGCH-012` already states the rule: the aggregate
   calls the source, the selector and the subscriptions with no gate held. Its
   last clause lists the TypeScript single-thread call-out sequences. A disposal
   from a call-out is one more sequence of the same rule. The TypeScript list in
   `spec/12-conformance.md` gains that sequence. A new ID would split one rule
   across two IDs, and the catalog count does not change.

1. **Chapter 21 is unchanged.** Section 9.4 already names the disposal of a
   selected subscription as a call-out. Section 9.7 already says that a
   reconciliation which sees disposal releases the subscriptions it staged but
   did not commit. The normative text already covers the fix.

1. **Other flavors are unchanged.** ADR-0214 rule 4 already requires the open
   check in C#, Python, Swift and Rust at the commit point, and this change does
   not touch them. Section 9.7 says that a staged subscription "can stay live
   after explicit disposal returns" until the reconciliation releases it. The
   commit-point check of those four flavors meets that sentence. The text does
   not say whether a reconciliation may still call the selector or subscribe for
   later members after disposal. TypeScript takes the stricter reading, and the
   other four take the looser one. This is a known cross-flavor divergence
   (CLAUDE.md §1), and it is not a defect of #1914. Owner item: decide whether
   §9.7 should state the rule, and if the stricter reading is wanted, align the
   other four flavors in a follow-up.

1. **No version bump and no API change.** `spec/VERSION` stays 3.30.0, because no
   `spec-v3.30.0` tag exists. The TypeScript package stays at its unreleased
   source version, 3.31.0. The public API baseline is unchanged. The change adds
   one `Fixed` entry to `langs/typescript/CHANGELOG.md` under
   `[3.31.0] — unreleased source version`.

1. **Mutation evidence.** The five checks are C1 after the snapshot, C2 after the
   selector, C3 after the subscribe, C4 after staging, and C5 after the removal
   loop. The two checks in `#initialize` are not mutated, because no test
   reaches them. Each mutation was applied to the fixed file, the
   `AGCH-012` tests were run, and the file was restored byte for byte.

   - M1, all checks removed (the pre-fix code): the four new tests fail.
   - M2, C5 removed: only the teardown test fails.
   - M3, C1 removed: only the snapshot test fails.
   - M4, C2 and C3 removed: only the selector test fails.
   - M5, C4 and C5 removed: the subscribe, selector and teardown tests fail.
     C4 and C5 are the release points. The snapshot test still passes, because
     the snapshot check C1 stops the work before any staging.

## 3. Consequences

- A disposed TypeScript aggregate delivers no `Membership` after its `complete`.
  No selected subscription stays live after a call-out disposes the aggregate.
- A reconciliation that does not see disposal behaves as before. Each admitted
  structural pulse still queues one `Membership`, and a pulse during staging
  still repeats the reconciliation.
- The added checks are reads of two fields. The public API is unchanged.
- The other four flavors keep a staged subscription live until their commit
  point, which §9.7 permits. The TypeScript flavor releases it at the next
  call-out check. The difference is recorded in decision 4 and decision 8.
- The construction-time checks cannot be reached through the public API. A
  reader should not expect a test for them.

## 4. Rejected alternatives

- **One check before the commit, as C#, Python, Swift and Rust use.** This
  releases the staged subscriptions, which §9.7 allows. It still calls the
  selector and subscribes to later members after the aggregate is disposed,
  which does work the aggregate no longer needs. Section 9.7 does not forbid
  that work, so the stricter form is a TypeScript choice, not a spec
  requirement. A check before the commit also misses the removal-teardown case.
  In TypeScript the teardown calls `unsubscribe` inside the commit, so a
  disposal from that call-out happens after the check.
- **Track staged entries on the instance, so that `dispose()` releases them.**
  The reconciliation already holds its plan. A second owner of staged
  subscriptions would need its own ordering rules.
- **A new `AGCH-013` ID.** See decision 5.
- **Leave TypeScript unchanged, on the single-thread argument of ADR-0214.** The
  defect is reproduced on one thread, so the argument does not hold.
