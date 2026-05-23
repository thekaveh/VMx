using System.Windows.Input;
using VMx.Components;
using VMx.Services;

namespace WpfTodoApp;

/// <summary>
/// ViewModel for a single to-do item. Wraps a <see cref="TodoItem"/> POCO inside a
/// <see cref="ComponentVM{M}"/> so that WPF's INotifyPropertyChanged binding wires up
/// automatically — no additional glue code needed.
///
/// Exposes:
///   • <see cref="Title"/> — bound to TextBlock in the ListBox item template.
///   • <see cref="Done"/>  — bound to CheckBox.IsChecked.
///   • <see cref="ToggleDoneCommand"/> — bound to CheckBox.Command.
/// </summary>
public sealed class TodoItemVM
{
    private readonly ComponentVM<TodoItem> _vm;

    public TodoItemVM(TodoItem item, IMessageHub hub, IDispatcher dispatcher)
    {
        _vm = ComponentVM<TodoItem>.Builder()
            .Name(item.Title)
            .Services(hub, dispatcher)
            .Model(item)
            .Build();

        ToggleDoneCommand = new RelayCommand(
            execute:    () => _vm.Model = _vm.Model with { Done = !_vm.Model.Done },
            canExecute: () => _vm.IsConstructed);
    }

    // ── Properties forwarded from the inner VM ────────────────────────────────

    /// <summary>The inner ComponentVM — exposes INotifyPropertyChanged for WPF.</summary>
    public ComponentVM<TodoItem> VM => _vm;

    /// <summary>Title of the to-do item; read-only binding target.</summary>
    public string Title => _vm.Model.Title;

    /// <summary>Whether the item is done; two-way binding target via ToggleDoneCommand.</summary>
    public bool Done => _vm.Model.Done;

    /// <summary>Toggles the Done flag on the underlying model.</summary>
    public ICommand ToggleDoneCommand { get; }

    // ── Lifecycle pass-through ─────────────────────────────────────────────────

    /// <summary>Constructs the inner ComponentVM (must be called before binding).</summary>
    public void Construct() => _vm.Construct();

    /// <summary>Destructs the inner ComponentVM.</summary>
    public void Destruct() => _vm.Destruct();

    // ── Tiny ICommand implementation (avoids extra dependencies) ─────────────

    private sealed class RelayCommand : ICommand
    {
        private readonly Action _execute;
        private readonly Func<bool> _canExecute;

        public RelayCommand(Action execute, Func<bool> canExecute)
        {
            _execute    = execute;
            _canExecute = canExecute;
        }

        public event EventHandler? CanExecuteChanged;
        public bool CanExecute(object? _) => _canExecute();
        public void Execute(object? _)    => _execute();

        public void RaiseCanExecuteChanged() =>
            CanExecuteChanged?.Invoke(this, EventArgs.Empty);
    }
}
