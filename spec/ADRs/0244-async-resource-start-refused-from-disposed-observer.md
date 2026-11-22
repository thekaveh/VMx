# ADR 0244 — A load or reload from an observer of the Disposed publication starts no loader

- **Status:** Accepted
- **Date:** 2026-11-21
- **Spec version:** 3.30.0 (chapter 12 `ARES-011`; chapter 23 §10 unchanged; no new conformance ID)
- **Clarifies:** [ADR-0100](0100-async-resource-vm.md) (its disposal rule, chapter 23 §10). Related: #1851, PR #2045 (TypeScript), #729 (the C# sibling for `Cancel()` from a `Loading` observer).

## 1. Context

Chapter 23 §10 says that after `Dispose` all commands and direct intents are inert.
It does not say whether an observer of the `Disposed` publication, which runs before
`Dispose` returns, counts as "after". Chapter 12 `ARES-011` did not name that case either.

Every flavor publishes `Disposed` before it runs `_onDispose()`. In the Swift flavor,
`_applyLifecyclePublicationLocked` sets `status` to `.disposed` under the lifecycle lock,
then `_deliverLifecyclePublication` sends the `ConstructionStatusChangedMessage` to the hub.
Observers run there. `_finishDisposalNow` calls `_onDispose()` only after that delivery.
`AsyncResourceVM._onDispose()` sets the disposal flag `resourceDisposed`, and `admit()`
checked only that flag.

An observer that spawns a task and calls `load()` on another thread could therefore be
admitted before `resourceDisposed` was set. The loader ran, the state stayed at `Loading`,
and the operation was cancelled and discarded by disposal. On origin/develop `9b161089`, a
200-iteration probe in which the observer calls `load()` ran the loader in 114 iterations.
A stopped earlier run measured 194 and then 193 of 200. The state stayed `Loading` in 184
of the 200 probe iterations. The TypeScript flavor had the same defect and fixed it in PR #2045.

Python has the same window. `_on_dispose()` sets `_resource_disposed` after the `DISPOSED`
status is published. A scheduled load, which is the form the existing conformance test uses,
runs after `dispose()` returns and is refused. A synchronous observer that drives the load to
completion inside the publication, with `asyncio.run(vm.load())`, is not refused. On origin/develop
`9b161089`, the loader runs once and the synchronous test fails with `assert calls == 0` (`1 == 0`).
The measurement is in §2.4.

## 2. Decision

### 2.1 The rule

In every flavor, a `load()` or `reload()` admitted from an observer of the `Disposed` publication
starts no loader. The state stays externally unchanged. A command that runs the same intent is
inert in the same way. Chapter 12 `ARES-011` names this case in its catalog text. Chapter 23 §10
keeps its wording, because "all commands and direct intents are inert afterward" already covers
the case once the observer is read as after the `Disposed` publication.

Python is in scope for its synchronous form too. The `ARES-011` catalog clause is stated for every
flavor, and issue #1851 asks that the `ARES-011` test of each of the five flavors start an intent
from a `Disposed` observer. A Python change that covered only the scheduled form would leave the
clause unmet for the synchronous form, and §1 shows that form is reachable on develop.

### 2.2 The check

In Swift, C#, TypeScript and Python, a start is refused when the VM's `status` is `Disposed`, in
addition to the disposal flag. The base sets `Disposed` before it publishes, and the disposal
flag is set later, in `_onDispose()`. The status is therefore the signal that is set first, and an
observer of the publication sees only the status. Each flavor applies the check where its start
path admits an intent:

- Swift: `admit()` refuses while `status` is `.disposed`. The read takes the lifecycle lock.
- C#: `StartAsync` refuses when `Status == ConstructionStatus.Disposed`.
- TypeScript: `#isInert()` checks the status. Its command predicates use it too (PR #2045).
- Python: `_is_inert()` is true when the disposal flag is set or `status` is `DISPOSED`. Its
  `_can_load`, `_can_reload` and `_start` call it. The `status` read is a plain attribute read with
  no lock, so it adds no lock order under the resource gate.
- Rust: no status check is added. `dispose()` sets `machine.disposed` under the machine lock
  before the component publishes `Disposed`, so the existing guards already refuse a start
  from an observer.

The status is used rather than a new flag in the four flavors that check it. A new flag
would need its own write, and setting the disposal flag earlier would move `_onDispose()`
ahead of the publication. That moves cleanup and cancellation for every component, which
this defect does not need.

### 2.3 Command enablement and cancellation

The rule does not require a command predicate to change in Swift and C#. Their commands run
and start nothing, because the start is refused in the body. TypeScript reads the status in its
command predicates too (PR #2045). Python's `_can_load` and `_can_reload` are the predicates of its
load and reload commands, so those commands report not executable from the `Disposed` publication
on, as in TypeScript. In each flavor, the guarantee is the same: the loader does not run, and the
state stays unchanged.

`cancel()` stays admitted from a `Disposed` observer. It finds no current operation and
changes no state.

### 2.4 Tests

Swift has two new tests, `testAres011LoadFromDisposedObserverStartsNoLoader` and
`testAres011ReloadFromDisposedObserverStartsNoLoader`. Each one keeps the observer's task,
awaits it after `dispose()` returns, and then checks the loader count.

C#, TypeScript and Rust already have observer tests for this case on origin/develop: C#
`ARES_011_Load_From_A_Disposed_Observer_Starts_No_Loader`, the TypeScript `describe("ARES-011")`
observer tests, and Rust `async_resource_load_from_disposed_observer_starts_no_loader`.

Python has two tests in `langs/python/tests/conformance/test_async_resource_vm.py`, both marked
`ARES-011`:

- `test_ares_011_load_from_disposed_observer_starts_no_loader` schedules the load on the running
  loop, awaits it after `dispose()` returns, and checks the loader count. It passes on
  origin/develop's Python library.
- `test_ares_011_synchronous_load_from_disposed_observer_starts_no_loader` is new. Its observer
  drives `asyncio.run(vm.load())` to completion inside the publication, then checks the loader
  count and the state. It fails on origin/develop's Python library and passes on this change.

Measured evidence on origin/develop `9b161089`: with `langs/python/src/vmx/state/async_resource_vm.py`
taken from develop and the rest of `langs/python` as on this change,
`uv run pytest tests/conformance/test_async_resource_vm.py -k ares_011` gives
`E       assert 1 == 0` and `1 failed, 5 passed`. The failing test is the synchronous one.

Mutation evidence (Python, applied to this change's `_is_inert()`, then reverted with
`langs/python` identical to the Python tree of commit `3840ffc8`): removing the
`or self.status is ConstructionStatus.DISPOSED` term gives the same `assert 1 == 0` and
`1 failed, 5 passed`. With that term removed, the start path tests only the disposal flag, as on
develop.

Mutation evidence (Swift, applied to this change's `admit()`, then reverted with the library
identical to HEAD): removing the `status != .disposed` term makes the load test fail with
`XCTAssertEqual failed: ("1") is not equal to ("0")` and
`("ready") is not equal to ("idle")`. Two runs of the load test gave the same result. The
mutation also makes the reload test fail with `("2") is not equal to ("1")` and
`("[1, 2]") is not equal to ("[1]")`.

## 3. Consequences

- A `Disposed` observer can issue `load()` or `reload()` in every flavor. The loader does not run,
  and the state keeps its value from before disposal. In Python this holds for the scheduled form
  and the synchronous form.
- The Swift check reads the status under the lifecycle lock while `admit()` holds the resource
  lock. The lifecycle code never calls an `AsyncResourceVM` method while it holds the lifecycle
  lock, and `_onDispose()` runs after that lock is released. The new read therefore adds no lock
  cycle.
- The Python check reads `status` without a lock, under the resource gate. The lifecycle lock is
  not taken there, so no new lock order is added.
- No public API changes, and no fixture changes.

## 4. Rejected alternatives

- Set the disposal flag before the `Disposed` publication. This moves `_onDispose()` ahead of
  observers for every component, which is wider than this defect. Rejected.
- Refuse starts in the command predicates only. A direct `load()` call would still reach the
  loader, and the rule covers direct intents too. Rejected.
- Add a public disposed predicate first (#1614). It would only name the same check. Not needed
  for this fix.
- Leave Python's synchronous form for a follow-up. §2.1 binds Python to the `ARES-011` clause, and
  §1 measures the gap on develop. Rejected.
