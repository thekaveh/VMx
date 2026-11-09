# ADR 0220 — A failing subscriber skips no later notification step of a collection change

- **Status:** Accepted
- **Date:** 2026-11-09
- **Spec version:** 3.30.0 (chapter 03 §3.6, chapter 21 §2.5, §3.3, §3.5,
  §4.6 and `COL-072`)
- **Extends:** [ADR-0171](0171-failing-local-subscriber-does-not-suppress-the-hub-message.md)
  and [ADR-0191](0191-subscriber-failures-do-not-stop-delivery-or-detach.md).
  Related: [ADR-0026](0026-observable-list.md),
  [ADR-0177](0177-dictionary-key-views-update-before-dictionary-events.md),
  #1367, #1430.

## 1. Context

ADR-0171 says that a failing local subscriber does not suppress the hub
message of a committed collection change. ADR-0191 says that the failure does
not stop the delivery to the later subscribers of the same channel. Both
decisions left three paths outside their rule.

- **`ObservableList` (#1367).** In C# and Python, the list sent the granular
  or `Reset` event, then `PropertyChanged("Count")`, with no exception
  boundary between the two steps. A failing event subscriber left the change
  committed, but the `Count` notification did not occur. In C#, the
  `CollectionChanged` event also did not occur. `ObservableList` has no hub in
  C# and Python, so ADR-0171 did not cover it.
- **Dictionary key views (#1430).** A throwing `Keys1` or `Keys2` subscriber
  skipped the dictionary's own events and its hub message. A throwing `Keys2`
  subscriber on `Add` also skipped the `Keys1` update, so `Keys1` did not list
  the new key. ADR-0171 linked this path to the open order question #1176.
  ADR-0177 then decided that order, so no open decision blocks this path.
- **C# `PropertyChanged` handlers (#1430).** `ObservableCollection<T>` raises
  `PropertyChanged("Count")` and `PropertyChanged("Item[]")` before it calls
  `OnCollectionChanged`. The VMx exception boundary was inside that override,
  so a throwing property handler skipped `CollectionChanged` and the hub
  message.

TypeScript reports a subscriber error through rxjs, and the mutation
continues. Rust `EventStream::send` runs each subscriber inside
`catch_unwind`. Swift subscribers cannot fail. These three flavors already
completed every step. PR #1537 changed C# and Python and added their tests.
It left the rule, the spec text and the conformance ID open, because no ADR
number was reserved for it.

## 2. Decision

Decided under the owner's 2026-11-07 delegation: all flavors follow one rule,
and the simplest common-sense form is chosen. The rule is the ADR-0171 and
ADR-0191 rule, applied to every notification step of a committed collection
change.

1. **No skipped step.** A failing subscriber of one notification step does not
   skip a later step of the same committed change. The steps are the granular
   or `Reset` event, the C# `CollectionChanged` event, the `Count` and
   `Item[]` property notifications, the key-view notifications, the
   dictionary's own events and the hub message. Each step reaches every
   subscriber that is attached when it starts (ADR-0191 rule 1).
1. **Failure route.** C# and Python rethrow the first failure after the last
   step. TypeScript, Swift and Rust keep their current route, and the call
   returns normally.
1. **`ObservableList`.** After a failing granular or `Reset` subscriber, the
   list still sends `Count` when `Count` changed. In C#, it also still raises
   `CollectionChanged`. The rule covers add, insert, remove, replace, clear,
   whole-list replacement and the batch exit.
1. **Key views.** After a failing `Keys1` or `Keys2` subscriber, the
   dictionary still updates the other view, raises its own events and sends
   its hub message. When the call returns, both views match the entries. A
   key view notifies before the dictionary's events, so its failure is the
   first failure. The order of the two key-view notifications stays
   unspecified (ADR-0177).
1. **C# `PropertyChanged` handlers.** During a serviced-collection mutation, a
   throwing `Count` or `Item[]` handler waits until `CollectionChanged` and the
   hub send have run. A `PropertyChanged` that is raised outside a mutation,
   such as a subclass's own property, runs every handler and rethrows the
   first failure at once.
1. **Conformance.** `COL-072` is normative. C# and Python test the list, the
   key views and, in C#, the property handlers, with a failing subscriber and
   the rethrown failure. TypeScript and Rust test the list and the key views
   with a failing subscriber and a normal return. Swift asserts the structure:
   every list and key-view publisher has the failure type `Never`.

Chapter 21 §2.5 states the rule, §3.3 and §3.5 apply it to `ObservableList`,
and §4.6 applies it to the key views. Chapter 03 §3.6 adds these channels to
the subscriber-failure channel list.

## 3. Consequences

- A binding to `Count` and a C# `CollectionChanged` binding see every committed
  list change, even when another subscriber fails.
- A hub observer of a dictionary or a C# serviced collection sees every
  committed change, even when a key-view or property handler fails.
- C# and Python callers still see the first failure.
- TypeScript, Swift and Rust do not change.
- The catalog gains `COL-072`.

## 4. Rejected alternatives

- **Keep the paths outside the rule.** Bindings in C# and Python would keep
  missing committed changes, and the five flavors would keep diverging.
- **Swallow the failure in C# and Python.** Both flavors propagate subscriber
  failures to the caller elsewhere (ADR-0171).
- **Raise the C# `Count` and `Item[]` notifications after `CollectionChanged`.**
  `ObservableCollection<T>` fixes that order, and WPF bindings depend on it.
  Holding the failure keeps the platform order.
