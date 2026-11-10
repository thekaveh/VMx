# ADR 0223 — The local-only raise primitive is inert after disposal

- **Status:** Accepted
- **Date:** 2026-11-09
- **Spec version:** 3.30.0 (chapter 05 §2.3, chapter 09 §1, `CVM-009` and
  `FWD-006`)
- **Amends:** [ADR-0221](0221-forwarding-decorators-notify-through-the-wrapped-component.md)
  Decision rule 4. Related:
  [ADR-0151](0151-forwarding-decorators-own-resources-on-the-wrapped-component.md),
  [ADR-0040](0040-iproperty-not-adopted.md), #1542.

## 1. Context

Chapter 05 §2.3 makes the dual-channel notification helper a no-op when a call
begins after VM disposal. The local-only raise primitive had no such rule.
ADR-0221 rule 4 therefore limited the forwarding-decorator disposal rule to the
dual-channel helper, because the C# primitive still raised its event (#1542).

The flavors that have a local-only primitive were checked against their source
and tests:

- **Python.** `_raise_property_changed` emits only while `_trigger_disposed` is
  false. Disposal sets that flag when the terminal publication finishes, and
  then completes the `property_changed` subject. A decorator calls the wrapped
  VM's primitive.
- **TypeScript.** `_raisePropertyChanged` emits only while `#triggersDisposed`
  is false. The terminal cleanup of disposal sets that flag and completes the
  `propertyChanged` subject. A decorator routes the call to the wrapped VM, so
  the wrapped VM's flag applies.
- **Swift.** `_raisePropertyChanged` returns at once when disposal was
  requested, when `status` is `.disposed`, or when the triggers are disposed.
  The terminal `status` and `isConstructed` notifications use a separate
  internal path that admits the disposed state. Both decorators override the
  primitive to call the wrapped VM.
- **C#.** `RaisePropertyChanged` invoked `PropertyChanged` with no check. The
  event keeps its handlers after disposal, so a handler ran. Both decorators
  forward to the wrapped VM's primitive, so they raised too.
- **Rust** has no local-only primitive.

The Python, TypeScript and Swift `FWD-006` tests already call the primitive
through a decorator after disposal and expect no emission. The C# `FWD-006`
test did not.

## 2. Decision

Decided under the owner's 2026-11-07 delegation: the rule that three flavors
already follow becomes the spec rule, and C# changes to match.

1. A call of the local-only raise primitive that begins after VM disposal is a
   no-op. Chapter 05 §2.3 states the rule next to the dual-channel rule.
1. A forwarding decorator's local-only primitive acts on the wrapped VM
   (ADR-0221), so it is a no-op after the wrapped VM is disposed. Chapter 09
   §1 states that neither helper emits after that disposal. This replaces
   ADR-0221 rule 4.
1. The library's own terminal `Status` and `IsConstructed` notifications are
   part of disposal. They still reach local observers.
1. C# `ComponentVMBase.RaisePropertyChanged` checks for `Disposed` under the
   lifecycle gate, as `NotifyPropertyChanged` does. Lifecycle publication and
   an admitted `NotifyPropertyChanged` call raise the event through a private
   path without that check. A call admitted before disposal therefore still
   completes, as chapter 05 §2.3 requires for the dual-channel helper.
1. `CVM-009` and `FWD-006` also call the local-only primitive after disposal,
   in every flavor that has one. No new conformance ID is needed.

The rule covers a call that begins after `dispose()` returns. A call made
inside `dispose()` itself, by a status observer or the dispose hook, is not
specified. C# and Swift refuse it once disposal is committed; Python and
TypeScript accept it until their terminal step sets the flag.

## 3. Consequences

- A C# subclass or decorator that raises a local notification after disposal
  no longer runs `PropertyChanged` handlers.
- The two notification helpers follow one disposal rule in every flavor.
- The C# change is a fix; the public surface does not change.

## 4. Rejected alternatives

- **Keep the C# behavior and document it as a divergence.** The other three
  flavors already no-op, and no binding needs a notification from a disposed
  VM.
- **Clear the C# `PropertyChanged` handlers at disposal.** The terminal
  `Status` notification must still reach them, and a handler that subscribes
  later would still run.
- **Specify the instant inside `dispose()` at which the primitive closes.**
  The flavors close at different points of the terminal publication, and no
  caller depends on that window.
