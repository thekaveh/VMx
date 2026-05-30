using System.Collections.ObjectModel;
using System.Reactive.Concurrency;
using VMx.Services;

namespace WpfTodoApp;

/// <summary>
/// Top-level ViewModel for <see cref="MainWindow"/>.
///
/// Holds an <see cref="ObservableCollection{T}"/> of <see cref="TodoItemVM"/> instances
/// so WPF's ListBox can bind directly via ItemsSource. A <see cref="VMx.Composites.CompositeVM{VM}"/>
/// manages the shared <see cref="IMessageHub"/> so every child VM participates in the
/// same hub — demonstrating cross-VM message flow without extra wiring.
/// </summary>
public sealed class MainWindowViewModel
{
    private readonly IMessageHub _hub;
    private readonly IDispatcher _dispatcher;

    /// <summary>
    /// Collection of to-do items displayed by the ListBox.
    /// New items are appended via <see cref="AddItem"/>.
    /// </summary>
    public ObservableCollection<TodoItemVM> Items { get; } = new();

    /// <summary>Text entered in the "New item" TextBox; bound two-way.</summary>
    public string NewItemTitle { get; set; } = string.Empty;

    public MainWindowViewModel()
    {
        // Use WPF's SynchronizationContext for foreground (already set by the time
        // the ViewModel is created in App.OnStartup / MainWindow constructor).
        _hub        = new MessageHub();
        _dispatcher = RxDispatcher.CreateForCurrentContext();

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
    /// Destructs all child VMs and disposes the hub. Call from Window.Closed.
    /// </summary>
    public void Shutdown()
    {
        foreach (var item in Items)
            item.Destruct();

        _hub.Dispose();
    }
}
