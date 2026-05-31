using Avalonia.Controls;
using Avalonia.Markup.Xaml;

namespace NotesShowcase.Views;

/// <summary>
/// Notes list view (centre pane). Pure-VM per spec §6.1 — code-behind only
/// loads XAML. Search, filtering, pagination, and selection are all bound to
/// <see cref="ViewModels.NotesViewVM"/>.
/// </summary>
public sealed partial class NotesListView : UserControl
{
    /// <summary>Loads the XAML; required by Avalonia.</summary>
    public NotesListView() => AvaloniaXamlLoader.Load(this);
}
