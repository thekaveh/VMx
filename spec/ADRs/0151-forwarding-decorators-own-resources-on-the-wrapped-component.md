# ADR 0151 — Forwarding decorators register owned resources on the wrapped component

- **Status:** Accepted
- **Date:** 2026-10-22
- **Spec version:** 3.30.0
- **Related:** [ADR-0090](0090-owned-resource-registration-and-public-hub.md) (owned-resource
  helper), [ADR-0124](0124-canonicalize-forwarding-ownership-and-callback-boundaries.md)
  (canonical forwarding ownership identity)

## 1. Context

A subclass of `ForwardingComponentVM` that registered a resource with the
owned-resource helper (chapter 02 §2.3) behaved differently in each flavor
(#650):

- TypeScript stored the resource on the decorator. The decorator's `dispose()`
  forwards to the wrapped component, so nothing released the resource, even
  when it was registered after disposal (`DISP-010`).
- Python decorators do not run the base initializer, so `_own` raised
  `AttributeError` on both `ForwardingComponentVM` and `ForwardingCompositeVM`.
- C# decorators do not derive from `ComponentVMBase` and had no `Own`.
- Swift and Rust forwarded `own` to the wrapped component.

ADR-0124 gives a wrapped component and every decorator around it one canonical
ownership identity for container membership. Chapter 09 did not say whether
resource ownership follows the same identity.

## 2. Options considered

1. **Register on the canonical identity.** The decorator's helper forwards to
   the wrapped component, as Swift and Rust already do. The resource follows
   the wrapped component's terminal disposal.
1. **Give each decorator its own resource list.** The decorator would release
   its resources when it is disposed. A decorator's `dispose()` forwards, and
   the wrapped component can be disposed through another decorator or
   directly, so this list would need a second disposal path and could release
   before or after the component it belongs to.
1. **Reject registration on a decorator.** Safe, but it removes a capability
   that Swift and Rust ship and that subclasses need for per-decorator
   subscriptions.

## 3. Decision

Option 1. Chapter 09 §1 defines it:

1. A decorator's owned-resource helper registers each resource with the
   canonical ownership identity. Nested decorators resolve to the same
   identity.
1. The resource is released when the wrapped component is disposed, through
   any decorator or directly, in the LIFO order shared by every registration
   on that identity (`DISP-007`). Registration after that disposal releases
   the resource at once, exactly once (`DISP-010`).
1. The rule applies to `ForwardingCompositeVM` in C#, Python, Swift, and Rust.
   The TypeScript `ForwardingCompositeVM` does not extend `ComponentVMBase`
   and has no helper (chapter 09 §2).
1. In C#, Python, and TypeScript a decorator may wrap a component that does
   not derive from the VMx base class. Such a decorator cannot register
   resources, and the call fails instead of keeping the resource.

Implementation: TypeScript and Python forward from the base helper when the
VM's ownership identity is not the VM itself. C# adds protected `Own`
overloads to both decorators that register through an internal seam on the
identity.

## 4. Consequences

- `FWD-005` covers nested decorators, LIFO release, registration after
  disposal, repeated disposal, and disposal of the wrapped component directly,
  in all five flavors.
- **Compatibility.** TypeScript resources registered on a decorator are now
  released; before, they were never released. Python registration on a
  decorator now works instead of raising. C# gains protected `Own` members on
  `ForwardingComponentVM<M>` and `ForwardingCompositeVM<VM>`; a subclass that
  already declares a member named `Own` now hides it and gets a compiler
  warning. Swift and Rust are unchanged. This is a minor spec bump to 3.30.0.
- A decorator that overrides `dispose()` without forwarding keeps its
  registrations until the wrapped component is disposed.
