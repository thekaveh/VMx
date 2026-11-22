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

## 2. Decision

### 2.1 The rule

In every flavor, a `load()` or `reload()` admitted from an observer of the `Disposed`
publication starts no loader. The state stays externally unchanged. A command that runs
the same intent is inert in the same way. Chapter 12 `ARES-011` names this case in its
catalog text. Chapter 23 §10 keeps its wording, because "all commands and direct intents
are inert afterward" already covers the case once the observer is read as after the
`Disposed` publication.

### 2.2 The check

In Swift, C#, TypeScript and Python, a start is refused when the VM's `status` is
`Disposed`, in addition to the disposal flag. The base sets `Disposed` before it publishes,
and the disposal flag is set later, in `_onDispose()`. The status is therefore the signal
that is set first, and an observer of the publication sees only the status. Each flavor
applies the check where its start path admits an intent:

- Swift: `admit()` refuses while `status` is `.disposed`. The read takes the lifecycle lock.
- C#: `StartAsync` refuses when `Status == ConstructionStatus.Disposed`.
- TypeScript: `#isInert()` checks the status. Its command predicates use it too (PR #2045).
- Python: `_is_inert()` checks the status. `_can_load`, `_can_reload` and both guards of
  `_start` use it, so the command predicates use it too. The read takes no lock, because
  the status is one attribute that the lifecycle lock writes.
- Rust: no status check is added. `dispose()` sets the disposal flag under the machine lock
  before the component publishes `Disposed`, so the existing guards already refuse a start
  from an observer.

The status is used rather than a new flag in the four flavors that check it. A new flag
would need its own write, and setting the disposal flag earlier would move `_onDispose()`
ahead of the publication. That moves cleanup and cancellation for every component, which
this defect does not need.

### 2.3 Command enablement and cancellation

The rule does not require a command predicate to change in Swift and C#. Their commands run
and start nothing, because the start is refused in the body. Python and TypeScript read the
status in their command predicates too, so their commands report not executable from the
`Disposed` publication on. The guarantee is the same in all flavors: the loader does not run,
and the state stays unchanged.

`cancel()` stays admitted from a `Disposed` observer. It finds no current operation and
changes no state.

### 2.4 Tests

Each flavor's `ARES-011` tests cover the case. The Swift tests are
`testAres011LoadFromDisposedObserverStartsNoLoader` and
`testAres011ReloadFromDisposedObserverStartsNoLoader`. Each one keeps the observer's
task, awaits it after `dispose()` returns, and then checks the loader count.

The Python test is `test_ares_011_synchronous_load_from_disposed_observer_starts_no_loader`.
Its observer drives the load with `asyncio.run(vm.load())` instead of scheduling a task.
A scheduled task runs after `dispose()` returns, when the disposal flag is already set, so
the existing Python test (`test_ares_011_load_from_disposed_observer_starts_no_loader`)
passes without the status check. The synchronous form is the one that reaches the window.
The C#, TypeScript and Rust `ARES-011` tests already cover the observer case (C#
`ARES_011_Load_From_A_Disposed_Observer_Starts_No_Loader`, the TypeScript `describe("ARES-011")`
observer tests, and Rust `async_resource_load_from_disposed_observer_starts_no_loader`).

Mutation evidence: removing the `status != .disposed` check from `admit()` makes the Swift load
test fail (loader calls 1, expected 0, and state `loading`, expected `idle`). It makes the Swift
reload test fail (loader calls 2, expected 1, and cleaned `[1, 2]`, expected `[1]`).
Removing the `status is DISPOSED` term from Python's `_is_inert()` makes the synchronous test
fail (`assert calls == 0`, with `1 == 0`), and the existing scheduled-task test still passes.

## 3. Consequences

- A `Disposed` observer can issue `load()` or `reload()` in any flavor. The loader does not
  run, and the state keeps its value from before disposal.
- The Swift check reads the status under the lifecycle lock while `admit()` holds the
  resource lock. The lifecycle code never calls an `AsyncResourceVM` method while it holds
  the lifecycle lock, and `_onDispose()` runs after that lock is released. The new read
  therefore adds no lock cycle.
- No public API changes, and no fixture changes.

## 4. Rejected alternatives

- Set the disposal flag before the `Disposed` publication. This moves `_onDispose()` ahead of
  observers for every component, which is wider than this defect. Rejected.
- Refuse starts in the command predicates only. A direct `load()` call would still reach the
  loader, and the rule covers direct intents too. Rejected.
- Add a public disposed predicate first (#1614). It would only name the same check. Not needed
  for this fix.
