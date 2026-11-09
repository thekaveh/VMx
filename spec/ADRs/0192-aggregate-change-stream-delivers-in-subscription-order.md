# ADR 0192 — `AggregateChangeStream` delivers each envelope in subscription order

- **Status:** Accepted
- **Date:** 2026-11-09
- **Spec version:** 3.30.0 (chapter 21 §9.5, §9.6, §9.7 and `AGCH-011`)
- **Extends:** [ADR-0098](0098-dynamic-aggregate-change-stream.md).
  Related: [ADR-0174](0174-formvm-queues-updates-during-approval-publication.md),
  [ADR-0191](0191-subscriber-failures-do-not-stop-delivery-or-detach.md),
  #1310.

## 1. Context

Chapter 21 §9.5 sends all aggregate envelopes through one serialized FIFO
drain. That rule orders envelopes. It does not order the subscribers of one
envelope. §9.6 offers the final `Batch` to a union of subscriptions and states
no order.

Swift keeps its output subscribers in a `[UUID: AggregateOutputEndpoint]`
dictionary and the batch recipients in a `Set<UUID>`. A probe at `349ca128`
subscribed five sinks, labelled 0 to 4 in subscription order. Six runs gave
six different orders for one plain change and for one batched change, for
example `plain=[4, 1, 3, 0, 2] batch=[0, 2, 3, 1, 4]`. Python printed
`[0, 1, 2, 3, 4]` for both in every run.

C#, Python and TypeScript keep the registrations in a list, and Rust in a
`BTreeMap` keyed by an increasing id. The batch union is an insertion-ordered
dict in Python, an insertion-ordered `Set` in TypeScript and a `BTreeMap` in
Rust. C# uses a `HashSet<T>`, and .NET does not document its enumeration
order. Open decision §2.5 in the cross-flavor ledger records the gap.

## 2. Decision

### 2.1. Owner decision

Decided under the owner's 2026-11-07 delegation: all flavors follow one rule,
and the simplest common-sense form is chosen. Four flavors already deliver in
subscription order, so the rule requires it.

### 2.2. Rule

Chapter 21 §9.5 states the rule.

1. The subscribers of one aggregate envelope receive it in subscription order:
   the order of their subscribe calls on that aggregate.
1. The rule applies to item, structural, final `Batch` and completion
   delivery. The `Initial` envelope has one recipient.
1. A subscriber that cancels and subscribes again is a new subscription. It is
   last in the order.
1. The final `Batch` reaches the union of §9.6 in subscription order, not in
   the order in which the subscribers joined the union.
1. The FIFO drain of §9.5 is unchanged. Each envelope reaches all of its
   recipients before the next envelope starts.

The rule does not change the order of hub subscribers or of the Swift
`VMxConcurrentSubject` sinks. ADR-0174 leaves that order unspecified, and it
stays so.

## 3. Flavor impact

- **Swift.** `AggregateChangeStream` keeps a registration order beside the
  `observers` dictionary. Structural, item, `Batch` and completion recipients
  come from that order. The batch union keeps its set for membership and
  takes its delivery order from the registration order.
- **C#.** `_batchRecipients` stops relying on `HashSet<T>` enumeration. Each
  registration gets an increasing sequence number, and the outermost batch
  exit orders the recipients by it.
- **Python, TypeScript and Rust.** No code change. Tests pin the order.

## 4. Conformance

`AGCH-011` subscribes five sinks and checks the order for one plain change, one
batched change and disposal, in all five flavors. The catalog count is stated
in ADR-0191 §4.

## 5. Consequences

- Swift aggregate delivery is deterministic, as in the other flavors.
- Tests and applications can rely on the order among the subscribers of one
  aggregate envelope. They still cannot rely on it for the hub or other
  streams.
- Open decision §2.5 in
  `docs/maintenance/2026-10-18-open-cross-flavor-decisions.md` is closed for
  `AggregateChangeStream`.

## 6. Rejected alternatives

- **Leave the order unspecified.** No library code would change, but Swift
  would stay the only flavor whose order changes between runs. Tests would
  need order-insensitive assertions for no gain.
- **Fix the order for every library stream.** The hub and
  `VMxConcurrentSubject` are outside #1310, and ADR-0174 chose not to fix
  their order.
