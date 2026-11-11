# ADR 0177 — Dictionary key views update before the dictionary events

- **Status:** Accepted (Failing key-view note superseded by ADR-0220)
- **Date:** 2026-11-08
- **Spec version:** 3.30.0 (chapter 21 §4.2, §8 and `COL-067`)

## 1. Context

`ObservableDictionary` keeps two live key views, `Keys1` and `Keys2`. Chapter
21 §4.2 said that the views "stay in sync with mutations". It did not state an
order for the view notifications. It also did not state what a handler can
read during a notification (#1176).

In C#, Python, TypeScript and Swift, `Add`, `Remove` and `Clear` change the
entries and the count first. Then `Keys2` changes and notifies, then `Keys1`
changes and notifies. Then the dictionary raises its own events and sends the
hub message. An indexer or `set` call that inserts a new key pair uses the same
path as `Add`. #960 and #1128 put `Keys2` first to fix #772 and #1075. Thus a
`Keys1` handler reads the updated `Keys2`, but a `Keys2` handler can read a
`Keys1` that does not show the change yet.

Rust `ObservableMultiDictionary` has no live views. `keys1()` and `keys2()`
return snapshots that they compute from the entries. Rust has no local event,
so mutations are observable only through the hub.

The issue named three options:

1. Specify the current order, with `Keys2` before `Keys1`.
1. Guarantee only the final state. A key-view handler must not rely on the
   other view.
1. Update both views before either view notifies, as chapter 21 §2.13 requires
   for the keyed collection.

## 2. Decision

Decided under the owner's 2026-11-07 delegation: option 2. All flavors follow
one rule, and the simplest common-sense form is chosen. No flavor needs a code
change.

- `Add`, `Remove`, `Clear`, and an indexer or `set` insert change the entries
  and `Count` first. Then each key view that changes notifies its own
  subscribers. A view changes only when a distinct key first appears or last
  disappears. Then the dictionary raises its own events and sends the hub
  message.
- The order of the `Keys1` and `Keys2` notifications is not specified. A
  key-view handler reads the updated entries, the updated `Count`, and its own
  updated view. It must not rely on the other view.
- A dictionary-event handler and a hub subscriber read both views updated for
  that mutation.
- A value replacement at an existing key pair changes no key view.
- A nested mutation from a key-view handler follows the same order. No single
  global order of nested and outer events is required, as in §2.13. During a
  nested mutation, a view can still lack the change of the outer mutation. The
  outer change shows in that view when the outer mutation completes. `COL-067`
  tests only mutations that are not nested.
- `COL-067` is normative. C#, Python, TypeScript and Swift record the state in
  handlers on both views, on the dictionary events and on the hub. Rust records
  the state in a hub subscriber that reads the `keys1()` and `keys2()`
  snapshots.

Decided under the owner's 2026-11-07 delegation: the new conformance ID is
`COL-067`, because `COL-066` already belongs to ADR-0171.

Failing key-view subscribers stay outside this rule. ADR-0171 already records
that a throwing key-view subscriber can skip the dictionary's own
notifications.

## 3. Consequences

- A consumer that needs both views together subscribes to the dictionary event
  or to the hub, not to one key view.
- The current `Keys2`-first order stays an implementation detail. The unit
  tests from #960 and #1128 keep it, because the first-appearance fixes for
  #772 and #1075 depend on it.
- The library conformance catalog grows from 445 to 446 IDs.

## 4. Rejected alternatives

- Option 1, specify the current order. Each flavor would have to keep a
  `Keys2`-first order that exists only to work around #772 and #1075. A
  `Keys2` handler would still read a stale `Keys1`.
- Option 3, update both views before either view notifies. Four flavors would
  need a new internal notification path. A handler that changes the dictionary
  could make the pending event index of the other view stale. The reentrancy
  handling from #960 and #1128 would need a redesign.
