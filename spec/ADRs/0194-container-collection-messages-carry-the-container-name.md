# ADR 0194 — Container collection messages carry the container's `Name`

- **Status:** Accepted
- **Date:** 2026-11-09
- **Spec version:** 3.30.0 (chapter 03 §1, chapter 21 §2.4, `COMP-042` and
  `GRP-012`)
- **Related:** [ADR-0054](0054-v3-typescript-uniform-message-sender.md),
  [ADR-0120](0120-rust-id-based-message-senders.md),
  [ADR-0142](0142-vm-collections-publish-collection-changes-on-the-hub.md),
  #1309.

## 1. Context

A `CompositeVM` or `GroupVM` sends one `CollectionChangedMessage` to its hub
for each membership change, with itself as sender (ADR-0142). Chapter 03 §1
says that the diagnostic sender name "typically" equals the sender VM's
`Name`. No section fixed the name of a container's collection message (#1309).

- C#, Python and TypeScript derive the name from the sender's runtime type:
  `GetType().Name`, `type(sender).__name__` and `constructor.name`. A C#
  `CompositeVM<T>` thus reports `` CompositeVM`1 ``. Their typed message has no
  stored name field.
- Swift passes `container.name`. Rust gives the container's item list the
  container name, and each message copies it into `sender_name`.

Other messages from the same container, such as
`ConstructionStatusChangedMessage`, carry its `Name`. In C#, Python and
TypeScript, a hub filter on the name `people` thus misses the collection
messages of a composite named `people`. The TypeScript DevTools observer shows
`CompositeVM` in each action type. The open-decisions ledger recorded the split
as item 2.4.

The issue named three rules: the container's `Name`, the runtime type name, or
a flavor-defined name.

## 2. Decision

Decided under the owner's 2026-11-07 delegation: the container's `Name`. It is
the simplest rule that all flavors can follow. It matches the other messages
that a container sends, such as `ConstructionStatusChangedMessage`.

1. A `CollectionChangedMessage` sent by a `CompositeVM`, a `GroupVM` or a
   subclass carries the container's `Name` as its sender name. A VM name does
   not change after construction, so the value is fixed.
1. A plain collection or dictionary has no `Name`. Its messages keep a
   flavor-defined sender name, its type name in every flavor today.
1. The typed message in C#, Python and TypeScript gains a stored sender name.
   Its default is the sender's runtime type name, so plain collections and
   third-party senders keep their current name. The container helper sets the
   name. Swift already stores `senderName`, and Rust already stores
   `sender_name`.
   - C#: `SenderName` becomes an `init` property whose default is
     `Sender.GetType().Name`. The container helper sets it with a `with`
     expression.
   - Python: `sender_name` becomes a keyword field that defaults to `""`.
     `__post_init__` replaces an empty value with `type(sender).__name__`.
   - TypeScript: `senderName` becomes a stored `readonly` field. Each factory
     takes an optional trailing `senderName`, which defaults to the
     constructor name.
1. `COMP-042` and `GRP-012` now require the sender name of a named container.
   The tests in all five flavors assert it.
1. Chapter 21 §2.4 states the rule. Chapter 03 §1 points to it.

## 3. Consequences

- A hub filter on a container's name sees its collection messages in every
  flavor.
- C#, Python and TypeScript change behavior. A consumer that filtered
  container messages by `CompositeVM` or `GroupVM` must filter by the
  container's `Name` or by sender identity instead. Each CHANGELOG states this.
- The TypeScript DevTools action type shows the container's name.
- The C# record equality of `CollectionChangedMessage<T>` now includes
  `SenderName`. Two messages with the same sender have the same name, so no
  equality result changes.
- Swift and Rust need no library change.
- Item 2.4 leaves the open-decisions ledger.
- The catalog gains no ID.

## 4. Rejected alternatives

- **The runtime type name.** A name filter could not tell two containers of
  one type apart. C# would report a generic arity suffix such as
  `` CompositeVM`1 ``. Swift, Rust and their tests would change.
- **A flavor-defined name.** The split would stay, and a cross-flavor hub
  filter would still need per-flavor code.
- **Deriving the name from the sender at read time.** The message type would
  depend on the component types. A stored value matches Swift and Rust.
