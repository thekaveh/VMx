# C# examples

Runnable example projects that exercise the VMx C# flavor.

## Projects

- **`HelloVMx/`** — minimal console app. Builds a `ComponentVMOf<UserModel>`, a
  `RelayCommand` with a reactive trigger, and a `CompositeVM<TabVM>`. Runs on
  any OS with the .NET SDK installed.
- **`WpfTodoApp/`** — small WPF todo app demonstrating XAML data binding
  against `INotifyPropertyChanged` + `ICommand`. Windows-only build target;
  `dotnet restore` succeeds cross-platform but the app only runs on Windows.

## Running

```bash
cd HelloVMx
dotnet run
```

Open `Examples.sln` in Visual Studio / Rider for an IDE workflow.
