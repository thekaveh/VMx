using Avalonia.Controls;
using Avalonia.Markup.Xaml;

namespace NotesShowcase.Views;

/// <summary>
/// Capability actions bar. Pure-VM per spec §6.1 — code-behind only loads
/// XAML. Action labels and commands come from
/// <see cref="ViewModels.CapabilityActionsVM"/>'s projected list.
/// </summary>
public sealed partial class CapabilityActionsView : UserControl
{
    /// <summary>Loads the XAML; required by Avalonia.</summary>
    public CapabilityActionsView() => AvaloniaXamlLoader.Load(this);
}
