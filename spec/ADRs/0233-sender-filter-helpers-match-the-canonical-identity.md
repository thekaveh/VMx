# ADR 0233 — Sender-filter hub helpers match the canonical ownership identity

- **Status:** Accepted
- **Date:** 2026-11-21
- **Spec version:** 3.30.0 (chapter 03 §7.1, §7.2, §7.4 and §8, chapter 09 §1 and §3, `FWD-007`)
- **Amends:** [ADR-0032](0032-property-value-changed-messages.md) and
  [ADR-0050](0050-v3-parent-member-messaging-and-selection-clarifications.md) §2.1,
  for the statement that §7.1 and §7.2 carry no conformance ID. Only their sender
  rule is tested, by `FWD-007`.
- **Extends:** [ADR-0124](0124-canonicalize-forwarding-ownership-and-callback-boundaries.md)
  (the canonical ownership identity) and
  [ADR-0221](0221-forwarding-decorators-notify-through-the-wrapped-component.md)
  (the wrapped component is the sender). Related:
  [ADR-0213](0213-typescript-forwarding-composite-joins-containers.md),
  [ADR-0160](0160-when-property-changed-several-names.md), #1350, #1352, #1635, #1911.

## 1. Context

Chapter 03 §7 names the hub subscription helpers. `whenPropertyChanged`,
`PropertyValueChangedMessagesFor` and `subscribeValue` each keep the messages whose
sender is the VM they are given. The C#, Python, TypeScript and Swift helpers test
that sender by identity against the object they receive.

ADR-0221 made the wrapped component the sender of each message that a forwarding
decorator causes. A decorator is a VM in its own right, so a helper given a
decorator matches no message. The subscription stays empty and reports no error
(#1911). The caller then has to pass the wrapped VM, through `wrappedBase` in
TypeScript, `_wrapped` in Swift, or a protected field in C#. The workaround does
not exist in Python for a public caller, because the wrapped VM is only
`_wrapped`.

ADR-0221 covers the component-base notification helpers, which send messages. It
does not cover the chapter 03 §7 hub subscription helpers, and no rule named them.
ADR-0124 defines the canonical ownership identity, which each flavor already
computes for its own ownership bookkeeping. The Rust helper compares the id that
the caller passes, and the decorator `id()` already returns the wrapped component's
id. Rust therefore needs no change.

## 2. Decision

Decided under the owner's 2026-11-07 delegation. The orchestrator chose the options
below, and each choice has its reason here.

1. **One identity rule in every flavor.** Each sender-filter helper matches a
   message whose sender is the canonical ownership identity of the VM it was given.
   An object that is not a VM is its own identity. Each flavor resolves the identity
   in its own way, and each resolution gives the same result:
   - C# uses the internal `GetOwnershipIdentity()`, which `ComponentVMBase` and the
     decorators already provide, through the new internal `SenderIdentity.Of`.
   - Python uses `_ownership_identity`, through the new internal
     `canonical_sender`.
   - TypeScript walks the public `wrappedBase` chain to its last VM, through the new
     internal `canonicalSender`. This is the chain that `useVm` already follows
     (ADR-0213). The walk stops at a VM with no `wrappedBase`, and at a getter that
     throws. The walk reads only the public surface, not the `@internal`
     `_ownershipIdentity` member.
   - Swift uses `_ownershipIdentity`, through the internal
     `canonicalSenderIdentity`.
1. **The identity is resolved once, when the helper subscribes.** A decorator's
   wrapped VM does not change after construction, so one lookup gives the same
   identity as a lookup per message. Each message then costs one comparison.
1. **A new conformance ID, `FWD-007`, covers the rule.** The rule is a new
   behavior of the helpers, and no existing ID states it. The ID is not an
   extension of `FWD-006`, for two reasons. `FWD-006` covers the component-base
   helpers that send messages, which are a different helper family. The ID also
   names one behavior, so a regression fails under one marker (the same reason as
   `SRCH-010`, ADR-0232 item 7). `SUBV-001` to `SUBV-004` are not extended either.
   They pin the normative `subscribeValue` state machine, and this rule changes
   only the sender that the state machine names. The ID is the next free `FWD`
   number. The issue's dependency section names no ID for this rule.
1. **The amendments and extensions.** This ADR amends ADR-0032 and ADR-0050 §2.1 for
   the statement that §7.1 and §7.2 carry no conformance ID. The sender rule of
   §7.1 and §7.2 is now tested. Every other rule of those sections stays
   informative. This ADR extends ADR-0124 and ADR-0221 by applying their identity
   and sender rules to the §7 helpers. Neither earlier rule changes. The back-links
   are in the `Status` lines and registry cells of ADR-0032, ADR-0050, ADR-0124 and
   ADR-0221 (`spec/ADRs/README.md` §2.2 and §2.3).
1. **Rust: no library change.** The helper is `MessageHub::subscribe_value` at
   `langs/rust/src/runtime.rs` L1196-L1216. It compares `change.sender_id` with the
   `sender_id` argument, which the caller supplies. A `ForwardingComponentVm` nests
   through `Forwarding(Box<…>)` (`langs/rust/src/forwarding.rs` L14) and `wrap`
   (L57). Its `id()` (L106-L107) returns `self.inner().id()`, and `inner()` (L98)
   recurses to the innermost component. So `subscribe_value(outer.id(), …)` already
   matches the canonical identity, through any number of layers. Rust gets the
   `FWD-007` marker and a regression test (`langs/rust/tests/conformance/forwarding.rs`).
   The test passes on the unchanged library. Rust does not diverge, so no entry is
   added to ADR-0009.
1. **The public API does not change.** No signature changes, so the API baselines
   stay the same. No accessor is added. ADR-0213 rule 3 stays in force, and Python
   and C# gain no public `wrappedBase`.
1. **Raw message filters are unchanged.** `isPropertyChanged` in
   `langs/typescript/src/messages/predicates.ts` is the raw-message predicate of
   §7.3, and `subscribeValue` passes it the canonical identity. The raw `Messages`
   stream is the tested contract, and it keeps its ADR-0221 behavior.
1. **Swift delegates.** The `propertyValueChangedMessagesFor` helper and the
   `Equatable` `subscribeValue` overload call the helpers above, so they need no
   edit of their own.
1. **Versions.** This is a behavior fix with no API change. Each changed package
   records a `Fixed` entry under its unreleased source-version section: C# `VMx`
   3.30.0, Python 3.30.0, TypeScript 3.31.0 and Swift 4.0.0. `spec/VERSION` stays at
   3.30.0, because no `spec-v3.30.0` tag exists (`CONTRIBUTING.md` §2.8 and §4.3).
   No package version is bumped, and no tag is created.

## 3. Consequences

- A helper given a decorator, through any number of layers, matches the messages
  of the wrapped VM in C#, Python, TypeScript and Swift. In Rust it already did.
- A helper given a plain VM behaves as before. A raw `Messages` filter behaves as
  before.
- The `FWD-007` tests fail on the pre-fix code in each of the four changed flavors,
  and pass after the fix. The Rust test passes on both.
- The chapter 03 §7 and chapter 09 §1 text names the rule. The chapter 03 §8 and
  chapter 09 §3 tables and chapter 12 §11 list `FWD-007`.
- Numbering. The highest registry row at the time of writing is ADR-0232.
  ADR-0231 is held by open pull request #2087 and has no row here
  (`spec/ADRs/README.md` §2.4). This ADR takes 0233, the next free number.

## 4. Rejected alternatives

- **Extend `FWD-006`.** Rejected, as decision 3 gives. `FWD-006` covers different
  helpers, and one marker must name one behavior.
- **Add a public `wrappedBase` accessor in Python and C#.** Rejected. It would
  amend ADR-0213 rule 3, and the canonical identity makes it unnecessary for the
  helpers. The issue keeps the accessor out of scope.
- **Resolve the identity for each message.** Rejected, as decision 2 gives. A
  decorator's wrapped VM does not change after construction, so the per-message
  lookup would add cost and no behavior.
- **Compare the decorator and the wrapped VM as two identities.** Rejected. A
  message names only the innermost VM, so a second comparison would never match
  anything that the first one misses. It would also make the helper depend on the
  decorator chain's depth.

## 5. Mutation evidence

Each new test was run against a library mutation before it was committed. The
library was then restored, and each restoration was checked.

- **M1, the pre-fix comparison.** The helper compares the sender with the object
  it was given. Python, TypeScript and Swift ran the new tests on the unchanged
  library before the fix, and the two-layer tests failed there. C# ran the test
  under M1 after the fix. Its two-layer test failed, and the other-VM guard passed,
  because the sender filter still holds.
- **M2, one wrapping level only.** The helper resolves only the first wrapped VM.
  The Python two-layer case and the TypeScript two-layer test fail, and the
  Python one-layer case passes.
- **M3, the sender filter removed.** The helper accepts every sender. The other-VM
  guard fails in Python, TypeScript and Swift.
- **M4, the Rust decorator id.** `ForwardingComponentVm::id()` returns the wrapped
  id plus one. The Rust `FWD-007` test fails, which shows that it depends on the
  canonical id.
