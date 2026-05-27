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
4. A `RelayCommand` whose `CanExecute` reacts to a property change.

**Run:**

```bash
cd HelloVMx
dotnet run
```

Cross-platform — runs anywhere the .NET SDK runs.

---

## 3. Example 2 — `WpfTodoApp/` (WPF + MVVM)

Full MVVM todo app using WPF data binding. Demonstrates:

- `TodoItemVM` subclassing `ComponentVM<TodoItem>` and exposing a
  `ToggleDoneCommand`.
- `MainWindowViewModel` holding a `CompositeVM<TodoItemVM>` and exposing
  `AddCommand` / `RemoveCommand` for the view to bind to.
- `MainWindow.xaml` — pure view; all logic lives in the ViewModel.
- XAML data binding against `INotifyPropertyChanged` + `ICommand` surface.

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
