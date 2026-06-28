# ADR 0048 — v3 FormVM semantics: injectable deep-equal `IsDirty`, deep default snapshot, and an approve error channel

**Status:** Accepted (2026-06-28)
**Spec version:** 3.0.0

## 1. Context

The v3 framework overhaul hardened `FormVM<TM>` (chapter 20) against the
forms-cluster findings of the merged framework critique
(`docs/audit/2026-06-27-vmx-merged-critique.md`, summary theme §1.2). The fixes
landed in code first (commits `f437a26`, `8692f28`, `1e3ec8d`) but chapter 20 still
described the pre-v3 behavior — most visibly a `JSON.stringify`-based dirty check
and shallow-by-default snapshots. This ADR reconciles the spec with the implemented
v3 semantics.

The findings reconciled here:

- **VMX-003** (Critical, TypeScript) — `FormVM.isDirty` used `JSON.stringify`: a
  hard crash on `BigInt`/circular models and silently wrong on
  `Map`/`Set`/`Date`/`undefined`/`NaN`/`-0`/key-order, while the default
  `structuredClone` snapshotter advertised exactly the types the comparison could
  not handle.
- **VMX-010** (Python) / **VMX-064** (C#) — the default snapshotter was a shallow
  copy (`copy.copy` / reflective `MemberwiseClone`), so a nested-object mutation
  was invisible to `IsDirty` and un-revertable by `DenyCommand`.
- **VMX-008** (C#/Python/TypeScript) — `ApproveCommand` swallowed persister
  failures fire-and-forget: no error event, no `OnApproved`, and (per runtime) a
  discarded faulted task surfacing only as an unobserved-exception warning at GC.
- **VMX-043** (spec) — `ApproveCommand.Execute()`'s fire-and-forget semantics were
  unspecified in chapter 20, and `FORM-007` cited a "chapter 20 §2" that did not
  contain the statement.
- **VMX-047** (C#/Python/TypeScript) — `OnApproved` diverged cross-flavor: C#
  emitted the pre-await captured snapshot while Python/TypeScript emitted the live
  post-await model, so a `SetModel` racing the persist changed the emitted payload
  on two flavors but not the third. ADR-0009 documented the divergence and deferred
  alignment.

## 2. Decision

### 2.1 `IsDirty` uses an injectable structural equality (chapter 20 §4)

Dirty state is derived from a structural value comparison of `Model` vs `Snapshot`,
evaluated by each flavor's idiomatic, overridable value-equality:

- **C#** — `object.Equals` (record types provide structural equality); the override
  is the model type's own `Equals`/`==`.
- **Python** — `__eq__` (`@dataclass` / `frozen=True` provide value equality); the
  override is the model's own `__eq__`.
- **TypeScript** — plain objects have no idiomatic value equality, so the framework
  ships a **structural deep-equal** default (`deepEquals`) **and** an injectable
  `equals(a, b)` predicate (constructor option / builder setter, exported type
  `ModelEquals<TM>`). The default mirrors the depth the default `structuredClone`
  snapshotter clones, so comparison and snapshotting stay internally consistent.

The TypeScript default deep-equal replaces `JSON.stringify`: it never throws on
`BigInt` (compared with `===`) or circular references (visited-pair guard); compares
`Date` by instant, `Map`/`Set` by contents, `RegExp` by source/flags, arrays/objects
by value; preserves `undefined`-valued keys as distinct from missing keys; treats
`NaN == NaN` and `+0 == -0`; and is key-order insensitive. The pre-v3 key-order
caveat recorded in ADR-0037 is therefore **retired** — `FORM-003`'s equal-values
guarantee now holds unconditionally in TypeScript. `Map`/`Set` membership uses the
engine's native `has` (SameValueZero), so object-typed keys/members compare by
reference; a model needing deep key comparison injects a custom `equals`. The
injectable equality hook is TypeScript-only because C# and Python models already
carry idiomatic value equality.

### 2.2 The default snapshot is a deep value-copy; the snapshotter stays injectable (chapter 20 §3)

The default snapshotter now produces a **deep** clone so the snapshot shares no
nested mutable state with the live `Model` — a correctness requirement, because a
shallow snapshot makes nested mutation invisible to `IsDirty` and un-revertable by
`DenyCommand`:

- **C#** — a `System.Text.Json` serialize → deserialize round-trip (BCL-only, no new
  package; the `JsonSerializerOptions` is cached per closed generic).
- **Python** — `copy.deepcopy`.
- **TypeScript** — `structuredClone` (already deep pre-v3).

The snapshotter **remains injectable** and an injected snapshotter always overrides
the default; it is the documented escape hatch for models the default deep-copy
cannot handle (JSON-unrepresentable members / delegates / cyclic graphs in C#,
unpicklable or live-handle objects under `deepcopy` in Python, non-cloneable values
in TypeScript). The snapshotter is applied in both directions (capture and
`DenyCommand` revert).

### 2.3 The approve command path surfaces persister failures on `ApproveErrors` (chapter 20 §2/§7)

`ApproveCommand.Execute()` is **fire-and-forget**: because `ICommand.Execute`
returns `void` (chapter 04 §1), it schedules the persist via `ApproveAsync` and
returns immediately, and a persister failure cannot propagate to the caller. Each
flavor exposes an **`ApproveErrors`** observable (`ApproveErrors` / `approve_errors`
/ `approveErrors`) onto which the command path routes the persister exception,
rather than discarding the faulted task. On the command path a failure mutates no
state (`IsDirty` stays `true`, `OnApproved` does not fire); on success the command
path is identical to the awaitable path.

The awaitable **`ApproveAsync()`** path is unchanged: a persister failure propagates
to the awaiter (`FORM-007`) and emits nothing on `ApproveErrors`. `ApproveErrors`
completes on `Dispose()`, and a failure landing after `Dispose()` is dropped (not
re-surfaced on a completed subject). This both fixes VMX-008 and pins the
fire-and-forget statement VMX-043 found missing — `FORM-007`'s "chapter 20 §2"
cross-reference now resolves.

### 2.4 `OnApproved` is pinned to the persisted value across flavors (chapter 20 §7, VMX-047)

`OnApproved` fires once after a successful persist with the value that was
**actually persisted**: the `Model` captured at the start of the approve flow,
before the persister await. A `SetModel` racing an in-flight persist leaves the form
dirty against the newer model but does **not** change the value `OnApproved`
reports. All three flavors now capture-before-await (C# already did; Python and
TypeScript were aligned to it), resolving the ADR-0009 `OnApproved` divergence note.

## 3. Consequences

- `20-form-vm.md` is revised: §1 (deep snapshot + injectable equality summary), §2
  (fire-and-forget vs awaitable failure semantics; `ApproveErrors` in the shape),
  §3 (deep default snapshot table + injectable snapshotter), §4 (injectable
  deep-equal contract, `JSON.stringify` prose removed), §7 (`OnApproved` persisted
  value + `ApproveErrors` channel), §9 (dispose completes `ApproveErrors`; late
  failure dropped).
- The catalog gains **`FORM-015`** (the genuinely-new normative surface: the
  command-path error channel), implemented as a real passing test in all three
  full-parity flavors. The deep-equal (VMX-003) and deep-snapshot (VMX-010/064)
  changes are documented as clarifications of existing IDs — `FORM-003` (deep-equal,
  retires the ADR-0037 key-order caveat), `FORM-002`/`FORM-004` (nested
  mutation/revert), `FORM-013` (default deep-copy) — since the fix commits already
  added unit-test coverage; no new IDs are minted for them. `FORM-006`'s note is
  amended for the `OnApproved` persisted-value semantics (VMX-047). Catalog library
  total: 233 → 234 (238 → 239 including the 5 THEME scenario IDs).
- Swift remains the documented subset (ADR-0037): its `FormVM` is outside the
  shipped Swift subset, so the `--require swift` subset manifest is unaffected and
  `FORM-015` is a full-parity (C#/Python/TypeScript) ID only.
- The coordinated `spec/VERSION` bump to 3.0.0, per-flavor package version bumps, and
  per-flavor README count reconciliation are handled by the v3 release task, not
  here; this ADR's "Spec version: 3.0.0" records the line the change belongs to.

## 4. Rejected alternatives

- **Keep `JSON.stringify` for TypeScript dirty-tracking** — rejected: it crashes on
  `BigInt`/circular and is silently wrong on `Map`/`Set`/`Date`, exactly the types
  the default `structuredClone` snapshotter clones (VMX-003). A structural deep-equal
  paired with the deep snapshotter is the only internally consistent default.
- **Keep the shallow default snapshot and only document the footgun** — rejected:
  shallow snapshots make the documented snapshot/revert contract silently incorrect
  for any model with nested mutable state; a deep default with an injectable escape
  hatch is the safe default, and the escape hatch preserves the shallow/cheap option.
- **Publish persister failures as a hub message** — rejected: a persist failure is a
  form-local control-flow signal for the owning view, not a cross-VM broadcast; a
  dedicated per-form observable keeps it scoped and avoids a new message type plus
  filtering ceremony on every subscriber.
- **Make `ApproveCommand.Execute()` block/await** — rejected: `ICommand.Execute` is
  `void` by the chapter 04 contract; awaiting inside it would either block the UI
  thread or silently fork. Fire-and-forget with an explicit error channel (and the
  awaitable `ApproveAsync()` for callers who want inline failures) preserves the
  command contract while making failures observable.
