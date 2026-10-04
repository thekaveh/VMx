# 8.6. Global Search & Token Paging

Global all-notes search is the scenario path that demonstrates
`TokenPagedComposition` beyond the simpler fixed-page notes list.

## 8.6.1. What It Proves

- forward-only token paging through repository-backed search
- search results that are independent of the currently focused notebook
- source-change refresh with an unchanged search term before token paging reads
  the new filtered projection
- a refresh whose first page is unchanged keeps every loaded result and its
  continuation, so Load More continues after the last visible result instead
  of fetching page two again (spec 21 §6.2, ADR-0136)
- explicit ownership of every lifecycle-bearing result VM created by a search,
  including results later replaced, equality-suppressed, or returned by stale
  asynchronous work
- the same conceptual flow across C#, Python, TypeScript, and Swift

## 8.6.2. Where It Lives

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
[C#](../../../examples/csharp/avalonia/NotesShowcase/README.md),
[Python](../../../examples/python/textual/notes_showcase/README.md),
[TypeScript](../../../examples/typescript/react/notes-showcase/README.md),
[Swift](../../../examples/swift/notes-showcase/README.md).

## 8.6.3. Result Ownership

The four host examples construct `NoteVM` instances from repository values and
enable `autoConstructOnAdd`. `TokenPagedComposition` deliberately does not own
item lifetimes, so the enclosing `GlobalSearchVM` keeps an identity registry of
every result it creates—not only the currently visible page. Disposal marks that
registry terminal, disposes every retained result, and immediately disposes any
late result produced by already-running asynchronous work.

This local ownership boundary prevents refresh, same-page equality suppression,
or superseded fetches from making a constructed result unreachable before its
lifecycle closes. Rust's TUI search stores cloned `NoteModel` values rather than
lifecycle-bearing result VMs, so it does not need this registry.

## 8.6.4. Token Types

The token is opaque, and `null` / `None` / `nil` both requests the first page
and ends paging. The showcases use string tokens. For an integer offset or
page cursor, C# needs a token type that can hold `null`: use `int?`, where `0`
is a valid cursor, rather than `int`, which cannot say "no next page" and is
rejected when the composition is constructed.

```csharp
var paged = new TokenPagedComposition<NoteVM, int?>(async offset =>
{
    var page = await repository.LoadPageAsync(offset ?? 0, pageSize);
    int? next = page.HasMore ? (offset ?? 0) + pageSize : null;
    return new TokenPage<NoteVM, int?>(page.Items, next);
});
```

Python, TypeScript, Swift, and Rust already express an absent token with
`None`, `null`, `nil`, and `Option`.

## 8.6.5. Related Reading

- [Notes Workspace](notes-workspace.md)
- [State & Reactive Helpers](../primitives/state-reactive-helpers.md)
- [Builders, Collections & Tree Utilities](../primitives/builders-collections-tree-utilities.md)
