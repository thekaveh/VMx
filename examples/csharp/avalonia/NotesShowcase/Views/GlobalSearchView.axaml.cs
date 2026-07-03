using Avalonia.Controls;
using Avalonia.Markup.Xaml;

namespace NotesShowcase.Views;

/// <summary>
/// Global all-notes search view. Pure-VM per spec §6.1 — code-behind only loads
/// XAML. Search input, token paging, and result selection are all bound to
/// <see cref="ViewModels.GlobalSearchVM"/>.
/// </summary>
public sealed partial class GlobalSearchView : UserControl
{
    /// <summary>Loads the XAML; required by Avalonia.</summary>
    public GlobalSearchView() => AvaloniaXamlLoader.Load(this);
}
