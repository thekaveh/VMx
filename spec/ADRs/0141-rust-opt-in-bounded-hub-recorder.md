# ADR 0141 — Retain Rust hub messages only through an opt-in bounded recorder

- **Status:** Accepted
- **Date:** 2026-10-07
- **Spec version:** 3.25.0 (Rust mapping; no normative change)
- **Clarifies:** [ADR-0103](0103-rust-owned-hot-stream-facade.md)

## 1. Context

Chapter 03 makes the hub hot: late subscribers see nothing earlier, and there
is no replay buffer. No other flavor's hub retains delivered messages.
TypeScript offers an opt-in `RecordingMessageHub` under its `./testing`
subpath.

Every Rust `MessageHub` appended a clone of each accepted message to a
`history` vector that nothing ever trimmed, and disposal did not clear it. One
million sends left one million messages in memory after `dispose()`. The same
growth happened in the private hubs inside commands, forms, collections,
paging, and notifications, which applications cannot reach. The public
`history()` returned a full copy, and 117 assertions in the Rust tests read it
(#325).

## 2. Decision

- A `MessageHub` retains no message. It holds subscribers, pending
  deliveries, and weak references to its recorders. This applies to every hub,
  including the private hubs inside other types.
- `MessageHub::record(capacity)` returns a `MessageRecorder`. The recorder
  records each message the hub accepts from then on, at acceptance and before
  delivery. Its order is therefore the delivery order, including messages
  queued in a batch and re-entrant sends accepted during delivery. Recording
  runs no callback, so it cannot change delivery order, subscriber panic
  isolation, or re-entrancy.
- The recorder keeps the newest `capacity` messages. When full, it evicts the
  oldest and counts it in `dropped()`. Capacity zero retains nothing and counts
  every message. `messages()` returns the retained messages, oldest first.
  `clear()` empties them without changing `dropped()`. Several recorders can
  watch one hub, each with its own capacity.
- The recorder owns its messages, and the hub refers to it weakly. A recorder
  never keeps its hub alive. Dropping it or calling `dispose()` stops recording
  and removes its registration; the messages it holds stay readable until it is
  dropped.
- Hub disposal releases every recorder registration. Recorders keep the
  messages they already hold and record nothing more. A recorder made on a
  disposed hub is inactive.
- `MessageHub::history()` is deprecated since 0.31.0 and always returns an empty
  list. A bounded window would look like complete history while silently
  missing older messages. The method can be removed in a later breaking release.
  Migration: attach a recorder before the sends to observe, then read
  `recorder.messages()`.
- The Rust tests now attach recorders explicitly, and no test reads
  `history()`. The spec, the conformance catalog, and the other flavors do not
  change.

## 3. Consequences

- Retained memory no longer grows with traffic. After one million sends, an
  ordinary hub holds no message, and a recorder of capacity 1024 holds 1024
  and reports 998,976 dropped.
- A hub without recorders no longer clones each message, so sends get cheaper.
- `history()` callers see a deprecation warning and an empty result. The crate
  is unpublished (#67) and the change ships in the unreleased 0.31.0, as its
  changelog records.

## 4. Rejected alternatives

A bounded default history on every hub would keep traffic in every private hub
and would read like full history while missing older messages.

Keeping `history()` unbounded behind a deprecation would keep the leak that
#325 reports.

Removing `history()` now would break callers without the deprecation period
that ADR-0137 and ADR-0139 give replaced Rust APIs.

A recording subscriber would see a message only when it is delivered, so
messages queued in a batch would stay invisible until the batch ends, and it
would add a subscriber call to every delivery.
