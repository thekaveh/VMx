# Component Family

Use `ComponentVM` for an addressable leaf VM that is not itself a container.

![Component Family Map](../../assets/diagrams/component-family.png)

Support links: [HTML](../../assets/diagrams/component-family.html),
[SVG](../../assets/diagrams/component-family.svg),
[PNG](../../assets/diagrams/component-family.png)

## Variants

- plain component for leaf state
- modeled component for mutable payload ownership
- readonly modeled component for immutable payload projection

## Key Traits

- owns no children
- participates fully in lifecycle and property change messaging
- exposes uniform selection commands even when the leaf implementation is inert

## Related Pages

- [[Composite Family|Framework-Primitives/ViewModel-Families/Composite-Family]]
- [[Forwarding & Wrapper Family|Framework-Primitives/ViewModel-Families/Forwarding-and-Wrapper-Family]]
