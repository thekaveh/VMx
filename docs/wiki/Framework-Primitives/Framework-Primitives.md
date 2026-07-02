# Framework Primitives

This section is the practical map of the VMx surface: which primitive to reach
for, what it owns, and how it participates in lifecycle and messaging.

## Start Here

- [[ViewModel Families|Framework-Primitives/ViewModel-Families/ViewModel-Families]] when choosing VM
  shape
- [[Command Families|Framework-Primitives/Command-Families]]
- [[Capability Families|Framework-Primitives/Capability-Families]]
- [[State & Reactive Helpers|Framework-Primitives/State-and-Reactive-Helpers]]
- [[Services, Messages & Dispatching|Framework-Primitives/Services-Messages-and-Dispatching]]
- [[Builders, Collections & Tree Utilities|Framework-Primitives/Builders-Collections-and-Tree-Utilities]]

## Common Rule

Choose the owning VM family first. Then layer commands, capabilities, helpers,
and services around that shape.
