using System.Text.Json;

namespace NotesShowcase.Models;

/// <summary>
/// Default <see cref="INoteRepository"/>: in-memory store with simulated I/O
/// delays (per plan §3.a.4). Thread-safe via a <see cref="SemaphoreSlim"/>
/// gate; safe to call from multiple async consumers.
/// </summary>
public sealed class InMemoryNoteRepository : INoteRepository
{
    private readonly List<NotebookModel> _notebooks;
    private readonly List<NoteModel> _notes;
    private readonly SemaphoreSlim _gate = new(1, 1);
    private readonly TimeSpan _loadAllDelay;
    private readonly TimeSpan _loadNotesDelay;
    private readonly TimeSpan _saveNoteDelay;
    private readonly TimeSpan _deleteNoteDelay;
    private readonly TimeSpan _addNotebookDelay;
    private readonly TimeSpan _exportDelay;

    /// <summary>
    /// Initializes the repository with <paramref name="seed"/>. Delay overrides
    /// are exposed for tests that need zero latency (default delays mirror the
    /// scenario doc §7: 300/150/200/120/120/150 ms).
    /// </summary>
    public InMemoryNoteRepository(
        (IReadOnlyList<NotebookModel> Notebooks, IReadOnlyList<NoteModel> Notes) seed,
        TimeSpan? loadAllDelay = null,
        TimeSpan? loadNotesDelay = null,
        TimeSpan? saveNoteDelay = null,
        TimeSpan? deleteNoteDelay = null,
        TimeSpan? addNotebookDelay = null,
        TimeSpan? exportDelay = null)
    {
        _notebooks = seed.Notebooks.ToList();
        _notes = seed.Notes.ToList();
        _loadAllDelay = loadAllDelay ?? TimeSpan.FromMilliseconds(300);
        _loadNotesDelay = loadNotesDelay ?? TimeSpan.FromMilliseconds(150);
        _saveNoteDelay = saveNoteDelay ?? TimeSpan.FromMilliseconds(200);
        _deleteNoteDelay = deleteNoteDelay ?? TimeSpan.FromMilliseconds(120);
        _addNotebookDelay = addNotebookDelay ?? TimeSpan.FromMilliseconds(120);
        _exportDelay = exportDelay ?? TimeSpan.FromMilliseconds(150);
    }

    /// <inheritdoc/>
    public async Task<(IReadOnlyList<NotebookModel> Notebooks, IReadOnlyList<NoteModel> Notes)> LoadAllAsync(
        CancellationToken ct = default)
    {
        await Task.Delay(_loadAllDelay, ct).ConfigureAwait(false);
        await _gate.WaitAsync(ct).ConfigureAwait(false);
        try
        {
            return (_notebooks.ToList(), _notes.ToList());
        }
        finally
        {
            _gate.Release();
        }
    }

    /// <inheritdoc/>
    public async Task<IReadOnlyList<NoteModel>> LoadNotesAsync(string notebookId, CancellationToken ct = default)
    {
        await Task.Delay(_loadNotesDelay, ct).ConfigureAwait(false);
        await _gate.WaitAsync(ct).ConfigureAwait(false);
        try
        {
            return _notes.Where(n => n.NotebookId == notebookId).ToList();
        }
        finally
        {
            _gate.Release();
        }
    }

    /// <inheritdoc/>
    public async Task SaveNoteAsync(NoteModel note, CancellationToken ct = default)
    {
        await Task.Delay(_saveNoteDelay, ct).ConfigureAwait(false);
        await _gate.WaitAsync(ct).ConfigureAwait(false);
        try
        {
            var idx = _notes.FindIndex(n => n.Id == note.Id);
            var stamped = note with { UpdatedAt = DateTimeOffset.UtcNow };
            if (idx >= 0) _notes[idx] = stamped;
            else _notes.Add(stamped);
        }
        finally
        {
            _gate.Release();
        }
    }

    /// <inheritdoc/>
    public async Task DeleteNoteAsync(string id, CancellationToken ct = default)
    {
        await Task.Delay(_deleteNoteDelay, ct).ConfigureAwait(false);
        await _gate.WaitAsync(ct).ConfigureAwait(false);
        try
        {
            _notes.RemoveAll(n => n.Id == id);
        }
        finally
        {
            _gate.Release();
        }
    }

    /// <inheritdoc/>
    public async Task AddNotebookAsync(NotebookModel notebook, CancellationToken ct = default)
    {
        await Task.Delay(_addNotebookDelay, ct).ConfigureAwait(false);
        await _gate.WaitAsync(ct).ConfigureAwait(false);
        try
        {
            _notebooks.Add(notebook);
        }
        finally
        {
            _gate.Release();
        }
    }

    /// <inheritdoc/>
    public async Task ExportAsync(
        IReadOnlyList<NotebookModel> notebooks,
        IReadOnlyList<NoteModel> notes,
        string path,
        CancellationToken ct = default)
    {
        await Task.Delay(_exportDelay, ct).ConfigureAwait(false);
        var payload = new { notebooks, notes };
        var json = JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true });
        await File.WriteAllTextAsync(path, json, ct).ConfigureAwait(false);
    }
}
