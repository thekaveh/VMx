using System.Diagnostics;
using NotesShowcase.Models;
using Xunit;

namespace NotesShowcase.Tests.Models;

/// <summary>
/// Repository tests per plan §3.a.4.
/// Timing tests assert only a lower-bound floor — that the simulated delay
/// actually elapsed (the load is not instant / did not take a TimeSpan.Zero
/// override) — and deliberately omit an upper bound: a wall-clock upper bound
/// is flaky on loaded CI runners (e.g. a ~150 ms delay can measure >500 ms
/// under load). We use the default delays here; faster overrides exist for VM
/// tests that don't care about wall-clock timing.
/// </summary>
public sealed class InMemoryNoteRepositoryTests
{
    [Fact]
    public async Task LoadAll_returns_seed_after_about_300ms()
    {
        var repo = new InMemoryNoteRepository(SeedData.Build());
        var sw = Stopwatch.StartNew();
        var (notebooks, notes) = await repo.LoadAllAsync();
        sw.Stop();
        Assert.True(
            sw.ElapsedMilliseconds >= 200,
            $"expected the ~300 ms simulated load delay; took {sw.ElapsedMilliseconds} ms");
        Assert.NotEmpty(notebooks);
        Assert.NotEmpty(notes);
    }

    [Fact]
    public async Task LoadNotes_filters_by_notebook_and_delays_about_150ms()
    {
        var repo = new InMemoryNoteRepository(SeedData.Build());
        var sw = Stopwatch.StartNew();
        var notes = await repo.LoadNotesAsync("nb-reviews");
        sw.Stop();
        Assert.True(
            sw.ElapsedMilliseconds >= 100,
            $"expected the ~150 ms simulated load delay; took {sw.ElapsedMilliseconds} ms");
        Assert.NotEmpty(notes);
        Assert.All(notes, n => Assert.Equal("nb-reviews", n.NotebookId));
    }

    [Fact]
    public async Task SaveNote_persists_change_and_loadNotes_reflects_it()
    {
        // Use fast overrides — timing isn't under test here.
        var repo = new InMemoryNoteRepository(
            SeedData.Build(),
            loadAllDelay: TimeSpan.Zero,
            loadNotesDelay: TimeSpan.Zero,
            saveNoteDelay: TimeSpan.Zero);
        var notes = await repo.LoadNotesAsync("nb-reviews");
        var first = notes[0] with { Title = "Updated" };
        await repo.SaveNoteAsync(first);
        var after = await repo.LoadNotesAsync("nb-reviews");
        Assert.Equal("Updated", after.Single(n => n.Id == first.Id).Title);
    }

    [Fact]
    public async Task DeleteNote_removes_note_so_loadNotes_no_longer_returns_it()
    {
        var repo = new InMemoryNoteRepository(
            SeedData.Build(),
            loadNotesDelay: TimeSpan.Zero,
            deleteNoteDelay: TimeSpan.Zero);
        var before = await repo.LoadNotesAsync("nb-reviews");
        var toDelete = before[0];
        await repo.DeleteNoteAsync(toDelete.Id);
        var after = await repo.LoadNotesAsync("nb-reviews");
        Assert.DoesNotContain(after, n => n.Id == toDelete.Id);
    }

    [Fact]
    public async Task SaveNote_inserts_when_id_is_new()
    {
        var repo = new InMemoryNoteRepository(
            SeedData.Build(),
            loadNotesDelay: TimeSpan.Zero,
            saveNoteDelay: TimeSpan.Zero);
        var fresh = new NoteModel(
            Id: "note-99",
            NotebookId: "nb-work",
            Title: "Brand new",
            Tags: Array.Empty<string>(),
            Body: "...",
            Starred: false,
            CreatedAt: DateTimeOffset.UtcNow,
            UpdatedAt: DateTimeOffset.UtcNow);
        await repo.SaveNoteAsync(fresh);
        var notes = await repo.LoadNotesAsync("nb-work");
        Assert.Contains(notes, n => n.Id == "note-99");
    }

    [Fact]
    public async Task AddNotebook_appends_and_loadAll_returns_it()
    {
        var repo = new InMemoryNoteRepository(
            SeedData.Build(),
            loadAllDelay: TimeSpan.Zero,
            addNotebookDelay: TimeSpan.Zero);
        await repo.AddNotebookAsync(new NotebookModel("nb-inbox", "Inbox", null));
        var (notebooks, _) = await repo.LoadAllAsync();
        Assert.Contains(notebooks, nb => nb.Id == "nb-inbox");
    }

    [Fact]
    public async Task Export_writes_json_with_notebooks_and_notes_fields()
    {
        var repo = new InMemoryNoteRepository(
            SeedData.Build(),
            loadAllDelay: TimeSpan.Zero,
            exportDelay: TimeSpan.Zero);
        var (nbs, notes) = await repo.LoadAllAsync();
        var path = Path.Combine(Path.GetTempPath(), $"notes-showcase-export-{Guid.NewGuid():N}.json");
        try
        {
            await repo.ExportAsync(nbs, notes, path);
            var content = await File.ReadAllTextAsync(path);
            Assert.Contains("notebooks", content);
            Assert.Contains("notes", content);
            Assert.Contains("nb-reviews", content);
        }
        finally
        {
            if (File.Exists(path)) File.Delete(path);
        }
    }
}
