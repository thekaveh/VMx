# ADR 0252 — A dispose from a container's own construct hook skips population

- **Status:** Accepted
- **Date:** 2026-11-24
- **Spec version:** 3.30.0 (chapter 02 §2.4, `LIFE-015` in chapter 12). The spec version does not move.
- **Amends:** [ADR-0218](0218-container-rollback-errors-walk-resumption-and-single-start.md)
  §3, the TypeScript note on rules 3 to 6. Related: #1369 (closed; fixed the foreign-dispose
  case in Python and C#), #1805.

## 1. Context

### 1.1 The rule as written

ADR-0218 rule 5 says: a container whose construct hook a foreign `dispose()` superseded does
not call its children factory and attaches nothing, and its `construct()` returns without an
error. Chapter 02 §2.4 states the same rule. It says that the hook rechecks terminal
supersession before any post-hook container action, and that factory population is such an
action. Chapter 12 `LIFE-015` has a factory clause that names only a foreign `dispose()`. Its
scenario says "When disposal is requested during that hook" and "terminal supersession
prevents any post-hook container lifecycle work". Chapter 02 §7.2 says that a call that
`Disposed` superseded raises nothing.

The sentences that state the general rule name no thread. Only the factory clause and rule 5
name a foreign dispose. None of the sentences says what happens when a dispose is only
deferred during the hook.

### 1.2 What TypeScript does

TypeScript has one thread, so a foreign dispose cannot reach a construct hook. In TypeScript a
hook is superseded by a same-thread `dispose()`, such as a call from the hook's own body. ADR-0218
gave the TypeScript note as "TypeScript has one thread, so rules 3 to 6 hold already". That reason
covers the threading rules. It does not cover rule 5, because the failing case is a same-thread
dispose.

Before this ADR, `CompositeVMBase._onConstruct` (`langs/typescript/src/composites/compositeVMBase.ts`)
and `GroupVM._onConstruct` (`langs/typescript/src/groups/groupVM.ts`) had no supersession check.
They ran population after the hook. For an admitted dispose from the hook, the factory ran once,
and the first admission check threw `Cannot attach a child while the container is disposing`.
`construct()` rethrew that error. The final status was `Disposed` with no children. Issue #1805
reproduces this for `CompositeVM`, `CompositeVMOf` and `GroupVM`. For a dispose that a membership
transaction or a current publication deferred during the hook, develop gave the same result: the
factory ran once and the same error was thrown. The deferred case was never wrong in TypeScript.
Only the admitted case changes (§2.4).

### 1.3 What the other flavors do

Before this ADR, C#, Python, Swift and Rust returned from the construct path when an admitted
dispose superseded the hook. Their population and walk did not run, and `construct()` returned
without an error. Their same-thread tests covered this path. The C#, Python and Swift tests
discarded the `construct()` outcome, and the Rust test asserted `Ok(())`. Section 3.3 records
those test changes.

The flavors did not agree on a dispose that a membership transaction or a current publication of
the container defers during the hook. Before this ADR:

- C#, Python and Swift returned from the construct path only when an admitted dispose had
  superseded the hook. A deferred dispose still reached population, and the attach refused it
  with the disposing error.
- TypeScript had no check at all. A deferred dispose called the factory once, and the attach
  threw the disposing error, as in C#, Python and Swift.
- Rust's composite population also checked the deferred flag. A deferred dispose returned
  `Ok(())` without calling the factory. Rust's group population checked only the admitted flag,
  as the other flavors do. Its deferred dispose called the factory once and then failed with
  `OwnershipTransactionInProgress` (§2.4).

After this ADR, the same rule holds in all five flavors: a deferred dispose does not supersede the
hook. The refusal is the disposing error in every flavor except one Rust case, which §2.4 records.
§2.1 states the rule, and §2.4 gives the reachability and the guards.

## 2. Decision

### 2.1 The rule

A dispose supersedes a container's construct hook only when it is admitted. A dispose that a
membership transaction or current publication of the container defers is not admitted, so it does
not supersede the hook.

1. **Admitted supersession.** A container whose construct hook an admitted `dispose()`
   superseded:

   1. does not call its children factory, and attaches nothing;
   1. does not run the child construct walk;
   1. returns from `construct()` without an error;
   1. ends with status `Disposed` and no children.

   The supersession counts whether the `dispose()` is foreign or comes from the hook's own body.

1. **Deferred dispose.** A `dispose()` that is deferred during the hook does not supersede it.
   For a container whose population has not run, population runs and calls the children factory
   once. Its attach is refused with the disposing error, so `construct()` reports that error and
   nothing attaches. The deferred disposal completes when its membership transaction or
   publication ends. Rust's composite membership-transaction case is refused with a different error
   (§2.4).
   For a container that is already populated, population does not run again (§2.5).

No chapter states the attach refusal in words. Chapter 06 §4.3 rule 3 refuses a non-null
selection during disposal, which is a different rule. This ADR, chapter 02 §2.4 and the `LIFE-015`
clause state the attach refusal directly.

Chapter 02 §2.4 and the `LIFE-015` clause name both cases. The code follows them in all five
flavors (§2.4), with the one Rust error difference that §2.4 records.

### 2.2 Why the rule covers a dispose from the hook's own body

The factory clause names a foreign `dispose()` because ADR-0218 rule 5 was written from the
foreign-dispose fix in #1369, which covered Python and C#. Three points show that the clause
was not meant to exclude an admitted dispose from the hook's own body.

1. The general sentences of §2.4 and `LIFE-015` name no thread. "Terminal supersession
   prevents any post-hook container lifecycle work" applies to any admitted supersession.
1. An admitted dispose from the hook's own body sets the same disposal flags and publishes the
   same `Disposed` status as a foreign dispose in every flavor. A post-hook action that checks
   the supersession must therefore stop for both. Chapter 02 §7 says that a dispose from the
   hook's own thread is "not foreign", which decides only how the children are disposed
   (inline, under §7.2). It does not allow population to run.
1. Chapter 02 §7.2 says a call that `Disposed` superseded raises nothing. A population that
   throws for an admitted same-thread dispose would break that rule.

For TypeScript, point 1 decides the case. The thread-based wording would give TypeScript no
supersession case at all, because a foreign dispose is impossible there.

### 2.3 Choice between option A and option B

Issue #1805 sets two options. The orchestrator recorded option A under the owner's 2026-11-07
delegation, which asks for the cross-flavor-uniform, simplest option to be picked and recorded.
The owner has not reviewed this choice. The Accepted status records the decision as made here;
it does not mean that a maintainer accepted it. This ADR records the choice and its reasons.

- **Option A (chosen).** The rule in §2.1 covers any admitted supersession, from the hook's own
  body or from another thread. TypeScript gains the supersession check that the other four
  flavors already have. The admitted case changes TypeScript. The deferred case changes only
  Rust's composite population, and Rust's group membership refusal (§2.4).
- **Option B (rejected, see §5.2).** A same-thread dispose from the hook makes `construct()`
  throw. Four flavors change.

Option A was recorded for three reasons:

- It agrees with chapter 02 §2.4, the factory clause and §7.2, and it changes no rule.
- It changes fewer flavors than option B, and option B makes the TypeScript factory run once
  before the throw, which the factory clause forbids.
- It is the simplest option that gives every flavor the same behavior, which the delegation
  asks for.

### 2.4 The deferred case and the guards

**Reachability.** A dispose is deferred during a construct hook when a membership transaction or
a current publication of the container is open. The disposing thread's own publication defers the
dispose before any wait. A transaction or publication that another thread holds also defers it,
after the wait for a foreign transaction where the flavor waits. TypeScript has one thread, so
only its own transactions and publications apply. The public API reaches that state. Setting
`current` to a member of a container that is not constructed yet publishes the change under the
publication lease. The container's `onCurrentChanged` callback then calls `construct()`, and the
hook calls `dispose()`, which is deferred. A dispose from the collection-changed callback of an
`add()` is deferred the same way, because that callback runs inside the add's membership
transaction.

| Flavor     | Where `dispose()` defers                                                                                                                                                                                                                                                              | Tests that reach it (composite, then group)                                                                                                                                                                                      |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| TypeScript | `compositeVMBase.ts` `dispose()` when `#membershipTransactionActive` or `#activeCurrentPublications > 0`. `groupVM.ts` `dispose()` when `#membershipTransactionActive`.                                                                                                               | `lifecycle.test.ts`: "refuses CompositeVM population when its construct hook's dispose is deferred by a publication", and "refuses GroupVM population when its construct hook's dispose is deferred by a membership transaction" |
| Python     | `composite_vm.py` `dispose()` when `get_ident()` is in `_current_publication_threads`, or, after the foreign-transaction wait, when `_membership_transaction_active` or `_active_current_publications > 0`. `group_vm.py` `dispose()` when `_membership_transaction_active`.          | `test_composite_vm.py`: `test_LIFE_015_deferred_dispose_in_hook_refuses_population_attach`; `test_group_vm.py`: `test_LIFE_015_deferred_group_dispose_in_hook_refuses_population_attach`                                         |
| C#         | `CompositeVMBase.cs` `Dispose()` when the thread is in `_currentPublicationThreads`, or, after the foreign-transaction wait, when `_membershipTransactionActive` or `_activeCurrentPublications > 0`. `GroupVMBase.cs` `Dispose()` when `_membershipTransactionActive`.               | `CompositeVMConformanceTests.cs`: `LIFE_015_Deferred_Dispose_In_Hook_Refuses_Population_Attach`; `GroupVMConformanceTests.cs`: `LIFE_015_Deferred_Group_Dispose_In_Hook_Refuses_Population_Attach`                               |
| Swift      | `CompositeVM.swift` `dispose()` when the caller holds a publication lease or owns the membership transaction, or when `activeCurrentPublications > 0`. Another thread's transaction is waited for first. `GroupVM.swift` `dispose()` when the caller owns the membership transaction. | `ContainerHookDisposalTests.swift`: `testDeferredDisposeInsideOwnHookRefusesPopulationAttach`; `testDeferredGroupDisposeInsideOwnHookRefusesPopulationAttach`                                                                    |
| Rust       | `composites.rs` `dispose()` and `groups.rs` `dispose()` when `dispose_disposition()` returns `Owned` or `PublishingThread` (`runtime.rs`). A composite also defers while a publication of any thread is open (`defer_while_publishing`).                                              | `container_hook_disposal.rs`: `deferred_composite_dispose_in_hook_refuses_population_attach`; `deferred_group_dispose_in_hook_refuses_population_attach`                                                                         |

**The refusal.** Every flavor refuses the population of a deferred dispose with its disposing
error, except Rust's composite when a membership transaction defers the dispose:

| Flavor         | Deferred by a publication                                                            | Deferred by a membership transaction       |
| -------------- | ------------------------------------------------------------------------------------ | ------------------------------------------ |
| TypeScript     | `Error`: `Cannot attach a child while the container is disposing`                    | same                                       |
| Python         | `RuntimeError`: `cannot attach a child while the container is disposing`             | same                                       |
| C#             | `ObjectDisposedException`: `Cannot attach a child while the container is disposing.` | same                                       |
| Swift          | `ContainerOwnershipError.attachmentFailed`                                           | same                                       |
| Rust composite | `VmxError::Disposed`                                                                 | `VmxError::OwnershipTransactionInProgress` |
| Rust group     | not reachable (groups have no publication)                                           | `VmxError::Disposed`                       |

In Rust, a composite's population begins a membership transaction in `attach_population`
(`composites.rs`) before it checks for disposal. When a membership transaction defers the dispose,
that transaction is still open, so the begin fails first and the composite returns
`OwnershipTransactionInProgress`. A publication holds no transaction, so the disposal check is
reached and returns `Disposed`. A group's population checks the deferred dispose in
`GroupVm::populate` (`groups.rs`) before it begins its transaction, so a membership-deferred
dispose returns `Disposed` there as well. §3.5 records that change and the composite case that
remains.

The other flavors check disposal before they begin a transaction, so the membership column holds
for their composites as well. The code shows it: TypeScript `#requireChildAdmission`, Python
`_require_child_admission`, C# `EnsureChildAdmission` and Swift `beginMembershipTransactionLocked`.
The tests cover the group case there, not the composite case.

The reachability was checked by running the public API. The TypeScript probe gave the same
deferred result on develop and on this branch: one factory call, the disposing error, and status
`Disposed`. The Rust membership results in the table above were observed the same way: the
composite refuses with `OwnershipTransactionInProgress`, and the group with `Disposed`, each after
one factory call. The Python populated cases in §2.5 were observed too.

**The guards before and after this ADR:**

| Flavor         | Guard that gates population in the construct hook                                                                                                                                             | Deferred case before this ADR                                                 | Deferred case after this ADR                                                                                                    |
| -------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| TypeScript     | `#disposeRequested` and `Disposed`, in `CompositeVMBase._onConstruct` (`compositeVMBase.ts` line 640) and `GroupVM._onConstruct` (`groupVM.ts` line 412). Before this ADR there was no guard. | Factory once, attach throws                                                   | Unchanged: factory once, attach throws                                                                                          |
| Rust composite | `CompositeVm::populate` (`composites.rs` line 1604): `dispose_requested` and `Disposed`                                                                                                       | Publication: no factory call, `Ok(())`. Membership: no factory call, `Ok(())` | Publication: factory once, `Err(VmxError::Disposed)`. Membership: factory once, `Err(VmxError::OwnershipTransactionInProgress)` |
| Rust group     | `GroupVm::populate` (`groups.rs` line 906): `dispose_requested` and `Disposed`                                                                                                                | Membership: factory once, `Err(OwnershipTransactionInProgress)`               | Membership: factory once, `Err(VmxError::Disposed)`. Other cases unchanged                                                      |
| C#             | `DisposalStarted()` (requested or Disposed): `CompositeVMBase.cs` line 1404 and `GroupVMBase.cs` line 588                                                                                     | Factory once, attach throws                                                   | Unchanged                                                                                                                       |
| Python         | `_population_superseded()` (requested or Disposed), reached only while not populated: `composite_vm.py` lines 882 to 884 and `group_vm.py` line 534                                           | Factory once, attach raises                                                   | Unchanged                                                                                                                       |
| Swift          | `_isDisposalRequested()` (requested or Disposed): `CompositeVM.swift` line 875 and `GroupVM.swift` line 651                                                                                   | Factory once, attach throws                                                   | Unchanged                                                                                                                       |

The change has three guard edits: two in TypeScript (`CompositeVMBase` and `GroupVM`) and one in
Rust (`CompositeVm::populate`). `CompositeVm::populate` in Rust now checks only the admitted flag
and the `Disposed` status, as `GroupVm::populate` already did. The TypeScript guards check the same
two conditions. They are new in this change, so the admitted case changes. The deferred case in
TypeScript does not change, because the guards do not test the deferred flag. The other flavors'
guards are unchanged.

`GroupVm::populate` keeps its guard and gains a refusal. After the children factory call, a
deferred dispose returns `Err(VmxError::Disposed)` before `attach_population` begins the
membership transaction. This is not a supersession: the factory still runs once, and the refusal is
the disposing error that the rule requires. The admitted case is unchanged.

**The choice.** The uniform rule is the admitted-flag rule in §2.1. It was recorded for three
reasons:

- It matches the most flavors. After this change, all five flavors check only the admitted flag
  in their construct-hook guards, and Rust's group already did. The other option changes the
  deferred case in TypeScript, C#, Python and Swift, and in Rust's group population (§5.3).
- It matches the spec. Chapter 02 §2.4 speaks of "terminal supersession", and a foreign dispose
  "publishes the terminal status". A deferred dispose is not terminal yet. Chapter 06 §4.3
  rule 5 starts a deferred disposal only when the last lease ends and no membership transaction
  is open, so the container is not terminal while the hook runs.
- It is the smallest change: three guard edits, and no change to C#, Python or Swift library code.

The attach refusal applies to a deferred dispose in every flavor, so population refuses it the
same way. The error type is idiomatic per flavor: `ObjectDisposedException` in C#,
`RuntimeError` in Python, `ContainerOwnershipError.attachmentFailed` in Swift, `VmxError::Disposed`
or `VmxError::OwnershipTransactionInProgress` in Rust (the table above), and `Error` with the
message `Cannot attach a child while the container is disposing` in TypeScript.

### 2.5 Behavior that does not change, and the populated cases

- A dispose inside the children factory still throws in TypeScript, because the admission check
  rejects it. The existing `LIFE-013` test "rejects composite and group factory output produced
  after reentrant disposal" keeps asserting this. Its case differs: the dispose is in the factory,
  not in the construct hook.
- An `add()` during disposal still fails.
- A dispose after population, outside the hook, follows the rules it followed before.
- **An admitted dispose on a populated container.** Population runs once, so after a first
  `construct()` a second `construct()` skips population. In Python, the admitted check sits
  inside `if not self._populated:` (`composite_vm.py` lines 882 to 884). After a prior population,
  an admitted dispose in the hook therefore still reaches the child walk. Observed in Python: the
  second `construct()` returns without an error, the child is not constructed again (its construct
  count stays at 1), and the status is `Disposed`. The walk skips the child because the cascade
  has already disposed it (chapter 06 §5: both walks skip a `Disposed` child). The guards in
  TypeScript, C# and Swift return before the walk, so their result is the same.
- **A deferred dispose on a populated container.** Population does not run, so there is no
  factory call and no attach. The child walk constructs the children that already exist, and
  `construct()` returns without an error. The deferred disposal then completes when its
  publication or transaction ends. Observed in Python: after a `destruct()`, a `current`
  selection inside a publication calls `construct()`. That `construct()` returns without an error,
  the existing child is constructed again, the factory is not called again, and the status is
  `Disposed` once the publication ends. The guard changes in this ADR do not touch the walk, and
  population had already committed, so develop gives the same result. No conformance test covers
  this case. The `LIFE-015` clause covers the unpopulated container only (chapter 12).

## 3. Consequences

### 3.1 Flavors

- **TypeScript.** `CompositeVMBase._onConstruct` (`compositeVMBase.ts` line 640) and
  `GroupVM._onConstruct` (`groupVM.ts` line 412) check `#disposeRequested` and the `Disposed`
  status. An admitted supersession of `CompositeVM`, `CompositeVMOf` and `GroupVM` now ends
  `Disposed` with no children and no error, and the factory does not run. Before, the factory
  ran and `construct()` threw. The deferred case is unchanged: the factory runs once and
  `construct()` throws the disposing error. The public API does not change, so
  `langs/typescript/api/vmx.api.txt` does not change.
- **Rust.** `CompositeVm::populate` (`composites.rs` line 1604) checks `dispose_requested` and the
  `Disposed` status, as `GroupVm::populate` does. A dispose deferred by a publication now returns
  `Err(VmxError::Disposed)` from `construct()`, after one factory call. A dispose deferred by a
  membership transaction now returns `Err(VmxError::OwnershipTransactionInProgress)`, after one
  factory call. Before, both returned `Ok(())` without calling the factory. `GroupVm::populate`
  (`groups.rs` line 906) refuses a dispose deferred by a membership transaction with
  `Err(VmxError::Disposed)`, after one factory call and before its transaction begins. Before, it
  returned `Err(VmxError::OwnershipTransactionInProgress)`. No public member changes.
- **C#, Python and Swift.** No library code change. Each already follows §2.1. Their
  same-thread and deferred tests change, as §3.3 says.

### 3.2 Specification

Chapter 02 §2.4 names the admitted supersession, the deferred case and the refusal. The `LIFE-015`
clause in chapter 12 names the same cases, and it scopes the refusal to a container whose
population has not run. §2.5 gives the populated outcome. No conformance ID is added, and
`spec/VERSION` does not change.

`spec/HISTORY.md` §39 gets one sentence that names this ADR and states the admitted case. Issue
#1805 asked for no edit to `spec/HISTORY.md`, and this ADR keeps the edit anyway. The release-record
test (rule B in `tools/tests/test_adr_release_records.py`) requires the 3.30.0 section to name
every 3.30.0 ADR, and it fails without this sentence. The recent ADR-0248 to ADR-0250 pull requests
did the same.

### 3.3 Tests

Each flavor has a test for the admitted supersession and a test for the deferred case, and
the two GroupVM deferred tests added here cover the group in every flavor. The same-thread
tests of C#, Python and Swift assert the `construct()` outcome, so no test in those flavors
discards it.

- **TypeScript.** Three tests under `describe("LIFE-015")` in `lifecycle.test.ts` cover
  `CompositeVM`, `CompositeVMOf` and `GroupVM` in an admitted supersession. Each asserts that
  `construct()` does not throw, that the factory ran 0 times, that `count` is 0, and that the
  status is `Disposed`. Two more tests cover the deferred case: `CompositeVM` through a current
  publication, and `GroupVM` through its membership transaction. Each asserts the disposing error,
  one factory call, and the final status. The TypeScript tests are unchanged by this ADR.
- **C#.** `LIFE_015_Same_Thread_Container_Disposal_Inside_Hook_Cascades_Immediately` asserts that
  `Record.Exception(composite.Construct)` is null and that the factory ran 0 times.
  `CompositeVMConformanceTests` opposing-container test and `GroupVMConformanceTests` child-cascade
  test assert the `construct()` results. `LIFE_015_Deferred_Dispose_In_Hook_Refuses_Population_Attach`
  is new. `LIFE_015_Deferred_Group_Dispose_In_Hook_Refuses_Population_Attach` in
  `GroupVMConformanceTests.cs` is new. It asserts `ObjectDisposedException`, one factory call, and
  status `Disposed`.
- **Python.** `test_LIFE_015_same_thread_composite_disposal_inside_hook_cascades_immediately`
  calls `construct()` without a `try`, and it asserts that the factory ran 0 times. The opposing,
  child-cascade and group tests record the `construct()` errors and assert that there are none.
  `test_LIFE_015_deferred_dispose_in_hook_refuses_population_attach` is new.
  `test_LIFE_015_deferred_group_dispose_in_hook_refuses_population_attach` in `test_group_vm.py`
  is new. It asserts a `RuntimeError` with the disposing message, one factory call, and status
  `DISPOSED`.
- **Swift.** `testSameThreadDisposeInsideOwnHookCascadesImmediately` calls `construct()` in a
  `do` block whose `catch` calls `XCTFail`. In `ContainerHookDisposalTests` and
  `LifecycleRaceTests`, the `construct()` and `reconstruct()` results are recorded and asserted to
  be empty, where the test is about a superseded call. `testNoContainerHookIsAdmittedDuringItsChildCascade`
  and `testNoAggregateHookIsAdmittedDuringItsSlotCascade` (AggregateVM1 to AggregateVM6) assert the
  transition error that a construct from the cascade raises after `Disposed`
  (`Cannot construct from state Disposed.`). The cascade runs after `Disposed` is published, so
  this is not a superseded call. `testDeferredDisposeInsideOwnHookRefusesPopulationAttach` is new.
  It asserts that `construct()` throws `ContainerOwnershipError.attachmentFailed`, the case that
  the other Swift tests assert, and no longer matches a private type name.
  `testDeferredGroupDisposeInsideOwnHookRefusesPopulationAttach` is new and asserts the same.
- **Rust.** `child_cascade_waits_for_the_admitted_hook` asserts that the construct returns
  `Ok(())`, where it discarded the result before. `deferred_composite_dispose_in_hook_refuses_population_attach`
  is new and asserts `Err(VmxError::Disposed)`. `deferred_group_dispose_in_hook_refuses_population_attach`
  is new. It asserts `Err(VmxError::Disposed)`, because the group checks the deferred dispose
  before its population transaction begins (§2.4). It also asserts one factory call and status
  `Disposed`. The composite's membership case has no test in this PR.

### 3.4 Changelog

The TypeScript changelog's `Fixed` entry describes the admitted supersession only. The deferred
case did not change in TypeScript. The Rust changelog's `Fixed` entry for the deferred
composite case names both error variants. A second bullet in that entry covers the group's
membership refusal. The C#, Python and Swift changelogs each get an
`Added` entry for their test changes, under their current `unreleased source version` headings,
and each now also names the GroupVM deferred test. No other package changes.

### 3.5 Open decision and registry gap

- **Rust membership-transaction refusal: resolved for the group, open for the composite.** A
  dispose deferred by a membership transaction during the group's construct hook now returns
  `Err(VmxError::Disposed)` from `construct()`, after one factory call. `GroupVm::populate`
  (`groups.rs`) checks the deferred dispose before it begins its transaction, and the attach keeps
  its own check. Before, the group's transaction began first, and the call returned
  `OwnershipTransactionInProgress`. The group test asserts `Disposed`. The composite is not changed
  by this ADR. `CompositeVm::populate` still begins its transaction in `attach_population`, so a
  dispose deferred by a membership transaction still returns `OwnershipTransactionInProgress`
  (§2.4), and the composite's membership case does not meet the rule in §2.1. Two options remain,
  as before, and the owner has to choose one: move the composite's disposal check ahead of its
  transaction, a Rust library change of the same kind as the group's, or keep the error and amend
  the spec clause to name it.
- **Registry gap.** The number 0251 is held by open PR #2236 (ADR-0251, #1917), which is not on
  develop yet. So the registry goes from 0250 to 0252 until that PR merges. This ADR does not depend
  on ADR-0251.

## 4. Conformance

- Before the change, the deferred cases diverged. In Rust the composite returned `Ok(())` without a
  factory call. TypeScript, C#, Python and Swift called the factory once and refused the attach.
  The Rust mutation below shows the old Rust result: `Ok(())`.
- Mutation, TypeScript composite: removing the guard from `CompositeVMBase._onConstruct` fails
  the two superseded tests, "skips CompositeVM population when its construct hook disposes it"
  and "skips CompositeVMOf population when its construct hook disposes it". The deferred case
  still passes, because the attach refusal alone gives that outcome.
- Mutation, TypeScript deferred clause: adding `#disposeDeferred` to the `CompositeVMBase` guard
  fails "refuses CompositeVM population when its construct hook's dispose is deferred by a
  publication". Adding it to the `GroupVM` guard fails "refuses GroupVM population when its
  construct hook's dispose is deferred by a membership transaction".
- Mutation, Rust composite: adding `disposal_pending()` to `CompositeVm::populate` fails
  `deferred_composite_dispose_in_hook_refuses_population_attach` with `left: Some(Ok(()))` and
  `right: Some(Err(Disposed))`.
- Mutation, Rust group: removing the deferred check from `GroupVm::populate`, which restores the
  order before this change, fails `deferred_group_dispose_in_hook_refuses_population_attach` with
  `left: Some(Err(OwnershipTransactionInProgress))` and `right: Some(Err(Disposed))`. This is the
  observed result on this branch.
- Mutation, C#: adding `_disposeDeferred` to the `GroupVMBase.OnConstruct` guard fails
  `LIFE_015_Deferred_Group_Dispose_In_Hook_Refuses_Population_Attach`, where `constructError` is null.
- Mutation, Python: adding `_dispose_deferred` to `GroupVM._population_superseded` fails
  `test_LIFE_015_deferred_group_dispose_in_hook_refuses_population_attach`, where no construct error
  is recorded.
- Mutation, Swift: adding `disposeDeferred` to the `GroupVM._onConstruct` guard fails
  `testDeferredGroupDisposeInsideOwnHookRefusesPopulationAttach`, where `construct()` does not throw
  and the factory does not run.
- Each mutation was reverted before the gates ran. The library diff is the intended change only.

## 5. Rejected alternatives

### 5.1 Keep the rule foreign-only

A foreign-only rule gives TypeScript no case to apply, because a foreign dispose cannot reach a
TypeScript hook. TypeScript would then keep the throw for the only reachable case. Rejected.

### 5.2 Option B: the construct throws in all five flavors

A same-thread dispose from the hook would make `construct()` throw in C#, Python, Swift and Rust.
This changes four flavors that behave correctly now. In TypeScript the factory would run once
before the throw, which the factory clause forbids. It would also contradict §7.2, which says a
superseded call raises nothing. A consumer that cancels a screen from its construct hook would then
get an exception in every flavor. Rejected.

### 5.3 Count a deferred dispose as a supersession

Skipping population for a deferred dispose too would make `construct()` return without an error
in every flavor. Relative to develop, it changes the deferred case in TypeScript, C#, Python and
Swift, and in Rust's group population. Rust's composite population already skips it on develop.
The deferred dispose also runs only when its transaction or publication ends, so the container is
not yet `Disposed` when `construct()` returns. §2.1 item 4 does not allow that state for a
superseded hook. Rejected.
