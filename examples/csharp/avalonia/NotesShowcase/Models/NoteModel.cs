namespace NotesShowcase.Models;

/// <summary>
/// Domain model for a single note.
///
/// See spec/proposals/2026-05-29-notes-showcase-scenario.md §3.2.
/// Pure data — no behavior, no VMx dependencies.
/// </summary>
public sealed record NoteModel(
    string Id,
    string NotebookId,
    string Title,
    IReadOnlyList<string> Tags,
    string Body,
    bool Starred,
    DateTimeOffset CreatedAt,
    DateTimeOffset UpdatedAt);
