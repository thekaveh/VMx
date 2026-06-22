# notes_showcase (Python / Textual)

VMx flagship example — Notes Workspace, the Python / Textual flavor. A
TUI built on Textual ≥ 0.80 that drives a single `WorkspaceVM` exercising
16 distinct VMx features (see the
[parity matrix](../../../notes-showcase-parity.md) for the full table, and
the
[VM hierarchy diagram](../../../assets/notes-showcase-vm-hierarchy.svg)
for the canonical visual of how the VMs compose). The canonical scenario
contract lives at
[`spec/proposals/2026-05-29-notes-showcase-scenario.md`](../../../../spec/proposals/2026-05-29-notes-showcase-scenario.md);
this README documents how the Textual implementation maps onto it.

The package is strictly partitioned into `models/`, `viewmodels/`, and
`views/`. Widget classes in `views/` expose only `compose()` /
`on_mount()` / one-statement `action_*()` methods — enforced by
`tools/check-textual-views.py`.

## Run

```bash
# From the repo root
uv run --project examples/python/textual/notes_showcase python -m notes_showcase
```

The first launch will resolve dependencies via `uv`; subsequent runs are
fast. Tests live under `tests/` and run from inside the project directory
(the coverage config in `pyproject.toml` resolves relative to the working
directory):

```bash
cd examples/python/textual/notes_showcase
uv run pytest
```

The package coverage gate is ≥ 90 % on `viewmodels/` + `views/adapter/`.

## Project layout

```
examples/python/textual/notes_showcase/
├── pyproject.toml
├── src/notes_showcase/
│   ├── __main__.py                  ← composition root
│   ├── models/
│   │   ├── notebook_model.py, note_model.py
│   │   ├── note_repository.py       ← Protocol
│   │   ├── in_memory_repository.py, seed.py
│   ├── viewmodels/
│   │   ├── workspace_vm.py          ← AggregateVM6 composition
│   │   ├── notebooks_root_vm.py, notebook_vm.py
│   │   ├── notes_view_vm.py, note_vm.py
│   │   ├── note_form_vm.py          ← FormVM wrapper
│   │   ├── status_bar_vm.py, notifications_vm.py
│   │   ├── capability_actions_vm.py, action_vm.py
│   │   └── dialog_service.py        ← VM-side port
│   └── views/
│       ├── app.py                   ← NotesShowcaseApp (Textual App)
│       ├── main_screen.py
│       ├── theme.tcss
│       ├── adapter/                 ← VMx → Textual bridge
│       │   ├── property.py, command.py, collection.py
│       │   ├── dispatcher.py, dialog.py
│       │   └── _hub_accessor.py
│       ├── notebooks_tree.py, notes_list.py, note_form.py,
│       │   status_bar.py, notifications.py, capability_actions.py
│       └── modals/{confirm_modal,save_file_modal,notify_modal}.py
└── tests/{models,viewmodels,views}/
```

## Feature traceability

| #   | Feature                          | Where                                                                                          |
| --- | -------------------------------- | ---------------------------------------------------------------------------------------------- |
| 1   | `HierarchicalVM`                 | `viewmodels/notebooks_root_vm.py` (composes `NotebookVM` children, emits `TreeStructureChangedMessage`) |
| 2   | `CompositeVM.current`            | `viewmodels/notes_view_vm.py` (`current` two-way binding)                                      |
| 3   | `ComponentVMOf[M]` modeled       | `viewmodels/note_vm.py`, `viewmodels/notebook_vm.py`                                            |
| 4   | `FormVM` snapshot / revert       | `viewmodels/note_form_vm.py` (owns a strict `FormVM[NoteModel]`)                                |
| 5   | `DerivedProperty`                | `viewmodels/status_bar_vm.py`, `note_form_vm.is_dirty`, `capability_actions_vm.actions`         |
| 6   | `RelayCommand` reactive          | `note_form_vm.approve_command` / `deny_command`, `note_vm.delete_command`                       |
| 7   | `SearchableState` + `IFilterable<TItem>`| `viewmodels/notes_view_vm.py` (debounced 150 ms search + `show_starred_only`)                   |
| 8   | `IPageable` + `PagedComposition` | `viewmodels/notes_view_vm.py` (page size 5, paging commands delegate to inner `PagedComposition`) |
| 9   | `INotificationHub` + `NotificationVM` | `viewmodels/notifications_vm.py`, `views/notifications.py`                                 |
| 10  | Async `construct()` + dispatcher | `viewmodels/workspace_vm.py` (`async construct()`), `views/adapter/dispatcher.py`               |
| 11  | `TreeStructureChangedMessage`    | `viewmodels/notebooks_root_vm.py` (`add_notebook` / `populate`)                                 |
| 12  | `ConfirmationDecoratorCommand`   | `viewmodels/note_vm.py` (`delete_command` wraps inner delete)                                   |
| 13  | `IDialogService`                 | `viewmodels/dialog_service.py`; implemented by `views/adapter/dialog.py` + `views/modals/`      |
| 14  | Capability-aware UI              | `viewmodels/capability_actions_vm.py` + `views/capability_actions.py`                           |
| 15  | `AggregateVM6` (spec 2.2.0)      | `viewmodels/workspace_vm.py` (wraps an `AggregateVM6[…]` of the six children)                   |
| 16  | `ThemeVM` scenario contract (spec 2.4.0, THEME-001..005) | `models/theme_model.py`, `viewmodels/theme_vm.py`, `messages/theme_changed.py`, `views/adapter/theme_adapter.py` (host-side palette / accent / font scale / high-contrast as a VM; standalone, not wired into `WorkspaceVM` until `AggregateVM7` lands) |

## Keyboard shortcuts

| Binding         | Action                                |
| --------------- | ------------------------------------- |
| `Ctrl+S`        | Approve (save) the form               |
| `Ctrl+N`        | New note in the current notebook      |
| `Ctrl+Shift+N`  | New notebook at the root              |
| `Ctrl+E`        | Export the workspace snapshot         |
| `Ctrl+F`        | Focus the search input                |

Bindings are declared as Textual `BINDINGS` on `views/app.py`. Each
`action_*` method is a single statement that calls into the VM, keeping the
Pure-VM contract intact.

## References

- Scenario contract: [`spec/proposals/2026-05-29-notes-showcase-scenario.md`](../../../../spec/proposals/2026-05-29-notes-showcase-scenario.md)
- Cross-flavor parity: [`examples/notes-showcase-parity.md`](../../../notes-showcase-parity.md)
- `AggregateVM6` rationale: [`spec/ADRs/0034-aggregate-vm6.md`](../../../../spec/ADRs/0034-aggregate-vm6.md)
