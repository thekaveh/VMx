# 09 — Forwarding decorators

VMx ships two forwarding decorators:

- `ForwardingComponentVM<M>` — wraps an `IComponentVM<M>`.
- `ForwardingCompositeVM<VM>` — wraps an `ICompositeVM<VM>`.

Forwarding decorators delegate every method and property of the wrapped VM to the
wrapped instance by default. Subclasses override individual members to customize
behavior. Use cases: lightweight proxies, caching wrappers, instrumentation,
logging.

## `ForwardingComponentVM<M>`

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

A subclass overrides any subset of these.

## `ForwardingCompositeVM<VM>`

Same pattern, but additionally forwards the `IList<VM>` surface (Add, Remove,
indexer, iterator, Count, …), the `Current` property, and the selection methods.

Override hooks specifically called out in the legacy library:

- `DoGetType()` → override to return a different `ViewModelType`.
- `DoGetCurrent()` → override to alter selection semantics.
- `DoGetName()` → override to compute a name.
- `DoGetHint()` → override to compute a hint.
- `DoGetEnumerator()` → override to alter iteration order.

Subclasses MUST forward `dispose()` to the wrapped instance unless they explicitly
own the wrapped's lifetime.

## Conformance

`FWD-001` through `FWD-003` in `12-conformance.md` cover:

- default delegation of every member to the wrapped VM
- selective override replaces a single behavior
- ForwardingCompositeVM forwards iteration
