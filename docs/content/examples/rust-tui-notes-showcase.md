# 8.5. Rust TUI Notes Showcase

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

## 8.5.1. What It Shows

- `WorkspaceVm` composes six child surfaces through `AggregateVm6`.
- `NotesViewVm` uses `CompositeVm`, `FilteredCompositeVm`, and
  `PagedComposition`.
- `NoteFormVm` uses strict `FormVm<NoteDraft>` validation and save/revert
  commands.
- `GlobalSearchVm` combines `SearchableState` with `TokenPagedComposition`.
- `NotificationsVm` uses `NotificationHub` and `NotificationVm` wrappers.
- `EditorModeVm` uses `DiscriminatorVm` for edit/preview switching.

## 8.5.2. Parity Scope

This is a **reduced companion**, not a fifth canonical Notes Workspace
flagship. It proves Rust-native MVVM composition, but it intentionally omits
`THEME-001..005`, `IDialogService` export, the capability action bar, the async
dispatcher scenario, and tag autocomplete. Consequently,
`tools/check-showcase-parity.py` continues to enforce the complete 19-feature
scenario across C#, Python, TypeScript, and Swift only.

## 8.5.3. Run It

=== "Smoke"

    ```bash
    cargo run --locked --manifest-path examples/rust/tui/notes-showcase/Cargo.toml -- --smoke
    ```

=== "Tests"

    ```bash
    cargo test --locked --manifest-path examples/rust/tui/notes-showcase/Cargo.toml
    ```

=== "Interactive"

    ```bash
    cargo run --locked --manifest-path examples/rust/tui/notes-showcase/Cargo.toml
    ```

## 8.5.4. MVVM Boundary

The TUI shell may keep focus and quit state. It must not keep note data, search
terms, selected note state, form draft state, page tokens, notifications, or
editor mode. Those concerns live in the VMx view models and are covered by the
example crate's VM-layer tests.
