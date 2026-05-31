using Avalonia.Controls;
using Avalonia.Markup.Xaml;

namespace NotesShowcase.Views;

/// <summary>
/// Note editor view (right pane). Pure-VM per spec §6.1 — code-behind only
/// loads XAML. Draft mutation, tag commands, and approve/deny flow through
/// <see cref="ViewModels.NoteFormVM"/>.
/// </summary>
public sealed partial class NoteFormView : UserControl
{
    /// <summary>Loads the XAML; required by Avalonia.</summary>
    public NoteFormView() => AvaloniaXamlLoader.Load(this);
}
