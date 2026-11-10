# VMx C# examples

Three self-contained demos of the [VMx C# package](../../langs/csharp/).
The [Example Diagram Gallery](../../docs/content/examples/example-diagram-gallery.md)
collects the generated architecture diagrams for all examples.

## 1. Setup

Each project carries its own `.csproj` and resolves `VMx` from the local
source build. After `VMx` is published to NuGet, a copied template can replace
that project reference with the `VMx` package name.

Prerequisites:

- A .NET 9 or later SDK. `Examples.sln` includes the NotesShowcase test
  project, which targets `net9.0`.
- The .NET 8 runtime to run the example apps, which target `net8.0`. §2 shows
  how to roll forward when only a newer runtime is installed.
- The .NET 9 runtime to run the NotesShowcase tests.

Run every later command in this README from `examples/csharp`. Start from the
repository root:

```bash
cd examples/csharp
dotnet restore      # restores Examples.sln
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

Diagram:
[`csharp-console-hello-vmx.svg`](../../docs/assets/diagrams/csharp-console-hello-vmx.svg)
([HTML](../../docs/assets/diagrams/csharp-console-hello-vmx.html),
[PNG](../../docs/assets/diagrams/csharp-console-hello-vmx.png)).

**Run:**

```bash
dotnet run --project console/HelloVMx
```

Cross-platform — runs anywhere the .NET SDK runs. The project targets
**`net8.0`**. A host that has only a newer runtime (for example .NET 9, no
.NET 8) fails at launch with `You must install or update .NET … 8.0.0 …
was not found`. On such a host, roll forward to the installed major version:

```bash
DOTNET_ROLL_FORWARD=Major dotnet run --project console/HelloVMx
```

(The `avalonia/NotesShowcase` flagship also targets `net8.0` and needs the same
roll-forward when only a newer runtime is present.)

---

## 3. Example 2 — `wpf/TodoApp/` (WPF + MVVM)

> **Platform: Windows only.** WPF is a Windows-only UI framework, so this
> example only *launches* on Windows. `dotnet restore` and `dotnet build`
> succeed cross-platform (the off-Windows `TargetFramework` drops the
> `-windows` suffix), but `dotnet run` requires Windows.

A todo app that wires VMx into a WPF view. Demonstrates:

- `TodoItemVM` *composes* a `ComponentVM<TodoItem>` instead of subclassing
  it. It exposes `Title`, `Done`, and `ToggleDoneCommand` for the item
  template. Use this composition pattern when the view needs properties that
  are not part of the model.
- `MainWindowViewModel` holds an `ObservableCollection<TodoItemVM>` that is
  bound to the ListBox. Its VMx `RelayCommand` (`AddCommand`) runs a task that
  calls the public `AddItem(string)`. The Add button binds
  `Command="{Binding AddCommand}"`.
- The Python `tk/todo_app` example uses a `CompositeVM<TodoItemVM>` for its
  collection. Both flavors drive the add through a VMx `RelayCommand`, each
  in the idiom of its UI toolkit.
- `MainWindow.xaml` is a pure view. Its XAML data binding uses the
  `INotifyPropertyChanged` surface of `TodoItemVM` and the `ICommand`
  `ToggleDoneCommand`. The outer wrapper forwards the hub-published
  `PropertyChangedMessage("Model")` of the inner `ComponentVM<TodoItem>` to
  standard INPC for `Title` and `Done`.

Diagram:
[`csharp-wpf-todo-app.svg`](../../docs/assets/diagrams/csharp-wpf-todo-app.svg)
([HTML](../../docs/assets/diagrams/csharp-wpf-todo-app.html),
[PNG](../../docs/assets/diagrams/csharp-wpf-todo-app.png)).

**Run (Windows only):**

```bash
dotnet run --project wpf/TodoApp
```

`wpf/RecipeHostCheck/` is not an app. It runs the XAML adapter from the
[WPF integration guide](../../docs/content/integration/wpf.md) against real WPF
bindings on a Dispatcher thread. The Windows CI job runs it with
`dotnet run --project wpf/RecipeHostCheck/RecipeHostCheck.csproj`.

`wpf/TodoAppHostCheck/` is not an app either. It compiles this example's own
window and view-models and opens the window on an STA Dispatcher. It types and
clicks Add through the real bindings, and then it closes the window. It checks
that the view-model is disposed and collectable. The same Windows job runs it
with `dotnet run --project wpf/TodoAppHostCheck/TodoAppHostCheck.csproj`.

---

## 4. Example 3 — `avalonia/NotesShowcase/` (Avalonia + MVVM, flagship)

The Notes Workspace flagship app is a cross-platform XAML editor on
Avalonia 12 + .NET 8 that exercises 19 VMx features in one scenario. The
[parity matrix](../notes-showcase-parity.md) lists them. Every view
`*.axaml.cs` code-behind under `Views/` is limited to the view constructor's
`AvaloniaXamlLoader.Load(this)` call. `App.axaml.cs` is the composition root
and is not a view.

Diagram:
[`csharp-avalonia-notes-showcase.svg`](../../docs/assets/diagrams/csharp-avalonia-notes-showcase.svg)
([HTML](../../docs/assets/diagrams/csharp-avalonia-notes-showcase.html),
[PNG](../../docs/assets/diagrams/csharp-avalonia-notes-showcase.png)).

**Run (macOS / Linux / Windows):**

```bash
dotnet run --project avalonia/NotesShowcase
```

Run the NotesShowcase tests, which need the .NET 9 runtime:

```bash
dotnet test avalonia/NotesShowcase.Tests
```

See [`avalonia/NotesShowcase/README.md`](avalonia/NotesShowcase/README.md)
for the project layout, feature-traceability table, and keyboard shortcuts.
The canonical scenario contract is at
[`../../spec/proposals/2026-05-29-notes-showcase-scenario.md`](../../spec/proposals/2026-05-29-notes-showcase-scenario.md).

---

## 5. IDE workflow

Open `Examples.sln` in Visual Studio or Rider to step through the C# example
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
│   ├── TodoApp/
│   │   └── WpfTodoApp.csproj
│   ├── RecipeHostCheck/   # CI host check for the XAML adapter recipe
│   │   └── RecipeHostCheck.csproj
│   └── TodoAppHostCheck/  # CI host check for the TodoApp window lifecycle
│       └── TodoAppHostCheck.csproj
└── avalonia/
    ├── NotesShowcase/
    │   └── NotesShowcase.csproj
    └── NotesShowcase.Tests/
        └── NotesShowcase.Tests.csproj
```
