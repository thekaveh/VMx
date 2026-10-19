using Avalonia.Automation;
using Avalonia.Controls;
using Avalonia.Headless;
using Avalonia.Headless.XUnit;
using Avalonia.Input;
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
/// Drives the real <see cref="MainWindow"/> headlessly to pin that selecting
/// another note while a save is still pending does not lose that save: the
/// repository write lands, the saved row refreshes, the "Saved" toast shows,
/// and a later save of that note does not write the old title back.
/// </summary>
public sealed class SaveInFlightHeadlessTests
{
    private const string EditedTitle = "Roadmap snapshot (edited)";

    [Trait("Category", "Smoke")]
    [AvaloniaFact]
    public async Task Selecting_another_note_mid_save_keeps_the_saves_effects()
    {
        var repo = new InMemoryNoteRepository(
            SeedData.Build(),
            loadAllDelay: TimeSpan.Zero,
            loadNotesDelay: TimeSpan.Zero,
            saveNoteDelay: TimeSpan.FromMilliseconds(300),
            deleteNoteDelay: TimeSpan.Zero,
            addNotebookDelay: TimeSpan.Zero,
            exportDelay: TimeSpan.Zero);
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
        PumpUntil(() => workspace.NotesView.VisibleItems.Count > 1);
        window.UpdateLayout();
        try
        {
            var list = (ListBox)window.FindDescendantByName("NotesList")!;
            var titleBox = window.GetVisualDescendants().OfType<TextBox>()
                .Single(t => AutomationProperties.GetName(t) == "Note title");
            var bodyBox = window.GetVisualDescendants().OfType<TextBox>()
                .Single(t => AutomationProperties.GetName(t) == "Note body");
            var note = workspace.NotesView.VisibleItems.Single(n => n.Title == "Roadmap snapshot");
            var other = workspace.NotesView.VisibleItems.First(n => !ReferenceEquals(n, note));

            list.SelectedItem = note;
            Pump();
            titleBox.Text = EditedTitle;
            Pump();
            Assert.True(workspace.NoteForm.IsDirty);

            // Ctrl+S, then click another note before the 300 ms save completes.
            window.KeyPressQwerty(PhysicalKey.S, RawInputModifiers.Control);
            window.KeyReleaseQwerty(PhysicalKey.S, RawInputModifiers.Control);
            Pump();
            list.SelectedItem = other;
            Pump();
            Assert.Same(other, workspace.NotesView.Current);
            Assert.Equal(other.Model.Title, workspace.NoteForm.Title);

            PumpUntil(() => note.Title == EditedTitle
                && workspace.Notifications.Visible.Any(
                    n => n.Notification.Message == $"Saved “{EditedTitle}”"));
            Assert.Equal(EditedTitle, (await LoadAsync(repo, note.Model.Id)).Title);
            // The newly bound note is untouched by the old save's settlement.
            Assert.Same(other, workspace.NotesView.Current);
            Assert.False(workspace.NoteForm.IsDirty);

            // A later save of the same note keeps the saved title.
            list.SelectedItem = note;
            Pump();
            Assert.Equal(EditedTitle, workspace.NoteForm.Title);
            bodyBox.Text = "later edit";
            Pump();
            window.KeyPressQwerty(PhysicalKey.S, RawInputModifiers.Control);
            window.KeyReleaseQwerty(PhysicalKey.S, RawInputModifiers.Control);
            PumpUntil(() => !workspace.NoteForm.IsDirty);
            var persisted = await LoadAsync(repo, note.Model.Id);
            Assert.Equal(EditedTitle, persisted.Title);
            Assert.Equal("later edit", persisted.Body);
        }
        finally
        {
            workspace.Dispose();
            window.Close();
        }
    }

    private static async Task<NoteModel> LoadAsync(InMemoryNoteRepository repo, string id)
    {
        var (_, notes) = await repo.LoadAllAsync();
        return notes.Single(n => n.Id == id);
    }

    private static void Pump() => Dispatcher.UIThread.RunJobs();

    private static void PumpUntil(Func<bool> condition)
    {
        var deadline = DateTime.UtcNow + TimeSpan.FromSeconds(5);
        while (true)
        {
            Dispatcher.UIThread.RunJobs();
            if (condition()) return;
            Assert.True(DateTime.UtcNow < deadline, "Timed out waiting for the UI to settle.");
            Thread.Sleep(10);
        }
    }
}
