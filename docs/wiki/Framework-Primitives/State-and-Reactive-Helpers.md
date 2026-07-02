# State & Reactive Helpers

Use these helpers when the VM shape is already correct but you need reusable
reactive behavior layered onto it.

## Main Helpers

- `SearchableState<TItem>`
- `ExpandableState`
- `DerivedProperty<TValue>`
- `DiscriminatorVM<TKey>`
- `FormVM<TM>`

## Guidance

These helpers usually compose inside a larger VM rather than becoming the outer
VM boundary themselves.

## Related Pages

- \[[Capability Families|Framework-Primitives/Capability-Families]\]
- \[[FormVM|Framework-Primitives/ViewModel-Families/Specialized/FormVM]\]
- \[[DiscriminatorVM|Framework-Primitives/ViewModel-Families/Specialized/DiscriminatorVM]\]
