# VMx Examples Modernization Design

## Goal

Bring every repository example up to date with the current VMx API surface, using the most specific framework component that fits each behavior and keeping view-model and view adapter code small.

## Scope

The primary implementation target is the four-language Notes Showcase: C# Avalonia, Python Textual, TypeScript React, and Swift SwiftUI. Smaller examples receive focused cleanups where they currently teach older patterns: C# WPF Todo, Python Tk Todo, and Python Textual Inspector. Console hello examples stay intentionally small.

## Design

### Form validation

`NoteFormVM` in every flagship flavor will delegate title validation to `FormVM` validators. The form remains strict, so approval is denied while invalid. The VM exposes the field error through a thin idiomatic property (`TitleError`, `title_error`, `titleError`, `titleError`) and the UI renders it inline. Existing save-button bindings continue to use the VMx command bridge, now backed by `FormVM.isValid` instead of duplicate local validity logic.

### Derived note-list state

`NotesViewVM` will expose empty-state and page-label state through `DerivedProperty` in every flavor. TypeScript and Python already do this; C# and Swift will adopt equivalent derived slots and bindable adapters. Pagination command predicates will be driven by the same page-state subject, so first/previous and next/last buttons disable at the correct boundaries through VMx `RelayCommand`.

### Capability add-note parity

`CapabilityActionsVM` will expose an add-note command in all four flagship flavors. The command calls the workspace add-note action and uses a host-provided predicate that checks the focused notebook is not read-only. Seed data will include a visible read-only notebook so the feature is not dormant.

### Token-paged global search

The showcase will add a compact global search/activity panel backed by `TokenPagedComposition`. Each repository exposes a token-paged all-notes search method returning a page of lightweight result models and the next opaque token. The VM accumulates results, supports refresh and load-more commands, and auto-refreshes when the search term changes. This demonstrates forward-only token paging without replacing the finite local notes list, where `PagedComposition` remains the right fit.

### Discriminator editor mode

`NoteFormVM` will own a `DiscriminatorVM` for editor mode with `edit` and `preview` keys. Views render a small segmented control or tab row. Edit mode shows the title/body/tag inputs; preview mode shows a read-only preview of the current model. This demonstrates active-key coordination without introducing a route system.

### Tag autocomplete

The current hierarchy diagram claims `TagDraft` is searchable, while implementations use a string. The example will make the diagram true: `NoteFormVM` gets a `SearchableState<string>` over known tags supplied by the repository/workspace. Views show suggestions while typing and adding a suggestion routes through the existing tag command path.

### Small-example cleanups

C# WPF Todo replaces its local nested command with VMx `RelayCommand`. Python Tk Todo wires command enablement through VMx command triggers instead of manual button-state refresh. Textual Inspector gains a small state-lab branch that demonstrates `FormVM`, `DiscriminatorVM`, and token paging at the view-model level.

## Constraints

- Apply every flagship feature across all four supported languages and platforms.
- Use idiomatic public names per ADR-0006.
- Do not introduce new reactive libraries.
- Keep console examples minimal.
- Follow TDD for behavior changes: write failing tests before production edits.
- Update parity docs, READMEs, and the hierarchy diagram after implementation.

## Verification

Run focused tests while developing each slice, then run the full example suites:

- `dotnet test examples/csharp/Examples.sln`
- `uv --project examples/python run pytest examples/python/textual/notes_showcase/tests`
- `cd examples/typescript/react/notes-showcase && npm test`
- `cd examples/swift/notes-showcase && swift test`

Format and lint checks should follow the existing project commands for each language where configured.
