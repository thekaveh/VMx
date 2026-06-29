namespace NotesShowcase.Models;

/// <summary>
/// Domain model for a single note.
///
/// See spec/proposals/2026-05-29-notes-showcase-scenario.md §3.2.
/// Pure data — no behavior, no VMx dependencies.
///
/// VMx v3 (ADR-0048 §2.1): <c>FormVM&lt;NoteModel&gt;.IsDirty</c> derives from the
/// model's own <c>object.Equals</c>, and the default snapshotter is a deep
/// System.Text.Json round-trip. A record's synthesized equality compares the
/// <see cref="Tags"/> collection by <em>reference</em>, so the deep-copied
/// snapshot's fresh list would read as perpetually dirty. The value-equality
/// override below (the documented v3 hook) compares <see cref="Tags"/>
/// element-wise so a structurally-identical snapshot is correctly clean.
/// </summary>
public sealed record NoteModel(
    string Id,
    string NotebookId,
    string Title,
    IReadOnlyList<string> Tags,
    string Body,
    bool Starred,
    DateTimeOffset CreatedAt,
    DateTimeOffset UpdatedAt)
{
    /// <summary>
    /// Value equality with element-wise <see cref="Tags"/> comparison
    /// (replaces the record-synthesized reference comparison for the list).
    /// </summary>
    public bool Equals(NoteModel? other)
    {
        if (other is null) return false;
        if (ReferenceEquals(this, other)) return true;
        return Id == other.Id
            && NotebookId == other.NotebookId
            && Title == other.Title
            && Body == other.Body
            && Starred == other.Starred
            && CreatedAt == other.CreatedAt
            && UpdatedAt == other.UpdatedAt
            && Tags.SequenceEqual(other.Tags);
    }

    /// <inheritdoc/>
    public override int GetHashCode()
    {
        var hash = new HashCode();
        hash.Add(Id);
        hash.Add(NotebookId);
        hash.Add(Title);
        hash.Add(Body);
        hash.Add(Starred);
        hash.Add(CreatedAt);
        hash.Add(UpdatedAt);
        foreach (var tag in Tags)
            hash.Add(tag);
        return hash.ToHashCode();
    }
}
