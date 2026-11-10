using Avalonia.Automation;
using Avalonia.Controls;
using Avalonia.Headless.XUnit;
using Avalonia.Threading;
using Avalonia.VisualTree;
using NotesShowcase.Models;
using NotesShowcase.ViewModels;
using NotesShowcase.Views;
using NotesShowcase.Views.Adapter;
using VMx.Dialogs;
using VMx.Notifications;
using VMx.Services;
using Xunit;

namespace NotesShowcase.Tests.Views;

/// <summary>
/// Drives the theme control strip of the real <see cref="MainWindow"/>
/// headlessly (ADR-0201 §2.4): one button per preset, a high-contrast toggle,
/// and font-size decrease and increase buttons.
/// </summary>
public sealed class ThemeControlsHeadlessTests
{
    [Trait("Category", "Smoke")]
    [AvaloniaFact]
    public async Task Theme_control_strip_runs_the_ThemeVM_commands()
    {
        var (workspace, window) = await OpenWindowAsync();
        try
        {
            var strip = (Control?)window.FindDescendantByName("ThemeControls");
            Assert.NotNull(strip);
            var buttons = strip!.GetVisualDescendants().OfType<Button>().ToList();
            var theme = workspace.Theme;

            foreach (var preset in theme.Presets)
            {
                Click(buttons.Single(b => Equals(b.Content, preset.Name)));
                Assert.Equal(preset.Name, theme.Model.Name);
            }

            Click(buttons.Single(b => Equals(b.Content, "light")));
            Assert.False(theme.Model.HighContrast);
            Click(ByName(buttons, "Toggle high contrast"));
            Assert.True(theme.Model.HighContrast);
            Click(ByName(buttons, "Toggle high contrast"));
            Assert.False(theme.Model.HighContrast);

            Assert.Equal(1.0, theme.Model.FontScaleFactor, 6);
            Click(ByName(buttons, "Increase font size"));
            Assert.Equal(1.1, theme.Model.FontScaleFactor, 6);
            Click(ByName(buttons, "Decrease font size"));
            Assert.Equal(1.0, theme.Model.FontScaleFactor, 6);
        }
        finally
        {
            workspace.Dispose();
            window.Close();
        }
    }

    private static Button ByName(IEnumerable<Button> buttons, string name)
        => buttons.Single(b => AutomationProperties.GetName(b) == name);

    private static void Click(Button button)
    {
        Assert.NotNull(button.Command);
        Assert.True(button.Command!.CanExecute(button.CommandParameter));
        button.Command.Execute(button.CommandParameter);
        Dispatcher.UIThread.RunJobs();
    }

    private static async Task<(WorkspaceVM Workspace, MainWindow Window)> OpenWindowAsync()
    {
        var repo = new InMemoryNoteRepository(
            SeedData.Build(),
            loadAllDelay: TimeSpan.Zero,
            loadNotesDelay: TimeSpan.Zero,
            saveNoteDelay: TimeSpan.Zero,
            addNotebookDelay: TimeSpan.Zero);
        var workspace = WorkspaceVM.Builder()
            .Repository(repo)
            .DialogService(NullDialogService.Instance)
            .NotificationHub(new NotificationHub())
            .MessageHub(new MessageHub())
            .Dispatcher(new AvaloniaDispatcher())
            .Build();
        var construct = workspace.ConstructAsync();
        var window = new MainWindow { DataContext = workspace };
        window.Show();
        window.UpdateLayout();
        await construct;
        Dispatcher.UIThread.RunJobs();
        window.UpdateLayout();
        return (workspace, window);
    }
}
