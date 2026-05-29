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

## 2. Example 1 — `HelloVMx/` (console)

Minimal console demo. Demonstrates:

1. Building a `ComponentVM<UserModel>` with the fluent builder.
2. Subscribing to hub messages (`ConstructionStatusChangedMessage` and
   `PropertyChangedMessage`).
3. The full lifecycle: construct → model mutations → destruct → dispose.
4. The equality guard: setting the same model value emits **no** hub
   message.

**Run:**

```bash
cd HelloVMx
dotnet run
```

Cross-platform — runs anywhere the .NET SDK runs.

---

## 3. Example 2 — `WpfTodoApp/` (WPF + MVVM)

A todo app that wires VMx into a WPF view. Demonstrates:

- `TodoItemVM` *composing* a `ComponentVM<TodoItem>` (rather than
  subclassing it) and exposing `Title`/`Done`/`ToggleDoneCommand` for
  the item template — illustrates the composition pattern when you need
  view-only properties that aren't part of the model.
- `MainWindowViewModel` holding an `ObservableCollection<TodoItemVM>`
  bound to the ListBox plus a public `AddItem(string)` method invoked
  from the Add button's click handler. (The Python `tk_todo_app`
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
cd WpfTodoApp
dotnet run
```

`dotnet restore` and `dotnet build` succeed cross-platform; the app only
launches on Windows because of the WPF target.

---

## 4. IDE workflow

Open `Examples.sln` in Visual Studio or Rider to step through both
projects with the debugger attached.

## 5. Project layout

```
examples/csharp/
├── Examples.sln
├── README.md          # this file
├── HelloVMx/
│   └── HelloVMx.csproj
└── WpfTodoApp/
    └── WpfTodoApp.csproj
```
