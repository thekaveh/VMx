# ADR 0054 — v3 TypeScript uniform message `sender`: remove the untyped `senderObject` field, restore ADR-0006 cross-flavor parity

**Status:** Accepted (2026-06-28)
**Spec version:** 3.0.0

## 1. Context

ADR-0006 commits VMx to *one conceptual shape with idiomatic surfaces* — only
casing and language-specific affordances differ between flavors. The merged
framework critique (`docs/audit/2026-06-27-vmx-merged-critique.md`) flags two
related items against that promise on the message hub:

- **VMX-016** (TypeScript) — the base message interface declared the runtime
  sender as an **untyped `senderObject: object`** field, while the typed
  `sender` only existed on the typed sub-interface (`ITypedMessage<TSender>`).
  The getting-started doc therefore taught subscribers to read
  `msg.senderObject === userVM`, whereas the C# and Python guides read
  `msg.Sender` / `msg.sender` after the same `instanceof` narrowing. That is a
  **field-name divergence beyond casing** — a real break of ADR-0006's
  "same shape" guarantee, visible to every hub subscriber.

- **VMX-083** (cross-flavor) — the naming/INPC-shape divergences ADR-0009
  catalogues are real but documented and intentional; its actionable half is to
  *expose a uniform sender* and reconcile the catalogue accordingly.

The starting state was, in fact, **the same dual shape in all four flavors**: an
untyped base accessor plus a typed `sender` on the typed message —
`IMessage.SenderObject` + `IMessage<TSender>.Sender` (C#),
`Message.sender_object` + `TypedMessage.sender` (Python),
`Message.senderObject` + `PropertyChangedMessage.sender` (Swift),
`IMessage.senderObject` + `ITypedMessage<TSender>.sender` (TypeScript). The
divergence VMX-016 actually bites in TypeScript was that **`senderObject` was
the only field on the base** `IMessage`, so the canonical/documented accessor
diverged from the other flavors, all of which document `sender`/`Sender`.

## 2. Decision

### 2.1 TypeScript: `sender` is the sole, canonical sender field (breaking)

The TypeScript base `IMessage` interface now declares `sender` (typed
`unknown`) as its runtime-sender field; `ITypedMessage<TSender>` narrows it to
`TSender`. The redundant untyped **`senderObject` field/getter is removed** from
every TypeScript message:

- `IMessage.senderObject: object` → `IMessage.sender: unknown`.
- `PropertyChangedMessage<TSender>` / `TreeStructureChangedMessage` /
  `FormRevertedMessage` drop their `senderObject` getter (they already stored a
  typed `sender`).
- `ConstructionStatusChangedMessage` / `CollectionChangedMessage` rename their
  stored `senderObject` field to `sender`.

`unknown` (not `object`) is the base type because the untyped base must be a
supertype of an **unconstrained** `TSender` — `object` is not (a primitive
`TSender` would not be assignable), which is precisely why the original split
existed. `unknown` is the only common-denominator type that lets
`ITypedMessage<TSender>` narrow `sender` to `TSender`, so the single-field shape
is expressible without the alias.

This is **breaking** for TypeScript consumers that read `msg.senderObject`; they
migrate to `msg.sender` (identical value, now typed). It is gated behind the
v3.0.0 major.

### 2.2 The other flavors retain `senderObject` as a deprecated alias

C#, Python, and Swift are **unchanged** by this ADR. Each already exposes the
canonical typed `Sender`/`sender`; each additionally keeps its untyped base
alias (`IMessage.SenderObject`, `Message.sender_object`, `Message.senderObject`)
for source compatibility. Those aliases return the same instance as `Sender` and
are now **deprecated**, slated for removal at each flavor's next major (tracked
in ADR-0009). The canonical accessor across all four flavors is `Sender`.

### 2.3 Spec and catalogue

- `spec/03-messages.md` §1 now models the base `IMessage` with a single
  `Sender : object` field (narrowed to `TSender` by `IMessage<TSender>`) and
  documents the canonical-field rule plus the deprecated per-flavor alias.
- ADR-0009 (cross-flavor divergence catalogue) gains an `IMessage` sender-field
  row recording the post-v3 state, and its historical
  `ConstructionStatusChangedMessage.sender` note is forward-linked here.

No new conformance ID is introduced: sender **identity** is already covered by
the existing `PROP-00x` / `HUB-00x` IDs, which assert reference equality of the
sender, not the member name. They pass unchanged with the renamed field.

## 3. Rationale

The whole point of ADR-0006 is that a developer reading one flavor's guide can
predict the others. A subscriber filtering by sender is the single most common
hub interaction, and it diverged on the *primary* field name — the most visible
possible place to break the promise. Collapsing TypeScript to a single `sender`
removes the redundant alias (dead ceremony, VMX-016) and makes the documented
shape uniform. Keeping the alias in C#/Python/Swift avoids an unscoped breaking
change in three flavors during a TypeScript-targeted fix; their removal is a
tracked follow-up, not a silent gap.

## 4. Consequences

- TypeScript `msg.senderObject` no longer compiles; `msg.sender` is the typed
  replacement. CHANGELOG records the breaking rename.
- The four flavors now agree on `sender`/`Sender` as the canonical field; the
  residual untyped aliases in C#/Python/Swift are documented-deprecated, not
  drift.
- Future parity audits treat the `senderObject`-equivalent aliases as scheduled
  removals (next major per flavor), not as a divergence to re-flag.

## 5. Rejected alternatives

- **Doc-only fix (rewrite the TS guide to use `msg.sender`, keep
  `senderObject`).** Leaves two names for one value on the public surface and a
  base interface whose only sender field is the untyped one — the structural
  split VMX-016 flags would persist for polymorphic `IMessage` holders.
- **Type the base `IMessage.sender` as `object`.** Cannot be narrowed to an
  unconstrained `TSender` (primitives are not `object`); would force `ITypedMessage`
  back into a second field — exactly the split being removed.
- **Remove `senderObject` from all four flavors in this change.** Out of scope
  for a TypeScript-targeted finding and an unannounced triple breaking change;
  deferred to each flavor's next major and tracked in ADR-0009.
