# Editor Mode & DiscriminatorVM

The note editor shows the current `DiscriminatorVM` use case in the example
portfolio: one editor surface, multiple active modes.

## Why It Matters

- mode changes are explicit VM state
- command enablement and derived labels stay attached to the VM layer
- host adapters bind current mode instead of maintaining separate flags

## Related Pages

- \[[DiscriminatorVM|Framework-Primitives/ViewModel-Families/Specialized/DiscriminatorVM]\]
- \[[Notes Workspace|Examples/Notes-Workspace]\]
