# Proposal — Notes Workspace showcase: cross-flavor flagship examples

**Status:** Accepted (2026-05-30); shipped in spec v2.2.0 (PR #6, merged 2026-05-31).
**Date:** 2026-05-29
**Target spec version:** 2.2.0 (minor bump — adds `AggregateVM6`)
**Branch:** `examples-notes-showcase` off `main` (merged)
**Sister artefacts (shipped):** [`examples/notes-showcase-parity.md`](../../examples/notes-showcase-parity.md) (16-row × 3-flavor parity matrix; row 16 — ThemeVM — added in v2.4.0 per `2026-06-02-theme-vm-scenario.md`), `assets/notes-showcase/{avalonia,textual,react}.png` (placeholder note — manual screenshot capture pending), and [ADR-0034](../ADRs/0034-aggregate-vm6.md) (extends `AggregateVM` arity to 6).

## 1. Executive summary

This proposal adds three flagship example apps to the VMx portfolio — one per
language flavor, one per chosen UI framework: **C# / Avalonia**, **Python /
Textual**, **TypeScript / React**. All three implement the same scenario, the
**Notes Workspace**, drawn from a single language-neutral VM API surface
defined in §6 below.

The three apps share one purpose: prove that VMx is a sufficient, idiomatic,
**pure** viewmodel layer that any UI framework can sit on top of. To make that
claim concrete, the design imposes:

1. **One shared scenario** (§5) rich enough to exercise 15 distinct spec
   features in one cohesive UX (one of which, `AggregateVM6`, is added by
   this proposal).
1. **Strict Model / ViewModel / View partitioning** (§7) inside each example.
   `Models/` owns persistence and records; `ViewModels/` owns every VMx-based
   VM plus the ports VMs declare (`IDialogService`); `Views/` owns UI controls,
   the adapter that bridges VMx hub messages to the framework's reactive
   primitive, the theme, and the dispatcher / dialog-service implementations.
1. **A Pure-VM contract** (§6.1) enforced by CI: views are declarative-only —
   no business state, no derived logic, no hub subscriptions outside the
   adapter.
1. **A single feature branch** (`examples-notes-showcase`) holding all
   phases (§10); no merges to `main` until the entire portfolio is
   audit-clean per the strict clean-pass gate convention.

Existing examples (`HelloVMx`, `WpfTodoApp`, `hello_vmx`, `tk_todo_app`,
`vmx_inspector`, `hello-vmx`) are preserved but relocated into a new
nested layout `examples/<lang>/<framework>/<app>/` (§4), opening room for
additional per-framework examples in future PRs.

**Spec / library extension prerequisite.** The `WorkspaceVM` root in §6.2
heterogeneously composes 6 children (notebooks tree, notes view, note form,
status bar, notifications, capability actions). The current spec ships
`AggregateVM1..5` (ADR-0007). This proposal treats the example portfolio as
a stress test for the library: rather than synthetically grouping children
into a "chrome" slot to fit arity 5, we **extend VMx itself to add
`AggregateVM6`**, landing as a minor spec bump (2.1.x → 2.2.0) under a new
**ADR-0034** that supersedes ADR-0007's "lift cap = future major" stance on
the grounds that adding a higher arity while preserving `AggregateVM1..5` is
purely additive and non-breaking. §10.2 schedules the spec / library
extension as Phase 2, before the example VM layer (Phase 3). This is the
intended virtuous cycle: real-world example needs drive spec evolution; spec
evolution flows through every flavor; new flavor capability is then
exercised by the example.

## 2. Goals and non-goals

**Goals**

- G1. Showcase what a VMx-based viewmodel layer makes possible across three
  framework idioms (XAML, TUI, web).
- G2. Provide a reference implementation for adopters who want to wire VMx into
  one of these three frameworks specifically.
- G3. Demonstrate that the same VM tree drives every visible behavior — the
  view is a stateless mirror.
- G4. Cover 15 spec features in one cohesive scenario (see §5.5), one of which (`AggregateVM6`) is added to VMx by this proposal.

**Non-goals**

- N1. Publishing per-framework binding packages (`vmx-react`,
  `vmx-avalonia`, `vmx-textual`). Adapters live inside each example as
  demonstrative code, ≤ ~250 lines. Promoting them to libraries is a future
  PR.
- N2. Adding **example-driven** entries to `spec/12-conformance.md`. Examples
  are not normative; the AGG-006 addition is driven by the `AggregateVM6`
  spec extension (Phase 2.s), not by the example apps themselves.
  Conformance is at 220 IDs after this branch lands.
- N3. Pixel-perfect visual parity or visual regression tests. Three screenshots
  in `assets/notes-showcase/` are the manual reference.
- N4. End-to-end simulated-user tests (Playwright / FlaUI / pyautogui). Headless
  smoke per framework (§9.3) is the substitute.
- N5. Multiple frameworks per language *in this PR* — see §4.2 for the
  forward-compatible layout that lets more arrive later.

## 3. Scope

### 3.1 Frameworks chosen for this PR

| Language   | Framework                 | Why this one                                                                                                                                       |
| ---------- | ------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| C#         | **Avalonia 11 on .NET 8** | Cross-platform XAML; runs on macOS / Linux / Windows from one project; modern MVVM-native. WPF stays as the smaller existing example.              |
| Python     | **Textual ≥ 0.80**        | TUI, reactive, async-native (matches the async-construct showcase). `vmx_inspector` already established Textual as the heavyweight Python example. |
| TypeScript | **React 18 + Vite**       | Largest SPA ecosystem; `useSyncExternalStore` aligns cleanly with VMx hub semantics.                                                               |

### 3.2 Frameworks deferred to future PRs

The nested layout `examples/<lang>/<framework>/<app>/` accommodates these
without further migration:

- C#: WPF (existing tiny todo will relocate), MAUI, UNO, WinUI 3.
- Python: PyQt6 / PySide6, NiceGUI, Kivy.
- TypeScript: Vue 3, Svelte, Angular, Ink, Lit, Electron.

## 4. Repository layout

### 4.1 New convention

```
examples/<lang>/<framework>/<app-name>/
```

Casing per ADR-0006: C# = `PascalCase`, Python = `snake_case`, TypeScript =
`kebab-case` for both `<framework>` (lowercase community name) and
`<app-name>` segments.

### 4.2 After-state tree

```
examples/
├── csharp/
│   ├── Examples.sln                 ← updated project paths
│   ├── README.md                    ← updated
│   ├── console/HelloVMx/            ← relocated
│   ├── wpf/TodoApp/                 ← relocated
│   └── avalonia/NotesShowcase/      ← NEW flagship
├── python/
│   ├── pyproject.toml               ← updated workspace members
│   ├── README.md                    ← updated
│   ├── console/hello_vmx/           ← relocated
│   ├── tk/todo_app/                 ← relocated
│   └── textual/
│       ├── inspector/               ← relocated (vmx_inspector)
│       └── notes_showcase/          ← NEW flagship
└── typescript/
    ├── README.md                    ← updated
    ├── console/hello-vmx/           ← relocated
    └── react/notes-showcase/        ← NEW flagship
```

### 4.3 Files needing path updates (mechanical pass — Phase 0)

- `examples/csharp/Examples.sln`
- `examples/python/pyproject.toml`
- `examples/python/textual/inspector/pyproject.toml` (relative `vmx` path
  source up-level)
- All three `examples/<lang>/README.md` — section paths and run snippets
- Root `README.md` §4.3 — example links
- `docs/getting-started/{csharp,python,typescript}.md` — any path references
- `CONTRIBUTING.md` — any example paths
- `.github/workflows/*.yml` — any paths referencing examples

## 5. The scenario — Notes Workspace

### 5.1 Layout (single window, 3 panes + status bar + capability action bar + toast region)

```
┌─ Toolbar: [+ Notebook] [+ Note] [Export…] [⌘F Search] ─────────────┐
├─────────────┬─────────────────────────┬──────────────────────────────┤
│ Notebooks   │ Notes (filtered/paged)  │ Note details / edit form     │
│  (tree)     │  Search ____________    │  Title  _______________      │
│ ▼ Work      │  ☐ Starred only         │  Tags   [x] [y] [+]          │
│   Specs     │  Q1 design review       │  Body                        │
│ ▶ Reviews◀  │  Auth migration ◀       │  [textarea]                  │
│   Personal  │  Vendor shortlist       │  [Save] [Revert] [Delete…]   │
│   Archive   │  Page 1/4  ◀ ▶ ⏮ ⏭     │                              │
├─────────────┴─────────────────────────┴──────────────────────────────┤
│ Status: 12 in Reviews · 3 starred · Editing 'Auth…' (dirty)         │
├─ Capability actions: [Close] [Save] [Delete…] [↻ Reconstruct]      ─┤
└──────────────────────────── toasts: "Saved" ────────────────────────┘
```

### 5.2 Behaviors (normative)

1. **App start.** `WorkspaceVM.construct()` awaits a ~300 ms simulated repository
   fetch, then loads notebooks and selects the first root notebook by default.
1. **Notebook selection.** Tree `current` change triggers
   `NotesViewVM.bindTo(notebook)`, which awaits a ~150 ms simulated
   notes-for-notebook fetch (via `reconstruct()`).
1. **Notes display.** `NotesViewVM` filters by selected notebook, applies the
   `SearchableState` debounced 150 ms title-search predicate, applies the
   `showStarredOnly` `IFilterable` predicate, and paginates 5 per page via
   `PagedComposition`.
1. **Note selection.** Notes-list `current` change drives `NoteFormVM` to
   re-snapshot from `current.model`; `draft` becomes the editable copy.
1. **Editing.** Mutating `draft.{title,body,starred,tags}` raises
   `PropertyChangedMessage`; `isDirty` (a `DerivedProperty`) flips true.
1. **Save.** `approveCommand.canExecute` = `isDirty && strict-valid`. Approve
   awaits ~200 ms persist, re-snapshots, clears dirty, publishes a "Saved"
   notification.
1. **Revert.** `denyCommand.canExecute` = `isDirty`. Deny restores `draft` from
   the snapshot.
1. **Delete.** `NoteVM.deleteCommand` is a `ConfirmationDecoratorCommand` over
   the inner delete; on click it calls `IDialogService.confirm("Delete '{title}'?")`. On yes, the note is removed and a "Deleted" notification
   fires.
1. **Add notebook / add note.** Toolbar commands invoke `NotebooksRootVM`
   `INewCreatable` / a sibling `newNoteCommand`. Adding a notebook re-publishes
   `TreeStructureChangedMessage`.
1. **Export.** `WorkspaceVM.exportCommand` calls
   `IDialogService.saveFile(suggested)`; on path returned, writes the snapshot
   via the repository and emits a notification.
1. **Capability action bar.** Reflects `workspace.focusedVM`'s implemented
   capabilities (§14.4 of the spec) — buttons for `ISelectable`, `IClosable`,
   `IDeletable`, `IPageable` (when focus is the notes view), etc. The
   capability set is observed via a `DerivedProperty`; the view binds.
1. **Notifications.** All toasts flow through the optional `INotificationHub`
   sub-package; `NotificationsVM` materializes auto-dismissing `NotificationVM`
   instances (spec §16.6-7), cap 5 visible.
1. **Shutdown.** Closing the window invokes `WorkspaceVM.dispose()` — the
   synchronous depth-first cascade per spec ch. 2.

### 5.3 Domain model

```
NotebookModel { id, name, parentId? }
NoteModel     { id, notebookId, title, tags[], body, starred,
                createdAt, updatedAt }
```

### 5.4 Sample data

Ship 4 root notebooks (`Work`, `Reviews`, `Personal`, `Archive`), a few
children under `Work` (`Specs`), and ~12 notes spread such that at least one
notebook has ≥ 6 notes (multi-page demonstration). 3 notes starred.

### 5.5 Feature traceability (15 features × 1 scenario)

| #   | Feature (spec ref)                                | Where in the scenario                              |
| --- | ------------------------------------------------- | -------------------------------------------------- |
| 1   | `HierarchicalVM` (ch. 18)                         | Notebooks tree                                     |
| 2   | `CompositeVM.Current` (ch. 6)                     | Notes selection (double-nested with notebook tree) |
| 3   | `ComponentVM<M>` modeled (ch. 5)                  | `NoteVM`, `NotebookVM`                             |
| 4   | `FormVM` snapshot/revert (ch. 20)                 | Note editor                                        |
| 5   | `DerivedProperty` (ch. 15)                        | Status bar, `isDirty`, capability actions          |
| 6   | `RelayCommand` reactive `canExecute` (ch. 4)      | Save / Revert / Delete                             |
| 7   | `SearchableState` + `IFilterable<T>` (§14.5–14.6) | Title search + starred filter                      |
| 8   | `IPageable` + `PagedComposition` (§14.10, ch. 21) | Notes pagination                                   |
| 9   | `INotificationHub` + `NotificationVM` (ch. 16)    | Toast region                                       |
| 10  | Async `construct()` + dispatcher (ch. 2, 11)      | Workspace load + notebook switch + save            |
| 11  | `TreeStructureChangedMessage` (ch. 18)            | Add notebook re-publishes tree                     |
| 12  | `ConfirmationDecoratorCommand` (ch. 4)            | Delete confirm                                     |
| 13  | `IDialogService` (ch. 19)                         | Export → save-file dialog                          |
| 14  | Capability-aware UI (§14.4)                       | Capability action bar                              |
| 15  | **`AggregateVM6`** (ch. 8 — **new in 2.2.0**)     | `WorkspaceVM` composes 6 heterogeneous children    |

## 6. ViewModel API (language-neutral)

Pseudo-code below is the contract; each flavor renders identifier casing per
ADR-0006.

### 6.1 The Pure-VM contract (normative)

The view layer is declarative only. Each framework's view is permitted to:

1. **Bind text / label** controls to one-way VM properties.
1. **Bind input** controls (text, checkbox, slider) two-way to mutable VM
   properties.
1. **Bind buttons / keybindings / menu items** to VM commands.
1. **Bind list / tree containers** to VM observable collections (and
   `SelectedItem` two-way to `CompositeVM.current` / `HierarchicalVM.current`).
1. **Provide one host-side adapter implementing `IDialogService`** (the
   per-framework boundary for modal interactions).

The view is forbidden to:

- Hold any UI-only mutable state — no `useState`/`useReducer` without a VM
  source, no XAML triggers that mutate non-VM state, no Textual `reactive`
  vars that aren't a one-line proxy to a VM property.
- Compute any conditional / derived logic — the VM exposes a `DerivedProperty`
  for every conditional UI fact (button-enabled, label visibility, badge text,
  list emptiness state).
- Subscribe to `IMessageHub` directly from view code — only the per-framework
  adapter does that.
- Hold flow state across multiple inputs — multi-step interactions are
  `FormVM` / `CompositeCommand` on the VM side.

This contract is enforced by CI checks; see §9.2.

### 6.2 VM tree

```
# ─── Domain (Plain records — Models/) ──────────────────────────────────
NotebookModel { id, name, parentId? }
NoteModel     { id, notebookId, title, tags[], body, starred,
                createdAt, updatedAt }

# ─── Persistence port (Models/) ────────────────────────────────────────
INoteRepository:
    loadAll()              : async → { notebooks[], notes[] }   # ~300 ms
    loadNotes(notebookId)  : async → notes[]                    # ~150 ms
    saveNote(model)        : async                              # ~200 ms
    deleteNote(id)         : async
    addNotebook(model)     : async
    export(snapshot, path) : async

# ─── Dialog port (ViewModels/) ─────────────────────────────────────────
IDialogService:
    confirm(prompt)      : async → bool
    saveFile(suggested)  : async → path?
    # notify is NOT here — notifications flow through INotificationHub.

# ─── ViewModels ────────────────────────────────────────────────────────

NotebookVM : ComponentVM<NotebookModel>
  implements ISelectable, IExpandable, ICollapsible,
             IExpansionTogglable, IReconstructable
  expansion : ExpandableState

NotebooksRootVM : HierarchicalVM<NotebookModel, NotebookVM>
  implements INewCreatable
  current             : NotebookVM?
  addNotebook(parent?, name)       # emits TreeStructureChangedMessage
                                   # + "Notebook added" notification

NotesViewVM : PagedComposition<NoteVM>     # wraps inner CompositeVM<NoteVM>
  implements IPageable, IFilterable<NoteVM>, ISearchable, IReconstructable
  current             : NoteVM?
  searchTerm          : string            # two-way bindable; debounced 150 ms
                                          # via an internal SearchableState
  showStarredOnly     : bool
  pageSize            : int = 5
  isEmpty             : DerivedProperty<bool>
  pageLabel           : DerivedProperty<string>     # "Page 1/4"
  moveTo{First,Previous,Next,Last}PageCommand : RelayCommand
  bindTo(notebook)                                  # awaits ~150 ms

NoteVM : ComponentVM<NoteModel>
  implements ISelectable, IClosable, IDeletable<NoteVM>,
             ISavable<NoteVM>, IReconstructable
  closeCommand  : RelayCommand
        # IClosable.close() = clear NotesViewVM.current (deselect from workspace).
  deleteCommand : ConfirmationDecoratorCommand
        # wraps inner delete; calls IDialogService.confirm.

NoteFormVM : FormVM<NoteModel>             # bound to NotesViewVM.current
  draft.title         : string             # two-way bindable
  draft.body          : string             # two-way bindable
  draft.starred       : bool               # two-way bindable
  draft.tags          : ObservableList<string>
  tagDraft            : string             # two-way: tag input box
  addTagCommand       : RelayCommand       # canExecute = tagDraft non-empty
  removeTagCommand    : RelayCommand<string>
  isDirty             : DerivedProperty<bool>
  isValid             : DerivedProperty<bool>      # title non-empty, etc.
  strict              : bool = true        # spec ch. 20: ApproveCommand.canExecute = isDirty
  approveCommand      : RelayCommand       # canExecute = isDirty && isValid
                                           # (strict provides the isDirty half;
                                           #  isValid is the NoteFormVM-specific addition)
  denyCommand         : RelayCommand       # canExecute = isDirty
  statusText          : DerivedProperty<string>     # "Saving…" / "Saved 2m ago"
  onApproved(model)   : async              # await ~200 ms persist + notify

StatusBarVM
  noteCountText : DerivedProperty<string>     # ← notesView.count + notebook.name
  starredText   : DerivedProperty<string>
  editingText   : DerivedProperty<string>

NotificationsVM
  visible : ObservableList<NotificationVM>    # auto-dismiss; cap 5

ActionVM { label : string, command : ICommand }

CapabilityActionsVM
  actions : DerivedProperty<list<ActionVM>>
        # derived from workspace.focusedVM and what it implements.

WorkspaceVM composes AggregateVM6<             # NEW in 2.2.0; see ADR-0034.
        NotebooksRootVM,                       # Component1
        NotesViewVM,                           # Component2
        NoteFormVM,                            # Component3
        StatusBarVM,                           # Component4
        NotificationsVM,                       # Component5
        CapabilityActionsVM>                   # Component6
  implements IReconstructable
        # Lifecycle cascade (construct/destruct/dispose) is provided by the
        # inner AggregateVM6; WorkspaceVM forwards it and adds the toolbar
        # commands plus the focused-VM derivation.
        # Composition note: C# `AggregateVM6` is sealed, so example
        # implementations wrap rather than subclass. Python and TypeScript
        # follow the same composition pattern for cross-language parity, so
        # the three flavors share an identical WorkspaceVM surface regardless
        # of host-language inheritance constraints.
  notebooksRoot       : NotebooksRootVM
  notesView           : NotesViewVM
  noteForm            : NoteFormVM
  statusBar           : StatusBarVM
  notifications       : NotificationsVM
  capabilityActions   : CapabilityActionsVM
  newNotebookCommand  : RelayCommand
  newNoteCommand      : RelayCommand
  exportCommand       : RelayCommand
  focusedVM           : DerivedProperty<VM?>
        # derived from the most-recent select()/focus signal among
        # {currentNotebook, currentNote, notesView}.

  async construct():
      await repo.loadAll()                    # ~300 ms
      notebooksRoot.populate(notebooks)
      notebooksRoot.current = first root
      # selection triggers notesView.bindTo(first root) → ~150 ms
```

### 6.3 Hub messages emitted (canonical)

| Message                                        | When                                             |
| ---------------------------------------------- | ------------------------------------------------ |
| `PropertyChangedMessage`                       | Every mutable property change.                   |
| `ConstructionStatusChangedMessage`             | Every lifecycle transition.                      |
| `CollectionChangedEvent`                       | `NotesViewVM.items`, `NotebooksRootVM` children. |
| `TreeStructureChangedMessage`                  | Add / remove notebook.                           |
| `NotificationMessage` (via `INotificationHub`) | Save / delete / create / export / error.         |

### 6.4 Builders

Every VM ships a builder per spec ch. 10. `WorkspaceVM.Builder()` is the
single composition root invoked by each example's `Main` / `__main__` /
`main.tsx`.

## 7. Per-framework adapter strategy

### 7.1 Five things every adapter provides

| Adapter piece        | Responsibility                                                                                                            |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| **PropertyBridge**   | Subscribes once to the VM's hub; translates `PropertyChangedMessage` → framework reactive primitive.                      |
| **CommandBridge**    | Wraps `RelayCommand` so the UI can bind to a framework-native command/handler with `canExecute` driving `disabled` state. |
| **CollectionBridge** | Wraps `CollectionChangedEvent` so list/tree containers update incrementally.                                              |
| **DialogService**    | Implements `IDialogService` against the framework's native modal stack (confirm, save-file).                              |
| **Dispatcher**       | Implements VMx's foreground/background scheduler contract (spec ch. 11) against the framework's UI loop.                  |

### 7.2 Adapter granularity (one decision)

**Whole-VM subscription** — bridge surfaces a single subscription per VM; the
UI binds individual properties through framework-idiomatic accessors. Single
subscribe = simpler resource accounting; matches `useSyncExternalStore`
(React) and INPC (Avalonia) natively; Textual still binds per-property but on
one subscription. Per-property subscription is rejected because
`PropertyChangedMessage` already carries the property name and granularity
doesn't buy anything beyond noise.

### 7.3 Per-framework adapter signatures

**C# / Avalonia** (`Views/Adapter/`)

```csharp
public sealed class BindableVm : INotifyPropertyChanged, IDisposable { ... }
public sealed class RelayCommandBridge : ICommand { ... }
public sealed class ObservableCollectionBridge<T> : ObservableCollection<T> { ... }
public sealed class AvaloniaDispatcher : IRxDispatcher { ... }
public sealed class AvaloniaDialogService : IDialogService { ... }
```

**Python / Textual** (`views/adapter/`)

```python
def bind_property(widget, attr, vm, vm_property) -> Subscription: ...
def bind_command(button, command) -> Subscription: ...
def bind_collection(list_view, vm_collection, factory) -> Subscription: ...
class TextualDispatcher(RxDispatcher): ...
class TextualDialogService(IDialogService): ...
```

**TypeScript / React** (`views/adapter/`)

```ts
export function useVm<T extends BaseVM>(vm: T): T;
export function useCommand(cmd: RelayCommand): { canExecute: boolean; execute(): void };
export function useVmCollection<TVM>(c: CompositeVM<TVM>): TVM[];
export class ReactDispatcher implements RxDispatcher { ... }
export class ReactDialogService implements IDialogService { ... }
```

## 8. Per-example project structure (M / VM / V partitioned)

### 8.1 Layer ownership

| Layer                  | What lives here                                                                                                                |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| **Models/**            | Plain records, repository contract, in-memory repository implementation, seed data.                                            |
| **ViewModels/**        | Every VMx-based VM, builders, ports declared by VMs (`IDialogService`), pure value types VMs expose (`ActionVM`).              |
| **Views/**             | UI controls, adapter, theme, `IDispatcher` implementation, `IDialogService` implementation, modal screens.                     |
| **(composition root)** | Single entry point (`Program.cs` / `__main__.py` / `main.tsx`) wiring `Model → VM → View`. Not inside any of the three layers. |

Cross-layer rule: `Models/` may not import `ViewModels/` or `Views/`;
`ViewModels/` may not import `Views/`; `Views/` may import anywhere.

### 8.2 C# Avalonia

```
examples/csharp/avalonia/NotesShowcase/
├── NotesShowcase.csproj
├── Program.cs                     ← composition root
├── App.axaml + App.axaml.cs       ← Avalonia entrypoint (InitializeComponent only)
├── Models/
│   ├── NotebookModel.cs
│   ├── NoteModel.cs
│   ├── INoteRepository.cs
│   ├── InMemoryNoteRepository.cs
│   └── SeedData.cs
├── ViewModels/
│   ├── IDialogService.cs
│   ├── ActionVM.cs
│   ├── WorkspaceVM.cs               (+ WorkspaceVM.Builder)
│   ├── NotebooksRootVM.cs
│   ├── NotebookVM.cs
│   ├── NotesViewVM.cs
│   ├── NoteVM.cs
│   ├── NoteFormVM.cs
│   ├── StatusBarVM.cs
│   ├── NotificationsVM.cs
│   └── CapabilityActionsVM.cs
└── Views/
    ├── Adapter/
    │   ├── BindableVm.cs
    │   ├── RelayCommandBridge.cs
    │   ├── ObservableCollectionBridge.cs
    │   ├── AvaloniaDispatcher.cs
    │   └── AvaloniaDialogService.cs
    ├── Theme/DarkTheme.axaml
    ├── MainWindow.axaml + .axaml.cs
    ├── NotebooksTreeView.axaml + .axaml.cs
    ├── NotesListView.axaml + .axaml.cs
    ├── NoteFormView.axaml + .axaml.cs
    └── Modals/{ConfirmDialog,SaveFileDialog}.axaml (+.cs)
```

### 8.3 Python Textual

```
examples/python/textual/notes_showcase/
├── pyproject.toml + README.md
├── src/notes_showcase/
│   ├── __init__.py
│   ├── __main__.py                ← composition root
│   ├── models/
│   │   ├── __init__.py
│   │   ├── notebook_model.py
│   │   ├── note_model.py
│   │   ├── note_repository.py     ← Protocol
│   │   ├── in_memory_repository.py
│   │   └── seed.py
│   ├── viewmodels/
│   │   ├── __init__.py
│   │   ├── dialog_service.py      ← Protocol
│   │   ├── action_vm.py
│   │   ├── workspace_vm.py        (+ builder)
│   │   ├── notebooks_root_vm.py
│   │   ├── notebook_vm.py
│   │   ├── notes_view_vm.py
│   │   ├── note_vm.py
│   │   ├── note_form_vm.py
│   │   ├── status_bar_vm.py
│   │   ├── notifications_vm.py
│   │   └── capability_actions_vm.py
│   └── views/
│       ├── __init__.py
│       ├── app.py                 ← NotesShowcaseApp (Textual App)
│       ├── theme.tcss
│       ├── adapter/
│       │   ├── __init__.py
│       │   ├── property.py
│       │   ├── command.py
│       │   ├── collection.py
│       │   ├── dispatcher.py
│       │   └── dialog.py          ← TextualDialogService
│       ├── main_screen.py
│       ├── notebooks_tree.py
│       ├── notes_list.py
│       ├── note_form.py
│       └── modals/{confirm_modal,save_file_modal}.py
└── tests/{models,viewmodels,views}/
```

### 8.4 TypeScript React

```
examples/typescript/react/notes-showcase/
├── package.json + vite.config.ts + tsconfig.json + index.html + README.md
├── src/
│   ├── main.tsx                   ← composition root
│   ├── models/
│   │   ├── notebookModel.ts
│   │   ├── noteModel.ts
│   │   ├── noteRepository.ts      ← interface
│   │   ├── inMemoryRepository.ts
│   │   └── seed.ts
│   ├── viewmodels/
│   │   ├── dialogService.ts       ← interface
│   │   ├── actionVM.ts
│   │   ├── workspaceVM.ts         (+ builder)
│   │   ├── notebooksRootVM.ts
│   │   ├── notebookVM.ts
│   │   ├── notesViewVM.ts
│   │   ├── noteVM.ts
│   │   ├── noteFormVM.ts
│   │   ├── statusBarVM.ts
│   │   ├── notificationsVM.ts
│   │   └── capabilityActionsVM.ts
│   └── views/
│       ├── App.tsx
│       ├── theme.css
│       ├── adapter/
│       │   ├── useVm.ts
│       │   ├── useCommand.ts
│       │   ├── useVmCollection.ts
│       │   ├── ReactDispatcher.ts
│       │   └── ReactDialogService.tsx
│       ├── components/
│       │   ├── Layout.tsx
│       │   ├── NotebooksTree.tsx
│       │   ├── NotesList.tsx
│       │   ├── NoteForm.tsx
│       │   ├── StatusBar.tsx
│       │   ├── Notifications.tsx
│       │   ├── CapabilityActions.tsx
│       │   └── modals/{ConfirmModal,SaveFileModal}.tsx
│       └── hooks/
│           └── useHotkeys.ts
└── tests/{models,viewmodels,views}/
```

## 9. Testing strategy

### 9.1 VM-layer unit tests (the bulk of coverage)

Tests mirror `src/` layout: `tests/{models,viewmodels,views}/`.

| Flavor           | Runner                               | Run command                             |
| ---------------- | ------------------------------------ | --------------------------------------- |
| C# Avalonia      | xUnit + `Microsoft.Reactive.Testing` | `dotnet test` (from `examples/csharp/`) |
| Python Textual   | pytest + `pytest-asyncio`            | `uv run pytest`                         |
| TypeScript React | vitest + `@testing-library/react`    | `npm test`                              |

**Per-VM test shape (identical structure across the three flavors):**

| Test file                                 | What it asserts                                                                                                                                                                                                                                         |
| ----------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `WorkspaceVMTests`                        | Builder validates required deps. `construct()` awaits `repo.loadAll`, emits `Constructing → Constructed`. `destruct()` cascades depth-first; `dispose()` is idempotent.                                                                                 |
| `NotebooksRootVMTests`                    | `addNotebook` emits `TreeStructureChangedMessage` + adds child. `current` two-way binding round-trip. `INewCreatable.canCreate` truthy.                                                                                                                 |
| `NotebookVMTests`                         | Capability set exactly = the 5 declared. `Expansion.IsExpanded` toggle emits property changed.                                                                                                                                                          |
| `NotesViewVMTests`                        | Search debounced 150 ms (use scheduler). `showStarredOnly` toggle re-filters. Pagination boundaries (no-op at first/last). Switching bound notebook reconstructs.                                                                                       |
| `NoteVMTests`                             | Capability set exactly = the 5 declared. Modeled property changes propagate.                                                                                                                                                                            |
| `NoteFormVMTests`                         | Snapshot taken on bind. Mutating `draft` sets `isDirty`. Approve persists + clears dirty + re-snapshots. Deny restores. `approveCommand.canExecute` requires `isDirty` (strict mode, spec ch. 20) AND `isValid` (NoteFormVM-specific: title non-empty). |
| `StatusBarVMTests`                        | Each `DerivedProperty` recomputes on every named source change; equality-guarded (no duplicate emission).                                                                                                                                               |
| `NotificationsVMTests`                    | Subscribes to `INotificationHub`. Auto-dismiss after configured TTL. Cap at 5 drops oldest.                                                                                                                                                             |
| `CapabilityActionsVMTests`                | Actions list reflects `focusedVM` implements set. Each action's command's `canExecute` follows the underlying VM's `can_*()` predicate.                                                                                                                 |
| `RepositoryTests` (under `tests/models/`) | `InMemoryNoteRepository` honors the simulated delays; `loadAll` returns seed; concurrent saves serialize.                                                                                                                                               |

**Coverage target:** ≥ 90% line coverage on the VM layer per flavor.

### 9.2 Pure-VM contract static checks

CI-enforced; failure = red build. Each is one small script under `tools/`.

| Flavor | Check scope                                                                             | Exemption                            |
| ------ | --------------------------------------------------------------------------------------- | ------------------------------------ |
| C#     | `Views/**/*.axaml.cs` bodies = `InitializeComponent()` only                             | `Views/Adapter/**`                   |
| Python | `views/**/*.py` widget classes: `compose()` / `on_mount()` / `action_*` (≤ 1 stmt) only | `views/adapter/**`                   |
| TS     | `views/components/**/*.tsx`: no `useState` / `useReducer` imported from `react`         | `views/adapter/**`, `views/hooks/**` |

Scripts:

- `tools/check-axaml-codebehind.py`
- `tools/check-textual-views.py`
- React: local ESLint config in the example with `no-restricted-imports`.

Plus one cross-layer check:

- `tools/check-layer-imports.py` — enforces `Models/` ⊄ `ViewModels/` ⊄
  `Views/` direction across all three example apps.

### 9.3 Headless UI smoke (one-shot launchability)

A single test per flavor that boots the app and asserts the main view rendered
without throwing.

| Flavor         | How                                                                                                                                                      |
| -------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| C# Avalonia    | `Avalonia.Headless.XUnit` — `[AvaloniaTest]` boots a headless instance; assert `MainWindow` shows + 4 sample notebooks visible.                          |
| Python Textual | `app.run_test()` async context; assert tree has 4 root nodes; press `down` to select first notebook, assert notes list updates.                          |
| React          | `render(<App workspace={ws} />)` with jsdom; await effect flush; assert tree, list, form all in the DOM; click a notebook li, assert notes list updates. |

### 9.4 Parity test (cross-language sanity)

`tools/check-showcase-parity.py` — given the three test discovery outputs,
assert each flavor's test suite contains the 10 VM test files from §9.1.

### 9.5 CI wiring

- `.github/workflows/csharp.yml` — add `examples/csharp/avalonia/NotesShowcase.Tests` to the `dotnet test` matrix.
- `.github/workflows/python.yml` — add `uv run --project examples/python/textual/notes_showcase pytest` step.
- `.github/workflows/typescript.yml` — add `npm test --prefix examples/typescript/react/notes-showcase` step.
- New job `examples-contract-checks` running the three §9.2 scripts + the §9.4 parity check + the cross-layer import check.

## 10. Phasing and execution plan (input to `writing-plans`)

### 10.1 Branch and worktree

- Single feature branch: **`examples-notes-showcase`** off `main`.
- Worktree at `.claude/worktrees/examples-notes-showcase/`.
- No merges to `main` until Phase 10 (audit-clean).

### 10.2 Phases

| #   | Phase                                         | Depends on   | Parallelizable      | Output                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| --- | --------------------------------------------- | ------------ | ------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 0   | Setup + layout migration                      | —            | —                   | Existing 6 examples relocated under `examples/<lang>/<framework>/<app>/`; all path references updated; CI green.                                                                                                                                                                                                                                                                                                                                                                        |
| 1   | Mark this doc accepted                        | 0            | —                   | Flip `Status:` from `Proposed` to `Accepted` after Phase 0 lands; the contract is then frozen for the rest of the phases.                                                                                                                                                                                                                                                                                                                                                               |
| 2   | **Spec & library extension (`AggregateVM6`)** | 1            | **2a ‖ 2b ‖ 2c**    | Write ADR-0034 ("Extend `AggregateVM` arity to 6 — additive, non-breaking; supersedes ADR-0007 §4 'future major' stance"). Extend `spec/08-aggregate-vm.md` (arity-6 row + builder + spec text). Add `AGG-006` to `spec/12-conformance.md`. Bump `spec/VERSION` to `2.2.0`. Update `compatibility-matrix.md` (add 2.2.x row). Implement `AggregateVM6` + builder + `AGG-006` conformance test in 2a C#, 2b Python, 2c TS. Bump each flavor's package to `2.2.0`. Update each CHANGELOG. |
| 3   | VM layer per flavor                           | 2a/2b/2c     | **3a ‖ 3b ‖ 3c**    | 3a C# VM project + tests; 3b Python `viewmodels/` + tests; 3c TS `viewmodels/` + tests. ≥ 90% coverage. No UI yet. `WorkspaceVM` uses `AggregateVM6` from Phase 2.                                                                                                                                                                                                                                                                                                                      |
| 4   | Adapters per framework                        | 3a/3b/3c     | **4a ‖ 4b ‖ 4c**    | The 5 bridge files per §7.3 each. Adapter unit tests where applicable.                                                                                                                                                                                                                                                                                                                                                                                                                  |
| 5   | UI per framework                              | 4a / 4b / 4c | **5a ‖ 5b ‖ 5c**    | Views per §8. Headless smoke (§9.3) green. Manual run verified once on macOS.                                                                                                                                                                                                                                                                                                                                                                                                           |
| 6   | Pure-VM contract checks                       | 5a/5b/5c     | partly parallel     | The three §9.2 scripts + the cross-layer import check. All three apps pass.                                                                                                                                                                                                                                                                                                                                                                                                             |
| 7   | Polish + parity artefacts                     | 6            | parallel internally | `examples/notes-showcase-parity.md`, three screenshots in `assets/notes-showcase/`, README updates, root README §4.3, scenario-doc cross-links.                                                                                                                                                                                                                                                                                                                                         |
| 8   | CI wiring                                     | 6, 7         | —                   | Extend the three lang workflows; add `examples-contract-checks` job; verify on a draft PR.                                                                                                                                                                                                                                                                                                                                                                                              |
| 9   | Multi-agent audit (clean-pass gate)           | 8            | 4–6 parallel agents | Repeated parallel audits (Critical / Important / Minor) until **10 consecutive zero-finding passes**; spot-checks between runs reset the counter on any miss. Phase-2 spec/library work and phase 3+ example work are audited together since they ship in one PR.                                                                                                                                                                                                                       |
| 10  | Merge to `main`                               | 9 (clean)    | —                   | PR-merge to `main`; close worktree. Spec v2.2.0 + three flavor v2.2.0 packages + three flagship example apps all land in one merge.                                                                                                                                                                                                                                                                                                                                                     |

### 10.3 Future directions (deliberately deferred)

- F1. Promote adapters to published packages (`vmx-react`, `vmx-avalonia`,
  `vmx-textual`). Out of scope here.
- F2. Add additional `<framework>` siblings (WPF, MAUI, PyQt6, NiceGUI, Vue,
  Svelte, Angular, …) — the layout already accommodates these.
- F3. Add per-framework `<app>` siblings within an existing framework (e.g.,
  `examples/csharp/avalonia/HelloVMx/` alongside `NotesShowcase/`).

## 11. References

- Spec chapters: 2 (lifecycle), 4 (commands), 5 (ComponentVM), 6 (CompositeVM), 8 (AggregateVM — extended to arity 6 in 2.2.0),
  10 (builders), 11 (threading), 14 (capabilities), 15 (derived properties),
  16 (notifications), 18 (HierarchicalVM), 19 (dialogs), 20 (FormVM), 21
  (collections).
- ADR-0006 (per-language identifier convention), ADR-0007 (`AggregateVM` arity
  cap — superseded by ADR-0034), ADR-0010 (capabilities additive), ADR-0017
  (Null\* defaults), ADR-0022 (`IFilterable`), ADR-0023 (`IPageable`),
  ADR-0027 (fluent command composition), ADR-0031 (`NotificationVM` /
  `ConfirmationVM`), **ADR-0034** (extend `AggregateVM` arity to 6 — to be
  written in Phase 2).
- `examples/csharp/README.md`, `examples/python/README.md`,
  `examples/typescript/README.md` for current examples context.
- `compatibility-matrix.md` for the spec ↔ flavor pairing convention; Phase 2
  adds a 2.2.x row.
