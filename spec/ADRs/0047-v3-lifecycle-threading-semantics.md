# ADR 0047 — v3 lifecycle/threading semantics: atomic transitions, foreground-marshalling, and transactional hook-failure rollback

**Status:** Accepted (2026-06-28)
**Spec version:** 3.0.0

## 1. Context

The v3 framework overhaul hardened the lifecycle/dispose concurrency path, which
the merged framework critique (`docs/audit/2026-06-27-vmx-merged-critique.md`)
identified as the structural weak point of the framework (VMX-001/002/003/004/025
/054). The hardening landed in code first (commits 4afc9b6, fd4423b, 47fcf00,
d4bb28a, 6ffc0bd) but the normative chapters (`02-lifecycle.md`,
`11-threading.md`) still described the pre-v3, non-atomic behavior. This ADR
reconciles the spec with the implemented v3 semantics and decides the one
remaining behavior gap (VMX-007).

The findings reconciled here:

- **VMX-001 / VMX-004 / VMX-054** — a background `construct → SetStatus` path
  raced `dispose()` (non-volatile/unsynchronized `_status`), risking VM
  resurrection, a post-dispose hub publish, and `ObjectDisposedException` /
  `on_next`-on-disposed-Subject on the pool thread.
- **VMX-025 / VMX-048** — there was no foreground-marshalling primitive: a
  background completion flipped status, emitted on Subjects, and (for composites)
  mutated child collections on the pool thread; ch.11's foreground-emission rule
  offered two observably non-equivalent `MAY` options with no pinned guarantee.
- **VMX-006** — a post-`dispose()` `IsCurrent` change still leaked a hub
  `PropertyChangedMessage` in C#/Python/TypeScript (Swift already suppressed it),
  violating the "Disposed is terminal" invariant.
- **VMX-117** — `LIFE-008` ("a second concurrent invocation MUST raise") named no
  enforcement primitive, leaving flavors free to detect re-entrancy with a racy
  status read.
- **VMX-007** — an exception in `OnConstruct`/`OnDestruct` left the VM wedged in
  the transient `Constructing`/`Destructing` state, recoverable only via
  `dispose()`. This was the one finding with no code in place yet.
- **VMX-046** — child construction/destruction order is unspecified, but the spec
  did not state that subscribers must not rely on it.
- **VMX-049** — the background-construct await primitive (terminal-status
  subscription) and its non-C# gaps were under-documented.
- **VMX-118** — the ch.11 default-dispatchers table omitted Swift.

## 2. Decision

### 2.1 Transitions are atomic, dispose-safe, and the concurrency guard is named (`02 §2.3`)

Every status transition — the `Status` read-modify-write, the
`ConstructionStatusChangedMessage` publish, and the command-trigger emission —
runs atomically with respect to other lifecycle operations on the **same VM**,
serialized behind a per-VM primitive (a lock/monitor in C# and Python; the
single-threaded event loop in TypeScript; an actor/lock in Swift — Phase 3). A
background completion that races `dispose()` observes the terminal `Disposed`
state under the guard and aborts: no resurrection, no post-dispose publish, no
emit on a torn-down stream. `LIFE-008` (concurrent re-invocation raises) is
enforced by this same per-VM guard plus an in-flight flag — explicitly **not** an
unsynchronized status read (VMX-117).

### 2.2 Background lifecycle completions marshal their terminal emission onto Foreground (`11 §3/§4`)

A background `construct()`/`destruct()` emits the intermediate transition
synchronously on the calling thread, runs the hook on `Background`, and marshals
the **terminal** transition (`Constructed`/`Destructed`, and the §2.3 rollback
emission) onto `IDispatcher.Foreground` (VMX-025). Ch.11's foreground rule is
pinned (VMX-048): a subscriber is guaranteed foreground delivery only when the
implementation marshals the `Send` (option (a)) **or** the subscriber opts in via
`ObserveOn`; absent both, no thread guarantee is made. The reference
implementations marshal background lifecycle completions via (a).

### 2.3 A post-dispose `IsCurrent` change is a silent no-op (`02` invariant 3, VMX-006)

A selection (`IsCurrent`) change requested after `Disposed` neither raises nor
emits a `PropertyChangedMessage` — it is a silent no-op, distinct from the
lifecycle operations, which raise from `Disposed`. C#/Python/TypeScript now mirror
the guard Swift already had.

### 2.4 Hook failure is transactional — roll back, do not wedge (`02 §2.4`, VMX-007 — newly implemented)

If `OnConstruct`/`OnDestruct` raises, `Status` rolls back to the prior settled
state before the exception propagates: a failed construct (or the construct phase
of `reconstruct()`) rolls back to `Destructed`; a failed destruct (or the destruct
phase) rolls back to `Constructed`. The rollback runs under the §2.3 guard,
publishes its own `ConstructionStatusChangedMessage` (so invariant 4 holds), and
clears the in-flight guard. In the synchronous form the original exception is
re-raised to the caller; in the background form the rollback emission is marshalled
onto `Foreground` and the exception is re-thrown on the scheduler (unobservable by
the already-returned caller). `OnDispose` is not subject to rollback — `dispose()`
is terminal and idempotent. Verified by the new **`LIFE-014`**.

The alternative — transition to a dedicated `Faulted`/error state — was rejected
(§4): it adds a sixth state and new transition edges to every flavor and fixture
for a path that "return to the last good state" already handles, and it would
still leave the VM un-`construct()`-able without a recovery operation.

### 2.5 Documentation reconciliations

- Child visitation order stays unspecified; subscribers MUST NOT rely on it and no
  conformance ID constrains it (`02 §6`, VMX-046).
- The background await primitive is the terminal-status subscription; the hub does
  not replay the last status, and a first-class completion/error future +
  composite "await all children" orchestration is C#-only today and a tracked
  follow-up for the other flavors (`11 §4`, VMX-049).
- The ch.11 default-dispatchers table gains a Swift row + a note that Swift ships
  no `RxDispatcher.default()` equivalent yet (host-provided Combine schedulers;
  deferred per ADR-0036 §2.E) (VMX-118).

## 3. Consequences

- `02-lifecycle.md` gains §2.3 (atomicity + concurrency guard), §2.4
  (transactional rollback), two new invariants (atomic transition; hook-failure
  rollback), an amended invariant 3 (post-dispose `IsCurrent` no-op) and 5 (named
  enforcement primitive), and a §6 child-order clause. `11-threading.md` §2/§3/§4
  are expanded as above.
- The catalog gains **`LIFE-014`** (the genuinely-new transactional-rollback
  behavior); it is implemented as a real passing test in all three full-parity
  flavors. The already-implemented behaviors (atomic transitions, fg-marshalling,
  post-dispose `IsCurrent`) are documented against existing tests
  (`LIFE-008`/`LIFE-004`/`THR-*`, `ComponentVMLifecycleRaceTests`) to avoid stub
  churn. Catalog library total: 232 → 233 (237 → 238 including the 5 THEME
  scenario IDs).
- At the time of this ADR Swift was the documented subset (ADR-0037): it trapped on
  illegal transitions and its atomicity + `LIFE-014` coverage were Phase-3 items.
  **Superseded by ADR-0053** (Swift converges to a *catchable* `StatusTransitionError`
  — it no longer traps on illegal transitions) and **ADR-0065** (subset manifest
  retired): Swift now covers `LIFE-014` at full parity in all four flavors.
- The coordinated `spec/VERSION` bump to 3.0.0, the per-flavor package version
  bumps, and the per-flavor README count reconciliation are handled by the v3
  release task, not here; this ADR's "Spec version: 3.0.0" records the line the
  change belongs to.

## 4. Rejected alternatives

- **A dedicated `Faulted` lifecycle state on hook failure** — rejected (§2.4):
  a sixth state and new fixture edges for what "roll back to the last settled
  state" already covers; the VM would still need an explicit recovery op.
- **Swallow the hook exception after rollback** — rejected: it would hide a real
  construction failure from the synchronous caller; re-raising after the rollback
  preserves the failure signal while still leaving the VM recoverable.
- **Hold the per-VM lock across the user hook** — rejected: the hook is
  user-supplied and may run arbitrarily long or re-enter the VM; only the
  `Status` RMW + publish + trigger emission are serialized, not the hook body.
