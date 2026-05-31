using Avalonia.Controls;
using Avalonia.Markup.Xaml;

namespace NotesShowcase.Views;

/// <summary>
/// Status bar view (footer). Pure-VM per spec §6.1 — code-behind only loads
/// XAML. Slot text values are projected by <see cref="ViewModels.StatusBarVM"/>'s
/// <see cref="VMx.Properties.DerivedProperty{T}"/> trio.
/// </summary>
public sealed partial class StatusBarView : UserControl
{
    /// <summary>Loads the XAML; required by Avalonia.</summary>
    public StatusBarView() => AvaloniaXamlLoader.Load(this);
}
