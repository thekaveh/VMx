# ADR 0239 — A failing subscriber skips no token-paging notification step

- **Status:** Accepted
- **Date:** 2026-11-21
- **Spec version:** 3.30.0 (chapter 03 §3.6, chapter 21 §6.2 and §8, `COL-073`)
- **Extends:** [ADR-0220](0220-failing-subscriber-skips-no-later-collection-notification.md)
  rules 1 and 2 for `TokenPagedComposition`, and
  [ADR-0191](0191-subscriber-failures-do-not-stop-delivery-or-detach.md) rules 1, 2
  and 5 for the call-fed route of its load and refresh. Related:
  [ADR-0136](0136-align-token-refresh-cursor-with-retained-pages.md),
  [ADR-0171](0171-failing-local-subscriber-does-not-suppress-the-hub-message.md),
  #1883.

## 1. Context

ADR-0220 closed the failing-subscriber defect for `ObservableList`, the
dictionary key views and the serviced collections (#1367, #1430). It did not
name `TokenPagedComposition`. A committed load or refresh of that composition has
its own notification steps: the `Reset` event, the `Items`, `CurrentToken` and
`HasMore` property notifications, and the re-signal of both commands'
`CanExecuteChanged`. No rule covered them, and chapter 03 §3.6 does not name the
token-paging channels.

The defect in the two flavors that have it:

- **C#.** `NotifyResetIfLive` raised `CollectionChanged`, and
  `NotifyPropertiesIfLive` raised each `PropertyChanged` name, as plain
  multicast invokes. A throwing `Reset` handler skipped the later `Reset`
  handlers, the three property notifications and the command re-signal.
- **Python.** The three channels were plain reactivex `Subject` instances.
  A raising observer stopped `Subject.on_next`, so a `Reset` failure skipped
  `_notify_properties`, and a property failure skipped the later names and the
  re-signal.

The reproduction in #1883 shows the first stop. A terminal load with a failing
`on_collection_changed` observer, followed by a counting observer, leaves
`items` as `['x', 'y']` and `has_more` as `False`. No property notification
occurs, and the counting observer receives nothing.

The other three flavors already complete every step:

- **TypeScript.** `TokenPagedComposition` sends through rxjs `Subject.next` with
  no exception boundary (`langs/typescript/src/collections/tokenPagedComposition.ts`
  lines 141-153). rxjs 7.8.2 runs each observer's `next` inside `try` and reports
  a throw through `handleUnhandledError` (`langs/typescript/node_modules/rxjs/dist/cjs/internal/Subscriber.js`
  lines 112-117). `reportUnhandledError` reports it asynchronously
  (`reportUnhandledError.js` lines 6-14). The loop continues, and the load returns.
- **Swift.** The three publishers are `PassthroughSubject<_, Never>`
  (`langs/swift/Sources/VMx/Collections/TokenPagedComposition.swift` lines 21-23).
  A `sink` closure cannot throw, and `notifyResetIfLive` and
  `notifyPropertiesIfLive` (lines 162-175) run every step.
- **Rust.** `publish_pager_changes` (`langs/rust/src/token_paging.rs` lines 149-173)
  sends each step through `MessageHub::send`. The hub drain calls each subscriber
  inside `catch_unwind` (`langs/rust/src/runtime.rs` line 1549), so `send`
  returns normally and the next step runs.

## 2. Decision

Chosen as the simplest rule that holds in all five flavors. Every flavor follows
one rule: the ADR-0220 rule for collection notifications applies to the steps of
a token-paging load or refresh.

1. **No skipped step.** A failing subscriber of one notification step of a
   committed load or refresh does not skip a later step of the same operation.
   The steps are the `Reset` event (C# `CollectionChanged`, Python
   `on_collection_changed`), the `Items`, `CurrentToken` and `HasMore` property
   notifications (`items`, `current_token` and `has_more` in Python), and the
   re-signal of both commands' `CanExecuteChanged`. Each step reaches every
   subscriber that is attached when it starts (ADR-0191 rule 1).
1. **Property handlers are covered.** A failing `PropertyChanged` handler of
   `TokenPagedComposition` also skips no later step. The default is yes, as #1883
   proposes. ADR-0191 §2.5 and ADR-0171 kept `PropertyChanged` handlers out of the
   rule, and ADR-0220 covered only the serviced collections' `Count` and `Item[]`
   handlers. This ADR covers every `PropertyChanged` subscriber of this
   composition. Reason: a bound view reads `Items`, `CurrentToken` and `HasMore`,
   and the command re-signal enables its "Load more" control. A failing handler
   that stopped those notifications would leave the view stale, which is the
   defect in #1883. The rejected alternative is in §4.
1. **Failure route.** C# and Python rethrow the first failure after the last
   step. A load or refresh is a call-fed delivery (chapter 03 §3.6), so the caller
   of `LoadMoreCommand` or `RefreshCommand` (C# `ExecuteAsync`, Python
   `execute_async`) receives the failure. TypeScript, Swift and Rust keep their
   current route, and the call returns normally. This extends ADR-0191 rule 5 and
   ADR-0220 rule 2.
1. **Disposal stops later steps.** A subscriber that disposes the composition
   stops the later steps. Each step checks the composition's disposal before it
   delivers, as the code already did before this change for the next step.
1. **Conformance.** The rule has a new ID, `COL-073`. `COL-072` keeps its
   meaning, and §4 gives the reason. Each flavor tests a failing `Reset`
   subscriber on a load and on a replacing refresh, a failing property
   subscriber, and a disposing `Reset` subscriber. C# and Python assert the
   rethrow; TypeScript, Swift and Rust assert a normal return and the step order.
1. **Flavors.** C# and Python change, because they have the defect. TypeScript,
   Swift and Rust need no library change, because §1 shows that they complete
   every step. Each adds a `COL-073` test. Had a flavor failed to complete a
   step, the fix would have been applied there too unless it exceeded about 30
   lines.
1. **Chapters.** Chapter 21 §6.2 states the rule for the token-paging steps.
   Chapter 21 §8 maps `COL-073` to the failing-subscriber rules. Chapter 03 §3.6
   names the token-paging channels, adds a token-paging load or refresh to the
   call-fed list, and no longer excludes token-paging `PropertyChanged` handlers
   from the rules. The call-fed list and the stream-fed route of rule 4 then agree.
1. **Mutation evidence.** Each new test fails under a named library mutation:
   - **M1** (C# and Python): restore the pre-fix step code, plain CLR invokes and
     plain reactivex `Subject`s. The load, replacing-refresh and property tests
     fail. The disposal test still passes, because the pre-fix code already
     stopped at disposal.
   - **M2** (TypeScript, Swift and Rust): skip the property and command steps
     after the `Reset` step. The load and replacing-refresh tests fail in all
     three flavors. The property test fails in TypeScript and Rust, which have
     one. The disposal test passes, because no property step then runs. Swift
     has no failing-property test, because its subscribers cannot fail.
   - **M3** (every flavor): remove the disposal check between the steps. In
     TypeScript and Swift, also remove the completion of the property and command
     channels in `dispose()`, because a completed channel ignores a later send.
     In Rust, remove the commit checks between the steps. The disposal test
     fails in every flavor.

## 3. Consequences

- A bound view of a token-paged composition sees every committed `Items`,
  `CurrentToken` and `HasMore` change, and every command re-signal, even when a
  handler fails.
- C# and Python callers still receive the first failure, after the last step.
- TypeScript, Swift and Rust do not change behavior.
- The public API does not change.
- The catalog gains `COL-073`.
- Numbering. ADR-0234 to ADR-0238 are on develop from PR #2109, which merged
  at develop `45971e65`. This ADR follows them at 0239. It was first drafted as
  ADR-0234 and renumbered to 0239 while #2109 was still open, so the two pull
  requests never shared a number. No gap remains, and the registry has no
  reserved rows.

## 4. Rejected alternatives

- **Extend `COL-072`.** `COL-072` is the rule for `ObservableList` and the key
  views, and each flavor's `COL-072` tests use those types. Adding the
  token-paging cases would put two composition types and two route sets in one
  entry. A separate ID gives chapter 21 §8 its own row and each flavor its own test
  file.
- **Keep property handlers out of the rule.** A failing `items` or `hasMore` handler
  would then stop the later property notifications and the command re-signal. A
  bound "Load more" control could stay disabled after a refresh, which is the
  defect in #1883.
- **Swallow the failure in C# and Python.** ADR-0171 keeps the failure visible to
  the caller, and both flavors propagate subscriber failures elsewhere.
- **Change TypeScript, Swift and Rust.** Their channels already complete every
  step (§1). A change would add code without changing behavior.
