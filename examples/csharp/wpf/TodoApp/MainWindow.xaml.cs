using System.Windows;

namespace WpfTodoApp;

/// <summary>
/// Code-behind for the main window. Sets the DataContext to a
/// <see cref="MainWindowViewModel"/> so WPF binding can resolve
/// <c>Items</c> and <c>NewItemTitle</c> automatically.
/// </summary>
public partial class MainWindow : Window
{
    private readonly MainWindowViewModel _viewModel;

    public MainWindow()
    {
        InitializeComponent();
        _viewModel  = new MainWindowViewModel();
        DataContext = _viewModel;
    }

    private void Window_Closed(object sender, EventArgs e)
    {
        _viewModel.Shutdown();
    }
}
