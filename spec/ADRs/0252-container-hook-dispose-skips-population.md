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
name a foreign dispose.

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

C#, Python, Swift and Rust return from the construct path when the hook superseded it.
Their population and walk do not run, and `construct()` returns without an error. Their
same-thread tests cover this path. The C#, Python and Swift tests discard the `construct()`
outcome, and the Rust test asserts `Ok(())`. This ADR does not change those tests.

## 2. Decision

### 2.1 The rule

A dispose that supersedes a container's construct hook stops population and the child walk.
The supersession counts whether the `dispose()` is foreign or comes from the hook's own
body. A container whose construct hook a `dispose()` superseded:

1. does not call its children factory, and attaches nothing;
1. does not run the child construct walk;
1. returns from `construct()` without an error;
1. ends with status `Disposed` and no children.

Chapter 02 §2.4 and the `LIFE-015` clause name this case. The TypeScript code follows it.

### 2.2 Why the rule covers a dispose from the hook's own body

The factory clause names a foreign `dispose()` because ADR-0218 rule 5 was written from the
foreign-dispose fix in #1369, which covered Python and C#. Three points show that the clause
was not meant to exclude a same-thread dispose.

1. The general sentences of §2.4 and `LIFE-015` name no thread. "Terminal supersession
   prevents any post-hook container lifecycle work" applies to any terminal supersession.
1. A dispose from the hook's own body sets the same disposal flags and publishes the same
   `Disposed` status as a foreign dispose in every flavor. A post-hook action that checks the
   supersession must therefore stop for both. Chapter 02 §7 says that a dispose from the hook's
   own thread is "not foreign", which decides only how the children are disposed (inline,
   under §7.2). It does not allow population to run.
1. Chapter 02 §7.2 says a call that `Disposed` superseded raises nothing. A population that
   throws for a same-thread dispose would break that rule.

For TypeScript, point 1 decides the case. The thread-based wording would give TypeScript no
supersession case at all, because a foreign dispose is impossible there.

### 2.3 Choice between option A and option B

Issue #1805 sets two options. Team triage on develop `7d445367` chose option A. This ADR
records the choice and its reasons.

- **Option A (chosen).** The rule in §2.1 covers any supersession. Only TypeScript changes.
  The TypeScript code gains the supersession check after the hook that the other four
  flavors already have.
- **Option B (rejected, see §5.2).** A same-thread dispose from the hook makes `construct()`
  throw. Four flavors change.

Option A was chosen for three reasons:

- It agrees with chapter 02 §2.4, the factory clause and §7.2, and it changes no rule.
- It changes one flavor. Option B changes four and makes the TypeScript factory run once before
  the throw, which the factory clause forbids.
- It is the simplest option that gives every flavor the same behavior, which is the goal
  of this wave's triage.

### 2.4 The TypeScript guard

`CompositeVMBase._onConstruct` returns after `super._onConstruct()` when
`#disposePending() || status === ConstructionStatus.Disposed`. `GroupVM._onConstruct` returns
under the same condition, written as `#disposeRequested || #disposeDeferred`, then `status === Disposed`. `#disposePending()` is the existing check for a requested or deferred dispose.
The `Disposed` check matches the Python `_population_superseded()` and the C#
`DisposalStarted()` checks, which both include a disposed status.

The `#disposeDeferred` part is included, as the issue's default plan says. A dispose that a
membership transaction or a current publication deferred still stops population in TypeScript.
Rust uses the same deferred condition. C#, Python and Swift check only the admitted dispose
flag, so a dispose deferred during the hook still reaches their admission check and throws
there. No test covers that corner in any flavor. This ADR does not change those flavors. The
difference is recorded here as an open corner, not as a decided behavior.

### 2.5 Behavior that does not change

- A dispose inside the children factory still throws in TypeScript, because the admission check
  rejects it. The existing `LIFE-013` test "rejects composite and group factory output produced
  after reentrant disposal" keeps asserting this. Its case differs: the dispose is in the factory,
  not in the construct hook.
- An `add()` during disposal still fails with the disposing error.
- A dispose after population, outside the hook, follows the rules it followed before.

## 3. Consequences

### 3.1 Flavors

- **TypeScript.** `CompositeVMBase._onConstruct` and `GroupVM._onConstruct` gain the early return.
  `CompositeVM`, `CompositeVMOf` and `GroupVM` now end with status `Disposed`, no children and no
  error, and the factory does not run. The public API does not change, so
  `langs/typescript/api/vmx.api.txt` does not change.
- **C#, Python, Swift and Rust.** No code change. Each already returns from the construct path
  for a superseded hook.

### 3.2 Specification

Chapter 02 §2.4 names the same-thread case. The `LIFE-015` clause in chapter 12 names it too.
No conformance ID is added, and `spec/VERSION` does not change.

`spec/HISTORY.md` §39 gets one sentence that names this ADR. The release-record test (rule B in
`tools/tests/test_adr_release_records.py`) requires the 3.30.0 section to name every 3.30.0 ADR,
and the recent ADR-0248 to ADR-0250 pull requests did the same. Issue #1805 asked for no edit to
`spec/HISTORY.md`. This ADR departs from that request, because the test fails without the
sentence.

### 3.3 Tests

Three TypeScript tests under `describe("LIFE-015")` in `lifecycle.test.ts` cover
`CompositeVM`, `CompositeVMOf` and `GroupVM`. Each disposes its container in the construct hook.
Each asserts that `construct()` does not throw, that the factory ran 0 times, that `count` is 0,
and that the status is `Disposed`.

The C#, Python and Swift same-thread tests still discard the `construct()` outcome. The Rust test
asserts `Ok(())`. This ADR leaves those tests unchanged, because the scope of issue #1805 is
TypeScript.

### 3.4 Changelog

The TypeScript changelog gets a `Fixed` entry under the current `unreleased source version`
heading. No other package changes.

## 4. Conformance

- The three new tests fail before the fix with `Cannot attach a child while the container is disposing` in each case, and pass after it.
- Mutation: removing the early returns from `CompositeVMBase._onConstruct` and
  `GroupVM._onConstruct` makes all three tests fail again with the same error. The
  library diff is empty after the mutation is reverted.

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
