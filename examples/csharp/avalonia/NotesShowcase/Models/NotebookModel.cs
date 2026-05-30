namespace NotesShowcase.Models;

/// <summary>
/// Domain model for a notebook (a node in the notebooks tree).
///
/// See spec/proposals/2026-05-29-notes-showcase-scenario.md §3.1.
/// Pure data — no behavior, no VMx dependencies.
/// </summary>
public sealed record NotebookModel(string Id, string Name, string? ParentId);
