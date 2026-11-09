# ADR 0171 — A failing local subscriber does not suppress the hub message

- **Status:** Accepted (Extended by ADR-0191 and ADR-0220; excluded paths
  superseded by ADR-0220)
- **Date:** 2026-11-07
- **Spec version:** 3.30.0 (chapter 01 §1.4, chapter 21 §2.5, §4.6 and
  `COL-066`)

## 1. Context

Each hub-publishing collection commits a change, then delivers the local
collection-change notification, then sends the equivalent
`CollectionChangedMessage` to its hub (chapter 21 §2.5). The local delivery
and the hub send ran in sequence with no exception boundary in C# and Python.
A local subscriber that threw therefore unwound past the hub send. The change
stayed committed, but the hub never received a message for it (#1051).

Probes at `cd84722d` showed this behavior in these paths:

- C# `ServicedObservableCollection<T>` and
  `KeyedServicedObservableCollection<TKey, TItem>`: a throwing
  `CollectionChanged` handler on add, remove, replace, move, clear and
  whole-list replacement.
- C# `ObservableDictionary`: a throwing `ItemAdded`, `ItemRemoved`,
  `ItemReplaced` or `Reset` handler. Such a handler also skipped the local
  `CollectionChanged` event.
- Python `ServicedObservableCollection`, `KeyedServicedObservableCollection`
  and `ObservableDictionary`: a raising subscriber of any local stream.

The other flavors already published. rxjs 7 reports a TypeScript subscriber
error asynchronously, so the mutation continues and returns normally. Rust
local delivery catches a panicking subscriber. Swift local publishers have the
failure type `Never`, and a Combine `sink` closure cannot throw.

Chapter 21 §2.5 said that subscriber failures follow the flavor's rules and
that the primitive adds no failure policy. That sentence allowed the C# and
Python behavior. The containers already sent the hub message and then rethrew
(#723). But chapter 01 §1.4 and ADR-0142 did not state a failure rule, so that
behavior existed only in code comments.

## 2. Decision

Decided under the owner's 2026-11-07 delegation: all flavors follow one rule,
and the simplest common-sense form is chosen.

- A failing local subscriber does not undo the committed change and does not
  suppress its hub message. The collection or container still sends exactly
  one `CollectionChangedMessage` for the change.
- C# and Python rethrow the first failure after publication. A local failure
  takes precedence over a later hub failure. C# keeps the original stack trace
  through `ExceptionDispatchInfo`. Python catches `BaseException`, as the
  container helper does.
- In the C# dictionary, a failing granular-event handler also does not skip the
  later `CollectionChanged` event. The first failure is rethrown after the hub
  send.
- TypeScript, Rust and Swift need no code change. TypeScript reports the
  failure through rxjs and returns normally. Rust catches the panic and returns
  normally. Swift subscribers cannot fail.
- Chapter 01 §1.4 states the rule for `CompositeVM` and `GroupVM`. Chapter 21
  §2.5 states it for the hub-publishing collections, and §4.6 refers to it for
  the dictionary.
- `COL-066` is normative. C#, Python, TypeScript and Rust test the behavior.
  Swift asserts the structure: every local publisher has the failure type
  `Never`, and each committed change reaches the hub once.

The rule covers the local collection-change channel and the dictionary's
granular events. These paths stay outside it:

- C# `PropertyChanged("Count")` and `PropertyChanged("Item[]")` handlers.
  `ObservableCollection<T>` raises them before `CollectionChanged`, so a
  throwing handler still skips the collection event and the hub message.
- Subscribers of the dictionary's `Keys1` and `Keys2` views. A throwing key-view
  subscriber still skips the dictionary's own notifications. The key-view
  notification order is an open question (#1176).

## 3. Consequences

- A hub observer sees every committed change, even when a local subscriber
  fails. C# and Python callers still see the local failure.
- The C# `ObservableCollection<T>` reentrancy block is still held only during
  the local delivery. The hub send runs after it is released, as before.
- A Python dictionary that is disposed before a mutation still publishes
  nothing.
- The library conformance catalog grows from 444 to 445 IDs.

## 4. Rejected alternatives

- Keep the flavor-specific policy. Hub observers in C# and Python would keep
  missing committed changes, and the five flavors would keep diverging.
- Swallow the local failure in C# and Python. Both flavors propagate subscriber
  failures to the caller elsewhere, including in the containers.
- Cover the C# `PropertyChanged` and key-view paths in this change. Both need a
  redesign of the notification sequence, and the key-view path depends on
  #1176.
