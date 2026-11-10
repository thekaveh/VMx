# ADR 0221 — Forwarding decorators report property changes through the wrapped component

- **Status:** Accepted (Decision rule 4 amended by ADR-0223)
- **Date:** 2026-11-09
- **Spec version:** 3.30.0 (chapter 09 §1, §2, §3 and `FWD-006`)
- **Extends:** [ADR-0151](0151-forwarding-decorators-own-resources-on-the-wrapped-component.md).
  Related: [ADR-0124](0124-canonicalize-forwarding-ownership-and-callback-boundaries.md),
  [ADR-0213](0213-typescript-forwarding-composite-joins-containers.md),
  [ADR-0040](0040-iproperty-not-adopted.md), #1352.

## 1. Context

Chapter 05 §2.3 gives each component base a dual-channel notification helper,
which sends one `PropertyChangedMessage` and one local notification. The C#,
Python, TypeScript and Swift bases also keep a local-only raise primitive. A
forwarding-decorator subclass that overrides a property needs one of them to
report a change. Chapter 09 had no rule for these helpers on a decorator, and
the flavors differed (#1352):

- Python decorators do not run the base initializer, so both helpers raised
  `AttributeError`.
- TypeScript and Swift decorators run the base initializer and have their own
  property-changed subject. Both helpers emitted on that subject. The
  decorator's `propertyChanged` returns the wrapped VM's stream, so no
  subscriber received the name. The hub message named the decorator as its
  sender.
- Rust `notify_property_changed` on both decorators called the wrapped VM's
  helper. Rust has no local-only raise primitive.
- C# decorators do not derive from `ComponentVMBase` and had no helper.

ADR-0151 routes the owned-resource helper to the canonical ownership identity
(ADR-0124). PR #1537 routed the notification helpers in the same way in every
flavor and added C# helpers. It left the spec rule and the conformance ID
open, because no ADR number was reserved for it.

## 2. Decision

Decided under the owner's 2026-11-07 delegation: all flavors follow one rule,
and the simplest common-sense form is chosen. Rust already used it.

1. A decorator's notification helpers act on the canonical ownership
   identity, which is the wrapped VMx component. Nested decorators resolve to
   the same identity.
1. One call of the dual-channel helper sends one `PropertyChangedMessage`
   whose sender is the wrapped component. The decorator's property-changed
   stream, which is the wrapped component's stream, emits the name once.
1. One call of the local-only raise primitive emits the name once on that
   stream and sends no hub message. Rust has no such primitive.
1. After the wrapped component is disposed, the dual-channel helper emits on
   neither channel (chapter 05 §2.3). Chapter 05 gives the local-only
   primitive no disposal rule, and the C# primitive still raises the event.
   This ADR adds no such rule.
1. C# `ForwardingComponentVM` and `ForwardingCompositeVM` gain protected
   `NotifyPropertyChanged` and `RaisePropertyChanged`.
1. In C#, Python and TypeScript a decorator may wrap a component that does not
   derive from the VMx base class. Such a decorator cannot report a property
   change, and the call fails, as a resource registration does (ADR-0151).
1. `FWD-006` is normative in all five flavors.

The wrapped component is the sender because every other message that a
decorator causes already comes from it. A binding that matches messages to the
wrapped component, such as the React `useVm` hook through `wrappedBase`
(ADR-0213), therefore sees the decorator's property changes too.

## 3. Consequences

- A decorator subclass can report a property change in every flavor, and its
  subscribers receive it.
- A hub subscriber that filters by sender sees the wrapped component, not the
  decorator.
- C# gains two protected members on each decorator. The change is additive.
- The catalog gains `FWD-006`.

## 4. Rejected alternatives

- **Send the hub message with the decorator as sender.** The decorator's local
  stream is the wrapped stream, so the local notification would still come
  from the wrapped component. The two channels would name different senders.
- **Give each decorator its own property-changed stream.** Every forwarded
  property already notifies through the wrapped stream. A second stream would
  split one property surface into two.
- **Leave the helpers undefined on decorators.** Python would keep raising,
  and TypeScript and Swift would keep dropping the local notification.
