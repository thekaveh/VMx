# Global Search & Token Paging

Global all-notes search is the scenario path that demonstrates
`TokenPagedComposition` beyond the simpler fixed-page notes list.

## What It Proves

- forward-only token paging through repository-backed search
- search results that are independent of the currently focused notebook
- the same conceptual flow across C#, Python, TypeScript, and Swift

## Where It Lives

- C#:
  `ViewModels/GlobalSearchVM.cs` in the Avalonia flagship
- Python:
  `viewmodels/global_search_vm.py` in the Textual flagship
- TypeScript:
  `viewmodels/globalSearchVM.ts` in the React flagship
- Swift:
  `Sources/NotesShowcaseCore/ViewModels/` in the Swift flagship core target

Use the per-flavor READMEs and source tree for the exact repository method names
and host wiring:
[C#](https://github.com/thekaveh/VMx/blob/main/examples/csharp/avalonia/NotesShowcase/README.md),
[Python](https://github.com/thekaveh/VMx/blob/main/examples/python/textual/notes_showcase/README.md),
[TypeScript](https://github.com/thekaveh/VMx/blob/main/examples/typescript/react/notes-showcase/README.md),
[Swift](https://github.com/thekaveh/VMx/blob/main/examples/swift/notes-showcase/README.md).

## Related Reading

- [Notes Workspace](notes-workspace.md)
- [State & Reactive Helpers](../primitives/state-reactive-helpers.md)
- [Builders, Collections & Tree Utilities](../primitives/builders-collections-tree-utilities.md)
