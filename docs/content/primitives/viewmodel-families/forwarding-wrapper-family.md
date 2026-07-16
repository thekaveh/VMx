# 6.2.7. Forwarding & Wrapper Family

## 6.2.7.1. When To Use It

Use forwarding wrappers when you need to instrument, adapt, or selectively
override a shipped VM without rewriting its whole surface. Logging, policy
checks, caching, and host-specific decoration are the common cases.

<img src="../../../assets/diagrams/forwarding-wrapper-family.svg" alt="Forwarding Wrapper Family Map" class="vmx-diagram" />

<p>
  <a href="../../../assets/diagrams/forwarding-wrapper-family.html">HTML</a>
  &middot;
  <a href="../../../assets/diagrams/forwarding-wrapper-family.svg">SVG</a>
  &middot;
  <a href="../../../assets/diagrams/forwarding-wrapper-family.png">PNG</a>
</p>

## 6.2.7.2. Shape And Ownership

VMx ships two forwarding families:

- `ForwardingComponentVM<M>` around a component-shaped inner VM
- `ForwardingCompositeVM<VM>` around a composite-shaped inner VM

By default every property, method, command, and iterator call delegates to the
wrapped instance. You override only the members you need to change.

## 6.2.7.3. Lifecycle And Messaging

Forwarding decorators do not add their own lifecycle semantics. They inherit the
inner VM's behavior unless an override changes it. In practice this means:

- property-changed and status behavior still originate from the wrapped VM
- iteration over forwarded composites still reflects the wrapped child list
- `dispose()` should usually forward so lifetime ownership remains explicit

## 6.2.7.4. Cross-Language Surface

| Concept                    | C#                                     | Python                        | TypeScript                      | Swift                            |
| -------------------------- | -------------------------------------- | ----------------------------- | ------------------------------- | -------------------------------- |
| Component wrapper          | `ForwardingComponentVM<M>`             | `ForwardingComponentVM[M]`    | `ForwardingComponentVM<M>`      | `ForwardingComponentVM<Model>`   |
| Composite wrapper          | `ForwardingCompositeVM<VM>`            | `ForwardingCompositeVM[VM]`   | `ForwardingCompositeVM<VM>`     | `ForwardingCompositeVM<Child>`   |
| Canonical wrapped contract | `IComponentVM<M>` / `ICompositeVM<VM>` | component/composite protocols | component/composite base shapes | component/composite base classes |

## 6.2.7.5. Example

The key design point is that the wrapper changes behavior by composition, not by
copying or re-implementing the wrapped VM:

=== "C#"

    ```csharp
    private sealed class HintOverrideVM : ForwardingComponentVM<string>
    {
        public HintOverrideVM(IComponentVM<string> inner) : base(inner) { }
        public override string Hint => "OVERRIDE";
    }
    ```

=== "Python"

    ```python
    class HintOverrideVM(ForwardingComponentVM[str]):
        @property
        def hint(self) -> str:
            return "OVERRIDE"
    ```

=== "TypeScript"

    ```ts
    class HintOverrideVM extends ForwardingComponentVM<string> {
      override get hint(): string {
        return "OVERRIDE";
      }
    }
    ```

=== "Swift"

    ```swift
    final class ModeledHintOverrideVM: ForwardingComponentVM<String> {
        override var modeledHint: String { "OVERRIDE" }
    }
    ```

Swift is the explicit divergence here: `name` and `hint` are stored `let`
properties on `ComponentVMBase`, so the nearest overridable analog is
`modeledHint`, not `hint`.

## 6.2.7.6. Common Pitfalls

- Re-implementing the entire VM instead of forwarding and overriding the one
  member that actually differs.
- Forgetting to forward disposal when the wrapper does not own an independent
  lifetime.
- Treating forwarding as a new hierarchy root. It is a wrapper around an
  existing contract, not a separate primitive family.

## 6.2.7.7. Related Primitives

- [Component Family](component-family.md)
- [Composite Family](composite-family.md)
- [Builders, Collections & Tree Utilities](../builders-collections-tree-utilities.md)
