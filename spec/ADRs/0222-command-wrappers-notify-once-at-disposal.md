# ADR 0222 — Command wrappers notify `CanExecuteChanged` once at disposal

- **Status:** Accepted
- **Date:** 2026-11-09
- **Spec version:** 3.30.0 (chapter 04 §8.4, §11 and `CMDD-019`)
- **Extends:** [ADR-0134](0134-disposed-command-wrappers-are-inert.md) Decision
  rule 7. Related: [ADR-0068](0068-disposed-relay-commands-are-inert.md),
  [ADR-0012](0012-command-decorators.md), PR #956, #1459.

## 1. Context

Chapter 04 §8.4 let a flavor notify `CanExecuteChanged` once when a
`CompositeCommand`, `DecoratorCommand` or `ConfirmationDecoratorCommand` is
disposed. ADR-0134 rule 7 left that notification optional. The flavors used
the option differently (#1459):

- TypeScript and Swift notified once on each wrapper's own stream. PR #956
  made the TypeScript wrappers notify, so a React control bound to a disposed
  wrapper re-reads `CanExecute`.
- Rust `CompositeCommand` notified once on its own hub. The Rust decorators
  returned the inner hub and sent nothing.
- The C# and Python wrappers sent nothing. The Python wrappers returned the
  inner stream or a merge of the inner streams.

A binding that listens only to the wrapper re-reads `CanExecute` when the
wrapper notifies. Without the notification, a control bound to a disposed C#
or Python wrapper, or to a Rust decorator, can stay enabled. The relay
commands of C#, Python and Rust already notify at disposal (chapter 04 §5).

PR #1537 made every wrapper notify once, on a stream of its own, in all five
flavors. It left the spec change and the conformance ID open, because no ADR
number was reserved for it.

## 2. Decision

Decided under the owner's 2026-11-07 delegation: all flavors follow one rule,
and the simplest common-sense form is chosen. Three of the five flavors
already notified for at least one wrapper.

1. Disposing a live wrapper sends exactly one `CanExecuteChanged`
   notification to the wrapper's own subscribers. The wrapper is already inert
   when it notifies, so a subscriber reads `CanExecute == false`.
1. A repeated disposal sends nothing.
1. The subscribers of an inner command receive nothing. A wrapper never sends
   on, completes or disposes an inner command's stream (ADR-0134 rule 7).
1. Each wrapper therefore exposes a stream of its own, which relays the inner
   notifications. In Python and TypeScript it also passes the inner
   completion through, and a Rust decorator's hub completes when the inner
   hub completes.
1. Whether the wrapper's own stream completes at disposal stays
   flavor-defined.
1. `CMDD-019` is normative in all five flavors. Each conformance test disposes
   each of the three wrappers twice.

The relay-command clause of chapter 04 §5 stays a MAY. This decision covers
the wrappers only.

## 3. Consequences

- A control bound to any disposed wrapper re-reads `CanExecute` and shows the
  disabled state in every flavor.
- C# and Python wrappers raise one more notification than before. Code that
  counted wrapper notifications sees one at disposal.
- Rust `DecoratorCommand` and `ConfirmationDecoratorCommand` no longer return
  the inner hub from `can_execute_changed()`. Their relayed messages carry the
  wrapper's sender name, as `CompositeCommand` messages do.
- The catalog gains `CMDD-019`.

## 4. Rejected alternatives

- **Keep the notification optional.** Bindings to C# and Python wrappers and
  to Rust decorators would keep showing an enabled control for an inert
  command.
- **Notify on the inner command's stream.** The inner command stays live and
  owned by its creator. Its other subscribers would see a change that did not
  happen to that command.
- **Complete the wrapper's stream at disposal in every flavor.** C# events
  have no completion, and the Python and TypeScript streams pass the inner
  completion through. The binding needs only the notification.
