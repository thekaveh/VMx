# NotesShowcase (C# / Avalonia)

VMx flagship example — Notes Workspace, the C# / Avalonia flavor. A
cross-platform XAML app on Avalonia 11 + .NET 8 that drives a single
`WorkspaceVM` exercising 19 distinct VMx features (see the
[parity matrix](../../../notes-showcase-parity.md) for the full feature
table, and the
[VM hierarchy diagram](../../../assets/notes-showcase-vm-hierarchy.svg)
plus
[VMx component map](../../../assets/notes-showcase-vmx-components.svg)
for the canonical visuals of how the VMs compose). The canonical scenario
contract lives at
[`spec/proposals/2026-05-29-notes-showcase-scenario.md`](../../../../spec/proposals/2026-05-29-notes-showcase-scenario.md);
this README documents how the C# implementation maps onto it.

The app is strictly partitioned into Model / ViewModel / View directories.
`Views/` is declarative-only — every `*.axaml.cs` code-behind is just the
XAML loader call (`AvaloniaXamlLoader.Load(this)`), enforced by
`tools/check-axaml-codebehind.py`.

## 1. Run

```bash
# From the repo root
dotnet run --project examples/csharp/avalonia/NotesShowcase
```

The app boots, awaits the simulated ~300 ms repository load, populates four
seed notebooks, and selects the first one. Headless smoke tests live under
[`examples/csharp/avalonia/NotesShowcase.Tests/`](../NotesShowcase.Tests/)
and run via `dotnet test`.

## 2. Project layout

```
examples/csharp/avalonia/NotesShowcase/
├── NotesShowcase.csproj
├── Program.cs                     ← process entry (composition root lives in App.BuildMainWindow)
├── App.axaml(.cs)                 ← Avalonia entrypoint
├── Models/
│   ├── NotebookModel.cs, NoteModel.cs
│   ├── INoteRepository.cs, InMemoryNoteRepository.cs
│   └── SeedData.cs
├── ViewModels/
│   ├── WorkspaceVM.cs             ← AggregateVM6 composition
│   ├── NotebooksRootVM.cs, NotebookVM.cs
│   ├── NotesViewVM.cs, NoteVM.cs
│   ├── NoteFormVM.cs              ← FormVM wrapper
│   ├── StatusBarVM.cs, NotificationsVM.cs
│   └── CapabilityActionsVM.cs, ActionVM.cs
│   (`IDialogService` itself ships in the VMx library at
│    `langs/csharp/src/VMx/Dialogs/IDialogService.cs`.)
└── Views/
    ├── Adapter/                   ← VMx → Avalonia bridge
    │   ├── BindableVm.cs, BindableDerived.cs
    │   ├── RelayCommandBridge.cs, ObservableCollectionBridge.cs
    │   ├── AvaloniaDispatcher.cs, AvaloniaDialogService.cs
    ├── Theme/DarkTheme.axaml
    ├── MainWindow.axaml(.cs)
    ├── NotebooksTreeView, NotesListView, NoteFormView,
    │   StatusBarView, NotificationsView, CapabilityActionsView (axaml + .axaml.cs)
    └── Modals/ConfirmDialog.axaml(.cs)
```

## 3. Feature traceability

| #   | Feature                                                  | Where                                                                                                                                                                                                                                                                     |
| --- | -------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Notebook tree projection                                 | `ViewModels/NotebooksRootVM.cs`, `ViewModels/NotebookVM.cs` (flat `ComponentVM`-based adapters representing the `HierarchicalVM` capability and emitting `TreeStructureChangedMessage`)                                                                                   |
| 2   | `CompositeVM.Current`                                    | `ViewModels/NotesViewVM.cs` (`Current` two-way binding to the inner composite)                                                                                                                                                                                            |
| 3   | `ComponentVM<M>` modeled                                 | `ViewModels/NoteVM.cs`, `ViewModels/NotebookVM.cs`                                                                                                                                                                                                                        |
| 4   | `FormVM` snapshot / revert / validation                  | `ViewModels/NoteFormVM.cs` (owns a strict `FormVM<NoteModel>`)                                                                                                                                                                                                            |
| 5   | `DerivedProperty`                                        | `ViewModels/StatusBarVM.cs`, `NoteFormVM.IsDirty`, `CapabilityActionsVM.Actions`                                                                                                                                                                                          |
| 6   | `RelayCommand` reactive                                  | `NoteFormVM.ApproveCommand` / `DenyCommand`, `NoteVM.DeleteCommand`                                                                                                                                                                                                       |
| 7   | `SearchableState` + `IFilterable<TItem>`                 | `ViewModels/NotesViewVM.cs` (debounced 150 ms search + `ShowStarredOnly`); `NoteFormVM` tag suggestions                                                                                                                                                                   |
| 8   | `IPageable` + `PagedComposition`                         | `ViewModels/NotesViewVM.cs` (page size 5, paging commands delegate to inner `PagedComposition`)                                                                                                                                                                           |
| 9   | `INotificationHub` + `NotificationVM`                    | `ViewModels/NotificationsVM.cs`, `Views/NotificationsView.axaml`                                                                                                                                                                                                          |
| 10  | Async `construct()` + dispatcher                         | `ViewModels/WorkspaceVM.cs` (`ConstructAsync`), `Views/Adapter/AvaloniaDispatcher.cs`                                                                                                                                                                                     |
| 11  | `TreeStructureChangedMessage`                            | `ViewModels/NotebooksRootVM.cs` (`AddNotebook` / `Populate`)                                                                                                                                                                                                              |
| 12  | `ConfirmationDecoratorCommand`                           | `ViewModels/NoteVM.cs` (`DeleteCommand` wraps inner delete)                                                                                                                                                                                                               |
| 13  | `IDialogService`                                         | Interface from VMx library (`langs/csharp/src/VMx/Dialogs/IDialogService.cs`); implemented here by `Views/Adapter/AvaloniaDialogService.cs` + `Views/Modals/ConfirmDialog.axaml`                                                                                          |
| 14  | Capability-aware UI                                      | `ViewModels/CapabilityActionsVM.cs` + `Views/CapabilityActionsView.axaml`                                                                                                                                                                                                 |
| 15  | `AggregateVM6` (spec 2.2.0)                              | `ViewModels/WorkspaceVM.cs` (wraps a sealed `AggregateVM6<…>` of the six children)                                                                                                                                                                                        |
| 16  | `ThemeVM` scenario contract (spec 2.4.0, THEME-001..005) | `Models/ThemeModel.cs`, `ViewModels/ThemeVM.cs`, `Messages/ThemeChangedMessage.cs`, `Views/Adapter/ThemeAdapter.cs` (workspace-owned `ThemeVM` sibling bound through the Avalonia adapter; still outside the `AggregateVM6` child list pending any future `AggregateVM7`) |
| 17  | `TokenPagedComposition`                                  | `ViewModels/GlobalSearchVM.cs` + repository token-paged `SearchNotesAsync`                                                                                                                                                                                                |
| 18  | `DiscriminatorVM`                                        | `ViewModels/NoteFormVM.cs` edit/preview editor mode                                                                                                                                                                                                                       |
| 19  | Tag autocomplete                                         | `ViewModels/NoteFormVM.cs` composes `SearchableState<string>` over workspace tags                                                                                                                                                                                         |

## 4. Keyboard shortcuts

| Gesture        | Action                           |
| -------------- | -------------------------------- |
| `Ctrl+N`       | New note in the current notebook |
| `Ctrl+Shift+N` | New notebook at the root         |
| `Ctrl+S`       | Approve (save) the form          |
| `Ctrl+E`       | Export the workspace snapshot    |

Bindings are declared in `Views/MainWindow.axaml` under
`<Window.KeyBindings>`; each gesture routes to a VM command, so `CanExecute`
gating happens entirely on the VM side.

## 5. References

- Scenario contract: [`spec/proposals/2026-05-29-notes-showcase-scenario.md`](../../../../spec/proposals/2026-05-29-notes-showcase-scenario.md)
- Cross-flavor parity: [`examples/notes-showcase-parity.md`](../../../notes-showcase-parity.md)
- `AggregateVM6` rationale: [`spec/ADRs/0034-aggregate-vm6.md`](../../../../spec/ADRs/0034-aggregate-vm6.md)
