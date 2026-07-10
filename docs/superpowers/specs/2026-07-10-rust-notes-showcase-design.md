# Rust Notes Showcase Design

## 1. Goal

Add a full Rust showcase example that proves VMx can own a realistic MVVM
application end to end. The host must be terminal-based and cross-platform, but
all application state, selection, validation, paging, commands, notifications,
and mode switching must live in VMx-backed view models.

## 2. Host Choice

The showcase uses Ratatui with crossterm. Ratatui is a rendering and widget
library, not an application architecture, so it can stay below the VM layer as a
thin terminal adapter. Higher-level TUI frameworks such as Cursive, tui-realm,
or TEA runtimes add their own component state/update model, which would blur
the purpose of this example.

## 3. MVVM Boundary

The example is split into three packages inside
`examples/rust/tui/notes-showcase/src/`:

- `models`: immutable note/notebook records, seed data, and an in-memory
  repository.
- `viewmodels`: VMx-owned state and commands. These types expose read-only
  snapshots and command methods for the host.
- `views` plus `app`: Ratatui drawing and key dispatch. These files may read VM
  getters and execute VM commands, but must not own domain state.

The TUI shell may keep transient terminal concerns such as the focused panel and
quit flag. It must not duplicate note lists, search state, current selection,
form state, notifications, or editor mode.

## 4. ViewModel Shape

`WorkspaceVm` composes the showcase as an `AggregateVm6`:

1. `NotebooksVm`: notebook selection backed by VMx component/composite patterns.
1. `NotesViewVm`: visible notes backed by `CompositeVm`, `FilteredCompositeVm`,
   and `PagedComposition`.
1. `NoteFormVm`: edit state backed by `FormVm<NoteDraft>`.
1. `GlobalSearchVm`: all-note search backed by `SearchableState` and
   `TokenPagedComposition`.
1. `NotificationsVm`: pending messages backed by `NotificationHub` and
   `NotificationVm`.
1. `EditorModeVm`: edit/preview mode backed by `DiscriminatorVm`.

Commands use `RelayCommand` and VMx command decorators where the behavior is a
direct fit. Delete uses a confirmation boundary; save/revert and selection are
exposed as VM-layer operations.

## 5. Example Behavior

The initial screen shows notebooks, a filtered/paged notes list, an editor pane,
global search results, and notifications. Users can type a search term, move
between pages, select a note, edit the note title/body/tags, save or revert the
draft, toggle edit/preview mode, and delete after confirmation. A scripted smoke
mode exercises the same VM commands without requiring an interactive terminal.

## 6. Tests and CI

Tests live inside the example crate and target the VM layer first. They cover
search/filtering, paging, form validation, save/revert, mode switching,
notification/confirmation, and workspace wiring. CI runs `cargo test` for the
showcase and a non-interactive `--smoke` command.

## 7. Documentation

Update the Rust examples README, site examples pages, wiki examples pages, and
Rust flavor docs. The existing Notes Workspace diagrams remain canonical for the
four GUI-backed flagships; add a Rust TUI VM-layer diagram only if the final VM
tree differs enough to need a separate visual.
