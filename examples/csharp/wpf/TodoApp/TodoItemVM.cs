using System.ComponentModel;
using System.Windows.Input;
using VMx.Commands;
using VMx.Components;
using VMx.Messages;
using VMx.Services;

namespace WpfTodoApp;

/// <summary>
/// ViewModel for a single to-do item. Wraps a <see cref="TodoItem"/> POCO inside a
/// <see cref="ComponentVM{M}"/> and forwards the inner VM's hub-published
/// <see cref="PropertyChangedMessage{TSender}"/> events to standard
/// <see cref="INotifyPropertyChanged"/> notifications so WPF data binding can
/// observe <see cref="Title"/> / <see cref="Done"/> updates on the outer wrapper
/// (which is what the XAML binds to).
///
/// Exposes:
///   • <see cref="Title"/> — bound to TextBlock in the ListBox item template.
///   • <see cref="Done"/>  — bound to CheckBox.IsChecked.
///   • <see cref="ToggleDoneCommand"/> — bound to CheckBox.Command.
/// </summary>
public sealed class TodoItemVM : INotifyPropertyChanged, IDisposable
{
    private readonly ComponentVM<TodoItem> _vm;
    private readonly IDisposable _hubSubscription;

    public TodoItemVM(TodoItem item, IMessageHub hub, IDispatcher dispatcher)
    {
        _vm = ComponentVM<TodoItem>.Builder()
            .Name(item.Title)
            .Services(hub, dispatcher)
            .Model(item)
            .Build();

        ToggleDoneCommand = RelayCommand.Builder()
            .Task(() => _vm.Model = _vm.Model with { Done = !_vm.Model.Done })
            .Predicate(() => _vm.IsConstructed)
            .Build();

        // The inner VM publishes a PropertyChangedMessage("Model") on the hub
        // when the Model record is replaced. Re-raise INPC for the projected
        // properties so XAML bindings on TodoItemVM.Title / .Done refresh.
        _hubSubscription = hub.Messages.Subscribe(msg =>
        {
            if (msg is PropertyChangedMessage<IComponentVM> pc
                && ReferenceEquals(pc.Sender, _vm)
                && pc.PropertyName == nameof(_vm.Model))
            {
                OnPropertyChanged(nameof(Title));
                OnPropertyChanged(nameof(Done));
            }
        });
    }

    public event PropertyChangedEventHandler? PropertyChanged;

    private void OnPropertyChanged(string propertyName) =>
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));

    // ── Properties forwarded from the inner VM ────────────────────────────────

    /// <summary>The inner ComponentVM — exposed for direct VMx-style binding.</summary>
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

    /// <summary>Disposes the inner ComponentVM and the hub subscription.</summary>
    public void Dispose()
    {
        _hubSubscription.Dispose();
        (ToggleDoneCommand as IDisposable)?.Dispose();
        _vm.Dispose();
    }

}
