using Avalonia.Controls;
using Avalonia.Markup.Xaml;

namespace NotesShowcase.Views;

/// <summary>
/// Theme control strip (ADR-0201 §2.4). Pure-VM per spec §6.1 — code-behind
/// only loads XAML. Every button runs a <see cref="ViewModels.ThemeVM"/>
/// command.
/// </summary>
public sealed partial class ThemeControlsView : UserControl
{
    /// <summary>Loads the XAML; required by Avalonia.</summary>
    public ThemeControlsView() => AvaloniaXamlLoader.Load(this);
}
