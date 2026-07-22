# 8.4. VM Layer Map

This page is the fast tour of how the Notes Workspace scenario composes VMx
primitives into the flagship app shape.

<img src="../../assets/diagrams/examples-vm-layer.svg" alt="Examples VM Layer Map" class="vmx-diagram" />

<p>
  <a href="../../assets/diagrams/examples-vm-layer.html">HTML</a>
  &middot;
  <a href="../../assets/diagrams/examples-vm-layer.svg">SVG</a>
  &middot;
  <a href="../../assets/diagrams/examples-vm-layer.png">PNG</a>
</p>

## 8.4.1. Canonical Hierarchy

The language-neutral VM hierarchy diagram lives in the examples tree:
[examples/assets/notes-showcase-vm-hierarchy.svg](../../../examples/assets/notes-showcase-vm-hierarchy.svg).
Use that diagram for node names and host-agnostic structure; use the local map
above for the VMx primitive-to-scenario routing.

The Rust TUI showcase has its own VM-layer map because its terminal host is a
Rust-specific adapter rather than one of the four UI-backed flagship hosts:
[Rust TUI Notes Showcase](rust-tui-notes-showcase.md).

## 8.4.2. Layer Walk

- `WorkspaceVM` is the composition root. In the current flagship apps it wraps
  an `AggregateVM6` over the six primary children.
- `NotebooksRootVM` and `NotebookVM` project the notebook tree through flat
  `ComponentVM`-based adapters that preserve `TreeStructureChangedMessage`
  behavior.
- `NotesViewVM` owns selection, filtering, and paging over notes.
- `NoteFormVM` owns edit/revert, validation, tag suggestions, and
  edit-versus-preview mode.
- `NotificationsVM`, `StatusBarVM`, and capability actions wire the supporting
  surfaces around the editor core.

## 8.4.3. Where To Verify

- Parity matrix:
  [examples/notes-showcase-parity.md](../../../examples/notes-showcase-parity.md)
- Architecture gallery version of this diagram:
  [Diagram Gallery](../architecture/diagram-gallery.md)
- Flavor READMEs:
  [C#](../../../examples/csharp/avalonia/NotesShowcase/README.md),
  [Python](../../../examples/python/textual/notes_showcase/README.md),
  [TypeScript](../../../examples/typescript/react/notes-showcase/README.md),
  [Swift](../../../examples/swift/notes-showcase/README.md)
