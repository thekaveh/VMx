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

Before this ADR, `CompositeVMBase._onConstruct` and `GroupVM._onConstruct` ran population after
the hook with no supersession check. A dispose in the hook set the disposal flags, so the
factory ran, and the first admission check threw `Cannot attach a child while the container is disposing`. `construct()` rethrew that error. In that sequence the factory ran once, the
error was thrown, and the final status was `Disposed` with no children. Issue #1805 reproduces
this for `CompositeVM`, `CompositeVMOf` and `GroupVM`.

### 1.3 What the other flavors do

Before this ADR, C#, Python, Swift and Rust returned from the construct path when an admitted
dispose superseded the hook. Their population and walk did not run, and `construct()` returned
without an error. Their same-thread tests covered this path. The C#, Python and Swift tests
discarded the `construct()` outcome, and the Rust test asserted `Ok(())`. Section 3.3 records
those test changes.

The flavors did not agree on a dispose that a membership transaction or a current publication
of the container defers during the hook. Before this ADR:

- C#, Python and Swift returned from the construct path only when an admitted dispose had
  superseded the hook. A deferred dispose still reached population, and the attach refused it
  with the disposing error.
- Rust's composite population and TypeScript's guards also checked the deferred flag. They
  returned without an error and without calling the factory. Rust's group population checked
  only the admitted flag, as the other flavors do.

After this ADR, one rule holds in all five flavors. §2.1 states it, and §2.4 gives the
reachability and the guards.

## 2. Decision

### 2.1 The rule

A dispose supersedes a container's construct hook only when it is admitted. A dispose that a
membership transaction or current publication of the container defers is not admitted, so it
does not supersede the hook.

1. **Admitted supersession.** A container whose construct hook an admitted `dispose()`
   superseded:

   1. does not call its children factory, and attaches nothing;
   1. does not run the child construct walk;
   1. returns from `construct()` without an error;
   1. ends with status `Disposed` and no children.

   The supersession counts whether the `dispose()` is foreign or comes from the hook's own body.

1. **Deferred dispose.** A `dispose()` that is deferred during the hook does not supersede it.
   Population runs and calls the children factory once. Its attach is refused with the
   disposing error that every flavor already raises for an attach during a requested or
   deferred disposal (chapter 06 §4.3 rule 1), so `construct()` reports that error. Nothing
   attaches. The deferred disposal completes when its membership transaction or publication
   ends.

Chapter 02 §2.4 and the `LIFE-015` clause name both cases. The code follows them in all five
flavors (§2.4).

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

Issue #1805 sets two options. Team triage on develop `7d445367` chose option A. This ADR
records the choice and its reasons.

- **Option A (chosen).** The rule in §2.1 covers any admitted supersession, from the hook's own
  body or from another thread. TypeScript gains the supersession check that the other four
  flavors already have. The deferred case in §2.4 changes TypeScript and Rust.
- **Option B (rejected, see §5.2).** A same-thread dispose from the hook makes `construct()`
  throw. Four flavors change.

Option A was chosen for three reasons:

- It agrees with chapter 02 §2.4, the factory clause and §7.2, and it changes no rule.
- It changes fewer flavors than option B, and option B makes the TypeScript factory run once
  before the throw, which the factory clause forbids.
- It is the simplest option that gives every flavor the same behavior, which is the goal
  of this wave's triage.

### 2.4 The deferred case and the guards

**Reachability.** A dispose is deferred during a construct hook when the container's own
membership transaction or current publication is open on the disposing thread. The public API
reaches that state. Setting `current` to a member of a container that is not constructed yet
publishes the change under the publication lease. The container's `onCurrentChanged` callback
then calls `construct()`, and the hook calls `dispose()`, which is deferred:

| Flavor     | Where the dispose is deferred                                                                                                                                                                             | Test that reaches it                                                                                                                                                                      |
| ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| TypeScript | `langs/typescript/src/composites/compositeVMBase.ts` `dispose()`, when `#activeCurrentPublications > 0` or a transaction is open. The group path is `langs/typescript/src/groups/groupVM.ts` `dispose()`. | `lifecycle.test.ts`: "refuses CompositeVM population when its construct hook's dispose is deferred by a publication" and the GroupVM test that uses the membership transaction of `add()` |
| Python     | `langs/python/src/vmx/composites/composite_vm.py` `dispose()`, when `get_ident()` is in `_current_publication_threads` or a transaction is open                                                           | `test_composite_vm.py`: `test_LIFE_015_deferred_dispose_in_hook_refuses_population_attach`                                                                                                |
| C#         | `langs/csharp/src/VMx/Composites/CompositeVMBase.cs` `Dispose()`, when the thread holds a publication or a transaction is open                                                                            | `CompositeVMConformanceTests.cs`: `LIFE_015_Deferred_Dispose_In_Hook_Refuses_Population_Attach`                                                                                           |
| Swift      | `langs/swift/Sources/VMx/Composites/CompositeVM.swift` `dispose()`, when `currentPublicationThreads` contains the caller or a transaction is open                                                         | `ContainerHookDisposalTests.swift`: `testDeferredDisposeInsideOwnHookRefusesPopulationAttach`                                                                                             |
| Rust       | `langs/rust/src/composites.rs` `dispose()`, when `dispose_disposition()` returns `PublishingThread` or `Owned` (`langs/rust/src/runtime.rs`)                                                              | `container_hook_disposal.rs`: `deferred_composite_dispose_in_hook_refuses_population_attach`                                                                                              |

The reachability was checked by running the public API. In TypeScript, the sequence with the old
guard returned without an error and made no factory call. After the change it makes one factory
call and throws. In Python, before the change, the factory ran once and the attach raised
`RuntimeError`.

**The guards before and after this ADR:**

| Flavor     | Guard that gates population in the construct hook                               | Deferred case before this ADR | Deferred case after this ADR            |
| ---------- | ------------------------------------------------------------------------------- | ----------------------------- | --------------------------------------- |
| TypeScript | `#disposePending()` (requested or deferred), in `CompositeVMBase` and `GroupVM` | No factory call, no error     | Factory once, attach throws             |
| Rust       | `CompositeVm::populate` checked `disposal_pending()` (requested or deferred)    | No factory call, `Ok(())`     | Factory once, `Err(VmxError::Disposed)` |
| C#         | `DisposalStarted()` (requested or Disposed)                                     | Factory once, attach throws   | Unchanged                               |
| Python     | `_population_superseded()` (requested or Disposed)                              | Factory once, attach raises   | Unchanged                               |
| Swift      | `_isDisposalRequested()` (requested or Disposed)                                | Factory once, attach throws   | Unchanged                               |

`CompositeVm::populate` in Rust and the TypeScript guards now check only the admitted flag and
the `Disposed` status, which matches C#, Python and Swift. Rust's `GroupVm::populate` already
did this. The other flavors' guards are unchanged.

**The choice.** The uniform rule is the admitted-flag rule in §2.1. It was chosen for three
reasons:

- It matches the most flavors. C#, Python and Swift already check only the admitted flag, and
  Rust's group does too. The other option changes three flavors (C#, Python, Swift).
- It matches the spec. Chapter 02 §2.4 speaks of "terminal supersession", and a foreign
  dispose "publishes the terminal status". A deferred dispose is not terminal yet. Chapter 06
  §4.3 rule 1 distinguishes "requested" from "deferred" and refuses attaches in both.
- It is the smallest change: two guard edits, and no change to C#, Python or Swift library code.

The attach refusal applies to a deferred dispose in every flavor, so population refuses it the
same way. The error type is idiomatic per flavor: `ObjectDisposedException` in C#,
`RuntimeError` in Python, `ContainerOwnershipError.attachmentFailed` in Swift, `VmxError::Disposed`
in Rust, and `Error` with the message `Cannot attach a child while the container is disposing`
in TypeScript.

### 2.5 Behavior that does not change

- A dispose inside the children factory still throws in TypeScript, because the admission check
  rejects it. The existing `LIFE-013` test "rejects composite and group factory output produced
  after reentrant disposal" keeps asserting this. Its case differs: the dispose is in the factory,
  not in the construct hook.
- An `add()` during disposal still fails with the disposing error.
- A dispose after population, outside the hook, follows the rules it followed before.

## 3. Consequences

### 3.1 Flavors

- **TypeScript.** `CompositeVMBase._onConstruct` and `GroupVM._onConstruct` check
  `#disposeRequested` and the `Disposed` status. An admitted supersession of
  `CompositeVM`, `CompositeVMOf` and `GroupVM` now ends `Disposed` with no children and no
  error, and the factory does not run. A deferred dispose now calls the factory once and the
  construct throws the disposing error. The public API does not change, so
  `langs/typescript/api/vmx.api.txt` does not change.
- **Rust.** `CompositeVm::populate` checks `dispose_requested` and the `Disposed` status, as
  `GroupVm::populate` does. A deferred dispose now returns `Err(VmxError::Disposed)` from
  `construct()`, after one factory call. No public member changes.
- **C#, Python and Swift.** No library code change. Each already follows §2.1. Their
  same-thread and deferred tests change, as §3.3 says.

### 3.2 Specification

Chapter 02 §2.4 names the admitted supersession and the deferred case. The `LIFE-015` clause in
chapter 12 names both too. No conformance ID is added, and `spec/VERSION` does not change.

`spec/HISTORY.md` §39 gets one sentence that names this ADR. Issue #1805 asked for no edit to
`spec/HISTORY.md`, and this ADR keeps the edit anyway. The release-record test (rule B in
`tools/tests/test_adr_release_records.py`) requires the 3.30.0 section to name every 3.30.0 ADR,
and it fails without this sentence. The recent ADR-0248 to ADR-0250 pull requests did the same.

### 3.3 Tests

Each flavor has a test for the admitted supersession and a test for the deferred case. The
same-thread tests of C#, Python and Swift assert the `construct()` outcome, so no test in those
flavors discards it.

- **TypeScript.** Three tests under `describe("LIFE-015")` in `lifecycle.test.ts` cover
  `CompositeVM`, `CompositeVMOf` and `GroupVM` in an admitted supersession. Each asserts that
  `construct()` does not throw, that the factory ran 0 times, that `count` is 0, and that the
  status is `Disposed`. Two more tests cover the deferred case: `CompositeVM` through a current
  publication, and `GroupVM` through its membership transaction. Each asserts the disposing error,
  one factory call, and the final status.
- **C#.** `LIFE_015_Same_Thread_Container_Disposal_Inside_Hook_Cascades_Immediately` asserts that
  `Record.Exception(composite.Construct)` is null and that the factory ran 0 times.
  `CompositeVMConformanceTests` opposing-container test and `GroupVMConformanceTests` child-cascade
  test assert the `construct()` results. `LIFE_015_Deferred_Dispose_In_Hook_Refuses_Population_Attach`
  is new.
- **Python.** `test_LIFE_015_same_thread_composite_disposal_inside_hook_cascades_immediately`
  calls `construct()` without a `try`, and it asserts that the factory ran 0 times. The opposing,
  child-cascade and group tests record the `construct()` errors and assert that there are none.
  `test_LIFE_015_deferred_dispose_in_hook_refuses_population_attach` is new.
- **Swift.** `testSameThreadDisposeInsideOwnHookCascadesImmediately` calls `construct()` in a
  `do` block whose `catch` calls `XCTFail`. In `ContainerHookDisposalTests` and
  `LifecycleRaceTests`, the `construct()` and `reconstruct()` results are recorded and asserted to
  be empty, where the test is about a superseded call. `testNoContainerHookIsAdmittedDuringItsChildCascade`
  and `testNoAggregateHookIsAdmittedDuringItsSlotCascade` (AggregateVM1 to AggregateVM6) assert the
  transition error that a construct from the cascade raises after `Disposed`
  (`Cannot construct from state Disposed.`). The cascade runs after `Disposed` is published, so
  this is not a superseded call. `testDeferredDisposeInsideOwnHookRefusesPopulationAttach` is new.
- **Rust.** `child_cascade_waits_for_the_admitted_hook` asserts that the construct returns
  `Ok(())`, where it discarded the result before. `deferred_composite_dispose_in_hook_refuses_population_attach`
  is new.

### 3.4 Changelog

The TypeScript changelog's `Fixed` entry states the admitted supersession and the deferred case.
The Rust changelog gets a `Fixed` entry for the deferred case. The C#, Python and Swift
changelogs each get an `Added` entry for their test changes, under their current
`unreleased source version` headings. No other package changes.

## 4. Conformance

- Before the change, the deferred cases diverged. In TypeScript the construct returned without an
  error and made no factory call. In Python the factory ran once and the attach raised. The Rust
  mutation below shows the old result: `Ok(())`.
- Mutation, TypeScript composite: removing the guard from `CompositeVMBase._onConstruct` fails
  the two superseded tests, "skips CompositeVM population when its construct hook disposes it"
  and "skips CompositeVMOf population when its construct hook disposes it". The deferred case
  still passes, because the attach refusal alone gives that outcome.
- Mutation, TypeScript deferred clause: restoring `#disposeDeferred` to the `CompositeVMBase`
  guard fails "refuses CompositeVM population when its construct hook's dispose is deferred by a
  publication". Restoring it to the `GroupVM` guard fails "refuses GroupVM population when its
  construct hook's dispose is deferred by a membership transaction".
- Mutation, Rust: restoring `disposal_pending()` to `CompositeVm::populate` fails
  `deferred_composite_dispose_in_hook_refuses_population_attach` with `left: Some(Ok(()))` and
  `right: Some(Err(Disposed))`.
- Each mutation was reverted before the gates ran. The library diff is the intended change only.

## 5. Rejected alternatives

### 5.1 Keep the rule foreign-only

A foreign-only rule gives TypeScript no case to apply, because a foreign dispose cannot reach a
TypeScript hook. TypeScript would then keep the throw for the only reachable case. Rejected.

### 5.2 Option B: the construct throws in all five flavors

A same-thread dispose from the hook would make `construct()` throw in C#, Python, Swift and
Rust. This changes four flavors that behave correctly now. In TypeScript the factory would
run once before the throw, which the factory clause forbids. It would also contradict §7.2,
which says a superseded call raises nothing. A consumer that cancels a screen from its construct
hook would then get an exception in every flavor. Rejected.

### 5.3 Count a deferred dispose as a supersession

Skipping population for a deferred dispose too would make `construct()` return without an error
in every flavor, but it changes three flavors (C#, Python and Swift), which check only the admitted
flag. The deferred dispose also runs only when its transaction or publication ends, so the
container is not yet `Disposed` when `construct()` returns. §2.1 item 4 does not allow that state
for a superseded hook. Rejected.
