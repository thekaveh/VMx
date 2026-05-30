using Avalonia.Controls;
using Avalonia.Markup.Xaml;

namespace NotesShowcase.Views.Modals;

/// <summary>
/// Minimal confirmation modal. Pure-VM per spec §6.1 — code-behind only loads
/// XAML. Result wiring (click → close with bool) is owned by the adapter
/// (<see cref="Adapter.AvaloniaDialogService"/>), which subscribes to the
/// named <c>YesButton</c> / <c>NoButton</c> after construction.
/// </summary>
public sealed partial class ConfirmDialog : Window
{
    /// <summary>Loads the XAML; required by Avalonia.</summary>
    public ConfirmDialog() => AvaloniaXamlLoader.Load(this);
}
