# ADR 0049 — v3 command semantics: confirmation-decorator error channel and CRUD can-execute reactivity

**Status:** Accepted (2026-06-28)
**Spec version:** 3.0.0

## 1. Context

The v3 framework overhaul reconciles the spec with the command-cluster findings of
the merged framework critique (`docs/audit/2026-06-27-vmx-merged-critique.md`).
The fixes landed in code first (commits `1e3ec8d`, `261056c`) but chapter 04 still
described the pre-v3 behavior — most visibly a `ConfirmationDecoratorCommand` whose
synchronous `Execute()` silently swallowed both a rejecting `confirm` delegate and a
throwing inner command. This ADR reconciles the spec with the implemented v3
semantics.

The findings reconciled here:

- **VMX-009** (Python/TypeScript) — `ConfirmationDecoratorCommand.Execute()` is
  synchronous (`ICommand.Execute` returns `void`, chapter 04 §1) while its `confirm`
  delegate is asynchronous (`() -> Task<bool>`). The decorator therefore runs the
  confirm gate as a fire-and-forget continuation, and a `confirm` that rejects/raises
  or an `inner.Execute()` that throws was **swallowed** — diverging from
  `RelayCommand`, whose throwing task propagates to the caller of `Execute` (chapter
  04 §3). In TypeScript a bare `void`-discarded promise would also surface as a fatal
  unhandled rejection on Node ≥ 15.
- **C# parity gap** (noted in the audit) — the same `ConfirmationDecoratorCommand`
  in C# kept the `_ = ExecuteAsync(...)` fire-and-forget discard, so the swallow was
  cross-flavor even though VMX-009 was originally scoped to Python/TypeScript.
- **VMX-044** (spec) — async confirm/persist gating inside the synchronous
  `ICommand.Execute` was unspecified across the confirmation decorators: chapter 04
  said "`Execute` invokes `confirm()`" without stating that `Execute` returns before
  the awaited gate resolves, nor what happens to a failure that cannot propagate.
- **VMX-011** (C#) — `ModeledCrudCommands` Update/Delete `CanExecute` reads the
  mutable `current` provider but wired no trigger, so a bound button's enabled state
  never refreshed when the selection changed (`CanExecuteChanged` fires only on a
  trigger emission, chapter 04 §4).
- **VMX-018** (C#/Python) — the five built-in `ComponentVMBase` commands were built
  eagerly even though four are permanently inert on leaf VMs. The fix made them lazy;
  this is an implementation optimization with no observable contract change, so it is
  **not** specified normatively here (the spec never mandated eager construction).

## 2. Decision

### 2.1 `ConfirmationDecoratorCommand` surfaces fire-and-forget errors on `errors` (chapter 04 §8.3.1)

The synchronous `Execute()` realizes the async confirm gate as a fire-and-forget
continuation: it schedules the `confirm()` → `inner.Execute()` flow and returns
immediately, before the gate resolves. Each flavor also exposes an awaitable
`ExecuteAsync()` (`execute_async` / `executeAsync`) that runs the same flow and can
be awaited to sequence it inline.

Because the synchronous `Execute()` has already returned, a `confirm` delegate that
rejects/raises and an `inner.Execute()` that throws have no caller to propagate to.
Such a failure is now routed to an **`errors`** observable (`Errors` / `errors`)
instead of being swallowed:

- `errors` emits the exception raised by either the `confirm` delegate or the
  throwing `inner.Execute()` when the failure arrives via the fire-and-forget
  `Execute()` path.
- The awaitable `ExecuteAsync()` path keeps the ordinary throw/reject behavior —
  awaiting it propagates the failure directly and the error is NOT additionally
  re-emitted on `errors`.
- `errors` completes on `Dispose()`; a failure landing after dispose is dropped (not
  re-surfaced on a completed subject).

This mirrors the `FormVM` approve-error channel (ADR-0048 §2.3): a fire-and-forget
command entry-point routes a failure that cannot propagate to a dedicated error
observable rather than discarding it.

### 2.2 The C# swallow is fixed for cross-flavor parity (ADR-0006)

The C# `ConfirmationDecoratorCommand.Execute` previously discarded the faulted task
(`_ = ExecuteAsync(parameter)`). It now attaches an `OnlyOnFaulted` continuation that
routes the base exception to a `Subject<Exception>` exposed as
`IObservable<Exception> Errors`, completed and disposed in `Dispose()`. With this,
the `errors` channel is normative in **every flavor that ships the decorator** —
C#, Python, and TypeScript — keeping ADR-0006 parity. Swift does not ship the command
decorators and is out of scope.

### 2.3 `ModeledCrudCommands` can-execute reacts to current-selection change (chapter 04 §4.2, chapter 06 §7)

The Update/Delete predicates read the mutable `current` provider (`current != null`),
so their `CanExecuteChanged` cannot fire on its own. `ModeledCrudCommands` gains an
optional `current_changed` trigger (`Observable<Unit>`) — typically the owning
composite's current-child-changed stream — that the helper wires as a `Triggers`
source on the Update and Delete commands, so each `CanExecute` is re-evaluated and
`CanExecuteChanged` fires the moment the selection changes. Supplying the trigger is
RECOMMENDED whenever the commands are bound to UI; omitting it leaves `CanExecute`
correct on demand but non-reactive. The optional parameter is first realized in C#
(VMX-011); the other flavors compose the same reactivity through the base `Triggers`
mechanism (chapter 04 §4.2).

## 3. Consequences

- `04-commands.md` is revised: §4.2 (new — selection-driven `CanExecute` recipe),
  §8.3.1 (new — async gating + the `errors` channel + throw-propagation contract,
  pinning the VMX-044 unspecified semantics), §10 (CMDD-010 in the conformance list).
- `06-composite-vm.md` §7 is revised: the optional `current_changed` trigger is added
  to the `ModeledCrudCommands` shape and its reactivity behavior specified.
- The catalog gains **`CMDD-010`** (the genuinely-new normative surface: the
  confirmation-decorator error channel), implemented as a real passing test in all
  three full-parity flavors that ship the decorator (a rejecting `confirm` and a
  throwing inner each surface on `errors`). The CRUD can-execute reactivity is
  documented as a clarification of the existing `COMP-021`/`COMP-023` IDs (whose
  predicate-value assertions are unchanged); the fix commit added C# unit coverage,
  so no new CRUD ID is minted. Catalog library total: 234 → 235 (239 → 240 including
  the 5 THEME scenario IDs).
- Swift remains the documented subset (ADR-0037): it ships neither
  `ConfirmationDecoratorCommand` nor `ModeledCrudCommands`, so the `--require swift`
  subset manifest is unaffected and `CMDD-010` is a full-parity (C#/Python/TypeScript)
  ID only.
- The coordinated `spec/VERSION` bump to 3.0.0, per-flavor package version bumps, and
  per-flavor README count reconciliation are handled by the v3 release task, not here;
  this ADR's "Spec version: 3.0.0" records the line the change belongs to.

## 4. Rejected alternatives

- **Keep swallowing the confirmation failure (or just log it)** — rejected: a
  swallowed reject/throw is invisible to the owning view, diverges from
  `RelayCommand`'s propagate contract, and in TypeScript becomes a fatal unhandled
  rejection. An observable error channel is consistent with the `FormVM` approve
  channel (ADR-0048) and keeps the failure scoped to the command's owner.
- **Make `ConfirmationDecoratorCommand.Execute()` block/await the confirm gate** —
  rejected: `ICommand.Execute` is `void` by the chapter 04 contract; awaiting inside
  it would block the UI thread or silently fork. Fire-and-forget with an explicit
  `errors` channel (and the awaitable `ExecuteAsync()` for inline failures) preserves
  the command contract while making failures observable — the same resolution
  ADR-0048 reached for `ApproveCommand`.
- **Push the CRUD can-execute refresh from inside `CompositeVM` automatically** —
  rejected for now: `ModeledCrudCommands` is an opt-in helper composed over a `current`
  provider that need not be a `CompositeVM` current-child stream. An explicit optional
  `current_changed` trigger keeps the helper decoupled from any particular selection
  source while still enabling reactive binding; the base `Triggers` mechanism already
  expresses it.
- **Mint a new conformance ID for the CRUD reactivity** — rejected: the normative
  predicate values (`CanExecute` iff `current != null`) are already covered by
  `COMP-021`/`COMP-023`, and the reactivity is the existing `Triggers` contract
  (chapter 04 §4) applied to a selection stream. A clarification plus the fix commit's
  unit coverage suffices; a new ID would duplicate `CMD-004`'s trigger semantics.
