using Avalonia.Controls;
using Avalonia.Markup.Xaml;

namespace NotesShowcase.Views;

/// <summary>
/// Notebooks pane view. Pure-VM per spec §6.1 — only loads the XAML; tree
/// expansion, selection, and structure changes all flow through bindings on
/// the wrapping <see cref="ViewModels.NotebooksRootVM"/>.
/// </summary>
public sealed partial class NotebooksTreeView : UserControl
{
    /// <summary>Loads the XAML; required by Avalonia.</summary>
    public NotebooksTreeView() => AvaloniaXamlLoader.Load(this);
}
