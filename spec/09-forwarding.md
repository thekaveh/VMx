# 09 — Forwarding decorators

VMx ships two forwarding decorators:

- `ForwardingComponentVM<M>` — wraps an `IComponentVM<M>`.
- `ForwardingCompositeVM<VM>` — wraps an `ICompositeVM<VM>`.

Forwarding decorators delegate every method and property of the wrapped VM to the
wrapped instance by default. Subclasses override individual members to customize
behavior. Use cases: lightweight proxies, caching wrappers, instrumentation,
logging.

Only the C# decorators are `abstract` classes. Python and TypeScript ship
concrete classes that a consumer can instantiate directly or subclass. Swift ships
`open class` decorators that subclass `ComponentVMOf` / `CompositeVM`. Rust has no
subclass overrides: `ForwardingComponentVm` exposes the builder-style
customization methods `with_hint_override` and `with_model_hint`, and
`ForwardingCompositeVm` exposes no override hooks.

The generic `IComponentVM<M>` extends `IComponentVM` with a `Model : M` property (settable
on the modeled component, read-only on the readonly component — see `05-component-vm.md`).
The generic `ICompositeVM<VM>` is declared canonically in `06-composite-vm.md` §2.1: it
extends `IComponentVM` with the `IList<VM>` surface, the `Current : VM?` slot, and the
`select_component`/`deselect_component`/`can_select_component` methods. The forwarding
decorators delegate every member of these generic interfaces.

## 1. `ForwardingComponentVM<M>`

```
abstract ForwardingComponentVM<M> : IComponentVM<M>:
    _wrapped : IComponentVM<M>
    Name => _wrapped.Name
    Hint => _wrapped.Hint
    Type => _wrapped.Type
    IsCurrent => _wrapped.IsCurrent
    IsConstructed => _wrapped.IsConstructed
    Status => _wrapped.Status
    Model => _wrapped.Model
    ModeledHint => _wrapped.ModeledHint
    SelectCommand => _wrapped.SelectCommand
    DeselectCommand => _wrapped.DeselectCommand
    SelectNextCommand => _wrapped.SelectNextCommand
    SelectPreviousCommand => _wrapped.SelectPreviousCommand
    ReconstructCommand => _wrapped.ReconstructCommand
    construct() => _wrapped.construct()
    destruct() => _wrapped.destruct()
    reconstruct() => _wrapped.reconstruct()
    dispose() => _wrapped.dispose()
    select() => _wrapped.select()
    deselect() => _wrapped.deselect()
    can_*() => _wrapped.can_*()
```

A subclass overrides any subset of these. (The `abstract` keyword above
describes the C# shape; see the flavor note at the top of this chapter.)

The decorator MAY be added to a composite or group anywhere its component type
is accepted. The wrapped component and every forwarding decorator around it
share one canonical ownership identity. Attaching any one of those public
identities therefore removes the previously retained component or decorator
from its composite or group before the new attachment commits. The destination
retains the exact decorator supplied by the caller, while parent ownership,
lifecycle, current flags, and built-in selection commands remain transparent to
the wrapped component. Multiple decorators MUST NOT make the wrapped component
a child of more than one container.

## 2. `ForwardingCompositeVM<VM>`

Same pattern, but additionally forwards the `IList<VM>` surface (Add, Remove,
indexer, iterator, Count, …), the `Current` property, and the selection methods.

Commonly-overridden hooks (these names are illustrative; each language flavor MAY adopt
its own convention as long as the override surface is documented; Rust's
`ForwardingCompositeVm` has none of these hooks):

- `DoGetType()` → override to return a different `ViewModelType`.
- `DoGetCurrent()` → override to alter selection semantics.
- `DoGetName()` → override to compute a name.
- `DoGetHint()` → override to compute a hint.
- `DoGetEnumerator()` → override to alter iteration order.

Subclasses MUST forward `dispose()` to the wrapped instance unless they explicitly
own the wrapped's lifetime.

A forwarding composite used as a child of another container follows the §1
ownership rules: one ownership identity with the wrapped composite, and
transparent parent and current flags. Open gaps: the TypeScript
`ForwardingCompositeVM` does not extend `ComponentVMBase`, and the Rust
`ForwardingCompositeVm` does not implement `VmNode`, so neither can be added to
a container; the type checker rejects the call.

## 3. Conformance

`FWD-001` through `FWD-004` in `12-conformance.md` cover:

- default delegation of every member to the wrapped VM
- transparent use as a composite or group child, including selection commands
- selective override replaces a single behavior
- ForwardingCompositeVM forwards iteration
- pre-owned and multiply decorated components retain one transferable owner

Forwarded disposal inherits `DISP-001`: repeated wrapper disposal may reach the
wrapped instance repeatedly at the call boundary, but the wrapped VM performs
terminal work at most once observably.
