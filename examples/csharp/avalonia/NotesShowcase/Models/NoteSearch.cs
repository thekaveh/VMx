namespace NotesShowcase.Models;

/// <summary>
/// The search rule of every notes showcase, for the notes list and the global
/// search alike.
/// </summary>
public static class NoteSearch
{
    /// <summary>
    /// Reports whether <paramref name="note"/> matches <paramref name="term"/>.
    /// The term is trimmed, and an empty term matches every note. Otherwise a
    /// note matches when its title, its body or one of its tags contains the
    /// term, ignoring case. Each field is matched on its own, so a term never
    /// spans two fields.
    /// </summary>
    public static bool Matches(NoteModel note, string term)
    {
        var needle = term.Trim();
        if (needle.Length == 0) return true;
        return note.Title.Contains(needle, StringComparison.OrdinalIgnoreCase)
            || note.Body.Contains(needle, StringComparison.OrdinalIgnoreCase)
            || note.Tags.Any(tag => tag.Contains(needle, StringComparison.OrdinalIgnoreCase));
    }
}
