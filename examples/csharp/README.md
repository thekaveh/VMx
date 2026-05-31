# VMx C# examples

Two self-contained demos of the [VMx C# package](../../langs/csharp/).

## 1. Setup

Each project carries its own `.csproj` and resolves `VMx` either from the
local source build (when run from this repository) or from
[NuGet](https://www.nuget.org/packages/VMx/) when used as a template.

```bash
dotnet restore
```

---

## 2. Example 1 — `console/HelloVMx/` (console)

Minimal console demo. Demonstrates:

1. Building a `ComponentVM<UserModel>` with the fluent builder.
2. Subscribing to hub messages (`ConstructionStatusChangedMessage` and
   `PropertyChangedMessage`).
3. The full lifecycle: construct → model mutations → destruct → dispose.
4. The equality guard: setting the same model value emits **no** hub
   message.

**Run:**

```bash
cd console/HelloVMx
dotnet run
```

Cross-platform — runs anywhere the .NET SDK runs.

---

## 3. Example 2 — `wpf/TodoApp/` (WPF + MVVM)

A todo app that wires VMx into a WPF view. Demonstrates:

- `TodoItemVM` *composing* a `ComponentVM<TodoItem>` (rather than
  subclassing it) and exposing `Title`/`Done`/`ToggleDoneCommand` for
  the item template — illustrates the composition pattern when you need
  view-only properties that aren't part of the model.
- `MainWindowViewModel` holding an `ObservableCollection<TodoItemVM>`
  bound to the ListBox plus a public `AddItem(string)` method invoked
  from the Add button's click handler. (The Python `tk/todo_app`
  example uses `CompositeVM<TodoItemVM>` + `RelayCommand` for the same
  shape — both patterns are idiomatic; this one shows the lighter
  WPF-flavoured wiring.)
- `MainWindow.xaml` — pure view; XAML data binding against
  `TodoItemVM`'s `INotifyPropertyChanged` surface (the outer wrapper
  forwards the inner `ComponentVM<TodoItem>`'s hub-published
  `PropertyChangedMessage("Model")` to standard INPC for `Title` /
  `Done`) plus the `ICommand`-exposing `ToggleDoneCommand`.

**Run (Windows only):**

```bash
cd wpf/TodoApp
dotnet run
```

`dotnet restore` and `dotnet build` succeed cross-platform; the app only
launches on Windows because of the WPF target.

---

## 4. Example 3 — `avalonia/NotesShowcase/` (Avalonia + MVVM, flagship)

The Notes Workspace flagship app — a cross-platform XAML editor on
Avalonia 11 + .NET 8 that exercises **15 distinct VMx features** in one
cohesive scenario (notebooks tree, paged + filterable notes list, FormVM
editor, capability-aware action bar, notifications, async lifecycle,
dialogs, `AggregateVM6` root). Pure-VM contract enforced; every `*.axaml.cs`
code-behind is `InitializeComponent()`-only.

**Run (macOS / Linux / Windows):**

```bash
cd ../../    # repo root
dotnet run --project examples/csharp/avalonia/NotesShowcase
```

See [`avalonia/NotesShowcase/README.md`](avalonia/NotesShowcase/README.md)
for the project layout, feature-traceability table, and keyboard shortcuts.
Cross-flavor parity is documented in
[`../notes-showcase-parity.md`](../notes-showcase-parity.md); the canonical
scenario contract lives at
[`../../spec/proposals/2026-05-29-notes-showcase-scenario.md`](../../spec/proposals/2026-05-29-notes-showcase-scenario.md).

---

## 5. IDE workflow

Open `Examples.sln` in Visual Studio or Rider to step through all three
projects with the debugger attached.

## 6. Project layout

```
examples/csharp/
├── Examples.sln
├── README.md              # this file
├── console/
│   └── HelloVMx/
│       └── HelloVMx.csproj
├── wpf/
│   └── TodoApp/
│       └── WpfTodoApp.csproj
└── avalonia/
    ├── NotesShowcase/
    │   └── NotesShowcase.csproj
    └── NotesShowcase.Tests/
        └── NotesShowcase.Tests.csproj
```
