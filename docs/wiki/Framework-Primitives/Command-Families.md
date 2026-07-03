# Command Families

Use the command family when behavior should be executable, bindable, and
reactively re-evaluated without changing the VM hierarchy itself.

![Commands And Capabilities Map](../../assets/diagrams/commands-capabilities.png)

Support links: [HTML](../../assets/diagrams/commands-capabilities.html),
[SVG](../../assets/diagrams/commands-capabilities.svg),
[PNG](../../assets/diagrams/commands-capabilities.png)

## Main Pieces

- `RelayCommand` and parameterized relay commands
- decorators such as composite and confirmation wrappers
- fluent helpers such as confirm, precede, succeed, and wrap
- `ModeledCrudCommands` for selection-driven CRUD bundles

## Related Pages

- [[Composite Family|Framework-Primitives/ViewModel-Families/Composite-Family]]
- [[FormVM|Framework-Primitives/ViewModel-Families/Specialized/FormVM]]
- [[Services, Messages & Dispatching|Framework-Primitives/Services-Messages-and-Dispatching]]
