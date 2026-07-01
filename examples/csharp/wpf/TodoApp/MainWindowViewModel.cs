using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Reactive;
using System.Reactive.Concurrency;
using System.Reactive.Subjects;
using System.Windows.Input;
using VMx.Commands;
using VMx.Services;

namespace WpfTodoApp;

/// <summary>
/// Top-level ViewModel for <see cref="MainWindow"/>.
///
/// Holds an <see cref="ObservableCollection{T}"/> of <see cref="TodoItemVM"/> instances
/// so WPF's ListBox can bind directly via ItemsSource. Each child VM is constructed
/// with the same <see cref="IMessageHub"/> instance owned by this VM, so all children
/// publish into the same hub — demonstrating cross-VM message flow without extra
/// wiring. (Cf. the Python <c>tk_todo_app</c> example, which uses
/// <c>CompositeVM[TodoItemVM]</c> instead; here we lean on
/// <see cref="ObservableCollection{T}"/> directly for WPF data-binding ergonomics.)
/// </summary>
public sealed class MainWindowViewModel : INotifyPropertyChanged
{
    private readonly IMessageHub _hub;
    private readonly IDispatcher _dispatcher;
    private readonly Subject<Unit> _newItemTitleChanged = new();
    private string _newItemTitle = string.Empty;

    /// <summary>
    /// Collection of to-do items displayed by the ListBox.
    /// New items are appended via <see cref="AddItem"/>.
    /// </summary>
    public ObservableCollection<TodoItemVM> Items { get; } = new();

    /// <summary>Text entered in the "New item" TextBox; bound two-way.</summary>
    public string NewItemTitle
    {
        get => _newItemTitle;
        set
        {
            if (_newItemTitle == value) return;
            _newItemTitle = value;
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(NewItemTitle)));
            _newItemTitleChanged.OnNext(Unit.Default);
        }
    }

    public event PropertyChangedEventHandler? PropertyChanged;

    /// <summary>
    /// Adds the item currently typed in <see cref="NewItemTitle"/>. CanExecute is
    /// false while the input is empty/whitespace and is re-evaluated on every
    /// <see cref="NewItemTitle"/> change, so the Add button enables/disables live.
    /// </summary>
    public ICommand AddCommand { get; }

    public MainWindowViewModel()
    {
        // Use WPF's SynchronizationContext for foreground (already set by the time
        // the ViewModel is created in App.OnStartup / MainWindow constructor).
        _hub        = new MessageHub();
        _dispatcher = RxDispatcher.CreateForCurrentContext();

        AddCommand = RelayCommand.Builder()
            .Task(() => AddItem(NewItemTitle))
            .Predicate(() => !string.IsNullOrWhiteSpace(NewItemTitle))
            .Triggers(_newItemTitleChanged)
            .Build();

        // Seed with a couple of items so the UI isn't empty on first launch.
        AddItem("Buy groceries");
        AddItem("Review pull request");
        AddItem("Write unit tests");
    }

    /// <summary>
    /// Creates and constructs a new <see cref="TodoItemVM"/> for <paramref name="title"/>
    /// and appends it to <see cref="Items"/>.
    /// Called by the Add button's Click handler.
    /// </summary>
    public void AddItem(string title)
    {
        if (string.IsNullOrWhiteSpace(title)) return;

        var item = new TodoItemVM(new TodoItem(title.Trim()), _hub, _dispatcher);
        item.Construct();
        Items.Add(item);
        NewItemTitle = string.Empty;
    }

    /// <summary>
    /// Destructs and disposes all child VMs and disposes the hub.
    /// Call from Window.Closed.
    /// </summary>
    public void Shutdown()
    {
        foreach (var item in Items)
        {
            item.Destruct();
            item.Dispose();
        }

        (AddCommand as IDisposable)?.Dispose();
        _newItemTitleChanged.Dispose();
        (_hub as IDisposable)?.Dispose();
    }
}
