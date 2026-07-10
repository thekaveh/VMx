# Rust TUI Notes Showcase

The Rust TUI Notes Showcase is the Rust-specific full MVVM example. Ratatui and
crossterm provide rendering and terminal input only; VMx owns the application
state, lifecycle, filtering, paging, commands, notifications, and editor mode.

<img src="../../assets/diagrams/rust-tui-notes-showcase.svg" alt="Rust TUI Notes Showcase VM Layer" class="vmx-diagram" />

<p>
  <a href="../../assets/diagrams/rust-tui-notes-showcase.html">HTML</a>
  &middot;
  <a href="../../assets/diagrams/rust-tui-notes-showcase.svg">SVG</a>
  &middot;
  <a href="../../assets/diagrams/rust-tui-notes-showcase.png">PNG</a>
</p>

## What It Shows

- `WorkspaceVm` composes six child surfaces through `AggregateVm6`.
- `NotesViewVm` uses `CompositeVm`, `FilteredCompositeVm`, and
  `PagedComposition`.
- `NoteFormVm` uses strict `FormVm<NoteDraft>` validation and save/revert
  commands.
- `GlobalSearchVm` combines `SearchableState` with `TokenPagedComposition`.
- `NotificationsVm` uses `NotificationHub` and `NotificationVm` wrappers.
- `EditorModeVm` uses `DiscriminatorVm` for edit/preview switching.

## Run It

=== "Smoke"

    ```bash
    cargo run --manifest-path examples/rust/tui/notes-showcase/Cargo.toml -- --smoke
    ```

=== "Tests"

    ```bash
    cargo test --manifest-path examples/rust/tui/notes-showcase/Cargo.toml
    ```

=== "Interactive"

    ```bash
    cargo run --manifest-path examples/rust/tui/notes-showcase/Cargo.toml
    ```

## MVVM Boundary

The TUI shell may keep focus and quit state. It must not keep note data, search
terms, selected note state, form draft state, page tokens, notifications, or
editor mode. Those concerns live in the VMx view models and are covered by the
example crate's VM-layer tests.
