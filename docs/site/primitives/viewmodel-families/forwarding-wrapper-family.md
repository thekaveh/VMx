# Forwarding & Wrapper Family

## When To Use It

Use forwarding wrappers when you need to instrument, adapt, or selectively
override a shipped VM without rewriting its whole surface. Logging, policy
checks, caching, and host-specific decoration are the common cases.

## Shape And Ownership

VMx ships two forwarding families:

- `ForwardingComponentVM<M>` around a component-shaped inner VM
- `ForwardingCompositeVM<VM>` around a composite-shaped inner VM

By default every property, method, command, and iterator call delegates to the
wrapped instance. You override only the members you need to change.

## Lifecycle And Messaging

Forwarding decorators do not add their own lifecycle semantics. They inherit the
inner VM's behavior unless an override changes it. In practice this means:

- property-changed and status behavior still originate from the wrapped VM
- iteration over forwarded composites still reflects the wrapped child list
- `dispose()` should usually forward so lifetime ownership remains explicit

## Cross-Language Surface

| Concept                    | C#                                     | Python                        | TypeScript                      | Swift                            |
| -------------------------- | -------------------------------------- | ----------------------------- | ------------------------------- | -------------------------------- |
| Component wrapper          | `ForwardingComponentVM<M>`             | `ForwardingComponentVM[M]`    | `ForwardingComponentVM<M>`      | `ForwardingComponentVM<Model>`   |
| Composite wrapper          | `ForwardingCompositeVM<VM>`            | `ForwardingCompositeVM[VM]`   | `ForwardingCompositeVM<VM>`     | `ForwardingCompositeVM<Child>`   |
| Canonical wrapped contract | `IComponentVM<M>` / `ICompositeVM<VM>` | component/composite protocols | component/composite base shapes | component/composite base classes |

## Example

The Python and Swift forwarding modules show the intended pattern clearly:

- Python documents a logging wrapper in `vmx/forwarding/component.py`
- Swift keeps `ForwardingComponentVM` and `ForwardingCompositeVM` as open
  classes whose overrides can alter selected accessors while the rest forward

The key design point is that the wrapper changes behavior by composition, not by
copying or re-implementing the wrapped VM.

## Common Pitfalls

- Re-implementing the entire VM instead of forwarding and overriding the one
  member that actually differs.
- Forgetting to forward disposal when the wrapper does not own an independent
  lifetime.
- Treating forwarding as a new hierarchy root. It is a wrapper around an
  existing contract, not a separate primitive family.

## Related Primitives

- [Component Family](component-family.md)
- [Composite Family](composite-family.md)
- [Builders, Collections & Tree Utilities](../builders-collections-tree-utilities.md)
