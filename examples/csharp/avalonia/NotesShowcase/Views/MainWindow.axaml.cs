using Avalonia.Controls;
using Avalonia.Markup.Xaml;

namespace NotesShowcase.Views;

/// <summary>
/// Root window for the Notes Workspace. Pure-VM per spec §6.1 — code-behind
/// only loads the XAML; every binding, command, and selection routes through
/// the <see cref="ViewModels.WorkspaceVM"/> tree set as <see cref="Window.DataContext"/>.
/// </summary>
public sealed partial class MainWindow : Window
{
    /// <summary>Loads the XAML; required by Avalonia.</summary>
    public MainWindow() => AvaloniaXamlLoader.Load(this);
}
