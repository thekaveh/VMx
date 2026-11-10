# 8.6. Global Search & Token Paging

Global all-notes search is the scenario path that demonstrates
`TokenPagedComposition` beyond the simpler fixed-page notes list.

## 8.6.1. What It Proves

- Token paging moves forward only, through repository-backed search.
- Search results do not depend on the focused notebook.
- A source change refreshes the results while the search term stays the same.
  The refresh occurs before token paging reads the new filtered projection.
- A refresh for the same term that does not change the first page keeps every
  loaded result and its continuation. Load More then continues after the last
  visible result and does not fetch page two again (spec 21 §6.2, ADR-0136).
- Load More fetches the next page for the term of the loaded pages, even after
  the term is edited. Only a search request refreshes, so an edited term that
  was not searched starts no refresh. A refresh for another term replaces the
  loaded pages and their continuation.
- Load More is not available while a refresh runs. A call made during a
  refresh does nothing, so the results never mix two terms.
- In Swift and Rust, a load that passed its check just before a refresh began
  can still start during that refresh, and the composition then discards the
  refresh. When the results then do not start with the page that the refresh
  fetched, the view model searches again. The check compares the notes and
  their term, so a discarded refresh for the unchanged term also runs again,
  and its new first page replaces the old pages. Rust searches at most three
  times for one `refresh()` call.
- The notes list and the global search match a note by one rule in every
  showcase. The term is trimmed, and an empty term matches every note.
  Otherwise a note matches when its title, its body or one of its tags
  contains the term, ignoring case.
- The search explicitly owns every lifecycle-bearing result VM it creates. This
  includes results that are later replaced, equality-suppressed, or returned by
  stale asynchronous work.
- C#, Python, TypeScript, Swift, and the Rust TUI search use the same
  conceptual flow and follow the same term and refresh rules.

## 8.6.2. Where It Lives

- C#:
  `ViewModels/GlobalSearchVM.cs` in the Avalonia flagship
- Python:
  `viewmodels/global_search_vm.py` in the Textual flagship
- TypeScript:
  `viewmodels/globalSearchVM.ts` in the React flagship
- Swift:
  `Sources/NotesShowcaseCore/ViewModels/` in the Swift flagship core target
- Rust:
  `GlobalSearchVm` in `src/viewmodels.rs` of the Rust TUI companion

Use the per-flavor READMEs and source tree for the exact repository method names
and host wiring:
[C#](../../../examples/csharp/avalonia/NotesShowcase/README.md),
[Python](../../../examples/python/textual/notes_showcase/README.md),
[TypeScript](../../../examples/typescript/react/notes-showcase/README.md),
[Swift](../../../examples/swift/notes-showcase/README.md),
[Rust](../../../examples/rust/README.md).

## 8.6.3. Result Ownership

The four host examples construct `NoteVM` instances from repository values and
enable `autoConstructOnAdd`. `TokenPagedComposition` deliberately does not own
item lifetimes, so the enclosing `GlobalSearchVM` keeps an identity registry of
every result it creates—not only the currently visible page. Disposal marks that
registry terminal, disposes every retained result, and immediately disposes any
late result produced by already-running asynchronous work.

This local ownership boundary prevents refresh, same-page equality suppression,
or superseded fetches from making a constructed result unreachable before its
lifecycle closes. Rust's TUI search stores `SearchHit` values, each a cloned
`NoteModel` with the term that found it, rather than lifecycle-bearing result
VMs, so it does not need this registry.

## 8.6.4. Token Types

The token is opaque, and `null` / `None` / `nil` both requests the first page
and ends paging. The four showcases use a private cursor record. It holds the
search term and the repository's string offset. The Rust TUI search uses a
`SearchCursor` with the term and a `usize` offset. For an integer offset or page
cursor, C# needs a token type that can hold `null`: use `int?`, where `0` is a
valid cursor, rather than `int`, which cannot say "no next page". With
`int`, the `TokenPagedComposition` constructor throws
`NotSupportedException`.

```csharp
var paged = new TokenPagedComposition<NoteVM, int?>(async offset =>
{
    var page = await repository.LoadPageAsync(offset ?? 0, pageSize);
    int? next = page.HasMore ? (offset ?? 0) + pageSize : null;
    return new TokenPage<NoteVM, int?>(page.Items, next);
});
```

Python, TypeScript, Swift, and Rust express an absent token with
`None`, `null`, `nil`, and `Option`.

## 8.6.5. Related Reading

- [Notes Workspace](notes-workspace.md)
- [State & Reactive Helpers](../primitives/state-reactive-helpers.md)
- [Builders, Collections & Tree Utilities](../primitives/builders-collections-tree-utilities.md)
