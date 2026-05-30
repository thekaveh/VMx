using Avalonia.Controls;
using Avalonia.Markup.Xaml;

namespace NotesShowcase.Views;

/// <summary>
/// Toast overlay. Pure-VM per spec §6.1 — code-behind only loads XAML;
/// auto-dismiss / cap-5 invariants live on <see cref="ViewModels.NotificationsVM"/>.
/// </summary>
public sealed partial class NotificationsView : UserControl
{
    /// <summary>Loads the XAML; required by Avalonia.</summary>
    public NotificationsView() => AvaloniaXamlLoader.Load(this);
}
