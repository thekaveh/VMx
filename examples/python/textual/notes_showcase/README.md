# notes_showcase (Python / Textual)

VMx flagship example — Notes Workspace, the Python / Textual flavor. A
TUI built on Textual ≥ 0.80 that drives a single `WorkspaceVM` exercising
19 distinct VMx features (see the
[parity matrix](../../../notes-showcase-parity.md) for the full table, and
the
[VM hierarchy diagram](../../../assets/notes-showcase-vm-hierarchy.svg)
plus
[VMx component map](../../../assets/notes-showcase-vmx-components.svg)
for the canonical visuals of how the VMs compose). The Python host-specific
diagram is
[`python-textual-notes-showcase.svg`](../../../../docs/assets/diagrams/python-textual-notes-showcase.svg)
([HTML](../../../../docs/assets/diagrams/python-textual-notes-showcase.html),
[PNG](../../../../docs/assets/diagrams/python-textual-notes-showcase.png)).
The canonical scenario
contract lives at
[`spec/proposals/2026-05-29-notes-showcase-scenario.md`](../../../../spec/proposals/2026-05-29-notes-showcase-scenario.md);
this README documents how the Textual implementation maps onto it.

The package is strictly partitioned into `models/`, `viewmodels/`, and
`views/`. Widget classes in `views/` expose only `compose()` /
`on_mount()` / one-statement `action_*()` methods — enforced by
`tools/check-textual-views.py`.

## 1. Run

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

The package coverage gate is ≥ 90 % on `models/`, `viewmodels/`, and `views/`.

## 2. Project layout

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
│   │   ├── global_search_vm.py       ← TokenPagedComposition (row 17)
│   │   ├── theme_vm.py               ← ThemeVM (row 16)
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

## 3. Feature traceability

| #   | Feature                                                  | Where                                                                                                                                                                                                                                                                 |
| --- | -------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Notebook tree projection                                 | `viewmodels/notebooks_root_vm.py`, `viewmodels/notebook_vm.py` (flat `ComponentVM`-based adapters representing the `HierarchicalVM` capability and emitting `TreeStructureChangedMessage`)                                                                            |
| 2   | `CompositeVM.current`                                    | `viewmodels/notes_view_vm.py` (`current` two-way binding)                                                                                                                                                                                                             |
| 3   | `ComponentVMOf[M]` modeled                               | `viewmodels/note_vm.py`, `viewmodels/notebook_vm.py`                                                                                                                                                                                                                  |
| 4   | `FormVM` snapshot / revert / validation                  | `viewmodels/note_form_vm.py` (owns a strict `FormVM[NoteModel]`)                                                                                                                                                                                                      |
| 5   | `DerivedProperty`                                        | `viewmodels/status_bar_vm.py`, `note_form_vm.is_dirty`, `capability_actions_vm.actions`                                                                                                                                                                               |
| 6   | `RelayCommand` reactive                                  | `note_form_vm.approve_command` / `deny_command`, `note_vm.delete_command`                                                                                                                                                                                             |
| 7   | `SearchableState` + `IFilterable<TItem>`                 | `viewmodels/notes_view_vm.py` (debounced 150 ms search + `show_starred_only`); `note_form_vm` tag suggestions                                                                                                                                                         |
| 8   | `IPageable` + `PagedComposition`                         | `viewmodels/notes_view_vm.py` (page size 5, paging commands delegate to inner `PagedComposition`)                                                                                                                                                                     |
| 9   | `INotificationHub` + `NotificationVM`                    | `viewmodels/notifications_vm.py`, `views/notifications.py`                                                                                                                                                                                                            |
| 10  | Async `construct()` + dispatcher                         | `viewmodels/workspace_vm.py` (`async construct()`), `views/adapter/dispatcher.py`                                                                                                                                                                                     |
| 11  | `TreeStructureChangedMessage`                            | `viewmodels/notebooks_root_vm.py` (`add_notebook` / `populate`)                                                                                                                                                                                                       |
| 12  | `ConfirmationDecoratorCommand`                           | `viewmodels/note_vm.py` (`delete_command` wraps inner delete)                                                                                                                                                                                                         |
| 13  | `IDialogService`                                         | `viewmodels/dialog_service.py`; `views/adapter/dialog.py` implements confirm / notify / save-file modals used by the scenario (`pick_file_to_open` is deliberately unwired and tested as such)                                                                        |
| 14  | Capability-aware UI                                      | `viewmodels/capability_actions_vm.py` + `views/capability_actions.py`                                                                                                                                                                                                 |
| 15  | `AggregateVM6` (spec 2.2.0)                              | `viewmodels/workspace_vm.py` (wraps an `AggregateVM6[…]` of the six children)                                                                                                                                                                                         |
| 16  | `ThemeVM` scenario contract (spec 2.4.0, THEME-001..005) | `models/theme_model.py`, `viewmodels/theme_vm.py`, `messages/theme_changed.py`, `views/adapter/theme_adapter.py` (workspace-owned `ThemeVM` sibling bound through the Textual adapter; still outside the `AggregateVM6` child list pending any future `AggregateVM7`) |
| 17  | `TokenPagedComposition`                                  | `viewmodels/global_search_vm.py` + repository token-paged `search_notes`                                                                                                                                                                                              |
| 18  | `DiscriminatorVM`                                        | `viewmodels/note_form_vm.py` edit/preview editor mode                                                                                                                                                                                                                 |
| 19  | Tag autocomplete                                         | `viewmodels/note_form_vm.py` composes `SearchableState[str]` over workspace tags                                                                                                                                                                                      |

## 4. Keyboard shortcuts

| Binding        | Action                           |
| -------------- | -------------------------------- |
| `Ctrl+S`       | Approve (save) the form          |
| `Ctrl+N`       | New note in the current notebook |
| `Ctrl+Shift+N` | New notebook at the root         |
| `Ctrl+E`       | Export the workspace snapshot    |
| `Ctrl+F`       | Focus the search input           |

Bindings are declared as Textual `BINDINGS` on `views/app.py`. Each
`action_*` method is a single statement that calls into the VM, keeping the
Pure-VM contract intact.

## 5. References

- Scenario contract: [`spec/proposals/2026-05-29-notes-showcase-scenario.md`](../../../../spec/proposals/2026-05-29-notes-showcase-scenario.md)
- Cross-flavor parity: [`examples/notes-showcase-parity.md`](../../../notes-showcase-parity.md)
- `AggregateVM6` rationale: [`spec/ADRs/0034-aggregate-vm6.md`](../../../../spec/ADRs/0034-aggregate-vm6.md)
