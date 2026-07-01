# VMx Examples Modernization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Modernize all VMx examples so each behavior is implemented with the best-fit current VMx abstraction across C#, Python, TypeScript, and Swift.

**Architecture:** Keep the Notes Showcase as the flagship parity surface and add only features that naturally demonstrate a specific VMx component. Use thin view adapters around VMx primitives instead of hand-rolled state in the examples.

**Tech Stack:** C#/.NET/Avalonia/WPF, Python/Textual/Tk, TypeScript/React/Vitest, Swift/SwiftUI/XCTest, VMx `FormVM`, `DerivedProperty`, `RelayCommand`, `SearchableState`, `PagedComposition`, `TokenPagedComposition`, and `DiscriminatorVM`.

## Global Constraints

- All flagship additions must ship in C#, Python, TypeScript, and Swift.
- Public names must stay idiomatic per ADR-0006.
- No new reactive libraries.
- Write failing tests before production changes.
- Keep console examples intentionally minimal.
- Update docs and diagrams after behavior changes.

______________________________________________________________________

### Task 1: FormVM Validation Parity

**Files:**

- Modify: `examples/*/notes-showcase*/**/NoteFormVM*`
- Modify: `examples/*/notes-showcase*/**/NoteForm*`
- Test: existing `NoteFormVMTests` and smoke/view tests in all four flagship examples.

**Interfaces:**

- Produces: title validation owned by `FormVM`; VM-level `titleError`/`TitleError`; save command disabled while invalid.

- [ ] Write failing tests asserting blank title produces a field error and disables approve/save.

- [ ] Run each focused test and confirm failure is due to missing FormVM validator wiring.

- [ ] Add FormVM title validator in each flavor and expose field error through the VM.

- [ ] Render inline title error in each view.

- [ ] Re-run focused tests and confirm green.

### Task 2: Derived NotesView State And Page Command Predicates

**Files:**

- Modify: `examples/csharp/avalonia/NotesShowcase/ViewModels/NotesViewVM.cs`
- Modify: `examples/swift/notes-showcase/Sources/NotesShowcaseCore/ViewModels/NotesViewVM.swift`
- Modify: `examples/python/textual/notes_showcase/src/notes_showcase/viewmodels/notes_view_vm.py`
- Modify: `examples/swift/notes-showcase/Sources/NotesShowcase/Views/NotesListView.swift`
- Modify: related tests in all four flagship examples.

**Interfaces:**

- Produces: `DerivedProperty`-backed empty/page label in all flavors; page commands with accurate `canExecute`.

- [ ] Write failing C#/Swift tests proving page label/empty are derived emissions.

- [ ] Write failing C#/Python/Swift tests proving page commands disable at boundaries.

- [ ] Implement derived properties and bindable adapters where needed.

- [ ] Add command predicates/triggers from page-state subjects.

- [ ] Re-run focused tests.

### Task 3: Capability Add-Note Parity And Read-Only Seed

**Files:**

- Modify: `CapabilityActionsVM*`, `WorkspaceVM*`, repository seed files, capability action views.
- Test: `CapabilityActionsVMTests`, `WorkspaceVMTests`, and smoke tests in all four flagship examples.

**Interfaces:**

- Produces: add-note command in `CapabilityActionsVM` for every flavor; command disabled when focused notebook is read-only.

- [ ] Write failing C#/Swift tests matching existing Python/TypeScript add-note behavior.

- [ ] Add read-only notebook seed and tests that focus it.

- [ ] Implement C#/Swift command parity and render the action.

- [ ] Confirm Python/TypeScript still pass with visible seed coverage.

### Task 4: TokenPaged Global Search

**Files:**

- Modify: repository interfaces and in-memory repositories in all four flagship examples.
- Create/modify: `GlobalSearchVM`/idiomatic equivalents and views in all four flagship examples.
- Test: repository, VM, and smoke tests in all four flagship examples.

**Interfaces:**

- Produces: token-paged search over all notes with `RefreshCommand`, `LoadMoreCommand`, accumulated results, and `HasMore`.

- [ ] Write failing repository tests for token-paged all-notes search.

- [ ] Write failing VM tests for refresh, load-more, term reset, and result accumulation.

- [ ] Implement repository page APIs using opaque string tokens.

- [ ] Implement global search VMs with `SearchableState` and `TokenPagedComposition`.

- [ ] Add compact views and wire commands through existing command adapters.

- [ ] Re-run focused tests.

### Task 5: Discriminator Editor Mode

**Files:**

- Modify: `NoteFormVM*` and `NoteForm*` views in all four flagship examples.
- Test: `NoteFormVMTests` and view smoke tests.

**Interfaces:**

- Produces: `editorMode`/`EditorMode` discriminator with `edit` and `preview` keys.

- [ ] Write failing tests for default edit mode, switching to preview, and active-key notifications.

- [ ] Implement `DiscriminatorVM` ownership and disposal.

- [ ] Add segmented edit/preview controls and preview rendering.

- [ ] Re-run focused tests.

### Task 6: Tag Autocomplete SearchableState

**Files:**

- Modify: repository tag APIs, `NoteFormVM*`, and tag-entry views.
- Test: `NoteFormVMTests` and view tests.

**Interfaces:**

- Produces: searchable tag suggestions from known tags; selecting a suggestion adds it through the existing add-tag command.

- [ ] Write failing tests for known-tag filtering and suggestion selection.

- [ ] Implement known-tag provider and `SearchableState<string>` in all four forms.

- [ ] Render suggestions in each UI with minimal adapter code.

- [ ] Update hierarchy diagram to match implementation.

### Task 7: Smaller Example Cleanups

**Files:**

- Modify: `examples/csharp/wpf/TodoApp/TodoItemVM.cs`
- Modify: `examples/python/tk/todo_app/__main__.py`
- Modify: `examples/python/textual/inspector/src/vmx_inspector/*`
- Test: build/tests for affected examples where available.

**Interfaces:**

- Produces: WPF Todo uses VMx `RelayCommand`; Tk Todo uses command triggers; Inspector includes a state-lab sample.

- [ ] Write or extend focused tests where harnesses exist.

- [ ] Replace WPF local command with VMx command.

- [ ] Wire Tk add-command can-execute updates through VMx command triggers.

- [ ] Add Inspector state-lab sample nodes.

- [ ] Build/run focused checks.

### Task 8: Documentation And Verification

**Files:**

- Modify: `examples/notes-showcase-parity.md`
- Modify: example READMEs.
- Modify: `examples/assets/notes-showcase-vm-hierarchy.svg`
- Modify: `examples/assets/notes-showcase-vm-hierarchy.html`

**Interfaces:**

- Produces: docs accurately describe all current example features.

- [ ] Update parity matrix for FormVM validation, token paging, discriminator, and tag autocomplete.

- [ ] Update READMEs with new feature descriptions and run commands.

- [ ] Update hierarchy diagram and embedded HTML.

- [ ] Run full verification commands for all affected examples.
