# ADR 0211 — Rust notifications: a Cargo feature, a hub trait, and no snapshot history

- **Status:** Accepted
- **Date:** 2026-11-09
- **Spec version:** 3.30.0 (Rust mapping in chapter 16; no normative change)
- **Clarifies:** [ADR-0013](0013-notification-service.md),
  [ADR-0141](0141-rust-opt-in-bounded-hub-recorder.md),
  [ADR-0149](0149-spec-prose-corrections-chapters-02-23.md)

## 1. Context

Chapter 16 makes the notifications sub-package opt-in: the core package does
not depend on it. C# ships it as a separate assembly. Python, TypeScript and
Swift ship it in the same distribution, under its own import path or
namespace. The Rust crate always compiled and exported the notification types,
and `Cargo.toml` had no feature for them (#1264).

Chapter 16 §3 gives the null hub `Post`, a no-op `Resolve` and `Pending`. C#,
Python, TypeScript and Swift each declare a hub interface or protocol, and the
null hub implements it. Rust had no hub trait. `NullNotificationHub` was a unit
struct with the associated functions `post`, `post_message` and
`pending_stream`, and no `resolve`. `make_confirm` took the concrete
`NotificationHub`. ADR-0149 recorded both items as open Rust gaps (#1264).

Rust `NotificationHub` also pushed a full copy of the pending list onto a
`pending_snapshots` history on each post, resolve and dispose. Nothing removed
the copies, and `dispose()` did not clear them. One pending notification and
100,000 post and resolve pairs left 200,001 snapshots holding 300,001
`Notification` values (#1275). No other flavor keeps a snapshot history.
ADR-0141 removed the same growth from `MessageHub::history()`.

## 2. Decision

Decided under the owner's 2026-11-07 delegation: pick the cross-flavor-uniform,
simplest option.

### 2.1 The `notifications` Cargo feature

- `vmx-rs` declares a `notifications` feature, and `default` includes it. A
  dependency with `default-features = false` compiles the core without the
  sub-package.
- The feature gates the `notifications` module and the exports
  `NotificationHub`, `NullNotificationHub`, `NotificationHubApi`,
  `make_confirm`, `Notification`, `NotificationType`, `NotificationReaction`,
  `NotificationWaiter`, `NotificationVm` and `ConfirmationVm`. `ModalVm`
  (chapter 19) stays in the core.
- The default includes the feature because Python, TypeScript and Swift ship
  the sub-package in the same distribution as the core, so adding the package
  makes it available. The core still does not depend on it, which is the
  chapter 16 rule. A default feature also keeps existing dependents building.
- Doctests in `src/lib.rs` prove the gate: each gated path compiles with the
  feature and fails to compile without it, and `ModalVm` compiles in both
  builds. The MSRV CI job runs clippy and the tests with
  `--no-default-features`.

### 2.2 The `NotificationHubApi` trait

- The public trait `NotificationHubApi: Send + Sync` declares
  `post_notification(notification) -> NotificationWaiter`,
  `resolve(notification_id, reaction)`, `pending()` and `pending_stream()`.
  These are the chapter 16 `Post`, `Resolve` and `Pending` operations, with
  the Rust names that `NotificationHub` already uses. `Arc<H>` implements it
  for every implementer `H`, so `Arc<dyn NotificationHubApi>` works.
- The name avoids a clash with the existing `NotificationHub` struct, as
  Swift's `NotificationHubProtocol` does.
- `NotificationHub` and `NullNotificationHub` both implement the trait. Each
  also keeps inherent methods with the same names, so a call on a concrete hub
  does not need the trait in scope.
- `NullNotificationHub` derives `Clone`, `Copy`, `Debug`, `Default`,
  `PartialEq` and `Eq`. Its functions become instance methods that mirror
  `NotificationHub`: `new`, `post_notification`, `post`, `post_with_waiter`,
  `resolve` (no effect), `pending` (always empty) and `pending_stream`, which
  replays the empty list once and completes. `post_message` is removed;
  `post_with_waiter(NotificationType::Notification, message)` replaces it.
- `make_confirm` accepts any `H: NotificationHubApi + Clone + 'static`. Over
  a `NullNotificationHub`, the predicate completes with `true` at once.
- `NotificationVm::with_hub` and `ConfirmationVm::with_hub` keep the concrete
  `NotificationHub`. They read the hub's record of each notification:
  `is_resolved()` needs to know that `resolve` removed it, with any reaction
  (`NOTIF-015`), and `ConfirmationVm::reaction()` reads its reaction. The
  three-operation contract carries neither. A view model over a null hub would
  also have no pending notification to present. `NotificationVm::new` and
  `ConfirmationVm::new` still create a private hub.

### 2.3 No snapshot history

- `NotificationHub` keeps the current pending list, the open waiters, the
  reactions and the queue of undelivered snapshots. It keeps no history of
  delivered snapshots. Its `pending_stream()` holds only the current snapshot,
  which it replays, as the other flavors' `Pending` does.
- `NotificationHub::pending_snapshots()` is deprecated since 0.36.0 and always
  returns an empty list, as ADR-0141 did for `MessageHub::history()`. A bounded
  window would look like full history while it misses older snapshots. The
  method can be removed in a later breaking release. Migration: subscribe to
  `pending_stream()` before the posts and resolutions to observe, and collect
  the values. The first value is the snapshot that is current at subscription.
  Rust adds no separate snapshot recorder, because the stream already delivers
  every committed snapshot in commit order.
- The `reactions` and `resolved` records keep one entry for each notification
  id that the hub has posted or resolved, for the life of the hub. The growth
  is linear and small, and `reaction()`, `NotificationVm::is_resolved()` and
  `ConfirmationVm::reaction()` read these entries after the resolution. This
  ADR does not change them.

### 2.4 Lock order in the notification view models

`NotificationVm` and `ConfirmationVm` hold their flags lock while they read the
hub's resolution record (#1293). Thus `dispose()` reads the hub and sets
`disposed` in one critical section, and `is_resolved()` returns a hub value
only if no disposal completed between its `disposed` check and its hub read.
Once `is_resolved()` returns `true`, a later read also returns `true`. The
order is the flags lock, then the hub state lock. The hub never calls out while
it holds its state lock, so no path takes the two locks in the other order.

## 3. Consequences

- A Rust consumer can build the core without the notification types, and can
  pass a `NullNotificationHub` wherever a caller takes `NotificationHubApi`.
- Callers of the old `NullNotificationHub::post(notification)`,
  `NullNotificationHub::pending_stream()` and
  `NullNotificationHub::post_message(message)` associated functions must call
  the instance methods. This is a breaking change. It ships in the unreleased
  0.36.0 source version, which is already a minor bump over the last release.
- Retained hub memory no longer grows with post and resolve traffic, apart
  from the per-id records in §2.3. Callers of `pending_snapshots()` see a
  deprecation warning and an empty list.
- Chapter 16 drops its two "Open Rust gap" paragraphs and states the Rust
  mapping. The spec, the conformance catalog and the other flavors do not
  change.

## 4. Rejected alternatives

A `notifications` feature outside `default` would make the opt-in explicit,
like the separate C# assembly. It would break every current Rust dependent and
the examples, and Python, TypeScript and Swift make the sub-package available
with the core distribution.

A bounded snapshot history would read like full history while it misses older
snapshots, and ADR-0141 rejected the same window for `MessageHub`.

Removing `pending_snapshots()` now would break callers without the deprecation
period that ADR-0141 gives `history()`.

Making `NotificationVm` and `ConfirmationVm` accept the trait would need a
resolution query and a reaction query on the public trait, beyond the three
chapter 16 operations, or a rewrite of the view models around the pending
stream.
