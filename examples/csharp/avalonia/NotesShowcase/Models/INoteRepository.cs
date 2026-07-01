namespace NotesShowcase.Models;

/// <summary>One token-paged all-notes search result.</summary>
public sealed record NoteSearchPage(IReadOnlyList<NoteModel> Items, string? NextToken);

/// <summary>
/// Async persistence port for notebooks and notes.
///
/// Spec/proposal §3.3: every example wires its VMs to ONE implementation of this
/// interface; the in-memory implementation is the default for the showcase.
/// </summary>
public interface INoteRepository
{
    /// <summary>Loads the full seed at startup (notebooks + notes).</summary>
    Task<(IReadOnlyList<NotebookModel> Notebooks, IReadOnlyList<NoteModel> Notes)> LoadAllAsync(
        CancellationToken ct = default);

    /// <summary>Loads only the notes belonging to <paramref name="notebookId"/>.</summary>
    Task<IReadOnlyList<NoteModel>> LoadNotesAsync(string notebookId, CancellationToken ct = default);

    /// <summary>Searches all notes with opaque forward-only token paging.</summary>
    Task<NoteSearchPage> SearchNotesAsync(
        string term,
        string? token,
        int pageSize,
        CancellationToken ct = default);

    /// <summary>Persists <paramref name="note"/> (insert-or-update by Id).</summary>
    Task SaveNoteAsync(NoteModel note, CancellationToken ct = default);

    /// <summary>Removes the note identified by <paramref name="id"/>.</summary>
    Task DeleteNoteAsync(string id, CancellationToken ct = default);

    /// <summary>Persists a new notebook (append).</summary>
    Task AddNotebookAsync(NotebookModel notebook, CancellationToken ct = default);

    /// <summary>Serializes the workspace to <paramref name="path"/> as JSON.</summary>
    Task ExportAsync(
        IReadOnlyList<NotebookModel> notebooks,
        IReadOnlyList<NoteModel> notes,
        string path,
        CancellationToken ct = default);
}
