# VM Layer Map

This page is the fast tour of how the Notes Workspace scenario composes VMx
primitives into the flagship app shape.

![Examples VM Layer Map](../../assets/diagrams/examples-vm-layer.png)

Support links: [HTML](../../assets/diagrams/examples-vm-layer.html),
[SVG](../../assets/diagrams/examples-vm-layer.svg),
[PNG](../../assets/diagrams/examples-vm-layer.png)

## Layer Walk

- `WorkspaceVM` is the composition root
- notebooks are projected through flat adapters preserving tree messages
- `NotesViewVM` owns selection, filtering, and paging
- `NoteFormVM` owns editing, validation, and mode switching
- notifications and status surfaces wrap the supporting workflows

## Related Pages

- \[[Notes Workspace|Examples/Notes-Workspace]\]
- \[[Hierarchical Family|Framework-Primitives/ViewModel-Families/Hierarchical-Family]\]
