# Forwarding & Wrapper Family

Use forwarding wrappers when you need to instrument, adapt, or selectively
override a shipped VM without copying its whole surface.

![Forwarding Wrapper Family Map](../../assets/diagrams/forwarding-wrapper-family.png)

Support links: [HTML](../../assets/diagrams/forwarding-wrapper-family.html),
[SVG](../../assets/diagrams/forwarding-wrapper-family.svg),
[PNG](../../assets/diagrams/forwarding-wrapper-family.png)

## Shipped Families

- `ForwardingComponentVM<M>`
- `ForwardingCompositeVM<VM>`

## Guidance

Wrappers delegate to an inner VM by default. Override only the members you need
to change.

## Related Pages

- [[Component Family|Framework-Primitives/ViewModel-Families/Component-Family]]
- [[Composite Family|Framework-Primitives/ViewModel-Families/Composite-Family]]
